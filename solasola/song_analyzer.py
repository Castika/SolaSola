import re
import music21
from collections import Counter
import numpy as np
import librosa
from scipy.spatial.distance import cdist
from scipy.special import softmax
from sklearn.cluster import KMeans 
from .srt_parser import srt_time_format

def _frames_to_srt_chords(chord_frames, frame_times):
    """
    Converts a list of per-frame chord detections into a standard SRT format string.
    This function groups consecutive identical chords into single SRT blocks for readability.
    """
    if not chord_frames or not frame_times.any():
        return ""

    srt_blocks = []
    sequence_number = 1
    
    i = 0
    while i < len(chord_frames):
        current_chord = chord_frames[i]
        
        # Ignore segments where no chord was detected.
        if current_chord == 'N':
            i += 1
            continue
            
        start_time = frame_times[i]
        
        # Find the end of the current chord segment.
        j = i
        while j < len(chord_frames) and chord_frames[j] == current_chord:
            j += 1
            
        end_time = frame_times[j] if j < len(frame_times) else frame_times[-1] + (frame_times[1] - frame_times[0])

        start_srt = srt_time_format(start_time)
        end_srt = srt_time_format(end_time)
        
        srt_blocks.append(f"{sequence_number}\n{start_srt} --> {end_srt}\n{current_chord}\n")
        sequence_number += 1
        i = j
    return "\n".join(srt_blocks)

def _measures_to_srt_chords(measure_chords_list, measure_boundaries, sr, total_duration):
    """
    Converts a list of measure-based chords (one chord per measure) into a
    standard SRT format string.
    """
    if not measure_chords_list or not measure_boundaries:
        return ""

    measure_times = librosa.frames_to_time(measure_boundaries, sr=sr)
    srt_blocks = []
    sequence_number = 1

    for i, chord in enumerate(measure_chords_list):
        if chord == '-': # Skip measures where no dominant chord was found.
            continue
        
        start_time = measure_times[i]
        end_time = measure_times[i+1] if i + 1 < len(measure_times) else total_duration

        start_srt = srt_time_format(start_time)
        end_srt = srt_time_format(end_time)
        
        srt_blocks.append(f"{sequence_number}\n{start_srt} --> {end_srt}\n{chord}\n")
        sequence_number += 1
    return "\n".join(srt_blocks)

def _recognize_chords(chroma, sr):
    """
    A simple template-based chord recognizer using cosine distance and Viterbi smoothing
    to identify major and minor chords from chroma features.
    """
    # Note names for labeling
    note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
    
    # Create templates for major and minor chords
    templates = np.zeros((24, 12))
    labels = []
    
    # Generate templates for all 12 major chords (e.g., 'C').
    for i in range(12):
        templates[i, i] = 1
        templates[i, (i + 4) % 12] = 1
        templates[i, (i + 7) % 12] = 1
        labels.append(note_names[i])
    
    # Generate templates for all 12 minor chords (e.g., 'Cm').
    for i in range(12):
        templates[i + 12, i] = 1
        templates[i + 12, (i + 3) % 12] = 1
        templates[i + 12, (i + 7) % 12] = 1
        labels.append(f"{note_names[i]}m")

    # Normalize chroma features to remove the influence of dynamics (loudness).
    chroma_norm = np.linalg.norm(chroma, axis=0)
    chroma_norm[chroma_norm < 1e-6] = 1.0 # Avoid division by zero
    chroma_normalized = chroma / chroma_norm

    # Compare each chroma frame to the chord templates using cosine distance.
    dist = cdist(chroma_normalized.T, templates, 'cosine')
    
    # Use Viterbi smoothing to reduce erratic, frame-by-frame chord changes.
    # We create a transition matrix that heavily favors staying on the same chord.
    transition_matrix = librosa.sequence.transition_uniform(24)
    transition_matrix = np.add(transition_matrix, np.eye(24) * 10)
    # The transition matrix must be normalized so that each row sums to 1,
    # as required by the Viterbi algorithm.
    transition_matrix /= transition_matrix.sum(axis=1, keepdims=True)
    
    # The viterbi function expects probabilities (0-1), not raw distances.
    # 1. Convert distance to similarity (a smaller distance means higher similarity).
    #    We scale it by a factor of 10 to make the softmax more decisive.
    similarity = -dist * 10
    # 2. Apply softmax along the templates axis to get a probability distribution for each time step,
    #    ensuring that for each frame, the probabilities of all possible chords sum to 1.
    probabilities = softmax(similarity, axis=1)
    # 3. Pass the transposed probabilities to viterbi, which expects an input shape
    #    of (number_of_states, number_of_timesteps).
    smoothed_path = librosa.sequence.viterbi(probabilities.T, transition_matrix)

    smoothed_chords = [labels[i] for i in smoothed_path]

    # Add a "No Chord" (N) for frames with very low energy
    energy_threshold = np.percentile(chroma_norm, 15) # Threshold at 15th percentile of energy
    for i, energy in enumerate(chroma_norm):
        if energy < energy_threshold:
            smoothed_chords[i] = 'N'
    return smoothed_chords

def analyze_audio_features(audio_path: str) -> dict:
    """
    Analyzes an audio file to extract features like tempo, chords, and structure.
    Returns a dictionary of the findings.
    """
    analysis = {}

    if audio_path:
        try:
            y, sr = librosa.load(audio_path)
            total_duration = librosa.get_duration(y=y, sr=sr)
            # 1. Tempo Analysis
            tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
            analysis["Tempo"] = f"{int(tempo)} BPM"

            # 2. Chord Analysis
            y_harmonic, _ = librosa.effects.hpss(y)
            chroma = librosa.feature.chroma_cqt(y=y_harmonic, sr=sr)
            chord_frames = _recognize_chords(chroma, sr)
            frame_times = librosa.frames_to_time(np.arange(len(chord_frames)), sr=sr)
            
            # This creates a detailed, time-synchronized SRT file for chords.
            analysis["detailed_sync_chords_srt"] = _frames_to_srt_chords(chord_frames, frame_times)

            # This block formats the chords into a more traditional, measure-based grid.
            if tempo > 0:
                beats = librosa.beat.beat_track(y=y, sr=sr, units='frames')[1]
                # Assuming 4/4 time signature for measure calculation
                beats_per_measure = 4
                measure_boundaries = [beats[i] for i in range(0, len(beats), beats_per_measure)]
                
                measure_chords_list = []
                for i in range(len(measure_boundaries) - 1):
                    start_frame, end_frame = measure_boundaries[i], measure_boundaries[i+1]
                    measure_chord_slice = chord_frames[start_frame:end_frame]
                    # Find the most common chord in the measure, excluding 'No Chord' frames.
                    if len(measure_chord_slice) > 0:
                        chord_counts = Counter(c for c in measure_chord_slice if c != 'N')
                        most_common = chord_counts.most_common(1)
                        measure_chords_list.append(most_common[0][0] if most_common else '-')
                
                if measure_chords_list:
                    # Create a simple grid layout (4 chords per line).
                    analysis["chord_grid_text"] = "\n".join(["| " + " | ".join(measure_chords_list[i:i+4]) + " |" for i in range(0, len(measure_chords_list), 4)])
                    # Create an SRT file where each entry corresponds to one measure.
                    analysis["simple_sync_chords_srt"] = _measures_to_srt_chords(measure_chords_list, measure_boundaries, sr, total_duration)

            # 3. Song Structure Analysis (e.g., Verse, Chorus)
            try:
                hop_length = 512 * 2
                chroma_structure = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=hop_length)
                num_segments = 10
                boundaries = librosa.segment.agglomerative(chroma_structure, num_segments)
                segment_features = []
                for i in range(len(boundaries) - 1):
                    start_frame, end_frame = boundaries[i], boundaries[i+1]
                    segment_chroma = chroma_structure[:, start_frame:end_frame]
                    segment_features.append(np.mean(segment_chroma, axis=1))
                
                if segment_features:
                    n_clusters = min(len(np.unique(segment_features, axis=0)), 5)
                    # --- FIX: Add a safeguard to ensure at least one cluster can be formed ---
                    # This prevents a ValueError if np.unique returns an empty array or only one unique segment,
                    # which can happen with very short or monotonous audio clips.
                    if n_clusters > 1: 
                        kmeans = KMeans(n_clusters=n_clusters, random_state=0, n_init='auto').fit(segment_features)
                        segment_labels = [f"S{label + 1}" for label in kmeans.labels_]
                        analysis["Song Structure"] = "-".join(segment_labels)
            except Exception as e:
                # This is an internal analysis step; logging to the console is sufficient.
                print(f"  -> [INFO] Song structure analysis failed and was skipped: {e}")
                traceback.print_exc()

        except Exception as e:
            print(f"  -> Librosa analysis failed: {e}")
            if "Tempo" not in analysis: analysis["Tempo"] = "Not Analyzed"

    return analysis

def analyze_midi_features(midi_path: str) -> dict:
    """Analyzes a MIDI file to extract features like key, time signature, and note count."""
    if not midi_path:
        return {}
        
    analysis = {}
    try:
        # Use music21 to parse the MIDI file into a score object.
        score = music21.converter.parse(midi_path)
    except Exception as e:
        print(f"  -> music21 failed to parse MIDI file {midi_path}: {e}")
        return {
            "Key": "Not Analyzed",
            "Time Signature": "Not Analyzed",
            "Pitch Range": "Not Analyzed",
            "Note Count": "Not Analyzed",
        }

    # 1. Key Analysis: Determine the song's key (e.g., "C major").
    try:
        key = score.analyze('key')
        analysis["Key"] = f"{key.tonic.name} {key.mode}" if key else "Not Analyzed"
    except Exception as e:
        print(f"  -> music21 key analysis failed: {e}")
        analysis["Key"] = "Not Analyzed"

    # 2. Time Signature Analysis: Find all time signatures used in the song.
    try:
        ts_list = score.flatten().getTimeSignatures()
        analysis["Time Signature"] = ", ".join(sorted(list(set(f"{ts.numerator}/{ts.denominator}" for ts in ts_list)))) if ts_list else "Not Analyzed"
    except Exception as e:
        print(f"  -> music21 time signature analysis failed: {e}")
        analysis["Time Signature"] = "Not Analyzed"

    return analysis

def analyze_srt(srt_data: list | None, total_duration: float) -> dict:
    """Analyzes SRT data for vocal characteristics."""
    if not srt_data or not total_duration or total_duration == 0:
        return {}
        
    analysis = {}
    
    total_vocal_time = sum(line['end'] - line['start'] for line in srt_data)
    total_words = sum(len(line['text'].split()) for line in srt_data)
    
    if total_vocal_time > 0:
        analysis['lyric_density'] = f"{int((total_words / total_vocal_time) * 60)} words/min"
        
    vocal_activity = (total_vocal_time / total_duration) * 100
    analysis['vocal_activity'] = f"{vocal_activity:.1f}%"
    
    return analysis

def create_song_profile(result_data: dict, audio_duration: float) -> dict:
    """Creates a high-level, human-readable profile of the song."""
    profile = {}

    # Add the song's total duration.
    if audio_duration > 0:
        minutes = int(audio_duration // 60)
        seconds = int(audio_duration % 60)
        profile['Duration'] = f"{minutes}:{seconds:02d}"

    # Add genre information, formatted with confidence percentages.
    if result_data.get('genre'):
        profile['Genre - AI Estimated'] = ", ".join(
            f"{g['genre'].title()} ({g['probability']:.0%})"
            for g in result_data['genre']
        )
    else:
        profile['Genre - AI Estimated'] = "Not Analyzed"

    # Directly add the analysis results that were passed in.
    profile.update({
        'Tempo': result_data.get('Tempo', 'Not Analyzed'),
        'Key': result_data.get('Key', 'Not Analyzed'),
        'Time Signature': result_data.get('Time Signature', 'Not Analyzed'),
        'Song Structure': result_data.get('Song Structure', 'Not Analyzed'),
    })

    # Analyze vocal characteristics based on the generated SRT data.
    if result_data.get('srt_data'):
        srt_analysis = analyze_srt(result_data['srt_data'].get('segments', []), audio_duration)
        if 'vocal_activity' in srt_analysis:
            profile['Vocal Activity'] = srt_analysis['vocal_activity']
        if 'lyric_density' in srt_analysis:
            profile['Lyric Density'] = srt_analysis['lyric_density']
            
    # Add the raw chord analysis results to the profile dictionary.
    # This makes them available to the backend for saving to files.
    if 'detailed_sync_chords_srt' in result_data: profile['detailed_sync_chords_srt'] = result_data['detailed_sync_chords_srt']
    if 'simple_sync_chords_srt' in result_data: profile['simple_sync_chords_srt'] = result_data['simple_sync_chords_srt']
    if 'chord_grid_text' in result_data: profile['chord_grid_text'] = result_data['chord_grid_text']
        
    return profile

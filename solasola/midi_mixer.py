"""
A dedicated utility for merging multiple MIDI files into a single, combined mix file.
"""
import mido
from pathlib import Path

def create_mix_midi(midi_paths, song_title, output_path):
    """
    Merges multiple MIDI files into a single Type 1 MIDI file, ensuring each
    track is correctly named based on its source filename.

    Args:
        midi_paths (list): A list of paths to the individual MIDI files.
        song_title (str): The title for the overall MIDI file.
        output_path (str): The path to save the merged MIDI file.

    Returns:
        str: The path to the created mixed MIDI file, or None if failed.
    """
    if not midi_paths:
        return None

    # Create a new Type 1 MIDI file (multi-track)
    merged_midi = mido.MidiFile(type=1)

    # MIDI channels are 0-15. Channel 9 (10 in 1-based systems) is for percussion.
    available_channels = [i for i in range(16) if i != 9]
    
    # Sort paths to process drums first, ensuring it gets channel 9 if available.
    # This makes the channel assignment predictable.
    midi_paths.sort(key=lambda p: 'drums' not in Path(p).stem.lower())

    # --- FIX: Find key metadata (tempo, time signature) from the first available source MIDI ---
    time_signature_message = None
    tempo_message = None
    for midi_path in midi_paths:
        try:
            input_midi = mido.MidiFile(midi_path)
            for track in input_midi.tracks:
                for msg in track:
                    if msg.type == 'time_signature' and not time_signature_message:
                        time_signature_message = msg
                    if msg.type == 'set_tempo' and not tempo_message:
                        tempo_message = msg
                if time_signature_message and tempo_message:
                    break
            if time_signature_message and tempo_message:
                break
        except Exception:
            continue # Ignore if a MIDI file is unreadable

    # --- FIX: Create and add the metadata track *before* processing note tracks. ---
    # This ensures it's always the first track, regardless of which file's
    # note tracks are processed first.
    meta_track = mido.MidiTrack()
    meta_track.append(mido.MetaMessage('track_name', name=song_title))
    if time_signature_message:
        meta_track.append(time_signature_message)
    if tempo_message:
        meta_track.append(tempo_message)
    merged_midi.tracks.append(meta_track)

    for midi_path in midi_paths:
        try:
            base_instrument_name = Path(midi_path).stem.replace('_', ' ').title()
            input_midi = mido.MidiFile(midi_path)

            # Assign ONE channel per file, not per track within the file.
            # This prevents channel exhaustion when a single stem file has many tracks.
            is_drum_file = 'drums' in base_instrument_name.lower()
            channel_for_this_file = 0 # Default fallback
            if is_drum_file:
                channel_for_this_file = 9
                if 9 in available_channels:
                    available_channels.remove(9)
            elif available_channels:
                channel_for_this_file = available_channels.pop(0)
            
            for i, input_track in enumerate(input_midi.tracks):
                # Skip empty tracks that contain no note data to avoid empty tracks in the final mix.
                if not any(msg.type.startswith('note') for msg in input_track):
                    continue

                new_track = mido.MidiTrack()

                track_name = base_instrument_name if len(input_midi.tracks) == 1 else f"{base_instrument_name} (Track {i + 1})"
                new_track.append(mido.MetaMessage('track_name', name=track_name))

                for msg in input_track:
                    if msg.is_meta:
                        if msg.type != 'track_name': # Keep all meta messages except the original track name
                            new_track.append(msg)
                    else: # Note, control change, etc.
                        # All notes from this file get the same, pre-assigned channel.
                        new_track.append(msg.copy(channel=channel_for_this_file))
                
                merged_midi.tracks.append(new_track)
        except Exception as e:
            print(f"  -> WARNING: Could not process MIDI file {midi_path} for mixing: {e}")

    if not merged_midi.tracks:
        return None

    try:
        merged_midi.save(output_path)
        print(f"  -> Successfully created 'Mix' MIDI at {output_path}")
        return output_path
    except Exception as e:
        print(f"  -> ERROR: Failed to save merged MIDI file: {e}")
        return None

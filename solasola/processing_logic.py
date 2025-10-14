# This file contains the core data processing logic, separated from the Flask web server routes.
import os
import shutil
import traceback
import logging
import time
import sys
import re
import subprocess
import json
import librosa
import threading
import gc
import torch
import hashlib
import math
import unicodedata
import select
from pydub import AudioSegment
from datetime import datetime, timedelta, timezone
from pathlib import Path
import mido
import music21

# Import from other SolaSola modules
from solasola.input_handler import parse_title_and_stem_from_filenames, group_files_as_single_project
from solasola.hardware_manager import get_processing_device
from solasola.cache_resolver import CacheResolver
from solasola.metadata_generator import MetadataGenerator
from solasola.model_manager import get_all_models_status, GENRE_MODEL_REPO_ID
from solasola.stem_separator import prepare_demucs_model, run_demucs_separation
from solasola.stem_separator_progress_checker import DemucsProgressParser
from solasola.midi_converter import convert_audio_to_midi
from solasola.srt_parser import create_srt_from_txt_file
from solasola.abc_generator import convert_midi_to_abc, generate_mix_abc
from solasola.midi_mixer import create_mix_midi
from solasola.audio_mixer import create_mix_audio
from solasola import song_analyzer # This is correct, it's a module
from solasola.ui_log_manager import log_to_ui

# Import from the new task manager
from solasola.task_manager import TASKS, update_detailed_status, check_for_cancellation, InterruptedError

def _validate_and_get_duration(task_id, audio_files: list, midi_files: list) -> float:
    """
    Validates music files and returns a definitive duration for the project.
    - For audio files, it performs strict validation (durations must be similar).
    - For MIDI files (if no audio), it performs loose validation (uses the longest duration).
    This centralizes duration logic and avoids redundant calculations.
    """
    # Prioritize audio files for duration calculation
    if audio_files:

        log_to_ui(task_id, "Validating audio files...", "rule", type='info', target='toast')
        log_to_ui(task_id, "Validating audio file durations and integrity...", "rule", type='info', target='log')
        try:
            durations = [librosa.get_duration(path=f['path']) for f in audio_files]
            if len(durations) > 1 and (max(durations) - min(durations) > 1.5):
                duration_str = ", ".join([f"{d:.1f}s" for d in durations])

                log_to_ui(task_id, f"Error: Files have significantly different durations ({duration_str}). They appear to be unrelated songs.", "error", type='error', target='both')
                raise ValueError("Audio files have significantly different durations. Please process one song at a time.")
            return durations[0] if durations else 0.0
        except Exception as e:
            print(f"Error during audio duration validation: {e}")
            raise e
    
    # If no audio files, use MIDI files
    if midi_files:

        log_to_ui(task_id, "Calculating duration...", "timer", type='info', target='toast')
        log_to_ui(task_id, "No audio files found. Calculating duration from MIDI files...", "timer", type='info', target='log')
        try:
            # For MIDI, we don't do strict validation. We use the longest duration
            # as different instrument parts can have slightly different lengths.
            return max(mido.MidiFile(f['path']).length for f in midi_files)
        except Exception as e:
            print(f"Error during MIDI duration calculation: {e}")
            raise e

    # If no music files are provided at all
    return 0.0

def _run_genre_classification(task_id, audio_path, temp_dir):
    """
    Runs genre classification in a separate process to prevent memory/forking issues.
    """
    all_statuses = get_all_models_status()
    genre_model_status = all_statuses.get('feature_models', {}).get(GENRE_MODEL_REPO_ID)

    if not genre_model_status or not genre_model_status.get('installed'):

        log_to_ui(task_id, "Genre model not installed.", "info", type='warning', target='toast')
        log_to_ui(task_id, "Genre analysis model is not installed. Skipping. You can install it from the 'Manage Models' menu.", "info", type='warning', target='log')
        return []

    output_path = Path(temp_dir) / "genre_result.json"
    command = [
        sys.executable,
        "-m", "solasola.sub_process.run_genre_classifier",
        "--audio_path", str(audio_path),
        "--output_path", str(output_path),
        "--task_id", task_id
    ]

    try:
        proc = subprocess.run(command, capture_output=True, text=True, check=False, encoding='utf-8', errors='replace')
        check_for_cancellation(task_id)

        if proc.returncode != 0:
            error_message = f"Genre classification subprocess failed. STDERR: {proc.stderr.strip()}"
            print(f"  -> {error_message}\n  -> STDOUT: {proc.stdout.strip()}")

            log_to_ui(task_id, "Genre analysis failed.", "error", type='warning', target='toast')
            log_to_ui(task_id, "Genre analysis failed and was skipped. See server logs for details.", "error", type='warning', target='log')
            return []

        with open(output_path, 'r', encoding='utf-8') as f:
            result = json.load(f)

        if result.get("error"):
            print(f"  -> Error from genre classification subprocess: {result['error']}")
            return []

        return result.get("genres", [])
    except FileNotFoundError:

        log_to_ui(task_id, "Genre model not found.", "info", type='warning', target='toast')
        log_to_ui(task_id, "Genre detection skipped (model files not found at expected path).", "info", type='warning', target='log')
        return []
    except Exception as e:
        print(f"  -> An error occurred while running genre classification subprocess: {e}")
        return []

def _create_progress_layout(task_id, demucs_model, files, mode):
    """Generates the 'blueprint' for the dynamic progress bar."""
    num_demucs_steps = 0
    num_midi_steps = 0

    if mode == 'abc':
        if files.get('midi'):
            num_midi_steps = len(files['midi'])
        elif files.get('audio'):
            # Ensemble models like 'htdemucs_ft' run multiple times on the same track.
            # We set the number of progress steps to match the number of models in the bag.
            num_demucs_steps = 4 if demucs_model == 'htdemucs_ft' else 1
            if len(files['audio']) > 1: # Pre-separated stems
                num_midi_steps = len(files['audio'])
            else: # Full mix
                if demucs_model == 'htdemucs_6s':
                    num_midi_steps = 6
                else: # htdemucs_ft, htdemucs, mdx_extra_q
                    num_midi_steps = 4
        if num_midi_steps > 0:
            num_midi_steps += 1 # For the 'mix' file

    layout = {
        "stages": [
            {"label": "1. Preparing Files", "weight": 2, "sub_stages": 3},
            {"label": "2. Analyzing Music", "weight": 3, "sub_stages": 2},
            {"label": "3. Preparing Model", "weight": 3, "sub_stages": 1},
            {"label": "4. Separating Stems", "weight": 83, "sub_stages": num_demucs_steps},
            {"label": "5. Converting to Score", "weight": 6, "sub_stages": num_midi_steps},
            {"label": "6. Finalizing Results", "weight": 3, "sub_stages": 3}
        ]
    }
    TASKS[task_id]['layout'] = layout
    return layout

def _get_num_stems(files, model_name):
    """Helper to estimate the number of stems for progress reporting."""
    if files.get('midi'): return len(files['midi'])
    if len(files.get('audio', [])) > 1: return len(files['audio'])
    if model_name == 'htdemucs_6s': return 6
    return 4


def _process_song(task_id, title, files, temp_dir, device, models, mode, base_progress, total_songs, song_num, cache_resolver, metadata_generator, audio_duration=0.0):
    """
    Processes a single song, from audio/MIDI files to the final results dictionary.
    This function contains the main logic for a single entry in the processing queue.
    """
    final_srt_content = None
    midi_paths_for_abc = []
    final_abc_files = None
    predicted_genres = []
    midi_analysis_results = {}
    audio_analysis_results = {}

    # Initialize all potential result variables at the top-level scope.
    # This ensures they are always defined, even if a processing step is skipped or fails.
    user_lyrics_text = None
    parsed_segments = None

    # --- REFACTOR: Use pre-calculated audio_duration passed from the wrapper ---
    # If no music files were provided but lyrics were, use a default duration.
    if audio_duration == 0 and mode == 'lyrics_only' and files.get('lyrics'):
        audio_duration = 210 # Default to 3m 30s

        log_to_ui(task_id, "Using default duration for lyrics.", "timer", type='info', target='toast')
        log_to_ui(task_id, "No music file provided. Using default duration (3m 30s) for lyrics split.", "timer", type='info', target='log')

    # Process lyrics early to provide fast feedback on lyrics file issues.
    try:
        # The 'audio_for_analysis' variable is defined here and used later for music analysis.
        # It's defined conditionally to prevent errors in lyrics-only mode.
        if files.get('audio'):
            audio_for_analysis = files['audio'][0]['path']
            if len(files['audio']) > 1:
                mixed_audio_path = Path(temp_dir) / "analysis_mix.wav"
                
                log_to_ui(task_id, "Creating temporary mix...", "blender", type='info', target='toast')
                log_to_ui(task_id, "Creating temporary mix from stems for analysis...", "blender", type='info', target='log')
                created_path = create_mix_audio(files['audio'], str(mixed_audio_path))
                if created_path:
                    audio_for_analysis = created_path
                else:
                    log_to_ui(task_id, "Mix creation failed.", "warning", type='warning', target='toast')
                    log_to_ui(task_id, "Could not create a temporary mix. Analysis will be based on the first stem only.", "warning", type='warning', target='log')

        update_detailed_status(task_id, 1, 3, 100, "Processing lyrics...") # This line is correct
        final_srt_content, user_lyrics_text, parsed_segments = process_lyrics(task_id, files, audio_duration)
        check_for_cancellation(task_id)

        # Handle lyrics processing failure only if a lyrics file was actually provided.
        # This prevents showing a "corrupt file" warning when no file was given.

        if files.get('lyrics') and (final_srt_content is None and user_lyrics_text is None and parsed_segments is None):
            log_to_ui(task_id, "Could not process the provided lyrics file. It may be corrupt or unreadable.", "subtitles_off", type='warning')

    except Exception as e:
        log_to_ui(task_id, f"Lyrics generation failed for '{title}': {e}", "error", type='error')
        return None

    # Music analysis (genre, chords, structure) only runs in 'abc' (Full Analysis) mode.
    if mode == 'abc' and 'audio_for_analysis' in locals():
        try:
            update_detailed_status(task_id, 2, 1, 50, "Analyzing genre...")
            predicted_genres = _run_genre_classification(task_id, audio_for_analysis, temp_dir)
            check_for_cancellation(task_id)
            update_detailed_status(task_id, 2, 2, 50, "Analyzing structure...")
            audio_analysis_results = song_analyzer.analyze_audio_features(audio_for_analysis)
        except Exception as e:
            log_to_ui(task_id, "Music analysis failed.", "error", type='error', target='toast')
            log_to_ui(task_id, f"Music pre-analysis failed for '{title}': {e}", "error", type='error', target='log')
            traceback.print_exc()

    # Main AI processing block for stem separation, MIDI conversion, and ABC generation.
    if mode == 'abc':
        try:
            # Use CacheResolver to check for existing results before processing.
            stems_instruction = cache_resolver.resolve('stems')
            if stems_instruction['action'] == 'CREATE_NEW':
                update_detailed_status(task_id, 3, 1, 10, "Preparing separation model...")
                # process_audio now returns the actual path where stems were saved
                actual_stems_path = process_audio(task_id, files, temp_dir, device, models['demucs'], stems_instruction['path'])
                if not actual_stems_path or not any(actual_stems_path.iterdir()):
                     raise Exception("Stem separation failed to produce any files.")
                # Write a manifest for the new stems so they can be cached for future runs.
                cache_resolver.write_manifest_for_step('stems') # This is now correct
                stems_instruction['path'] = actual_stems_path # Update path for the next step
            else: # USE_EXISTING
                actual_stems_path = stems_instruction['path']
            
            midi_instruction = cache_resolver.resolve('midi')
            if midi_instruction['action'] == 'CREATE_NEW':
                convert_stems_to_midi(task_id, actual_stems_path, midi_instruction['path'], models['demucs'])
                cache_resolver.write_manifest_for_step('midi')
                # Populate the list of MIDI paths for the next step (ABC generation).
                midi_paths_for_abc = [str(p) for p in midi_instruction['path'].glob('*.mid')]
            else: # USE_EXISTING
                midi_paths_for_abc = [str(p) for p in midi_instruction['path'].glob('*.mid')]

            if not midi_paths_for_abc:
                raise Exception("MIDI files were not found in the cache or could not be generated.")
        except Exception as e:
            log_to_ui(task_id, "Audio processing failed.", "error", type='error', target='toast')
            log_to_ui(task_id, f"Audio processing failed for '{title}': {e}", "error", type='error', target='log')
            print(f"--- DETAILED ERROR IN AUDIO PROCESSING BLOCK FOR TASK {task_id} ---")
            traceback.print_exc()
            return None
    if final_srt_content:
        try:
            lyrics_output_dir = cache_resolver.result_dir / "lyrics"
            lyrics_output_dir.mkdir(exist_ok=True)
            (lyrics_output_dir / "lyrics.srt").write_text(final_srt_content, encoding='utf-8')
        except Exception as e:
            print(f"  -> WARNING: Could not save generated SRT file: {e}")

    if mode == 'abc' and midi_paths_for_abc:
        abc_instruction = cache_resolver.resolve('abc_files')
        if abc_instruction['action'] == 'USE_EXISTING':
            final_abc_files = {}
            for abc_file in abc_instruction['path'].glob('*.abc'):
                instrument_name = abc_file.stem
                final_abc_files[instrument_name] = abc_file.read_text(encoding='utf-8')
        else:
            try:
                update_detailed_status(task_id, 6, 2, 50, "Generating ABC notation...")
                final_abc_files = convert_midi_to_abc(midi_paths=midi_paths_for_abc, song_title=title)
                if final_abc_files:
                    print(f"  -> Successfully generated ABC for '{title}'.")
                    for instrument, content in final_abc_files.items():
                        (abc_instruction['path'] / f"{instrument}.abc").write_text(content, encoding='utf-8')
                    cache_resolver.write_manifest_for_step('abc_files')
            except Exception as e:
                log_to_ui(task_id, "ABC generation failed.", "error", type='error', target='toast')
                log_to_ui(task_id, f"ABC score generation failed for '{title}': {e}", "error", type='error', target='log')
                traceback.print_exc()
    elif mode == 'abc':
        print(f"No MIDI files could be processed for '{title}'. Skipping ABC generation.")

    # Perform final analysis based on the generated MIDI files.
    if mode == 'abc' and midi_paths_for_abc:
        # Create the mixed MIDI file ONCE in its final destination.
        output_path_for_mix = str(midi_instruction['path'] / "solasola_mixed.mid")
        mix_midi_path = create_mix_midi(midi_paths_for_abc, title, output_path_for_mix)
        if mix_midi_path:
            # 1. Use the mixed MIDI for final song profile analysis.
            midi_analysis_results = song_analyzer.analyze_midi_features(mix_midi_path)

            # 2. Use the SAME mixed MIDI to generate the "Mix" ABC score.
            if final_abc_files is not None: # Ensure individual ABCs were created
                mix_abc_content = generate_mix_abc(mix_midi_path, title)
                if mix_abc_content:
                    # Prepend the Mix to make it the first tab in the UI
                    final_abc_files = {'Mix': mix_abc_content, **final_abc_files}
                    (abc_instruction['path'] / "Mix.abc").write_text(mix_abc_content, encoding='utf-8')
                    # Re-write the manifest to include the newly created Mix.abc
                    cache_resolver.write_manifest_for_step('abc_files')
        else:
            log_to_ui(task_id, "Could not create Mix.", "warning", type='warning', target='toast')
            log_to_ui(task_id, "Could not create a combined Mix. Skipping final MIDI analysis.", "warning", type='warning', target='log')

    # Assemble all generated data for the final song profile.
    lyrics_data_for_profile = None
    if final_srt_content:
        lyrics_data_for_profile = {"segments": parsed_segments}

    lyrics_source_method = None
    if files.get('lyrics'):
        lyrics_ext = Path(files['lyrics'][0]['path']).suffix.lower()
        if lyrics_ext in ['.txt', '.lrc']:
            lyrics_source_method = 'simple_split'
        elif lyrics_ext == '.srt':
            lyrics_source_method = 'user_srt'

    # Extract Tempo from the generated Mix ABC file, as it's often more reliable than librosa's analysis.
    if final_abc_files and 'Mix' in final_abc_files:
        tempo_match = re.search(r'Q:\s*(?:".*?"\s*)?(?:(?:\d+/\d+)\s*=\s*)?\s*(\d+)', final_abc_files['Mix'])
        if tempo_match:
            audio_analysis_results['Tempo'] = f"{tempo_match.group(1)} BPM"

    song_profile_data = song_analyzer.create_song_profile(
        {
            'srt_data': lyrics_data_for_profile,
            'genre': predicted_genres, # This was being passed correctly here
            **audio_analysis_results,
            **midi_analysis_results # This now contains Key, Time Sig, Pitch Range, and Note Count
        },
        audio_duration
    )

    # The project_info dictionary holds all data for the final UI and metadata files.
    project_info = {'genres': predicted_genres}
    project_info = {**song_profile_data}
    project_info["lyrics_source_method"] = lyrics_source_method
    project_info["is_lyrics_only_split"] = (mode == 'lyrics_only' and not files.get('audio'))

    chord_charts = {}
    detailed_chords = project_info.get('detailed_sync_chords_srt')
    simple_chords = project_info.get('simple_sync_chords_srt')
    grid_chords = project_info.get('chord_grid_text')

    if detailed_chords or simple_chords or grid_chords:
        chord_instruction = cache_resolver.resolve('chords')
        if chord_instruction['action'] == 'CREATE_NEW':
            if detailed_chords: (chord_instruction['path'] / "detailed_sync_chords.srt").write_text(detailed_chords, encoding='utf-8')
            if simple_chords: (chord_instruction['path'] / "simple_sync_chords.srt").write_text(simple_chords, encoding='utf-8')
            if grid_chords: (chord_instruction['path'] / "chord_grid.txt").write_text(grid_chords, encoding='utf-8')
            # Write manifest for the newly created chords
            cache_resolver.write_manifest_for_step('chords')

    metadata_generator.add_song_profile(project_info)


    detailed_chords = project_info.get('detailed_sync_chords_srt')
    simple_chords = project_info.get('simple_sync_chords_srt')
    grid_chords = project_info.get('chord_grid_text')
    instrument_order = {'mix': 0, 'vocals': 1, 'drums': 2, 'bass': 3}
    sorted_abc_files = dict(sorted(
        (final_abc_files or {}).items(),
        key=lambda item: instrument_order.get(item[0].lower(), 99)
    ))
    
    chord_charts = {}
    if grid_chords: chord_charts['Chord Grid'] = grid_chords
    if simple_chords: chord_charts['Simple Sync (SRT)'] = simple_chords
    if detailed_chords: chord_charts['Detailed Sync (SRT)'] = detailed_chords
    
    results = {
        "lyrics": {
            "generated_lyrics": final_srt_content,
            "input_lyrics": user_lyrics_text
        },
        "abc_notation": sorted_abc_files,
        "chord_chart": chord_charts if chord_charts else None
    }

    # The final object returned to the UI must contain the song_profile at the top level.
    final_ui_results = {
        "song_profile": project_info,
        **results
    }

    metadata_generator.add_final_results(results)
    return final_ui_results # Return the object structured for the UI

def process_task_wrapper(task_id, temp_dir, classified_files, processing_mode, demucs_model, original_music_filenames, display_title_override=None, keep_models_cached=False, base_output_dir=None, raw_form_data=None, version_info=None):
    """The main processing logic that runs in a background thread."""
    start_time = time.time()

    try:
        if raw_form_data:
            print("\n--- Raw Request Received ---")
            for key, value in raw_form_data.items():
                print(f"  - {key}: '{value}'")
            print("----------------------------\n")

        demucs_map = {
            'htdemucs': "Fast",
            'htdemucs_6s': "Fast6",
            'htdemucs_ft': "Deep",
        }
        if processing_mode == 'abc':
            mode_label = f"Full Analysis ({demucs_map.get(demucs_model, demucs_model)})"
        else:
            mode_label = "Lyrics File Simple Split"

        update_detailed_status(task_id, 1, 1, 33, "Parsing filenames...")
        parsed_data = parse_title_and_stem_from_filenames(classified_files)
        check_for_cancellation(task_id)

        songs_to_process = group_files_as_single_project(parsed_data, original_music_filenames)

        print(f"\nFound {len(songs_to_process)} song(s) to process.")

        _create_progress_layout(task_id, demucs_model, classified_files, processing_mode)

        final_results = {}
        total_songs = len(songs_to_process)
        song_num = 0 # This seems unused, consider removing if not needed for multi-song logic

        main_audio_duration = _validate_and_get_duration(task_id, classified_files.get('audio', []), classified_files.get('midi', []))

        processing_device = 'cpu' # Default to CPU for lyrics-only mode
        device_map = {
            "cuda": "NVIDIA GPU (CUDA)",
            "mps": "Apple Silicon GPU (MPS)",
            "cpu": "CPU"
        }
        if processing_mode == 'abc':
            update_detailed_status(task_id, 1, 2, 66, "Detecting hardware...")
            processing_device = get_processing_device()

        for title, files in songs_to_process.items():
            try:
                song_num += 1
                base_progress = 10 + (85 * (song_num - 1) / total_songs)

                title_for_ui = display_title_override or title

                log_to_ui(task_id, f"Starting analysis for '{title_for_ui}'", "lab_profile")
                log_to_ui(task_id, f"Processing Mode: {mode_label}", "tune", type='success')
                if processing_mode == 'abc':
                    log_to_ui(task_id, f"Processing hardware: {device_map.get(processing_device, 'CPU')}", "memory")
                log_to_ui(task_id, "File validation passed", "file_present", type='success')
                
                # --- Folder Naming and Resolver/Generator Setup ---
                file_hashes = {}
                if files.get('audio'):
                    main_audio_path = next((f['path'] for f in files['audio'] if 'vocals' not in f.get('stem', '')), files['audio'][0]['path'])
                    file_hashes['audio'] = CacheResolver.get_file_hash(main_audio_path)

                file_fingerprint = f"{file_hashes.get('audio', 'no_audio')[:12]}"
                mode_key_parts = [
                    processing_mode,
                    demucs_model if processing_mode == 'abc' else 'na',
                ]
                mode_key = "-".join(mode_key_parts)
                settings_fingerprint = hashlib.sha256(mode_key.encode('utf-8')).hexdigest()[:8]
                
                fingerprint = f"{file_fingerprint}_{settings_fingerprint}"

                client_time_offset_seconds = TASKS[task_id].get('client_time_offset', 0)
                local_time = datetime.fromtimestamp(time.time() + client_time_offset_seconds)
                timestamp_str = local_time.strftime("%Y%m%d_%H%M%S")

                i = 1
                while True:
                    result_dir_name = f"{timestamp_str}_{i}_{fingerprint}"
                    final_results_dir = base_output_dir / result_dir_name
                    if not final_results_dir.exists():
                        break
                    i += 1
                final_results_dir.mkdir(parents=True, exist_ok=True)

                TASKS[task_id]['input_files'] = files


                # Send a concise message to the toast.
                log_to_ui(task_id, "Results will be saved to...", "folder_open", type='success', target='toast')
                # Send a more detailed message to the log.
                log_to_ui(task_id, f"Result folder: '{result_dir_name}'", "folder_open", type='info', target='log')

                cache_resolver = CacheResolver(task_id, base_output_dir, fingerprint, final_results_dir)
                metadata_generator = MetadataGenerator(task_id, version_info, final_results_dir, client_time_offset_seconds)
                
                settings_info = {
                    "mode": mode_label,
                    "processing_device": device_map.get(processing_device, 'CPU')
                }
                metadata_generator.add_settings_info(settings_info)
                metadata_generator.add_input_info(classified_files, original_music_filenames)

                result_entry = _process_song(
                    task_id, title_for_ui, files, temp_dir, processing_device,
                    {'demucs': demucs_model}, processing_mode, base_progress, total_songs, song_num,
                    cache_resolver, metadata_generator, audio_duration=main_audio_duration
                )
                if result_entry:
                    metadata_generator.add_cache_provenance(cache_resolver.provenance)
                    end_time = time.time()
                    processing_duration_seconds = end_time - start_time
                    minutes, seconds = divmod(int(processing_duration_seconds), 60)
                    duration_str = f"{minutes}m {seconds}s"
                    metadata_generator.add_processing_time(duration_str)

                    metadata_generator.write_metadata()
                    final_results[title] = result_entry
            except InterruptedError:
                raise
            except Exception as song_e:
                print(f"Error processing song '{title}': {song_e}")
                traceback.print_exc()
                log_to_ui(task_id, f"Failed to process '{title}'.", "error", type='error', target='toast')
                log_to_ui(task_id, f"Failed to process '{title}': {song_e}", "error", type='error', target='log')

        if not final_results:
            raise Exception("All files failed to process. Please check the logs for details.")

        TASKS[task_id]['results'] = final_results
        update_detailed_status(task_id, 6, 3, 100, "Finalizing...", status='completed')

    except InterruptedError:
        update_detailed_status(task_id, -1, -1, -1, "Processing cancelled by user.", status='cancelled')
    except Exception as e:
        print(f"Error in task {task_id}: {e}")
        traceback.print_exc()
        update_detailed_status(task_id, -1, -1, -1, str(e), status='failed')
        log_to_ui(task_id, "A critical error occurred.", "error", type='error', target='toast')
        log_to_ui(task_id, f"A critical error occurred: {e}", "error", type='error', target='log')
    finally:
        print(f"Cleaning up temporary directory for task {task_id}: {temp_dir}")
        shutil.rmtree(temp_dir, ignore_errors=True)
        if task_id in TASKS:
            TASKS[task_id]['process'] = None
        if processing_mode == 'abc':
            if not keep_models_cached:
                log_to_ui(task_id, "Releasing models from memory.", "autorenew", type='info', target='toast')
                log_to_ui(task_id, "Releasing AI models from memory...", "autorenew", type='info', target='log')
                print(f"Task {task_id} finished. Releasing models from memory (default behavior).")
                
                try:
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                        print("  -> CUDA cache cleared.")
                    
                    gc.collect()
                except Exception as e:
                    print(f"  -> Error during model release: {e}")
            else:
                log_to_ui(task_id, "Keeping models in memory.", "memory", type='info', target='toast')
                log_to_ui(task_id, "Keeping AI models in memory for faster subsequent processing.", "memory", type='info', target='log')

def process_lyrics(task_id, files, audio_duration=0):
    """
    Helper function to handle user-provided lyrics files.
    - If an SRT file is provided, it's used directly.
    - If a TXT/LRC file is provided, it's split evenly over the audio duration.
    """
    if not files.get('lyrics'):
        print("  -> No user lyrics file provided. Skipping lyrics generation.")
        log_to_ui(task_id, "Proceeding with music-only analysis.", "info", type='info', target='toast')
        log_to_ui(task_id, "Lyrics file not found. Proceeding with music-only analysis.", "info", type='info', target='log')
        return None, None, None

    lyrics_info = files['lyrics'][0]
    lyrics_path = lyrics_info['path']
    lyrics_ext = Path(lyrics_path).suffix.lower()
    lyrics_encoding = lyrics_info['encoding']

    log_to_ui(task_id, "Processing lyrics...", "linear_scale", type='info', target='toast')
    log_to_ui(task_id, "Distributing lyrics evenly across the song's duration.", "linear_scale", type='info', target='log')
    print(f"  -> User provided TXT. Applying simple time distribution via srt_parser.")
    return create_srt_from_txt_file(lyrics_path, lyrics_encoding, audio_duration)

def process_audio(task_id, files, temp_dir, device, model_name, stems_output_dir):
    """
    Handles audio processing: separation or copying of stems.
    Returns the actual path where the final stems are located.
    """
    final_stem_path = stems_output_dir
    if files['midi']:
        raise NotImplementedError("Direct MIDI processing path needs refactoring with new architecture.")
    
    if len(files['audio']) == 1 and files['audio'][0]['stem'] == 'full_mix':
        print("  -> Single audio file detected. Treating as a full mix for AI instrument separation.")
        original_audio_path = Path(files['audio'][0]['path'])
        
        safe_audio_path = Path(temp_dir) / "processing_audio.wav"
        try:
            os.link(original_audio_path, safe_audio_path)
            print(f"  -> Created hard link for processing: {safe_audio_path.name}")
        except Exception as e:
            print(f"  -> Hard link failed ({e}), copying file for processing...")
            shutil.copy(original_audio_path, safe_audio_path)

        audio_to_process = str(safe_audio_path)

        demucs_proc = None
        expected_demucs_output_path = None
        try:
            # 1. Request a cleanup from the state manager before starting.
            print("  -> Requesting model state cleanup before separation...")
            subprocess.run([sys.executable, "-m", "solasola.sub_process.demucs_state_watcher", "--action", "cleanup"], check=True, capture_output=True, text=True)
            print("  -> Cleanup complete.")
            check_for_cancellation(task_id)

            # 2. Start the download watcher to capture the 'before' state.
            print("  -> Starting Demucs download watcher...")
            subprocess.run([
                sys.executable, "-m", "solasola.sub_process.demucs_download_watcher",
                "--action", "start",
                "--task-id", task_id,
                "--model-name", model_name
            ], check=True)
            check_for_cancellation(task_id)

            # 3. Prepare the model (triggers download if not present).
            loaded_model = prepare_demucs_model(model_name)

            # 4. Stop the watcher immediately to create the manifest for the downloaded files.
            print("  -> Signaling download watcher to finalize and create manifest...")
            subprocess.run([sys.executable, "-m", "solasola.sub_process.demucs_download_watcher", "--action", "stop", "--task-id", task_id, "--model-name", model_name], check=True)
            print("  -> Watcher has been signaled and manifest created.")
            check_for_cancellation(task_id)

            # 5. Run the actual Demucs separation process using the pre-loaded model.
            demucs_temp_output = Path(temp_dir) / "demucs_output"
            demucs_temp_output.mkdir()
            demucs_proc, expected_demucs_output_path = run_demucs_separation(task_id, loaded_model, audio_to_process, demucs_temp_output, device=device, model_name=model_name)

            if demucs_proc:
                TASKS[task_id]['process'] = demucs_proc

                # Use the dedicated parser to handle stdout parsing.
                progress_parser = DemucsProgressParser(model_name)
                line_buffer = ""
                if demucs_proc.stdout:
                    with demucs_proc.stdout:
                        for char in iter(lambda: demucs_proc.stdout.read(1), ''):
                            if char in ['\r', '\n']:
                                if line_buffer:
                                    # --- ROBUSTNESS FIX ---
                                    # Wrap the parsing logic in a try-except block. This ensures that if
                                    # Demucs changes its output format in the future, a parsing error will
                                    # not crash the entire stem separation process. The progress bar might
                                    # stop, but the core functionality will continue.
                                    try:
                                        progress_update = progress_parser.parse_line(line_buffer)
                                        if progress_update:
                                            update_detailed_status(task_id, progress_update['stage'], progress_update['sub_stage'], 
                                                                   progress_update['progress'], progress_update['message'])
                                    except Exception as e:
                                        print(f"  -> [WARNING] Demucs progress parsing failed: {e}. Separation will continue.")
                                    check_for_cancellation(task_id)
                                
                                line_buffer = ""
                            else:
                                line_buffer += char

                demucs_proc.wait()
                TASKS[task_id]['process'] = None
                check_for_cancellation(task_id)

                if demucs_proc.returncode != 0:
                    raise Exception("Demucs separation process failed.")

        finally:
            pass # The watcher is now stopped before separation begins.

        # Move the results from the temporary location to the final stems directory.
        if not expected_demucs_output_path.exists():
            raise FileNotFoundError(f"Demucs output path not found after processing: {expected_demucs_output_path}")

        search_path = expected_demucs_output_path
        moved_files = 0
        for wav_file in search_path.glob('*.wav'):
            shutil.move(str(wav_file), stems_output_dir / wav_file.name)
            moved_files += 1
        
        if moved_files == 0:
            raise Exception("Demucs ran but produced no .wav files.")

        final_stem_path = stems_output_dir
    else:
        # This case handles pre-separated stems provided by the user.
        # We just copy them to the target stems directory.
        print("Multiple audio files detected. Treating them as pre-separated stems and copying.")
        for audio_file in files['audio']:
            dest_path = stems_output_dir / Path(audio_file['path']).name
            shutil.copy(audio_file['path'], dest_path)
    
    return final_stem_path

def convert_stems_to_midi(task_id, stems_dir, midi_output_dir, demucs_model):
    """Converts all .wav files in a directory to MIDI."""
    separated_stems = {p.stem: str(p) for p in stems_dir.glob('*.wav')}
    print(f"  -> Found {len(separated_stems)} stems to process: {list(separated_stems.keys())}")

    if not separated_stems:
        return

    num_stems = len(separated_stems)
    for i, (stem_name, stem_path) in enumerate(separated_stems.items()):
        step_message = f"Converting stem {i+1}/{num_stems} ({stem_name})..."
        update_detailed_status(task_id, 5, i + 1, 50, step_message)
        success = convert_audio_to_midi(task_id, stem_path, midi_output_dir, demucs_model=demucs_model)
        if not success:
            print(f"  -> Failed to convert '{stem_name}'. Continuing to next stem.")
        check_for_cancellation(task_id)

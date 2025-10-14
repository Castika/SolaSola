import sys
import time
import subprocess
import shutil
import traceback
from pathlib import Path
import json
import os
import re
import threading
import math

from .hardware_manager import get_processing_device
from .task_manager import TASKS, update_status, check_for_cancellation, InterruptedError, update_detailed_status
from .model_manager import get_model_path, get_all_models_status, _get_repo_size_str, create_manifest_for_model, GENRE_MODEL_REPO_ID
from .xet_manager import xet_manager
from .ui_log_manager import log_to_ui

STATS_FILE_NAME = "download_stats.json"
DEFAULT_DOWNLOAD_RATE_MB_S = 12
MAX_STATS_ENTRIES = 10

def _load_download_stats(stats_file_path: Path) -> list:
    """Loads historical download speed statistics from a JSON file."""
    if not stats_file_path.exists():
        return []
    try:
        with open(stats_file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []

def _save_download_stats(stats_file_path: Path, stats: list):
    """Saves the latest download speed statistics to a JSON file."""
    try:
        with open(stats_file_path, 'w', encoding='utf-8') as f:
            json.dump(stats, f)
    except IOError as e:
        print(f"  -> WARNING: Could not save download stats to {stats_file_path}: {e}")

def _get_adaptive_download_rate(stats_file_path: Path) -> float:
    """
    Calculates the average download rate from historical stats to provide a more
    accurate time estimate for the progress bar. Falls back to a default if no history exists.
    """
    if not stats_file_path:
        return DEFAULT_DOWNLOAD_RATE_MB_S
        
    stats = _load_download_stats(stats_file_path)
    if not stats:
        print(f"  -> No download history found. Using default rate: {DEFAULT_DOWNLOAD_RATE_MB_S} MB/s")
        return DEFAULT_DOWNLOAD_RATE_MB_S
    
    average_rate = sum(stats) / len(stats)
    print(f"  -> Using adaptive download rate based on {len(stats)} past download(s): {average_rate:.2f} MB/s")
    return average_rate

def install_model_wrapper(task_id, repo_id, ui_container_id, sse_manager, client_id, install_lock):
    """
    The main logic for handling a model installation, designed to be run in a background thread.
    It manages the download subprocess, progress reporting, and manifest creation.
    """
    download_duration = 0
    download_started_for_xet = False # Flag to ensure finish_download is always called if start_download was.
    
    try:
        # Detect hardware inside the thread, so the log appears closer to the actual work.
        device = get_processing_device()
        update_status(task_id, 5, "Starting download...")
        # Use 'target' to show a simple toast but log the specific model being downloaded.
        log_to_ui(task_id, "Downloading model...", "download", type='info', target='toast')
        log_to_ui(task_id, f"Starting download for model: {repo_id}", "download", type='info', target='log')

        # Notify the .xet cache manager that a download is starting.
        xet_manager.start_download()
        download_started_for_xet = True

        # Step 1: Run the download subprocess.
        command = [
            sys.executable,
            "-m", "solasola.sub_process.install_model",
            "--model_type", "genre", # Explicitly tell the subprocess what to do
            "--device", device,
            "--repo_id", repo_id,
        ]

        install_proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
        TASKS[task_id]['process'] = install_proc

        # Store download stats in the main AI Models directory for persistence across container restarts.
        ai_models_dir = Path(os.getenv("HF_HOME", "/app/ai_models"))
        stats_file_path = ai_models_dir / STATS_FILE_NAME if ai_models_dir else None
        base_rate_mb_per_sec = _get_adaptive_download_rate(stats_file_path)

        model_size_str, size_in_mb = _get_repo_size_str(repo_id, return_mb=True)
        
        # Estimate the download time based on the model's size and the user's historical download speed.
        # This is used to make the progress bar move at a realistic pace.
        size_match = re.search(r'([\d.]+)\s*(GB|MB|KB)', model_size_str, re.IGNORECASE)
        estimated_seconds = 30  # Default to 30s
        if size_match:
            size_val = float(size_match.group(1))
            unit = size_match.group(2).upper()
            
            if size_in_mb > 0:
                estimated_seconds = max(10, size_in_mb / base_rate_mb_per_sec)

        start_time = time.time()
        download_duration = 0

        # Read stdout line-by-line to prevent the pipe from deadlocking.
        # We use a separate thread to update the progress bar so that reading stdout (a blocking call)
        # does not prevent the progress bar from updating.
        progress_thread_stop = threading.Event()
        def update_progress_periodically():
            while not progress_thread_stop.is_set():
                check_for_cancellation(task_id)
                elapsed_time = time.time() - start_time
                
                step_text = "Downloading..."
                progress_float = (elapsed_time / estimated_seconds) * 100
                if progress_float >= 98:
                    pulse = 96 + 2 * math.sin(time.time() * math.pi / 2)
                    progress_float = min(progress_float, pulse)
                    if int(time.time()) % 2 == 0:
                        step_text = "Waiting..."

                # Broadcast the estimated progress via SSE. This is essential for the
                # installing user's (the "actor") progress bar to fill up.
                sse_manager.broadcast({
                    "action": "progress_update",
                    "payload": {
                        "actor_client_id": client_id,
                        "task_id": task_id,
                        "repo_id": repo_id,
                        "manifest_id": "",
                        "ui_container_id": ui_container_id,
                        "deletion_path": "",
                        "status": "running",
                        "progress": int(progress_float),
                        "message": step_text,
                    }
                })
                time.sleep(1)

        progress_updater = threading.Thread(target=update_progress_periodically, daemon=True)
        progress_updater.start()

        for line in iter(install_proc.stdout.readline, ''):
            print(f"  -> [Install Proc] {line.strip()}")
            check_for_cancellation(task_id)
        
        progress_thread_stop.set()
        progress_updater.join()
        install_proc.wait()

        download_duration = time.time() - start_time # This is now the actual download duration

        # Calculate and save the actual download speed for this session to improve future estimates.
        if download_duration > 1 and size_in_mb > 0 and stats_file_path:
            try:
                actual_speed_mb_s = size_in_mb / download_duration
                print(f"  -> Actual download speed for this session: {actual_speed_mb_s:.2f} MB/s")
                stats = _load_download_stats(stats_file_path)
                stats.append(actual_speed_mb_s)
                # --- FIX: Use the correct constant to limit the number of saved stats. ---
                stats = stats[-MAX_STATS_ENTRIES:]
                _save_download_stats(stats_file_path, stats)
            except Exception as e:
                # This is not a critical failure, so we just log it and continue.
                print(f"  -> WARNING: Could not update download speed statistics: {e}")

        TASKS[task_id]['process'] = None
        check_for_cancellation(task_id)

        if install_proc.returncode != 0:
            stdout, _ = install_proc.communicate()
            print(f"  -> Model installation subprocess failed.\n  -> OUTPUT: {stdout}")
            error_message = f"Installation failed. See server logs for details."
            # Try to find a more specific error in the output
            if "ERROR:" in stdout:
                error_message = stdout.split("ERROR:")[-1].strip()
            raise Exception(error_message)

        # Step 2: A brief, artificial "Verifying" step. This provides user feedback
        # that the download is complete and the system is finalizing the installation.
        update_status(task_id, 0, "Verifying...")
        # Use 'target' for concise toast and detailed log.
        log_to_ui(task_id, "Verifying installation...", "fact_check", type='info', target='toast')
        log_to_ui(task_id, "Download complete. Verifying integrity of model files...", "fact_check", type='info', target='log')

        for i in range(5):
            check_for_cancellation(task_id)
            time.sleep(1)
            progress = int(100 * ((i + 1) / 5))
            sse_manager.broadcast({
                "action": "progress_update",
                "payload": {
                    "actor_client_id": client_id, "task_id": task_id, "repo_id": repo_id,
                "manifest_id": "",
                "ui_container_id": ui_container_id,
                "deletion_path": "",
                "status": "running",
                "progress": progress,
                "message": "Verifying..."
                }
            })

        # Step 3: Create a manifest file. This file "fingerprints" the installation,
        # listing all downloaded files and their hashes, which is crucial for validation.

        # Use 'target' for concise toast and detailed log.
        log_to_ui(task_id, "Finalizing installation...", "fingerprint", type='info', target='toast')
        log_to_ui(task_id, "Verification complete. Creating installation manifest...", "fingerprint", type='info', target='log')
        update_status(task_id, 100, "Creating manifest...")
        sse_manager.broadcast({
            "action": "progress_update",
            "payload": {
                "actor_client_id": client_id, "task_id": task_id, "repo_id": repo_id,
                "manifest_id": "",
                "ui_container_id": ui_container_id,
                "deletion_path": "",
                "status": "running", "progress": 100, "message": "Creating manifest..."
            }
        })
        
        model_path = get_model_path(repo_id)

        try:
            if model_path and model_path.exists():
                # Determine the user-friendly display name for the manifest.
                model_name_for_manifest = "Genre Classifier" if repo_id == GENRE_MODEL_REPO_ID else repo_id
                if not create_manifest_for_model(repo_id, model_path, name=model_name_for_manifest, model_type="genre"):
                    raise ValueError("Failed to create a valid model manifest.")
            else:
                raise FileNotFoundError(f"Model directory not found after download: {model_path}")
        except ValueError as e:
            raise Exception(f"Failed to create a valid model manifest: {e}")


        # Use 'target' for a simple success toast and a detailed log entry.
        log_to_ui(task_id, "Model installed successfully.", "done", 'success', target='toast')
        log_to_ui(task_id, f"Model '{repo_id}' installed and verified successfully.", "done", 'success', target='log')
        final_status = update_status(task_id, 100, "Installation complete.", status='completed')
    except InterruptedError:
        update_status(task_id, TASKS[task_id]['progress'], "Installation cancelled by user.", status='cancelled')
        sse_manager.broadcast({
            "action": "status_update",
            "payload": {
                "actor_client_id": client_id, "task_id": task_id, "repo_id": repo_id, "status": "cancelled",
                "manifest_id": "", "ui_container_id": ui_container_id, "deletion_path": "", "progress": TASKS[task_id]['progress'], "message": "Installation cancelled"
            }
        })

    except Exception as e:
        print(f"Error in task {task_id}: {e}")
        traceback.print_exc()  # Log the full traceback for easier debugging
        # If installation fails, attempt to clean up the partially downloaded model directory.
        model_path_to_cleanup = get_model_path(repo_id)
        if model_path_to_cleanup and model_path_to_cleanup.exists():
            print(f"  -> Cleaning up failed installation directory: {model_path_to_cleanup}")
            shutil.rmtree(model_path_to_cleanup, ignore_errors=True)
            # Use 'target' for concise toast and detailed log.
            log_to_ui(task_id, "Installation failed. Cleaning up...", "delete", 'error', target='toast')
            log_to_ui(task_id, f"Installation failed for '{repo_id}'. Attempting to clean up partial files.", "delete", 'error', target='log')
        error_message = f"An error occurred: {e}"
        update_status(task_id, TASKS[task_id]['progress'], error_message, status='failed')
        sse_manager.broadcast({
            "action": "status_update",
            "payload": {
                "actor_client_id": client_id, "task_id": task_id, "repo_id": repo_id, "status": "failed", "message": str(e),
                "manifest_id": "", "ui_container_id": ui_container_id, "deletion_path": "", "progress": TASKS[task_id]['progress']
            }
        })

        # Use 'target' for concise toast and detailed log.
        log_to_ui(task_id, "An unexpected error occurred.", "error", 'error', target='toast')
        log_to_ui(task_id, f"An unexpected error occurred during installation of '{repo_id}': {e}", 'error', 'error', target='log')

    finally:
        if download_started_for_xet:
            xet_manager.finish_download(download_duration) # Pass 0 if it failed before duration was calculated.

        # Release the global lock and broadcast a refresh event to all clients.
        install_lock.release()
        print(f"Installation thread for task {task_id} finished. Lock released. Broadcasting refresh.")
        sse_manager.broadcast({
            "action": "refresh_all",
            "payload": {
                "actor_client_id": client_id,
                "task_id": task_id,
                "repo_id": repo_id,
                "manifest_id": "",
                "ui_container_id": ui_container_id,
                "deletion_path": "",
                "status": "completed",
                "progress": 100,
                "message": "Task finished."
            }
        })

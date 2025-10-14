from pathlib import Path
import os
import shutil
import json
import re
import threading
import time
import hashlib
import sys
import subprocess
from urllib.parse import urlparse
from huggingface_hub import model_info
from huggingface_hub.utils import HfHubHTTPError
from .task_manager import TASKS
from .utils import calculate_file_hash as calculate_file_hash_util

# Define base directories used throughout the module.
BASE_CACHE_DIR = Path("/app/cache")
BUILT_IN_MODELS_DIR = Path(os.getenv("BUILT_IN_MODELS_DIR", "/app/built_in_models"))

_size_cache = {} # In-memory cache for repo sizes
_model_status_cache = None # Server-side cache for the entire model status dictionary
_cache_lock = threading.Lock() # A lock to prevent race conditions during cache builds

def _format_size(size_bytes: int) -> str:
    """Converts bytes to a human-readable string (KB, MB, GB)."""
    if size_bytes is None:
        return "N/A"
    if size_bytes < 1024:
        return f"{size_bytes} B"
    power = 1024
    n = 0
    power_labels = {0: '', 1: 'KB', 2: 'MB', 3: 'GB', 4: 'TB'}
    while size_bytes >= power and n < len(power_labels) - 1:
        size_bytes /= power
        n += 1
    # Use 1 decimal place for MB and above, but no decimals for KB.
    if n > 1:
        return f"{size_bytes:.1f} {power_labels[n]}"
    else:
        return f"{int(size_bytes)} {power_labels[n]}"

def _get_repo_size_str(repo_id: str, return_mb: bool = False) -> tuple[str, float] | str:
    """
    Gets the total size of a Hugging Face Hub repository and formats it as a string.
    Caches the result in memory to avoid repeated API calls.
    It intelligently excludes `pytorch_model.bin` if `model.safetensors` is present.
    """
    if repo_id in _size_cache:
        size_str, size_mb = _size_cache[repo_id]
        return (size_str, size_mb) if return_mb else size_str

    try:
        info = model_info(repo_id, files_metadata=True)
        
        # If `model.safetensors` exists, we can ignore the older `pytorch_model.bin`
        # to get a more accurate representation of the required download size.
        has_safetensors = any(s.rfilename == "model.safetensors" for s in info.siblings)
        
        files_to_sum = []
        if has_safetensors:
            files_to_sum = [s for s in info.siblings if s.rfilename != "pytorch_model.bin"]
        else:
            files_to_sum = info.siblings

        total_size = sum(s.size for s in files_to_sum if s.size is not None)
        size_str = _format_size(total_size)
        size_in_mb = total_size / (1024 * 1024) if total_size else 0
        _size_cache[repo_id] = (size_str, size_in_mb)
        return (size_str, size_in_mb) if return_mb else size_str
    except HfHubHTTPError as e:
        print(f"  -> Could not fetch model info for '{repo_id}': {e}")
        _size_cache[repo_id] = ("N/A", 0) # Cache the failure to avoid repeated failed API calls.
        return ("N/A", 0) if return_mb else "N/A"
    except Exception as e:
        print(f"  -> An unexpected error occurred while fetching size for '{repo_id}': {e}")
        _size_cache[repo_id] = ("N/A", 0)
        return ("N/A", 0) if return_mb else "N/A"


# Genre Classifier Model
GENRE_MODEL_REPO_ID = "sanchit-gandhi/distilhubert-finetuned-gtzan"
GENRE_MODEL_PATH = Path(os.getenv("HF_HOME", "/app/user_models")) / "hub" / f"models--{GENRE_MODEL_REPO_ID.replace('/', '--')}"

def _get_manifest_dir() -> Path:
    """Returns the path to the dedicated directory for SolaSola's model manifests."""
    hf_home = Path(os.getenv("HF_HOME", "/app/user_models"))
    manifest_dir = hf_home / "solasola_manifests"
    manifest_dir.mkdir(exist_ok=True) # Ensure it exists
    return manifest_dir

def get_model_path(repo_id: str) -> Path:
    """
    Returns the expected path for a Hugging Face model in the local cache.
    This follows the standard caching structure used by the `huggingface-hub` library.
    """
    hf_home = Path(os.getenv("HF_HOME", "/app/user_models"))
    model_dir_name = f"models--{repo_id.replace('/', '--')}"
    return hf_home / "hub" / model_dir_name

def _get_file_list_from_directory(model_root_dir: Path) -> list[dict]:
    """
    Recursively scans a model's directory to get a list of all its constituent
    files and symlinks, which is used for creating a manifest.
    """
    file_list = []
    ignored_filenames = {'.DS_Store', '.solasola_manifest.json'}

    for item in model_root_dir.rglob('*'):
        if item.name in ignored_filenames:
            continue

        if item.is_file() or item.is_symlink():
            try:
                file_list.append({
                    # Record the path and hash of the symlink/file itself, not its resolved target.
                    "path": str(item),
                    "size": item.lstat().st_size,
                    "hash": calculate_file_hash_util(item)
                })
            except FileNotFoundError:
                print(f"  -> WARNING: Skipping broken link or missing file: {item.name}")
            except Exception as e:
                print(f"  -> WARNING: Could not process file {item.name}: {e}")
    return file_list

def delete_model_from_manifest(manifest_filename: str) -> bool:
    """
    Deletes all files listed in a given manifest file, and then deletes the manifest itself.
    This is the centralized deletion logic for all model types.
    It safely constructs the path from a filename to prevent path traversal.
    """
    # --- SECURITY FIX: Path Traversal Vulnerability ---
    # Construct the path on the server-side from a sanitized filename to prevent
    # an attacker from providing a malicious path like `../../config.yaml`.
    manifest_dir = _get_manifest_dir()
    # werkzeug.utils.secure_filename is a robust way to sanitize filenames.
    from werkzeug.utils import secure_filename
    safe_filename = secure_filename(manifest_filename)
    manifest_path = manifest_dir / safe_filename


    if not manifest_path.is_file():
        print(f"  -> ERROR: Manifest file not found for deletion: '{safe_filename}'")
        return False

    try:
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest_data = json.load(f)

        files_to_delete = manifest_data.get("files", [])
        print(f"  -> Deleting {len(files_to_delete)} files based on manifest '{manifest_path.name}'...")

        for file_info in files_to_delete:
            file_path = Path(file_info["path"])
            # Use os.remove, which correctly deletes a symlink itself, not the file it points to.
            if file_path.is_symlink() or file_path.is_file():
                print(f"    - Deleting file/symlink: {file_path}")
                try:
                    os.remove(file_path)
                except OSError as e:
                    print(f"    -> ERROR: Could not delete {file_path}: {e}")

        # Finally, delete the manifest file itself
        manifest_path.unlink()
        print(f"  -> Successfully deleted manifest file.")
        return True

    except (json.JSONDecodeError, KeyError, OSError) as e:
        print(f"  -> ERROR: Failed to process or delete files from manifest '{manifest_path.name}': {e}")
        return False

def clear_model_size_cache():
    """
    Clears all in-memory model caches. This is called on a manual refresh from the UI
    to force a complete re-scan of the disk state.
    """
    with _cache_lock:
        global _size_cache
        global _model_status_cache
        _model_status_cache = None
        _size_cache.clear()
        print("  -> Server-side caches (model status and size) cleared.")

def create_manifest_for_model(repo_id: str, model_path: Path, name: str, model_type: str) -> bool:
    """
    Creates a manifest file in the central `solasola_manifests` directory for a given model,
    "fingerprinting" its contents for future validation.
    """
    manifest_dir = _get_manifest_dir()
    manifest_filename = f"hf_{repo_id.replace('/', '--')}.json"
    manifest_path = manifest_dir / manifest_filename

    print(f"  -> Generating manifest for '{repo_id}' at '{manifest_path}'...")

    file_list = _get_file_list_from_directory(model_path)
    if not file_list:
        print(f"  -> WARNING: No files found in '{model_path}'. Manifest not created.")
        return False

    total_size = sum(f["size"] for f in file_list)
    manifest = {
        "name": name,
        "repo_id": repo_id,
        "model_type": model_type,
        "creation_timestamp": time.time(),
        "file_count": len(file_list),
        "total_size_bytes": total_size,
        "files": file_list,
    }

    try:
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2)
        print(f"  -> Successfully wrote manifest for '{repo_id}'.")
        return True
    except IOError as e:
        print(f"  -> ERROR: Could not write manifest file: {e}")
        return False

def _apply_installing_status(statuses: dict) -> dict:
    """
    Iterates through active installation tasks and marks the corresponding
    models in the status dictionary with an 'installing' flag.
    """
    active_install_tasks = {}
    for task_id, task in TASKS.items():
        if task.get('status') in ['starting', 'running'] and 'model_info' in task:
            model_info = task['model_info']
            repo_id = model_info.get('repo_id')
            if repo_id:
                active_install_tasks[repo_id] = task.get('actor_client_id')

    all_models = {**statuses.get('feature_models', {}), **statuses.get('separation_models', {})}
    for repo_id, data in all_models.items():
        data['installing'] = repo_id in active_install_tasks
        data['installer_client_id'] = active_install_tasks.get(repo_id)

    return statuses

def _build_model_status_cache():
    """The core logic for building the model status cache from scratch."""
    with _cache_lock:
        # Run a global cleanup before building the cache. This ensures the status list
        # is always 100% consistent with the actual state of the files on disk.
        try:
            print("  -> [Model Manager] Requesting model state cleanup before building status cache...")
            subprocess.run([sys.executable, "-m", "solasola.sub_process.global_model_state_watcher", "--action", "cleanup"], check=True, capture_output=True, text=True)
            print("  -> [Model Manager] Cleanup complete.")
        except Exception as e:
            # If cleanup fails, we still attempt to build the list, but log a severe warning.
            print(f"  -> CRITICAL WARNING: Failed to run model state cleanup: {e}")

        hf_home = Path(os.getenv("HF_HOME", "/app/user_models"))
        hub_dir = hf_home / "hub"

        # Get the host cache paths from the environment variables set by the startup script.
        # Provide a generic fallback message if the variable is not set.
        host_ai_models_path = os.getenv("HOST_AI_MODELS_DIR", "a folder on your computer")
        host_music_path = os.getenv("HOST_MUSIC_DIR", "a folder on your computer")
        
        # All model statuses are derived by reading the central manifest directory.
        manifest_dir = _get_manifest_dir()
        installed_repo_ids = set()
        
        feature_models = {}
        separation_models = {}

        if manifest_dir.is_dir():
            for manifest_path in manifest_dir.glob('*.json'):
                try:
                    with open(manifest_path, 'r', encoding='utf-8') as f:
                        manifest = json.load(f)

                    repo_id = manifest.get("repo_id")
                    if not repo_id:
                        continue

                    print(f"  -> Processing manifest: {manifest_path.name} for repo_id: {repo_id}")
                    installed_repo_ids.add(repo_id)
                    model_type = manifest.get("model_type", "unknown")
                    
                    # At this point, we trust that the cleanup process has already removed any invalid
                    # manifests, so we can assume the files listed here exist.

                    model_data = {
                        "name": manifest.get("name", repo_id),
                        "installed": True,
                        "size": _format_size(manifest.get('total_size_bytes', 0)),
                        "repo_id": repo_id,
                        "deletion_path": str(manifest_path)
                    }

                    if model_type == "genre":
                        feature_models[repo_id] = model_data
                    else: # demucs, etc.
                        separation_models[repo_id] = model_data

                except (IOError, json.JSONDecodeError, KeyError) as e:
                    print(f"  -> WARNING: Skipping corrupted or invalid manifest {manifest_path.name}: {e}")

        # After checking installed models, add entries for any known models that are not installed.
        if GENRE_MODEL_REPO_ID not in installed_repo_ids:
            feature_models[GENRE_MODEL_REPO_ID] = {
                "name": "Genre Classifier", "installed": False, "size": _get_repo_size_str(GENRE_MODEL_REPO_ID), "repo_id": GENRE_MODEL_REPO_ID, "deletion_path": ""
            }

        status = {
            "feature_models": feature_models,
            "separation_models": separation_models,
            "host_ai_models_path": host_ai_models_path,
            "host_processing_cache_path": host_music_path,
        }
        
        global _model_status_cache
        _model_status_cache = status # Store in cache
        print("  -> Model status cache has been built.")
        return status

def get_all_models_status(force_refresh=False) -> dict:
    """
    Checks the installation status of all on-demand models.
    Caches the result in memory for the duration of the server session.
    This function always rebuilds the cache to reflect real-time disk changes.
    The underlying build function is thread-safe.
    """
    status = _build_model_status_cache()
    return _apply_installing_status(status)

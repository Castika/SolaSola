import argparse
import json
import os
import time
from pathlib import Path
import tempfile
from solasola.utils import get_ai_models_dir, get_manifest_dir, is_path_excluded, calculate_file_hash
def _get_state_file_path(task_id: str) -> Path:
    """Gets the path to the temporary state file for a given task."""
    return Path(tempfile.gettempdir()) / f"solasola_watcher_{task_id}.state"

def get_current_state(ai_models_dir: Path) -> dict:
    """
    Scans the target directory and returns a dictionary of file paths and their
    metadata.
    """
    state = {}
    for root, dirs, files in os.walk(ai_models_dir, topdown=True):
        # Prune excluded directories to avoid scanning them
        dirs[:] = [d for d in dirs if not is_path_excluded(Path(root) / d, # noqa
                                                          ai_models_dir)] # noqa

        for name in files:
            file_path = Path(root) / name
            if not is_path_excluded(file_path, ai_models_dir):
                try:
                    # Use lstat() to get info about the symlink itself, not its target file. # noqa
                    # This is crucial for correct hash and size validation.
                    stat = file_path.lstat() 
                    state[str(file_path)] = {
                        "size": stat.st_size, # This will now be the size of the symlink
                        "mtime": stat.st_mtime
                    }
                except FileNotFoundError:
                    # File might have been deleted during the scan, just skip it.
                    continue
    return state


def start_watching(task_id: str):
    """Records the initial state of the model directory."""
    print("--- Demucs Download Watcher: START ---")
    ai_models_dir = get_ai_models_dir()
    state_file = _get_state_file_path(task_id)

    print(f"  -> Capturing initial state of '{ai_models_dir}'...")
    initial_state = get_current_state(ai_models_dir)

    with open(state_file, 'w', encoding='utf-8') as f:
        json.dump(initial_state, f)

    print(f"  -> Initial state with {len(initial_state)} files saved to "
          "temporary state file.")
    print("--- Watcher is now in waiting state. ---")


def stop_watching_and_register(task_id: str, model_name: str):
    """Compares states, finds new files, and creates a manifest if needed."""
    print("--- Demucs Download Watcher: STOP ---")
    ai_models_dir = get_ai_models_dir()
    manifest_dir = get_manifest_dir(ai_models_dir)
    state_file = _get_state_file_path(task_id)

    if not state_file.exists():
        print("  -> ERROR: Initial state file not found. Cannot determine "
              "changes.")
        return

    print("  -> Capturing final state...")
    final_state = get_current_state(ai_models_dir)

    with open(state_file, 'r', encoding='utf-8') as f:
        initial_state = json.load(f)

    # Find new files by comparing the keys (file paths) of the two states
    new_files = set(final_state.keys()) - set(initial_state.keys())

    if not new_files:
        print("  -> No new model files were detected. No manifest will be created.")
    else:
        print(f"  -> Detected {len(new_files)} new file(s). Generating manifest...")

        manifest_files = []
        total_size = 0
        for file_path_str in new_files:
            file_path = Path(file_path_str)
            size = file_path.lstat().st_size
            total_size += size
            manifest_files.append({
                "path": file_path_str,
                "size": size,
                "hash": calculate_file_hash(file_path)
            })

        manifest_data = {
            "name": f"Demucs - {model_name}",
            # For Demucs, the name is the unique ID
            "repo_id": model_name,
            "model_type": "separation",
            "creation_timestamp": time.time(),
            "file_count": len(manifest_files),
            "total_size_bytes": total_size,
            "files": manifest_files
        }

        # e.g., demucs_htdemucs_ft.json
        manifest_filename = f"demucs_{model_name}.json"
        manifest_path = manifest_dir / manifest_filename

        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest_data, f, indent=2)

        print(f"  -> Successfully created manifest: {manifest_path.name}")

    # Cleanup the temporary state file
    try:
        os.remove(state_file)
        print("  -> Cleaned up temporary state file.")
    except OSError as e:
        print(f"  -> WARNING: Could not remove state file {state_file}: {e}")

    print("--- Watcher finished. ---")


def main():
    """Main entry point for the download watcher script."""
    parser = argparse.ArgumentParser(
        description="SolaSola Demucs Download Watcher.")
    parser.add_argument("--action", required=True, choices=['start', 'stop'],
                        help="The action to perform.")
    parser.add_argument("--task-id", required=True,
                        help="The unique ID of the processing task.")
    parser.add_argument("--model-name",
                        help="The name of the Demucs model being used "
                             "(required for 'stop').")
    args = parser.parse_args()

    if args.action == 'start':
        start_watching(args.task_id)
    elif args.action == 'stop':
        if not args.model_name:
            print("Error: --model-name is required for the 'stop' action.")
            exit(1)
        stop_watching_and_register(args.task_id, args.model_name)


if __name__ == "__main__":
    main()
"""
Performs a global cleanup of the AI models directory.
Removes orphaned files and validates known models.
"""
import argparse
import json
import os
from pathlib import Path

from solasola.utils import (get_ai_models_dir, get_manifest_dir,
                            is_path_excluded, calculate_file_hash)


def cleanup():
    """
    Performs a comprehensive cleanup of the entire AI models cache directory.
    """
    print("--- SolaSola Global Model Watcher: Starting Cleanup ---")
    ai_models_dir = get_ai_models_dir()
    manifest_dir = get_manifest_dir(ai_models_dir)

    known_files = set()
    all_manifests = list(manifest_dir.glob('*.json'))
    manifests_to_check = {}

    # Step 1: Build a set of all "known" files.
    for manifest_path in all_manifests:
        known_files.add(manifest_path)
        try: # noqa
            with open(manifest_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if 'files' in data and isinstance(data['files'],
                                              list):
                manifest_file_paths = {Path(f['path']) for f in data['files']}
                known_files.update(manifest_file_paths)
                manifests_to_check[manifest_path] = data['files']
        except (json.JSONDecodeError, KeyError) as e:
            print(f"  -> WARNING: Could not read or parse manifest "
                  f"{manifest_path.name}: {e}")

    # Step 2: Delete any "orphaned" files.
    print("\n  -> Scanning for orphaned model files...")
    for root, dirs, files in os.walk(ai_models_dir):
        dirs[:] = [d for d in dirs if not is_path_excluded(Path(root) / d, ai_models_dir)]
        for name in files: # noqa
            file_path = Path(root) / name
            if (not is_path_excluded(file_path, ai_models_dir) and
                    file_path not in known_files):
                print(f"  -> Deleting orphaned file: "
                      f"{file_path.relative_to(ai_models_dir)}")
                try:
                    os.remove(file_path)
                except OSError as e:
                    print(f"    -> ERROR: Could not delete file: {e}")

    # Step 3: Verify integrity of "known" files.
    print("\n  -> Verifying integrity of known files...")
    for manifest_path, files_in_manifest in manifests_to_check.items():
        for file_info in files_in_manifest:
            manifest_path_obj = Path(file_info['path'])
            expected_hash = file_info.get('hash')
            if (manifest_path_obj.exists() and
                    calculate_file_hash(manifest_path_obj) != expected_hash):
                print(
                    f"  -> Deleting corrupted file (hash mismatch): "
                    f"{manifest_path_obj.relative_to(ai_models_dir)}")
                os.remove(manifest_path_obj)

    # Step 4: Delete manifests pointing to missing files.
    print("\n  -> Scanning for orphaned manifests...")
    for manifest_path, files_in_manifest in manifests_to_check.items():
        if any(not Path(f['path']).exists() for f in files_in_manifest):
            print(f"  -> Deleting orphaned manifest: {manifest_path.name}")
            try:
                os.remove(manifest_path)
            except OSError as e:
                print(f"    -> ERROR: Could not delete manifest: {e}")

    print("\n--- Global Cleanup Complete ---")


def main():
    parser = argparse.ArgumentParser(
        description="SolaSola Global Model State Watcher.")
    parser.add_argument("--action", required=True, choices=['cleanup'],
                        help="The action to perform.")
    args = parser.parse_args()

    if args.action == 'cleanup':
        cleanup()


if __name__ == "__main__":
    main()

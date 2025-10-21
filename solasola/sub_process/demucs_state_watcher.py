"""
Performs an integrity check for Demucs models.
This script validates that all files for installed Demucs models exist and are
not corrupted. If an issue is found, it removes the model's manifest file.
"""
import argparse
import json
import os
from pathlib import Path

from solasola.utils import (get_ai_models_dir, get_manifest_dir,
                            calculate_file_hash)


def cleanup():
    """
    Validates all installed Demucs models by reading their manifests, verifying
    file existence and hashes, and deleting invalid manifests.
    """
    print("--- SolaSola Demucs Watcher: Starting Cleanup ---")
    ai_models_dir = get_ai_models_dir()
    manifest_dir = get_manifest_dir(ai_models_dir)

    manifests_to_check = {}

    for manifest_path in manifest_dir.glob('*.json'):
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # This watcher only cares about Demucs ('separation') models.
            if (data.get("model_type") == "separation" and 'files' in data and
                    isinstance(data['files'], list)):
                manifests_to_check[manifest_path] = data['files']
            else:
                pass  # Silently skip non-demucs manifests.
        except (json.JSONDecodeError, KeyError) as e:
            print(f"  -> WARNING: Could not read or parse manifest "
                  f"{manifest_path.name}: {e}")

    # Verify integrity of all known Demucs models from their manifests.
    print("\n  -> Verifying integrity of Demucs model files...")
    for manifest_path, files_in_manifest in manifests_to_check.items():
        is_valid = True
        for file_info in files_in_manifest:
            path_obj = Path(file_info['path'])
            expected_hash = file_info.get('hash')
            if not path_obj.exists():
                is_valid = False
                break
            # Demucs files are not symlinks, so direct hash is correct.
            if calculate_file_hash(path_obj) != expected_hash:
                is_valid = False
                break

        if not is_valid:
            print(f"  -> Deleting invalid or corrupted Demucs manifest: "
                  f"{manifest_path.name}")
            try:
                os.remove(manifest_path)
            except OSError as e:
                print(f"    -> ERROR: Could not delete manifest: {e}")

    print("\n--- Cleanup Complete ---")


def main():
    """Main entry point for the Demucs state watcher script."""
    parser = argparse.ArgumentParser(
        description="SolaSola Demucs Model State Watcher.")
    parser.add_argument("--action", required=True, choices=['cleanup'],
                        help="The action to perform.")
    args = parser.parse_args()

    if args.action == 'cleanup':
        cleanup()


if __name__ == "__main__":
    main()
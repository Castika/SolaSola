import os
import shutil
from pathlib import Path
import logging
import json
import hashlib

from .task_manager import TASKS
from .ui_log_manager import log_to_ui

def _validate_processing_cache(directory: Path) -> bool:
    """Validates a cache directory against its manifest."""
    manifest_path = directory / ".solasola_manifest.json"
    if not manifest_path.is_file():
        return False

    try:
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest_data = json.load(f)

        if "files" not in manifest_data or not manifest_data["files"]:
            return False

        # Ensure cache contains expected output files.
        asset_type = directory.name
        expected_extensions = {
            'stems': '.wav',
            'midi': '.mid',
            'abc_files': '.abc',
        }
        expected_ext = expected_extensions.get(asset_type)
        if expected_ext and not any(f['name'].endswith(expected_ext) for f in manifest_data['files']):
            print(f"  -> Invalid cache for '{asset_type}': No '{expected_ext}' files found in manifest.")
            return False

        # Verify every file in the manifest exists.
        for file_info in manifest_data["files"]:
            file_path = directory / file_info["name"]
            if not file_path.is_file() or file_path.stat().st_size != file_info["size"]:
                return False
        
        return True
    except (json.JSONDecodeError, IOError, KeyError) as e:
        print(f"  -> Processing cache validation failed for {directory} due to manifest read error: {e}")
        return False

def _safe_copy_tree(source_dir: Path, dest_dir: Path):
    """Recursively copies a directory, ignoring if it exists."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    for item in source_dir.iterdir():
        dest_item_path = dest_dir / item.name
        if item.is_dir():
            _safe_copy_tree(item, dest_item_path)
        else: # It's a file
            shutil.copy2(item, dest_item_path)

class CacheResolver:
    """
    Handles cache lookups, validation, and copying.
    """
    def __init__(self, task_id: str, base_output_dir: Path, fingerprint: str, result_dir: Path):
        self.task_id = task_id
        # Path inside container, mounted from host.
        self.base_output_dir = base_output_dir
        self.fingerprint = fingerprint
        self.result_dir = result_dir
        self.candidate_folders = self._find_candidate_folders()
        self.provenance = {}

    def _find_candidate_folders(self) -> list[Path]:
        """Finds folders matching fingerprint, latest first."""
        candidates = []
        if not self.base_output_dir.is_dir():
            return []
            
        for folder in self.base_output_dir.iterdir():
            if folder.is_dir() and self.fingerprint in folder.name:
                candidates.append(folder)
        
        candidates.sort(key=lambda p: p.name, reverse=True)
        logging.info(f"Found {len(candidates)} cache candidates for fingerprint '{self.fingerprint}'.")
        return candidates

    def resolve(self, asset_type: str) -> dict:
        """
        Resolves an asset, using cache if valid.
        """
        logging.info(f"Attempting to resolve cache for asset type: '{asset_type}'")
        destination_path = self.result_dir / asset_type

        for candidate_folder in self.candidate_folders:
            source_path = candidate_folder / asset_type
            if source_path.is_dir() and _validate_processing_cache(source_path):
                logging.info(f"  -> CACHE HIT: Found valid '{asset_type}' in '{candidate_folder.name}'.")
                log_messages = {
                    "stems": ("Skipping stem separation (previously processed).", "skip_next"),
                    "midi": ("Skipping MIDI conversion (previously processed).", "skip_next"),
                    "abc_files": ("Skipping ABC notation generation (previously processed).", "skip_next"),
                    "chords": ("Skipping chord analysis (previously processed).", "skip_next"),
                }
                message, icon = log_messages.get(asset_type, (f"Re-using cached {asset_type}.", "inventory_2"))

                # Use 'target' for concise toast and detailed log.
                log_to_ui(self.task_id, "Found previously analyzed files. Re-using.", icon, 'info', target='toast')
                log_to_ui(self.task_id, f"Re-using previously analyzed '{asset_type}' files from project '{candidate_folder.name}'.", icon, 'info', target='log')
                
                try:
                    _safe_copy_tree(source_path, destination_path)
                    logging.info(f"  -> Copied '{asset_type}' from cache to '{self.result_dir.name}'.")
                    
                    self.provenance[asset_type] = {
                        "status": "COPIED_FROM_CACHE",
                        "source": str(candidate_folder)
                    }
                    return {"action": "USE_EXISTING", "path": destination_path}
                except Exception as e:
                    logging.error(f"  -> FAILED to copy cache for '{asset_type}' from '{source_path}': {e}")

        # No valid cache found.
        logging.info(f"  -> CACHE MISS: No valid cache found for '{asset_type}'. Processing from scratch.")

        # Show specific message for user-provided stems.
        if asset_type == 'stems' and self.task_id in TASKS and len(TASKS[self.task_id].get('input_files', {}).get('audio', [])) > 1:

            log_to_ui(self.task_id, "Processing provided stems...", "input", type='info', target='toast')
            log_to_ui(self.task_id, "Multiple audio files detected. Treating as pre-separated stems.", "input", type='info', target='log')
        else:
            log_messages = {
                "stems": ("Starting stem separation...", "call_split"),
                "midi": ("Converting stems to MIDI...", "piano"),
                "abc_files": ("Generating ABC notation...", "music_note"),
                "chords": ("Analyzing chords...", "compost")
            }
            message, icon = log_messages.get(asset_type, (f"Processing {asset_type} files...", "info"))

            log_to_ui(self.task_id, message, icon, 'info', target='toast')
            log_to_ui(self.task_id, f"Processing {asset_type} files...", icon, 'info', target='log')

        destination_path.mkdir(parents=True, exist_ok=True)
        self.provenance[asset_type] = {
            "status": "CREATED_NEW",
            "source": None
        }
        return {"action": "CREATE_NEW", "path": destination_path}

    @staticmethod
    def get_file_hash(file_path: str) -> str:
        """Computes the SHA256 hash of a file."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def write_manifest_for_step(self, asset_type: str):
        """Creates a manifest for a processing step's output."""
        directory = self.result_dir / asset_type
        
        expected_extensions = {
            'stems': '.wav',
            'midi': '.mid',
            'abc_files': '.abc',
            'chords': ('.srt', '.txt') # Chords can be multiple types
        }
        expected_ext = expected_extensions.get(asset_type)
        if expected_ext:
            has_valid_files = any(p.name.endswith(expected_ext) for p in directory.iterdir() if p.is_file())
            if not has_valid_files:
                logging.warning(f"  -> No valid output files found for '{asset_type}'. Skipping manifest creation.")
                return

        manifest_path = directory / ".solasola_manifest.json"
        files_data = [{"name": p.name, "size": p.stat().st_size} for p in directory.iterdir() if p.is_file() and p.name != ".solasola_manifest.json"]
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump({"files": files_data}, f, indent=2)
        logging.info(f"  -> Wrote cache manifest for {asset_type} at {directory}")
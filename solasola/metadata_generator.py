import json
import time
import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone

def _safe_write_json(data: dict, dest_path: Path) -> Path:
    """
    Writes a dictionary to a JSON file. If a file with the same name already
    exists (which is unlikely but possible in a race condition), it finds a new
    name by appending a suffix like '_1', '_2', etc.
    Returns the path of the actually written file.
    """
    path_to_write = dest_path
    if dest_path.exists():
        i = 1
        while True:
            new_dest_path = dest_path.parent / f"{dest_path.stem}_{i}{dest_path.suffix}"
            if not new_dest_path.exists():
                path_to_write = new_dest_path
                break
            i += 1
    
    with open(path_to_write, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    
    return path_to_write

class MetadataGenerator:
    """
    Collects all processing information for a task and generates the final
    `info.json` and `info.txt` files that are saved in the result directory.
    """
    def __init__(self, task_id: str, version_info: dict, result_dir: Path, local_timestamp: datetime):
        self.result_dir = result_dir
        
        # Combine version and build number into a single, user-friendly string.
        version_str = version_info.get('version', 'N/A')
        build_str = version_info.get('build', '0')
        full_version_str = f"{version_str} (build {build_str})"

        self.metadata = {
            "project_info": {
                "sola_sola_version": full_version_str,
                "processing_id": task_id,
                "processing_timestamp_local": local_timestamp.isoformat(),
                "processing_duration": "N/A",
            },
            "input_info": {},
            "settings_info": {},
            "cache_provenance": {},
            "output_info": {
                "files": [], # This is populated by the .txt report generator, not stored in the JSON.
                "guidance": "This folder is self-contained and can be safely moved or deleted without affecting other analysis results."
            },
            "song_profile": {},
            "results": {} # For final ABC, SRT, etc.
        }

    def add_input_info(self, classified_files: dict, original_filenames: list):
        """Adds information about the input files."""
        self.metadata["input_info"]["original_filenames"] = original_filenames
        # This part is currently not used but is kept for potential future features.
        file_hashes = {}
        for file_type, files in classified_files.items():
            for f in files:
                # Assuming 'hash' is added to the file dict during fingerprinting
                if 'hash' in f:
                    file_hashes[f['name']] = f['hash']
        self.metadata["input_info"]["file_hashes"] = file_hashes

    def add_settings_info(self, settings: dict):
        """Adds information about the processing settings used."""
        self.metadata["settings_info"] = settings

    def add_cache_provenance(self, provenance: dict):
        """Adds the cache provenance data from the CacheResolver."""
        self.metadata["cache_provenance"] = provenance

    def add_processing_time(self, duration_str: str):
        """Adds the total processing duration."""
        self.metadata["project_info"]["processing_duration"] = duration_str

    def add_final_results(self, results: dict):
        """Adds the final user-facing results (ABC, SRT, etc.)."""
        self.metadata["results"] = results

    def add_song_profile(self, profile: dict):
        """Adds the generated song profile data."""
        self.metadata["song_profile"] = profile

    def _generate_txt_report(self) -> str:
        """Generates a human-readable .txt summary from the collected metadata."""
        report = []
        info = self.metadata

        report.append("--- SolaSola Analysis Report ---")
        report.append(f"Version: {info['project_info']['sola_sola_version']}")
        report.append(f"Processing ID: {info['project_info']['processing_id']}")
        report.append(f"Timestamp (Local): {info['project_info']['processing_timestamp_local']}")
        report.append(f"Processing Time: {info['project_info']['processing_duration']}")
        report.append("\n--- Settings ---")
        for key, value in info['settings_info'].items():
            report.append(f"{key.replace('_', ' ').title()}: {value}")
        
        report.append("\n--- Input Files ---")
        for name in info['input_info'].get('original_filenames', []):
            report.append(f"- {name}")

        report.append("\n--- Cache Summary ---")
        for asset, prov in info['cache_provenance'].items():
            status = prov['status'].replace('_', ' ').title()
            if prov['status'] == 'COPIED_FROM_CACHE':
                source_folder = Path(prov['source']).name
                report.append(f"- {asset.title()}: {status} (from {source_folder})")
            else:
                report.append(f"- {asset.title()}: {status}")

        # Add the key-value pairs from the generated song profile.
        if info.get("song_profile"):
            report.append("\n--- Song Profile ---")
            # Filter out raw data fields from the text report
            profile_items = {k: v for k, v in info["song_profile"].items() if not (
                k.endswith('_srt') or k.endswith('_text') or k.startswith('is_') or k.startswith('lyrics_')
            )}
            for key, value in profile_items.items():
                report.append(f"{key}: {value}")

        report.append("\n--- Output Files ---")
        for file_path in self.result_dir.rglob('*'):
            # Exclude internal manifest files from the user-facing report.
            if file_path.is_file() and file_path.name != ".solasola_manifest.json":
                report.append(f"- {file_path.relative_to(self.result_dir)}")

        report.append(f"\n--- Notes ---\n{info['output_info']['guidance']}")
        return "\n".join(report)

    def write_metadata(self):
        """Writes the collected metadata to info.json and info.txt."""
        # Create a copy for serialization that excludes the bulky 'results' dictionary
        # (which contains full ABC/SRT content) to keep the JSON file focused on metadata.
        metadata_for_disk = self.metadata.copy()
        if "results" in metadata_for_disk:
            del metadata_for_disk["results"]

        # Write JSON file
        json_path = self.result_dir / "info.json"
        _safe_write_json(metadata_for_disk, json_path)
        
        # Write TXT file
        txt_report = self._generate_txt_report()
        txt_path = self.result_dir / "info.txt"
        txt_path.write_text(txt_report, encoding='utf-8')
        logging.info(f"Successfully wrote metadata files to {self.result_dir.name}")
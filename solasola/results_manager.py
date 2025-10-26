import os
import json
import shutil
import io
import zipfile
import logging
from pathlib import Path
import hashlib
import re
from flask import (Blueprint, render_template, jsonify, request,
                   send_file, current_app, abort)
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

# Blueprint for the results manager, organizing it as a modular component.
results_manager_bp = Blueprint('results_manager', __name__)

def get_base_output_dir():
    """Get the base output directory from the current app's config."""
    return Path(current_app.config.get('BASE_OUTPUT_DIR', '/app/output'))

def get_serializer():
    """Creates a serializer instance with the app's secret key."""
    return URLSafeTimedSerializer(current_app.secret_key)


def _count_files_in_subdirs(base_path, subdirs):
    """Counts files in specified subdirectories."""
    counts = {}
    for subdir_name in subdirs:
        subdir_path = base_path / subdir_name
        if subdir_path.is_dir():
            counts[subdir_name] = len([f for f in subdir_path.iterdir() if f.is_file()])
    return counts

def _get_folder_stats(folder_path: Path):
    """Recursively calculates the total size and file count of a folder."""
    total_size = 0
    file_count = 0
    try:
        for f in folder_path.rglob('*'):
            if f.is_file():
                total_size += f.stat().st_size
                file_count += 1
    except Exception as e:
        logging.warning(f"Could not calculate stats for {folder_path}: {e}")
    return {"size": total_size, "file_count": file_count}

def _generate_report_from_json_data(data: dict, item_path: Path) -> str:
    """Generates a human-readable .txt summary from the parsed info.json data."""
    report = []
    info = data

    report.append("--- SolaSola Analysis Report ---")
    report.append(f"Version: {info.get('project_info', {}).get('sola_sola_version', 'N/A')}")
    report.append(f"Processing ID: {info.get('project_info', {}).get('processing_id', 'N/A')}")
    report.append(f"Timestamp (Local): {info.get('project_info', {}).get('processing_timestamp_local', 'N/A')}")
    report.append(f"Processing Time: {info.get('project_info', {}).get('processing_duration', 'N/A')}")
    report.append("\n--- Settings ---")
    for key, value in info.get('settings_info', {}).items():
        report.append(f"{key.replace('_', ' ').title()}: {value}")
    
    report.append("\n--- Input Files ---")
    for name in info.get('input_info', {}).get('original_filenames', []):
        report.append(f"- {name}")

    report.append("\n--- Cache Summary ---")
    for asset, prov in info.get('cache_provenance', {}).items():
        status = prov.get('status', 'UNKNOWN').replace('_', ' ').title()
        source_folder = Path(prov['source']).name if prov.get('source') else None
        report.append(f"- {asset.title()}: {status}" + (f" (from {source_folder})" if source_folder else ""))

    if info.get("song_profile"):
        report.append("\n--- Song Profile ---")
        profile_items = {k: v for k, v in info["song_profile"].items() if not (k.endswith('_srt') or k.endswith('_text') or k.startswith('is_') or k.startswith('lyrics_'))}
        for key, value in profile_items.items():
            report.append(f"{key}: {value}")

    return "\n".join(report)

def _parse_settings_from_txt(report_content: str) -> dict:
    """Parses settings like mode and device from the content of an info.txt file."""
    settings = {'mode': 'na', 'processing_device': 'na'}
    
    mode_match = re.search(r"Mode:.*?Analysis \((.*?)\)", report_content)
    if mode_match:
        mode_text = mode_match.group(1).lower()
        if 'deep' in mode_text: settings['mode'] = 'Deep'
        elif 'fast6' in mode_text: settings['mode'] = 'Fast6'
        elif 'fast' in mode_text: settings['mode'] = 'Fast'

    device_match = re.search(r"Processing (?:Device|hardware): (.*?)(?: \(|)", report_content)
    if device_match:
        device_text = device_match.group(1).lower()
        if 'gpu' in device_text: settings['processing_device'] = 'GPU'
        elif 'cpu' in device_text: settings['processing_device'] = 'CPU'

    return settings


@results_manager_bp.route('/library')
def library_page():
    """Renders the main UI page for the results library."""
    return render_template('library.html')

@results_manager_bp.route('/api/results', methods=['GET'])
def get_results():
    """
    Scans the output directory and returns a detailed list of analysis results.
    It safely handles missing or corrupted metadata files.
    """
    results = []
    base_dir = get_base_output_dir()
    if not base_dir.is_dir():
        return jsonify([])

    # Iterate through each item in the base output directory.
    for item in sorted(base_dir.iterdir(), key=os.path.getmtime, reverse=True):
        if not item.is_dir():
            continue

        folder_name = item.name
        info_path = item / 'info.json'
        report_path = item / 'info.txt'  # Human-readable report
        s = get_serializer()
        deletion_token = s.dumps(folder_name, salt='delete-folder')
        processing_marker_path = item / 'on_processing.json'
        folder_stats = _get_folder_stats(item)
        
        # Check if the folder is currently being processed by looking for a marker file.
        if processing_marker_path.is_file():
            results.append({
                "folder_name": folder_name,
                "title": folder_name,
                "analyzed_at": None,
                "is_processing": True, # Add a flag for the frontend
                "folder_stats": folder_stats,
                "deletion_token": None, # No token for processing items
                "details": {}
            })
        elif report_path.is_file(): # Prioritize info.txt for display
            title = folder_name
            analyzed_at = None
            settings_info = {}
            settings_info = {} # --- FIX: Initialize settings_info ---
            details_data = {} # --- FIX: Prepare a dict for details ---
            
            # Parse info.txt for settings if info.json is missing
            report_text = report_path.read_text(encoding='utf-8')
            settings_info = _parse_settings_from_txt(report_text)

            if info_path.is_file():
                try:
                    with open(info_path, 'r', encoding='utf-8') as f:
                        data = json.load(f) # noqa
                    # --- FIX: Restore correct title parsing from original_filenames ---
                    # The title should be derived from the original filename if available.
                    original_filenames = data.get('input_info', {}).get('original_filenames', [])
                    if original_filenames:
                        title = original_filenames[0]
                    else:
                        title = folder_name
                    analyzed_at = data.get('project_info', {}).get('processing_timestamp_local')
                    # Overwrite parsed settings if info.json is available and has them
                    if data.get('settings_info'):
                        settings_info = data.get('settings_info')
                    details_data = data
                except (json.JSONDecodeError, KeyError, IndexError):
                    pass # Ignore errors, we have the txt as fallback.
            
            # Check for lyrics file existence directly in the filesystem
            has_lyrics = any((item / "lyrics").glob("*.srt"))
            details_data.setdefault('input_info', {})['has_lyrics'] = has_lyrics

            results.append({
                "folder_name": folder_name,
                "title": title,
                "analyzed_at": analyzed_at,
                "is_degraded": True, # Force text view because we are prioritizing info.txt
                "settings_info": settings_info,
                "has_lyrics": has_lyrics,
                "folder_stats": folder_stats,
                "deletion_token": deletion_token,
                "details": {
                    "report_text": report_text,
                    **details_data}
            })
        elif info_path.is_file():
            try:
                with open(info_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                report_text = _generate_report_from_json_data(data, item)
                original_filenames = data.get('input_info', {}).get('original_filenames', [])
                if original_filenames:
                    title = original_filenames[0]
                else:
                    title = folder_name
                analyzed_at = data.get('project_info', {}).get('processing_timestamp_local')
                settings_info = data.get('settings_info', {})
                # Check if any of the input files were lyrics files.
                has_lyrics = any((item / "lyrics").glob("*.srt"))
                
                # Inject the calculated 'has_lyrics' status into the data object.
                data.setdefault('input_info', {})['has_lyrics'] = has_lyrics
                results.append({
                    "folder_name": folder_name, "title": title, "analyzed_at": analyzed_at, "is_degraded": False, "settings_info": settings_info, "has_lyrics": has_lyrics,
                    "folder_stats": folder_stats,
                    "deletion_token": deletion_token,
                    "details": {"report_text": report_text, **data}
                })
            except (json.JSONDecodeError, KeyError, IndexError) as e:
                logging.warning(f"Could not process metadata for '{folder_name}': {e}")
                results.append({
                    "folder_name": folder_name, "title": folder_name, "analyzed_at": None, "is_degraded": True, "settings_info": {}, "has_lyrics": False, "folder_stats": folder_stats, "deletion_token": None, "details": {"report_text": "info.json is corrupted. No other information available."}
                })
        else:
            has_lyrics = any((item / "lyrics").glob("*.srt")) # Check for lyrics file existence directly

            results.append({
                "folder_name": folder_name,
                "title": folder_name, # Use folder name as a fallback title.
                "has_lyrics": False,
                "settings_info": {},
                "folder_stats": folder_stats, "is_degraded": True, "deletion_token": None, "details": {
                    "report_text": "No information available for this folder.",
                    "settings_info": {}, "input_info": {"has_lyrics": has_lyrics}
                }
            })
            
    return jsonify(results)

@results_manager_bp.route('/api/results/status', methods=['GET'])
def get_results_status():
    """
    Calculates a hash representing the current state of the results directory.
    This is a lightweight endpoint for clients to poll for changes.
    The hash is based on folder names and their modification times.
    """
    base_dir = get_base_output_dir()
    if not base_dir.is_dir():
        return jsonify({"hash": ""})

    try:
        # Create a string that represents the state of all subdirectories.
        # Format: "foldername1:mtime1,foldername2:mtime2,..."
        dir_state_parts = []
        for item in sorted(base_dir.iterdir()):
            if item.is_dir():
                dir_state_parts.append(f"{item.name}:{item.stat().st_mtime}")
        state_string = ",".join(dir_state_parts)
        return jsonify({"hash": hashlib.md5(state_string.encode('utf-8')).hexdigest()})
    except Exception as e:
        logging.error(f"Error calculating results status hash: {e}")
        return jsonify({"error": "Failed to get directory status."}), 500

@results_manager_bp.route('/api/results/<path:folder_name>', methods=['DELETE'])
def delete_result(folder_name: str):
    """Deletes a result folder, but only if a valid, timed token is provided."""
    base_dir = get_base_output_dir()
    s = get_serializer()
    token = request.json.get('token')

    if not token:
        logging.error("SECURITY ALERT: Deletion attempt without a token.")
        abort(403)  # Forbidden

    try:
        # Validate the token. It must be valid, not expired (max_age=60s),
        # and the folder name inside the token must match the one in the URL.
        unpacked_folder_name = s.loads(token, salt='delete-folder', max_age=60)
        if unpacked_folder_name != folder_name:
            raise BadSignature("Token does not match the requested folder.")
    except SignatureExpired:
        logging.warning(f"SECURITY: Expired deletion token received for '{folder_name}'.")
        abort(408)  # Request Timeout
    except BadSignature:
        logging.error(f"SECURITY ALERT: Invalid deletion token received for '{folder_name}'.")
        abort(403)  # Forbidden

    # --- SECURITY BEST PRACTICE ---
    # After validation, exclusively use the folder name extracted from the trusted token
    # to construct the path, not the one from the URL.
    target_path = base_dir / unpacked_folder_name

    if not target_path.is_dir():
        return jsonify({'error': 'Folder not found.'}), 404

    try:
        shutil.rmtree(target_path)
        logging.info(f"Successfully deleted folder: {target_path}")
        return jsonify({'status': 'ok', 'message': 'Folder deleted successfully.'})
    except Exception as e:
        logging.error(f"Error deleting folder {unpacked_folder_name}: {e}")
        return jsonify({'error': 'Failed to delete folder on the server.'}), 500

@results_manager_bp.route('/api/results/<path:folder_name>/download', methods=['GET'])
def download_result(folder_name: str):
    """Compresses a result folder into a ZIP file and sends it for download."""
    base_dir = get_base_output_dir()

    # --- SECURITY: Robust Path Traversal Prevention ---
    normalized_path_part = os.path.normpath(folder_name)

    if ".." in normalized_path_part.split(os.sep) or normalized_path_part.startswith('/'):
        logging.error(f"SECURITY ALERT: Path traversal attempt detected in DOWNLOAD: {folder_name}")
        abort(403)

    from werkzeug.utils import secure_filename
    safe_folder_name = secure_filename(normalized_path_part)
    if safe_folder_name != normalized_path_part:
        logging.error(f"SECURITY ALERT: Potentially malicious folder name provided for DOWNLOAD: {folder_name}")
        abort(403)

    target_path = base_dir / safe_folder_name

    if not target_path.is_dir():
        return jsonify({'error': 'Folder not found.'}), 404

    # Create a ZIP file in memory.
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(target_path):
            for file in files:
                file_path = Path(root) / file
                # The arcname is the path inside the ZIP file.
                arcname = file_path.relative_to(target_path)
                zf.write(file_path, arcname)
    
    memory_file.seek(0)
    
    # Send the in-memory ZIP file to the user.
    return send_file(
        memory_file,
        as_attachment=True,
        download_name=f'{folder_name}.zip',
        mimetype='application/zip'
    )
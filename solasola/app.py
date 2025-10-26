import yaml
from flask import (Flask, jsonify, render_template, request,
                   send_from_directory, make_response)
from pathlib import Path
import os
import tempfile
import zipfile
import logging
import subprocess
import uuid
import json
import argparse
import sys
import time
import shutil
import traceback
import threading

# Import from other SolaSola modules
from solasola.input_handler import classify_and_validate_files
from solasola.model_manager import (
    delete_model_from_manifest,
    get_all_models_status,
    clear_model_size_cache
)

# Import from the new modules
from solasola.sse_manager import SSEManager
from solasola.task_manager import TASKS, cleanup_old_tasks
from solasola.processing_logic import process_task_wrapper
from solasola.installation_manager import install_model_wrapper
from solasola.xet_manager import xet_manager
from solasola.results_manager import results_manager_bp

# Load version info from a JSON file at startup.
VERSION_INFO = {"version": "v0.0.0", "timestamp": "N/A", "commit_hash": "N/A"}
try:
    with open(Path(__file__).parent / 'version.json', 'r') as f:
        data = json.load(f)
        VERSION_INFO['version'] = data.get('version', 'v0.0.0')
        VERSION_INFO['build'] = data.get('build', '0')
        VERSION_INFO['timestamp'] = data.get('timestamp', 'N/A')
        VERSION_INFO['commit_hash'] = data.get('commit_hash', 'N/A')
except (FileNotFoundError, json.JSONDecodeError):
    print("Warning: version.json not found or invalid. Using default version.")

# --- Centralized Logging Setup ---

logging.basicConfig(
    # Default to INFO. This will be adjusted based on CLI args when run directly
    level=logging.INFO, 
    format='%(asctime)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

BASE_CACHE_DIR = Path("/app/cache")
BASE_OUTPUT_DIR = Path("/app/output")
INSTALL_LOCK = threading.Lock()

app = Flask(__name__, static_folder='static')

# Initialize the Server-Sent Events manager for real-time client updates.
sse_manager = SSEManager()

# --- SECURITY: Set a secret key for signing tokens ---
# This is essential for creating secure, tamper-proof tokens for actions like deletion.
app.secret_key = os.urandom(24)

app.register_blueprint(results_manager_bp)
# This log filter removes noisy, non-critical warnings from libraries
# (e.g., "Tensorflow is not installed") to make the server console log cleaner
# and easier to debug.
class NoisyWarningsFilter(logging.Filter):
    """A custom log filter to suppress non-critical warnings."""

    def filter(self, record):
        msg = record.getMessage()
        noisy_substrings = [
            "Coremltools is not installed", "onnxruntime is not installed",
            "Tensorflow is not installed", "The value of the smallest subnormal"
        ]
        return not any(sub in msg for sub in noisy_substrings) and "torchaudio" not in msg

logging.getLogger().addFilter(NoisyWarningsFilter())


def load_config():
    """Load configuration from config.yaml."""
    with open('config.yaml', 'r') as f:
        return yaml.safe_load(f)

@app.route('/')
def index():
    """Renders the main page with the file upload form."""
    return render_template('index.html', version_info=VERSION_INFO)


@app.route('/licenses')
def licenses_page():
    """Renders the page that shows open source license information."""
    return render_template('licenses.html', version_info=VERSION_INFO)


@app.route('/processing')
def processing_page():
    """Renders the page that shows the dynamic progress bar for a task."""
    return render_template('processing.html')


@app.route('/favicon.ico')
def favicon():
    """Serves the favicon."""
    return send_from_directory(
        os.path.join(app.root_path, 'static', 'favicon'),
        'favicon.png', mimetype='image/png')


@app.route('/test')
def test_page():
    """Renders the test page for ABC.js development."""
    return render_template('test.html', version_info=VERSION_INFO)

@app.route('/offline')
def offline_page():
    """Renders a page indicating that the server connection is lost.
    This page is cached by the browser so it can be displayed when the server is down."""
    return render_template('offline.html')


@app.route('/templates/<path:filename>')
def serve_template(filename):
    """Serves a single template file from the templates directory."""
    return send_from_directory('templates', filename)

@app.route('/api/config') # Provides user-defined configuration from a JSON file.
def get_user_config(): # This allows users to override default frontend constants without editing source code.
    config_path = Path(app.root_path) / 'user_config.json'
    if config_path.is_file():
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return jsonify(json.load(f))
        except (IOError, json.JSONDecodeError) as e:
            logging.warning(f"Could not read or parse user_config.json: {e}")
            return jsonify({'error': 'Invalid user config file.'}), 500
    return jsonify({})


def run_health_checks():
    """Performs a series of checks to ensure backend dependencies are met."""
    checks = {
        'ffmpeg': {'status': 'ok', 'message': 'FFmpeg is installed.'},
        'abcmidi': {'status': 'ok', 'message': 'abcmidi (for ABC conversion) is installed.'},
        'genre_model': {'status': 'ok', 'message': 'Genre classification model is loaded.'}
    }
    overall_status = 'ok'

    if not shutil.which('ffmpeg'):
        checks['ffmpeg']['status'] = 'missing'
        checks['ffmpeg']['message'] = ('FFmpeg executable not found in PATH. '
                                      'Audio processing will fail.')
        overall_status = 'degraded'

    if not shutil.which('midi2abc'):
        checks['abcmidi']['status'] = 'missing'
        checks['abcmidi']['message'] = ('midi2abc (from abcmidi) not found in '
                                       'PATH. ABC conversion will fail.')
        overall_status = 'degraded'
    
    return overall_status, checks

@app.route('/health')
def health_check():
    """A simple health check endpoint to confirm the server is running."""
    status, checks = run_health_checks()
    http_status_code = 200 if status == 'ok' else 503  # Service Unavailable

    # Prevent browsers from caching the health check response to ensure it's always live.
    response = make_response(
        jsonify({'status': status, 'checks': checks}), http_status_code)
    response.headers['Cache-Control'] = ('no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0')
    response.headers['Pragma'] = 'no-cache'
    return response
# --- SSE Endpoint ---

@app.route('/api/model-status-stream')
def model_status_stream():
    """Endpoint for clients to subscribe to real-time model status updates."""
    from flask import Response
    return Response(sse_manager.stream(), mimetype='text/event-stream')


@app.route('/api/models_status', methods=['GET'])
def models_status():
    """Returns the installation status of all supported on-demand models."""
    try:
        status = get_all_models_status()
        return jsonify(status)
    except Exception as e:
        logging.error(f"Error checking language model status: {e}") # noqa
        return jsonify({"error": "Could not retrieve model status."}), 500


@app.route('/api/task_layout/<task_id>')
def task_layout(task_id):
    """Returns the dynamically generated layout for the progress bar for a given task."""
    task = TASKS.get(task_id)
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    if 'layout' not in task:
        return jsonify({'error': 'Task layout not generated yet.'}), 404
    return jsonify(task['layout'])


@app.route('/api/refresh_models_status', methods=['POST'])
def refresh_models_status_route():
    """Clears the model size cache and refetches all statuses."""
    try:
        logging.info("  -> [API Refresh] Requesting model state cleanup...")
        subprocess.run([sys.executable, "-m", "solasola.sub_process.global_model_state_watcher", "--action", "cleanup"], check=True, capture_output=True, text=True) # noqa
        logging.info("  -> [API Refresh] Cleanup complete.")
    except Exception as e:
        logging.warning(f"  -> Failed to run model state cleanup during manual refresh: {e}")
    try:
        clear_model_size_cache()
        status = get_all_models_status()
        return jsonify(status)
    except Exception as e:
        logging.error(f"Error refreshing model status: {e}")
        return jsonify({"error": "Could not refresh model status."}), 500


@app.route('/api/manage_model', methods=['POST'])
def manage_model():
    """A unified endpoint to handle all model management actions (install, delete)."""
    data = request.get_json()
    action = data.get('action')
    client_id = request.headers.get('X-Client-ID')

    if action == 'install':
        if not INSTALL_LOCK.acquire(blocking=False):
            # If lock is not acquired, another installation is in progress.
            return jsonify({"status": "waiting", "message": "Another "
                            "installation is already in progress."})

        # Lock acquired, proceed with installation.
        try:
            repo_id = data.get('repo_id')
            ui_container_id = data.get('ui_container_id')
            if not repo_id:
                raise ValueError("Missing repo_id for install action.")

            task_id = str(uuid.uuid4())
            TASKS[task_id] = {
                'timestamp': time.time(),
                'status': 'starting',
                'progress': 0,
                'current_step': "Preparing to download model...",
                'results': None,
                'cancel_requested': False,
                'ui_logs': [],
                'process': None,
                'model_info': {'repo_id': repo_id, 'ui_container_id': ui_container_id},
                'actor_client_id': client_id
            }

            # Broadcast install_start event
            sse_manager.broadcast({
                "action": "status_update",
                "payload": {
                    "actor_client_id": client_id,
                    "task_id": task_id,
                    "repo_id": repo_id,
                    "manifest_id": "",
                    "ui_container_id": ui_container_id,
                    "deletion_path": "",
                    "status": "running",
                    "progress": 0,
                    "message": "Installation started.",
                }
            })

            thread = threading.Thread(target=install_model_wrapper, args=(
                task_id, repo_id, ui_container_id, sse_manager, client_id, INSTALL_LOCK
            ))
            thread.daemon = True
            thread.start()

            return jsonify({'status': 'running', 'task_id': task_id})

        except Exception as e:
            INSTALL_LOCK.release() # Ensure lock is released on error
            traceback.print_exc()
            return jsonify({'error': 'An internal server error occurred during '
                            'model installation.'}), 500

    elif action == 'delete':
        deletion_path = data.get('deletion_path')
        ui_container_id = data.get('ui_container_id')
        if not deletion_path:
            return jsonify({'error': 'Missing deletion_path for delete action.'}), 400

        if not INSTALL_LOCK.acquire(blocking=False):
            # Prevent deletion while an installation is in progress.
            return jsonify({"status": "waiting", "message": "Another task is in progress. Please try again."})

        try:
            # Use only the filename for deletion to prevent path traversal.
            manifest_filename = Path(deletion_path).name
            success = delete_model_from_manifest(manifest_filename)
            if success:
                # Broadcast a refresh event for the specific container
                sse_manager.broadcast({
                    "action": "refresh_all",
                    "payload": {
                        "actor_client_id": client_id,
                        "task_id": "",
                        "repo_id": "",
                        "manifest_id": "",
                        "ui_container_id": ui_container_id,
                        "deletion_path": deletion_path,
                        "status": "completed",
                        "progress": 100,
                        "message": "A model was deleted.",
                    }
                })
                return jsonify({'status': 'ok', 'message': 'Model deleted successfully.'})
            else:
                return jsonify({'status': 'error', 'message': 'Failed to delete the model on the server.'}), 500
        except Exception as e:
            traceback.print_exc()
            return jsonify({'error': 'An internal server error occurred during model deletion.'}), 500
        finally:
            INSTALL_LOCK.release() # Ensure lock is always released

    else:
        return jsonify({'error': f'Invalid action: {action}'}), 400

@app.route('/start_processing', methods=['POST'])
def start_processing():
    """Handles file uploads, starts the background processing task, and returns a task ID."""
    music_files = request.files.getlist('music_files')
    lyrics_file = request.files.get('lyrics_file')
    processing_mode = request.form.get('mode', 'abc')

    if processing_mode == 'abc':
        if not music_files or music_files[0].filename == '':
            return jsonify({'error': 'Full Analysis mode requires at least one music file.'}), 400
    elif processing_mode == 'lyrics_only':
        if not lyrics_file or not lyrics_file.filename:
            return jsonify({'error': 'Lyrics File Simple Split mode requires a lyrics file.'}), 400

    temp_dir = None # Initialize to ensure it's available in the finally block
    try:
        original_music_filenames = [f.filename for f in music_files]

        all_files = music_files
        if lyrics_file and lyrics_file.filename:
            all_files.append(lyrics_file)

        temp_dir = tempfile.mkdtemp()
        logging.info(f"Created temporary directory for this session: {temp_dir}")
        task_id = str(uuid.uuid4())

        for file in all_files:
            if file:
                filename = file.filename
                file_path = os.path.join(temp_dir, filename)
                file.save(file_path)
                if filename.lower().endswith('.zip'):
                    logging.info(f"ZIP file detected: '{filename}', attempting to extract.")
                    try:
                        with zipfile.ZipFile(file_path, 'r') as zip_ref:
                            zip_ref.extractall(temp_dir)
                        logging.info(f"  -> Successfully extracted.")
                    except zipfile.BadZipFile:
                        logging.error(f"  -> Error: '{filename}' is not a valid ZIP file.")
                    finally:
                        os.remove(file_path)

        logging.info("\nStarting file validation and classification...")
        classified_files = classify_and_validate_files(temp_dir)
        
        # Collect raw form data for logging and processing
        raw_form_data = {key: value for key, value in request.form.items()}
        client_time_offset = int(raw_form_data.get('client_time_offset', 0))
        client_os = raw_form_data.get('client_os', 'unknown')
        demucs_model = raw_form_data.get('demucs_model', 'htdemucs_ft')

        TASKS[task_id] = {
            'timestamp': time.time(),
            'status': 'starting',
            'progress': 0,
            'client_os': client_os,
            'client_time_offset': client_time_offset,
            'current_step': 'Initializing...',
            'results': None,
            'cancel_requested': False,
            'ui_logs': [],
            'process': None,
        }

        # Start the main processing logic in a background thread.
        thread = threading.Thread(target=process_task_wrapper, args=(
            task_id, temp_dir, classified_files, processing_mode, demucs_model,
            original_music_filenames, raw_form_data.get('display_title'),
            app.config.get('KEEP_MODELS_CACHED', False), BASE_OUTPUT_DIR,
            raw_form_data, VERSION_INFO
        ))
        thread.daemon = True
        thread.start()

        return jsonify({'task_id': task_id})
    except Exception as e:
        logging.error(f"An error occurred during initial file setup: {e}")
        traceback.print_exc()
        return jsonify({'error': 'Failed to prepare files for processing. Please check server logs for details.'}), 500


@app.route('/status/<task_id>')
def task_status(task_id):
    """Provides the status of a background task."""
    task = TASKS.get(task_id)
    if not task:
        return jsonify({'status': 'not_found'}), 404
    

    response = {
        'status': task['status'],
        'progress_details': task.get('progress_details', {}),
        'current_step': task['current_step'],
        'ui_logs': task.get('ui_logs', [])
    }
    if task['status'] == 'completed':
        response['results'] = task['results']

    
    return jsonify(response)


@app.route('/cancel/<task_id>', methods=['POST'])
def cancel_task(task_id):
    """Requests cancellation of a background task."""
    task = TASKS.get(task_id)
    if not task:
        return jsonify({'status': 'not_found'}), 404
    
    logging.info(f"Cancellation requested for task {task_id}")
    task['cancel_requested'] = True
    
    process_to_kill = task.get('process')
    if process_to_kill and process_to_kill.poll() is None:
        logging.info(f"Terminating process PID {process_to_kill.pid} for task {task_id}...")
        process_to_kill.terminate()
        try:
            process_to_kill.wait(timeout=5)
            logging.info("Process terminated gracefully.")
        except subprocess.TimeoutExpired:
            process_to_kill.kill()
            logging.warning(f"Process for task {task_id} had to be killed.")
    
    return jsonify({'status': 'cancellation_requested'})

if __name__ == '__main__':
    config = load_config()
    port = config.get('server', {}).get('port', 5656)

    # Parse arguments only when the script is run directly.
    parser = argparse.ArgumentParser(description="Run SolaSola Flask App.")
    parser.add_argument(
        '--no-debug', action='store_true',
        help="Run in production mode without debug features.")
    parser.add_argument(
        '--keep-models-cached', action='store_true',
        help="Keep AI models in memory after a task is finished.")
    cli_args = parser.parse_args()

    # Store settings in Flask's config for app-wide access
    app.config['KEEP_MODELS_CACHED'] = cli_args.keep_models_cached
    app.config['BASE_OUTPUT_DIR'] = BASE_OUTPUT_DIR
    debug_mode = not cli_args.no_debug
    log_level = logging.INFO if debug_mode else logging.WARNING
    logging.getLogger().setLevel(log_level)

    # Suppress Werkzeug's default INFO logs for successful requests for a cleaner console.
    logging.getLogger('werkzeug').setLevel(logging.WARNING)

    # This check ensures the startup messages are only printed once by the main process.
    if not debug_mode or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        # ANSI color codes for better log visibility
        YELLOW = '\033[93m'
        RESET = '\033[0m'
        full_version_str = f"SolaSola {VERSION_INFO['version']} ({VERSION_INFO['timestamp']} @ {VERSION_INFO['commit_hash']})"
        banner_width = max(60, len(full_version_str) + 4)
        banner_line = '-' * banner_width
        logging.warning(f"\n{YELLOW}{banner_line}{RESET}")
        logging.warning(f"{YELLOW}{full_version_str.center(banner_width)}{RESET}")
        logging.warning(f"{YELLOW}{banner_line}{RESET}")
        logging.warning(f"\n{YELLOW} SolaSola Web Server Started. Ready for file processing. {RESET}")
        logging.warning(f"{YELLOW}{'='*60}{RESET}\n")

        # Perform a health check on startup to verify essential dependencies.
        logging.warning(f"{YELLOW}--- Running Startup Health Checks ---{RESET}")
        startup_status, startup_checks = run_health_checks()
        for check_name, check_result in startup_checks.items():
            if check_result['status'] == 'ok' or check_result['status'] == 'loaded':
                logging.info(f"  [OK] {check_name.ljust(12)}: {check_result['message']}")
            else:
                logging.warning(f"  [!!] {check_name.ljust(12)}: {check_result['message']}")
        if startup_status != 'ok':
            logging.warning(f"{YELLOW}WARNING: Some dependencies are missing. The application is in a degraded state.{RESET}")
        logging.warning(f"{YELLOW}-------------------------------------{RESET}\n")

    # Ensure base directories exist before starting any background threads.
    try:
        BASE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        BASE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        logging.info(f"  [OK] Output and cache directories are ready.")
    except OSError as e:
        logging.critical(f"  [!!] FATAL: Could not create or access required directories: {e}")

    # Start a background thread to periodically clean up old, completed task data from memory.
    cleanup_thread = threading.Thread(target=cleanup_old_tasks, daemon=True)
    cleanup_thread.start()

    # Start a background thread to manage the cleanup of the temporary .xet cache.
    xet_cleanup_thread = threading.Thread(target=xet_manager.run, daemon=True)
    xet_cleanup_thread.start()

    def warm_up_cache():
        # Run a model state cleanup once at startup before building the cache.
        try:
            logging.info("  -> [Startup] Running initial model state cleanup...")
            subprocess.run([sys.executable, "-m", "solasola.sub_process.global_model_state_watcher", "--action", "cleanup"], check=True, capture_output=True, text=True)
            logging.info("  -> [Startup] Initial cleanup complete.")
        except Exception as e:
            logging.warning(f"  -> WARNING: Failed to run initial model state cleanup: {e}")

        logging.info("  -> Warming up model status cache in the background...")
        get_all_models_status(force_refresh=True)
    threading.Thread(target=warm_up_cache, daemon=True).start()

    app.run(host='0.0.0.0', port=port, debug=debug_mode, use_reloader=False)

import os
from pathlib import Path
import subprocess
import logging
import sys
import re
import shutil
from demucs import pretrained

def prepare_demucs_model(model_name: str):
    """
    Pre-loads a Demucs model. This function serves two purposes:
    1. It triggers the model download from Hugging Face Hub if it's not already cached.
    2. It returns the loaded model object, ready for use in the separation process.
    This is called before `run_demucs_separation` to allow the download watcher to
    create a manifest of the newly downloaded files.

    Args:
        model_name (str): The name of the Demucs model to load (e.g., 'htdemucs').

    Returns:
        The loaded model object.
    """
    try:
        print(f"  -> Pre-loading Demucs model '{model_name}' to trigger download if necessary...")
        # This function from the `demucs` library handles both downloading and loading the model.
        model = pretrained.get_model(name=model_name)
        print("  -> Model is ready.")
        return model
    except Exception as e:
        raise RuntimeError(f"Failed to download or load the Demucs model '{model_name}': {e}")

def run_demucs_separation(task_id: str, model, audio_path: str, output_dir: str, device: str, model_name: str, stems_to_separate: list = None):
    """Runs the Demucs separation process as a command-line subprocess using a pre-loaded model."""
    print(f"\nStarting stem separation for: {Path(audio_path).name}")
    logging.info(f"Starting stem separation for: {Path(audio_path).name}")
    logging.info(f"  -> Using Demucs model: {model_name}")

    # Demucs v4's primary interface is command-line based.
    # We use subprocess to call it, which is robust against internal API changes.
    logging.info(f"  -> Output directory: {output_dir}")
    command = [
        sys.executable,  # Use the same Python interpreter that's running the app.
        "-m", "demucs.separate",
        # The -o flag sets the base output directory. Demucs will create a subdirectory
        # inside this path based on the model name (e.g., output_dir/htdemucs/filename/).
        "-o", str(output_dir.resolve()),
        "-d", str(device),
        "-n", model_name
    ]
    # For efficiency, if the user only requests vocals, we can use the --two-stems
    # option, which is significantly faster than a full 4-stem separation.
    if stems_to_separate and 'vocals' in stems_to_separate and len(stems_to_separate) == 1:
        command.append("--two-stems=vocals")
    command.append(str(Path(audio_path).resolve()))

    proc = None
    try:

        # Log the complete Demucs command for debugging purposes.
        command_str = ' '.join(command)
        logging.info(f"  -> Starting Demucs command: {command_str}")

        # Use Popen to run the command as a non-blocking background process.
        # We pipe stdout and stderr together so the calling function can stream progress updates.
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')

        expected_output_path = output_dir / model_name / Path(audio_path).stem
        return proc, expected_output_path
    except Exception as e:
        logging.error(f"  -> An error occurred while starting Demucs: {e}")
        if proc:
            # If process started but failed, get the output and error
            stdout, stderr = proc.communicate()
            logging.error(f"  -> Demucs stdout: {stdout}")
            logging.error(f"  -> Demucs stderr: {stderr}")
        print(f"An error occurred: {e}")
        return None, None

def get_stem_paths(demucs_output_dir: Path):
    """After a successful Demucs run, this finds the generated stem files."""
    if not demucs_output_dir.is_dir():
        logging.error(f"  -> Error: Demucs output directory not found at {demucs_output_dir}")
        return None
    saved_stems = {p.stem: str(p.resolve()) for p in demucs_output_dir.glob('*.wav')}
    print(f"  -> Found stems: {list(saved_stems.keys())}")
    return saved_stems

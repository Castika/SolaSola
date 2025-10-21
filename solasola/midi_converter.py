import subprocess
import sys
from pathlib import Path
import json
import traceback
import os


def convert_audio_to_midi(task_id: str, audio_path: str, output_dir: Path, demucs_model: str) -> bool:
    """
    Converts a single audio file to MIDI using the basic-pitch model.
    
    This function runs the `basic-pitch` model in a separate, isolated Python process.
    This is crucial to avoid dependency conflicts, as `basic-pitch` requires an older
    version of NumPy (v1.x) that conflicts with other libraries in the main environment.
    """
    stem_name = Path(audio_path).stem
    output_midi_path = output_dir / f"{stem_name}.mid"
    
    print(f"-> [MIDI Converter] Starting conversion for: {Path(audio_path).name} using isolated environment.")

    # Use the python executable from the dedicated basic-pitch virtual environment.
    # This path is correct for the Docker container. For local testing, it's overridden by the test fixture.
    basic_pitch_python_executable = os.getenv("BASIC_PITCH_PYTHON", "/opt/venv_basic_pitch/bin/python")

    command = [
        basic_pitch_python_executable,
        "-m", "solasola.sub_process.run_basic_pitch",
        "--audio_path", audio_path,
        "--output_path", str(output_midi_path)
    ]
    print(f"  -> Running command: {' '.join(command)}")

    try:
        proc = subprocess.run(
            command,            
            capture_output=True,
            text=True,
            check=False,
            encoding='utf-8',
            errors='replace'
        )

        if proc.returncode != 0:
            # The subprocess is designed to write a `.error.json` file on failure.
            # This is a robust way to pass detailed error information back to the main process.
            error_file = output_midi_path.with_suffix('.error.json')
            if error_file.exists():
                with open(error_file, 'r') as f:
                    error_data = json.load(f)
                print(f"  -> Detailed error from subprocess: {error_data.get('details')}")
                # Return False to indicate failure without crashing the entire song analysis.
                return False
            else:
                # If the JSON error file wasn't created, fall back to printing the raw
                # stdout and stderr from the subprocess for debugging.
                error_details = f"STDOUT: {proc.stdout.strip()}\nSTDERR: {proc.stderr.strip()}"
                print(f"  -> An error occurred during MIDI conversion: Basic Pitch subprocess failed with exit code {proc.returncode}.\n{error_details}")
                return False
        
        # If the subprocess returns a zero exit code, the conversion was successful.
        return True

    except FileNotFoundError:
        # This would happen if the Python executable itself is not found, which is unlikely.
        print(f"  -> An error occurred during MIDI conversion: {traceback.format_exc()}")
        return False
    except Exception as e:
        print(f"  -> An error occurred during MIDI conversion: {e}")
        return False

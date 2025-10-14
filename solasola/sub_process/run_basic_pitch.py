"""
Runs Basic Pitch to convert audio to MIDI.
Executed in a dedicated venv to avoid NumPy version conflicts.
"""
import argparse
import json
import traceback
from pathlib import Path

try:
    import numpy
    numpy_version = tuple(map(int, numpy.__version__.split('.')))
    if numpy_version[0] >= 2:
        raise ImportError(
            "Basic Pitch requires NumPy v1.x, but a newer version is installed.") # noqa
except ImportError as e:
    # Write error to JSON for the main process to parse.
    parser = argparse.ArgumentParser()
    parser.add_argument("--output_path", required=True)
    args, _ = parser.parse_known_args()  # Parse only the output_path we need

    error_info = {
        "error": "NumPy version conflict.",
        "details": str(e),
        "traceback": traceback.format_exc()
    }
    error_file_path = Path(args.output_path).with_suffix('.error.json')
    with open(error_file_path, 'w') as f:
        json.dump(error_info, f, indent=2)

    # Also print to stderr for logging.
    import sys
    print(f"ERROR: {error_info['error']} - {error_info['details']}",
          file=sys.stderr)
    sys.exit(1)

# Now, import the rest of the libraries
from basic_pitch.inference import predict_and_save
from basic_pitch import ICASSP_2022_MODEL_PATH


def convert(audio_path_str: str, output_path_str: str):
    """
    The core MIDI conversion logic, running in an isolated process.
    """
    print(f"  -> [Basic Pitch] Starting conversion for: "
          f"{Path(audio_path_str).name}")
    # Use basic-pitch's predict_and_save function.
    predict_and_save(
        audio_path_list=[audio_path_str],
        output_directory=str(Path(output_path_str).parent),
        save_midi=True,
        sonify_midi=False,
        save_model_outputs=False,
        save_notes=False,
        model_or_model_path=ICASSP_2022_MODEL_PATH,
    )

    # Rename auto-generated file.
    generated_path = (Path(output_path_str).parent /
                      f"{Path(audio_path_str).stem}_basic_pitch.mid")
    if generated_path.exists():
        generated_path.rename(output_path_str)
        print(f"  -> [Basic Pitch] Conversion complete. Output renamed to: "
              f"{Path(output_path_str).name}")
    else:
        raise FileNotFoundError("Basic Pitch did not generate the expected "
                                f"output file: {generated_path}")


def main():
    parser = argparse.ArgumentParser(description="Run Basic Pitch MIDI conversion.")
    parser.add_argument("--audio_path", required=True,
                        help="Path to the audio file.")
    parser.add_argument(
        "--output_path",
        required=True,
        help="Path to save the output MIDI file.")
    args = parser.parse_args()

    try:
        convert(args.audio_path, args.output_path)
    except Exception as e:
        # Write detailed error to a JSON file.
        error_info = {
            "error": "MIDI conversion failed.",
            "details": str(e),
            "traceback": traceback.format_exc()
        }
        error_file_path = Path(args.output_path).with_suffix('.error.json')
        with open(error_file_path, 'w') as f:
            json.dump(error_info, f, indent=2)

        # Also print to stderr for logging.
        import sys
        print(f"ERROR: {error_info['error']} - {error_info['details']}",
              file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

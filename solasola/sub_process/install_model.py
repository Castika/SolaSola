"""
Handles model download in an isolated subprocess.
"""
import argparse
import sys
import traceback

from solasola.model_manager import GENRE_MODEL_REPO_ID


def install(model_type, device, language=None, repo_id=None):
    """
    The core installation logic, now running in an isolated process.
    This function downloads a model from Hugging Face Hub.
    """
    print("--- Starting model installation in subprocess ---", file=sys.stdout)
    print(f"Model Type: {model_type}, Device: {device}, Language: {language}, "
          f"Repo ID: {repo_id}", file=sys.stdout)

    if model_type == 'genre':
        from transformers import AutoFeatureExtractor, AutoModelForAudioClassification
        print(
            f"Downloading Genre Classifier model ({GENRE_MODEL_REPO_ID})...",
            file=sys.stdout)
        AutoFeatureExtractor.from_pretrained(GENRE_MODEL_REPO_ID)
        AutoModelForAudioClassification.from_pretrained(GENRE_MODEL_REPO_ID)
        print("Genre Classifier model download complete.", file=sys.stdout)
    else:
        raise ValueError(f"Unsupported model_type: {model_type}")


def main():
    parser = argparse.ArgumentParser(
        description="Run model installation in a separate process.")
    parser.add_argument("--model_type", required=True,
                        help="Type of model to install (e.g., 'genre').")
    parser.add_argument("--device", required=True,
                        help="Processing device (e.g., 'cpu', 'cuda').")
    parser.add_argument("--language",
                        help="Language code for the model (optional).")
    parser.add_argument("--repo_id",
                        help="Hugging Face repository ID (optional).")
    args = parser.parse_args()

    try:
        install(args.model_type, args.device, args.language, args.repo_id)
        print("--- Subprocess finished successfully. ---", file=sys.stdout)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()

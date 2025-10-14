"""
Handles the download of a model from Hugging Face Hub in an isolated subprocess.

This script is called by the main application to ensure that model downloads,
which can be resource-intensive, do not block or interfere with the main web server process.
"""
import argparse
import sys
import traceback

# Import model info from the centralized model_manager.
from solasola.model_manager import GENRE_MODEL_REPO_ID

def install(model_type, device, language=None, repo_id=None):
    """
    The core installation logic, now running in an isolated process.
    This function downloads a model from Hugging Face Hub.
    """
    print(f"--- Starting model installation in subprocess ---")
    print(f"Model Type: {model_type}, Device: {device}, Language: {language}, Repo ID: {repo_id}")

    # This script currently only handles the installation of the 'genre' model type.
    if model_type == 'genre':
        from transformers import AutoFeatureExtractor, AutoModelForAudioClassification
        print(f"Downloading Genre Classifier model ({GENRE_MODEL_REPO_ID})...")
        # These commands will download the model to the location specified by the HF_HOME environment variable.
        AutoFeatureExtractor.from_pretrained(GENRE_MODEL_REPO_ID)
        AutoModelForAudioClassification.from_pretrained(GENRE_MODEL_REPO_ID)
        print("Genre Classifier model download complete.")
    else:
        raise ValueError(f"Unsupported model_type for installation: {model_type}")

def main():
    parser = argparse.ArgumentParser(description="Run model installation in a separate process.")
    parser.add_argument("--model_type", required=True, help="Type of model to install (e.g., 'genre').")
    parser.add_argument("--device", required=True, help="Processing device (e.g., 'cpu', 'cuda').")
    parser.add_argument("--language", help="Language code for the model (optional).")
    parser.add_argument("--repo_id", help="Hugging Face repository ID for custom models (optional).")
    args = parser.parse_args()

    try:
        install(args.model_type, args.device, args.language, args.repo_id)
        print("--- Subprocess finished successfully. ---")
    except Exception as e:
        # Print the error to stderr so the parent process can capture it.
        print(f"ERROR: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()

"""
Runs genre classification on an audio file in an isolated subprocess.

This script is called by the main application to load the genre classification
model, analyze a short clip of the audio, and return the top predicted genres.
Running this in a separate process prevents memory leaks and potential library
conflicts from affecting the main web server.
"""
import argparse
import json
import sys
import traceback
from pathlib import Path
import warnings

import torch
import librosa

# Import the model path directly from the centralized model_manager.
from solasola.model_manager import GENRE_MODEL_PATH as MODEL_PATH

def classify(task_id: str, audio_path_str: str, top_n: int = 3) -> list:
    """
    The core classification logic, now running in an isolated process.
    """
    # Lazy import inside the function to ensure it's only loaded when needed.
    from transformers import AutoFeatureExtractor, AutoModelForAudioClassification

    def _find_model_files_dir(directory: Path) -> Path:
        """
        Finds the directory containing the actual model files within the Hugging Face
        cache structure, which could be in the root or a versioned 'snapshots' subdirectory.
        """
        # Strategy 1: Use the 'refs/main' file to find the correct snapshot hash.
        refs_main_path = directory / "refs" / "main"
        if refs_main_path.is_file():
            try:
                snapshot_hash = refs_main_path.read_text().strip()
                snapshot_dir = directory / "snapshots" / snapshot_hash
                if snapshot_dir.is_dir():
                    return snapshot_dir
            except Exception:
                pass

        # Strategy 2: Fallback to the most recently modified snapshot if it exists.
        snapshots_dir = directory / "snapshots"
        if snapshots_dir.is_dir():
            try:
                subdirs = [p for p in snapshots_dir.iterdir() if p.is_dir()]
                if subdirs:
                    latest_snapshot = sorted(subdirs, key=lambda p: p.name, reverse=True)[0]
                    return latest_snapshot
            except ValueError:
                pass

        # Strategy 3: Default to the root directory.
        return directory


    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"Genre model not found at the expected path: {MODEL_PATH}")

    # Intelligently find the actual model files within the cache structure.
    actual_model_path = _find_model_files_dir(MODEL_PATH)
    if not actual_model_path or not actual_model_path.exists():
        raise FileNotFoundError(f"Could not locate genre model files inside {MODEL_PATH}")
    
    print(f"  -> [Genre Load] Loading model from path: {actual_model_path}")

    feature_extractor = AutoFeatureExtractor.from_pretrained(str(actual_model_path))
    model = AutoModelForAudioClassification.from_pretrained(str(actual_model_path))
    
    print(f"  -> [Genre Proc] Classifying genre for: {Path(audio_path_str).name}")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        # Load only the first 30 seconds for efficiency and stability.
        # This is sufficient for genre classification and prevents memory issues with long files.
        y, sr = librosa.load(audio_path_str, sr=16000, mono=True, duration=30.0)

    inputs = feature_extractor(y, sampling_rate=sr, return_tensors="pt")

    with torch.no_grad():
        logits = model(**inputs).logits

    probabilities = torch.nn.functional.softmax(logits, dim=-1)
    # Get both the probabilities and indices of the top N predictions.
    top_probs, top_indices = torch.topk(probabilities, top_n)
    top_probs = top_probs[0].tolist()
    top_indices = top_indices[0].tolist()
    
    # Create a list of dictionaries containing both the genre name and its confidence score.
    predicted_genres = []
    for i, prob in zip(top_indices, top_probs):
        genre_name = model.config.id2label[i]
        predicted_genres.append({'genre': genre_name, 'probability': prob})

    # Log the genres only for clarity in the console
    print(f"  -> [Genre Proc] Detected genres: {[g['genre'] for g in predicted_genres]}")
    return predicted_genres

def main():
    parser = argparse.ArgumentParser(description="Run Genre Classification in a separate process.")
    parser.add_argument("--audio_path", required=True, help="Path to the audio file.")
    parser.add_argument("--output_path", required=True, help="Path to save the JSON result.")
    # Accept the task_id for potential future audit logging.
    parser.add_argument("--task_id", required=True, help="Task ID for audit logging.")
    args = parser.parse_args()

    try:
        genres = classify(args.task_id, args.audio_path)
        result = {"genres": genres, "error": None}
    except Exception as e:
        result = {"genres": [], "error": str(e), "traceback": traceback.format_exc()}
        
    Path(args.output_path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')

if __name__ == "__main__":
    main()
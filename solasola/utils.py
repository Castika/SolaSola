import os
import hashlib
from pathlib import Path

def get_ai_models_dir() -> Path:
    """Returns the root directory where all user-downloaded AI models are stored."""
    return Path(os.getenv("HF_HOME", "/app/user_models"))

def get_manifest_dir(ai_models_dir: Path) -> Path:
    """Returns the directory where SolaSola's manifests for ALL models are stored."""
    manifest_dir = ai_models_dir / "solasola_manifests"
    manifest_dir.mkdir(exist_ok=True)
    return manifest_dir

def is_path_excluded(path: Path, ai_models_dir: Path) -> bool:
    """
    Checks if a given path should be excluded from cleanup or monitoring operations.
    This is the centralized exclusion logic used by all watcher scripts.
    """
    manifest_dir = get_manifest_dir(ai_models_dir)

    # Exclude the manifest directory itself and anything inside it
    if path == manifest_dir or manifest_dir in path.parents:
        return True

    # Exclude the temporary huggingface-hub download cache folder (e.g., /app/user_models/xet)
    if path.name == "xet" and path.parent == ai_models_dir:
        return True

    # Exclude .locks directories within the hub cache
    if ".locks" in path.parts:
        return True

    # Exclude hidden files like .DS_Store
    if path.name.startswith('.'):
        return True

    # Exclude the download statistics file from cleanup
    if path.name == "download_stats.json":
        return True

    return False

def calculate_file_hash(file_path: Path) -> str:
    """Calculates the SHA256 hash of a file, handling symlinks correctly."""
    sha256_hash = hashlib.sha256()
    if file_path.is_symlink():
        try:
            target_path = os.readlink(file_path)
            sha256_hash.update(target_path.encode('utf-8'))
            return sha256_hash.hexdigest()
        except (OSError, FileNotFoundError):
            return "N/A"
    elif file_path.is_file():
        try:
            with open(file_path, "rb") as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)
            return sha256_hash.hexdigest()
        except IOError:
            return "N/A"
    return "N/A"

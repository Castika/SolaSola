import torch

def get_processing_device():
    """
    Detects and returns the most appropriate processing device.
    Prioritizes CUDA, then Apple's MPS, and falls back to CPU.

    Returns:
        str: The name of the device to use ('cuda', 'mps', or 'cpu').
    """
    if torch.cuda.is_available():
        device = "cuda"
        print("Hardware Report: CUDA (NVIDIA GPU) detected. Full acceleration enabled.")
 
    elif torch.backends.mps.is_available() and torch.backends.mps.is_built():
        # MPS is Apple's Metal Performance Shaders for Apple Silicon GPUs
        device = "mps"
        print("Hardware Report: MPS (Apple Silicon GPU) detected. Note: Demucs (instrument separation) will use CPU.")
    else:
        device = "cpu"
        print("Hardware Report: No compatible GPU detected. Using CPU for all operations.")
    return device
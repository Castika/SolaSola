"""
A dedicated utility for merging multiple audio files into a single, combined mix file.
"""
from pydub import AudioSegment
from pathlib import Path

def create_mix_audio(audio_files: list, output_path: str) -> str | None:
    """
    Merges multiple audio files into a single 'mix' audio file for analysis.
    This is used when a user provides pre-separated stems, allowing analysis
    modules to work on a complete mix.
    """
    if not audio_files:
        return None
    
    print("  -> Creating combined 'Mix' audio file for analysis...")
    
    try:
        # Start with the first audio file
        # Normalize each segment to prevent clipping when overlaying.
        # -1.0 dBFS is a safe peak level for mixing.
        combined = AudioSegment.from_file(audio_files[0]['path']).normalize()
        
        # Overlay the rest of the audio files
        for audio_file_info in audio_files[1:]:
            segment = AudioSegment.from_file(audio_file_info['path']).normalize()
            combined = combined.overlay(segment)
            
        # Normalize the final combined audio one last time to ensure a consistent volume level.
        combined = combined.normalize()

        combined.export(output_path, format="wav")
        return output_path
    except Exception as e:
        print(f"  -> WARNING: Could not create 'Mix' audio file: {e}")
        return None
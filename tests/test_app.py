import pytest
from solasola import app as flask_app
from solasola import processing_logic
import time
import io
import wave
import struct
import math
import sys
from unittest.mock import MagicMock
import subprocess
from pathlib import Path


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Create and configure a new app instance for each test."""
    # Create temporary directories for output and cache for this test session
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    models_dir = tmp_path / "user_models"
    models_dir.mkdir()

    # Use monkeypatch to override the hardcoded paths in the app module
    monkeypatch.setattr(flask_app, 'BASE_OUTPUT_DIR', output_dir)
    monkeypatch.setattr(flask_app, 'BASE_CACHE_DIR', cache_dir)
    # Also override the environment variable used for model storage
    monkeypatch.setenv('HF_HOME', str(models_dir))
    # CRITICAL FIX: Also override TORCH_HOME to redirect torch.hub downloads
    monkeypatch.setenv('TORCH_HOME', str(models_dir))
    
    flask_app.app.config['TESTING'] = True
    with flask_app.app.test_client() as client:
        yield client

def create_test_wav(duration_ms=1000):
    """Creates a mono WAV file with a simple sine wave tone."""
    n_channels = 1
    sampwidth = 2  # 16-bit
    framerate = 44100
    n_frames = int(framerate * (duration_ms / 1000.0))
    frequency = 440.0  # A4 pitch

    wav_file = io.BytesIO()
    with wave.open(wav_file, 'wb') as wf:
        wf.setnchannels(n_channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(framerate)
        for i in range(n_frames):
            value = int(32767.0 * math.sin(2 * math.pi * frequency * i / framerate))
            wf.writeframes(struct.pack('<h', value))
    wav_file.seek(0)
    return wav_file


def test_index_page_loads(client):
    """Test that the index page loads correctly."""
    response = client.get('/')
    assert response.status_code == 200
    assert b"SolaSola" in response.data


def test_lyrics_only_processing(client):
    """
    Tests the 'lyrics_only' processing mode by uploading a text file and
    verifying the generated SRT output.
    """
    lyrics_content = "Hello world\nThis is a test"
    data = {
        'lyrics_file': (io.BytesIO(lyrics_content.encode('utf-8')), 'test.txt'),
        'mode': 'lyrics_only'
    }

    # 1. Start the processing task
    response = client.post('/start_processing', data=data, content_type='multipart/form-data')
    assert response.status_code == 200
    task_data = response.get_json()
    assert 'task_id' in task_data
    task_id = task_data['task_id']

    # 2. Poll for completion
    for _ in range(30):  # Poll for a maximum of 30 seconds
        time.sleep(1)
        status_response = client.get(f'/status/{task_id}')
        status_data = status_response.get_json()
        if status_data['status'] == 'completed':
            # 3. Assert the results
            results = status_data['results']
            # The key is dynamically generated, so we get the first one.
            song_title = list(results.keys())[0]
            assert 'generated_lyrics' in results[song_title]['lyrics']
            assert '00:00:00,000 --> 00:01:45,000\nHello world' in results[song_title]['lyrics']['generated_lyrics']
            return
    pytest.fail("Task did not complete within the time limit.")


def test_full_abc_processing(client, monkeypatch):
    """
    Tests the full 'abc' processing mode with a real MP3 file.
    This is an end-to-end test for the main audio pipeline.
    """
    # Path to the test audio file located in the same directory as the test script.
    audio_path = Path(__file__).parent / "castika_logo.mp3"

    if not audio_path.exists():
        pytest.skip("Test audio file 'castika_logo.mp3' not found in tests/ directory.")

    # --- MOCKING THE MIDI CONVERSION STEP ---
    # This is the definitive fix. Instead of trying to install and run basic-pitch
    # locally (which fails due to tflite-runtime incompatibility on macOS ARM),
    # we mock the function that calls it.
    def mock_convert_stems_to_midi(task_id, stems_dir, midi_output_dir, demucs_model):
        # Simulate the successful creation of MIDI files.
        for stem_file in stems_dir.glob('*.wav'):
            (midi_output_dir / f"{stem_file.stem}.mid").touch()
        print("  -> MOCK: Simulated successful MIDI conversion for all stems.")

    # Replace the real function with our mock for the duration of this test.
    monkeypatch.setattr(processing_logic, 'convert_stems_to_midi', mock_convert_stems_to_midi)


    with open(audio_path, "rb") as audio_file:
        data = {
            'music_files': (audio_file, 'castika_logo.mp3'),
            'mode': 'abc',
            'demucs_model': 'htdemucs'  # Use the fastest model for testing
        }

        # 1. Start the processing task
        response = client.post('/start_processing', data=data, content_type='multipart/form-data')
        assert response.status_code == 200
        task_data = response.get_json()
        assert 'task_id' in task_data
        task_id = task_data['task_id']

    # 2. Poll for completion (allow more time for audio processing)
    for _ in range(180):  # Poll for up to 3 minutes
        time.sleep(1)
        status_response = client.get(f'/status/{task_id}')
        status_data = status_response.get_json()
        if status_data.get('status') == 'completed':
            # 3. Assert the results structure
            results = status_data.get('results')
            assert results is not None, "Results object is missing"
            song_title = list(results.keys())[0]
            assert 'abc_notation' in results[song_title]
            assert 'song_profile' in results[song_title]
            assert 'Tempo' in results[song_title]['song_profile']
            return
    pytest.fail("Full ABC processing task did not complete within the time limit.")
# --- Stage 1: Main Application Environment Builder ---
# This stage builds the primary virtual environment with all dependencies EXCEPT basic-pitch.
FROM python:3.11-slim AS poetry-builder

RUN apt-get update && apt-get install -y --no-install-recommends build-essential cmake git && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV VENV_PATH=/opt/venv
RUN python3 -m venv $VENV_PATH
ENV PATH="$VENV_PATH/bin:$PATH"

RUN pip install poetry==2.1.4 poetry-plugin-export
COPY pyproject.toml poetry.lock ./
# Export requirements, excluding basic-pitch related dependencies which will be in their own venv.
RUN poetry export -f requirements.txt --output requirements.txt --without-hashes --without dev && \
    # This is crucial: remove basic-pitch dependencies from the main requirements file.
    sed -i '/numpy<2.0/d' requirements.txt && \
    sed -i '/tflite-runtime/d' requirements.txt

# Install main dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch torchaudio torchvision && \
    pip install --no-cache-dir -r requirements.txt && \
    # Aggressive cleanup
    find $VENV_PATH -type d -name "__pycache__" -exec rm -rf {} + && \
    find $VENV_PATH -type f -name "*.pyc" -delete && \
    find $VENV_PATH/lib/python3.11/site-packages/ -type d -name "tests" -exec rm -rf {} +

# --- Stage 2: Basic-Pitch Environment Builder ---
# This stage builds a completely separate virtual environment ONLY for basic-pitch and its specific dependencies.
FROM python:3.11-slim AS basic-pitch-builder

RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV VENV_PATH=/opt/venv_basic_pitch
RUN python3 -m venv $VENV_PATH
ENV PATH="$VENV_PATH/bin:$PATH"

# Install basic-pitch with its specific (older) numpy version.
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir "numpy<2.0" "librosa>=0.8.0" "scipy>=1.4.1" "soxr" "resampy<0.4.3,>=0.2.2" "scikit-learn" "mido>=1.1.16" "pretty_midi>=0.2.9" "mir-eval>=0.6" "typing-extensions" "tflite-runtime" && \
    pip install --no-cache-dir --no-deps "basic-pitch[tflite]" && \
    # Aggressive cleanup
    find $VENV_PATH -type d -name "__pycache__" -exec rm -rf {} + && \
    find $VENV_PATH -type f -name "*.pyc" -delete && \
    find $VENV_PATH/lib/python3.11/site-packages/ -type d -name "tests" -exec rm -rf {} +

# --- Stage 3: Final, lightweight application image ---
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV VENV_PATH=/opt/venv
ENV BASIC_PITCH_PYTHON=/opt/venv_basic_pitch/bin/python
ENV PATH="/opt/venv/bin:/opt/venv_basic_pitch/bin:$PATH"

# Copy the site-packages from both builder stages into their respective final locations.
COPY --from=poetry-builder $VENV_PATH $VENV_PATH
COPY --from=basic-pitch-builder /opt/venv_basic_pitch /opt/venv_basic_pitch

# Install runtime dependencies
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends ffmpeg abcmidi && apt-get clean && rm -rf /var/lib/apt/lists/*

# --- HOTFIX: Apply numba cache fix to BOTH environments in the final image ---
RUN find /opt/venv/lib/python3.11/site-packages/librosa -type f -name "*.py" -print0 | xargs -0 sed -i 's/cache=True/cache=False/g' && \
    find /opt/venv_basic_pitch/lib/python3.11/site-packages/librosa -type f -name "*.py" -print0 | xargs -0 sed -i 's/cache=True/cache=False/g'

# Copy the application code
COPY --chown=65532:65532 ./solasola /app/solasola
COPY --chown=65532:65532 config.yaml .

# Switch to a non-root user for security
USER 65532

# Define default volumes for user data and models
VOLUME /app/cache
VOLUME /app/user_models

# Expose the port the app runs on
EXPOSE 5656

# Add a health check to allow Docker to monitor the application's status.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["python", "-m", "solasola.healthcheck"]

# Set the default command to run the application
CMD ["python", "-m", "solasola.app", "--no-debug"]

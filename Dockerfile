# --- Stage 1: Builder ---
# This stage installs all dependencies, including build-time tools,
# into a single, unified virtual environment.
FROM python:3.11 AS poetry-builder

# Update base image packages to patch security vulnerabilities
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install system dependencies required for building Python packages
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    build-essential python3-dev cmake git \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Create a virtual environment
ENV VENV_PATH=/opt/venv
RUN python3 -m venv $VENV_PATH
ENV PATH="$VENV_PATH/bin:$PATH"

# Install poetry and export requirements.txt
RUN pip install poetry==2.1.4 poetry-plugin-export
COPY pyproject.toml poetry.lock ./
RUN poetry export -f requirements.txt --output requirements.txt --without-hashes --without dev

# Install all dependencies into the single virtual environment
RUN pip install --no-cache-dir --upgrade pip setuptools wheel
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch torchaudio torchvision
RUN pip install --no-cache-dir --no-deps "basic-pitch[tflite]"
RUN pip install --no-cache-dir "numpy<2.0" "librosa>=0.8.0" "scipy>=1.4.1" "soxr" "resampy<0.4.3,>=0.2.2" "scikit-learn" "mido>=1.1.16" "pretty_midi>=0.2.9" "mir-eval>=0.6" "typing-extensions" "tflite-runtime"
RUN pip install --no-cache-dir -r requirements.txt

# --- HOTFIX: Globally disable numba caching in librosa ---
RUN find $VENV_PATH/lib/python3.11/site-packages/librosa -type f -name "*.py" -print0 | xargs -0 sed -i 's/cache=True/cache=False/g'

# --- Stage 2: Final, lightweight application image ---
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Copy only the installed packages from the builder stage's virtual environment
# This is the key optimization step.
COPY --from=poetry-builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install runtime dependencies
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends ffmpeg abcmidi && apt-get clean && rm -rf /var/lib/apt/lists/*

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

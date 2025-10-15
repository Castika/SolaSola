# Stage 1: Create a platform-agnostic requirements.txt from the lock file.
# The name 'poetry-builder' is kept for compatibility with the dog.sh script.
FROM python:3.11 AS poetry-builder

# Update base image packages to patch security vulnerabilities
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install poetry
RUN pip install poetry==2.1.4 poetry-plugin-export

# Copy only the files needed to resolve dependencies
COPY pyproject.toml poetry.lock ./

# Export from poetry.lock to requirements.txt. This is the most reliable method
# as it avoids running the complex `poetry install` resolver inside the container.
# It creates a platform-agnostic requirements file based on the trusted lock file.
RUN poetry export -f requirements.txt --output requirements.txt --without-hashes --without dev

# Stage 2: Build the main virtual environment using the generated requirements.txt
FROM python:3.11 AS venv-builder

WORKDIR /app

# Install system dependencies required for building Python packages
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    build-essential python3-dev cmake git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create a virtual environment
ENV VENV_PATH=/opt/venv
RUN python3 -m venv $VENV_PATH
ENV PATH="$VENV_PATH/bin:$PATH"

# Copy requirements from the first stage
COPY --from=poetry-builder /app/requirements.txt .

# Install dependencies in two steps to force CPU-only PyTorch.
# 1. Install torch, torchaudio, and torchvision specifically from the CPU index.
# 2. Install the rest of the packages from the requirements file.
RUN pip install --no-cache-dir --upgrade pip setuptools wheel
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch torchaudio torchvision && \
    pip install --no-cache-dir -r requirements.txt && \
    # --- AGGRESSIVE CLEANUP: Remove all caches and unnecessary files in a single layer ---
    rm -rf /root/.cache/pip && \
    find $VENV_PATH -type d -name "__pycache__" -exec rm -rf {} + && \
    find $VENV_PATH -type f -name "*.pyc" -delete && \
    find $VENV_PATH -type f -name "*.o" -delete && \
    # Remove test directories from installed packages, which can be quite large
    find $VENV_PATH/lib/python3.11/site-packages/ -type d -name "tests" -exec rm -rf {} + && \
    find $VENV_PATH/lib/python3.11/site-packages/ -type d -name "test" -exec rm -rf {} +

# --- HOTFIX: Globally disable numba caching in librosa ---
# This command is now guaranteed to work because pip correctly installed librosa.
RUN find $VENV_PATH/lib/python3.11/site-packages/librosa -type f -name "*.py" -print0 | xargs -0 sed -i 's/cache=True/cache=False/g'


# Stage 3: Build the isolated basic-pitch environment
FROM python:3.11 AS basic-pitch-builder

WORKDIR /app

# Create an isolated virtual environment.
RUN python3 -m venv /opt/venv_basic_pitch
ENV PATH="/opt/venv_basic_pitch/bin:$PATH"

# Rebuild the basic-pitch environment correctly from scratch
# 1. Upgrade pip first.
# 2. Install basic-pitch *without* its heavy dependencies (like tensorflow).
# 3. Manually install only the *required* dependencies for basic-pitch to run with tflite-runtime.
# This avoids installing the full tensorflow package altogether.
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir --no-deps "basic-pitch[tflite]" && \
    pip install --no-cache-dir "numpy<2.0" "librosa>=0.8.0" "scipy>=1.4.1" "soxr" "resampy<0.4.3,>=0.2.2" "scikit-learn" "mido>=1.1.16" "pretty_midi>=0.2.9" "mir-eval>=0.6" "typing-extensions" "tflite-runtime" && \
    # --- AGGRESSIVE CLEANUP for basic-pitch venv ---
    rm -rf /root/.cache/pip && \
    find /opt/venv_basic_pitch -type d -name "__pycache__" -exec rm -rf {} + && \
    find /opt/venv_basic_pitch -type f -name "*.pyc" -delete && \
    find /opt/venv_basic_pitch -type f -name "*.o" -delete && \
    find /opt/venv_basic_pitch/lib/python3.11/site-packages/ -type d -name "tests" -exec rm -rf {} + && \
    find /opt/venv_basic_pitch/lib/python3.11/site-packages/ -type d -name "test" -exec rm -rf {} +

# --- HOTFIX: Apply the same numba cache fix to this isolated environment ---
RUN find /opt/venv_basic_pitch/lib/python3.11/site-packages/librosa -type f -name "*.py" -print0 | xargs -0 sed -i 's/cache=True/cache=False/g'

# Stage 4: Final, lightweight application image
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV VENV_PATH=/opt/venv
ENV PATH="/opt/venv/bin:/opt/venv_basic_pitch/bin:$PATH"

# Copy the virtual environments from the builder stages
COPY --from=venv-builder $VENV_PATH $VENV_PATH
COPY --from=basic-pitch-builder /opt/venv_basic_pitch /opt/venv_basic_pitch

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

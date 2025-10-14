# Stage 1: Build the requirements.txt file in a dedicated environment
FROM python:3.11 AS poetry-builder

# Update base image packages to patch security vulnerabilities
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

WORKDIR /builder

# Define a build argument to control dependency installation
ARG INSTALL_DEV_DEPS=false

# Install poetry
RUN pip install poetry==2.1.4 poetry-plugin-export

# Copy only the files needed to resolve dependencies
# Copy pyproject.toml, and optionally poetry.lock if it exists.
COPY pyproject.toml poetry.lock* ./

# Export dependencies to requirements.txt.

# This ensures the lock file is always in sync with pyproject.toml before exporting.
RUN if [ ! -f poetry.lock ] || [ pyproject.toml -nt poetry.lock ]; then \
        echo "-> pyproject.toml is new or modified, running poetry lock..."; \
        poetry lock; \
    fi && \
    poetry export -f requirements.txt --output requirements.txt --without-hashes

# Stage 2: Build the Python virtual environment with all dependencies
FROM python:3.11 AS venv-builder

WORKDIR /app


# Install system dependencies required for building Python packages
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    build-essential python3-dev cmake git ffmpeg abcmidi jq \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create a virtual environment
ENV VENV_PATH=/opt/venv
RUN python3 -m venv $VENV_PATH
ENV PATH="$VENV_PATH/bin:$PATH"

# Copy requirements from the first stage
COPY --from=poetry-builder /builder/requirements.txt .

# Install dependencies into the virtual environment

# Upgrade pip and setuptools first to ensure the latest versions are used for dependency installation. This resolves known vulnerabilities.
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# --- FIX: Force installation of CPU-only torch to drastically reduce image size ---
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

# --- HOTFIX: Globally disable numba caching in librosa to prevent errors in Docker. ---
RUN find $VENV_PATH/lib/python3.11/site-packages/librosa -type f -name "*.py" -print0 | xargs -0 sed -i 's/cache=True/cache=False/g'


# Stage 2.5: Build the isolated basic-pitch environment
FROM python:3.11 AS basic-pitch-builder

WORKDIR /app

# Create an isolated virtual environment.
RUN python3 -m venv /opt/venv_basic_pitch

ENV PATH="/opt/venv_basic_pitch/bin:$PATH"

# --- FINAL, FINAL, FINAL FIX: Rebuild the basic-pitch environment correctly from scratch ---
# 1. Upgrade pip and setuptools first.
# 2. Install basic-pitch *without* its heavy dependencies (like tensorflow).
# 3. Manually install only the *required* dependencies for basic-pitch to run with tflite-runtime.
# This avoids installing the full tensorflow package altogether.
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir --no-deps "basic-pitch[tflite]" && \
    pip install --no-cache-dir \
        "numpy<2.0" \
        "librosa>=0.8.0" "scipy>=1.4.1" "soxr" "resampy<0.4.3,>=0.2.2" \
        "scikit-learn" "mido>=1.1.16" "pretty_midi>=0.2.9" "mir-eval>=0.6" "typing-extensions" && \
    pip install --no-cache-dir "tflite-runtime"

# --- HOTFIX: Apply the same numba cache fix to this isolated environment ---
RUN find /opt/venv_basic_pitch/lib/python3.11/site-packages/librosa -type f -name "*.py" -print0 | xargs -0 sed -i 's/cache=True/cache=False/g'

# Stage 3: Final application image (lightweight)
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV HF_HOME=/app/user_models
ENV TORCH_HOME=/app/user_models/torch
ENV VENV_PATH=/opt/venv
ENV PATH="$VENV_PATH/bin:$PATH"

# Copy the virtual environments from the venv-builder stage
COPY --from=venv-builder $VENV_PATH $VENV_PATH
COPY --from=basic-pitch-builder /opt/venv_basic_pitch /opt/venv_basic_pitch

RUN /usr/local/bin/pip install --no-cache-dir --upgrade setuptools

# --- NEW: Install runtime dependencies directly into the final image ---

RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends ffmpeg abcmidi && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy the application code
COPY --chown=65532:65532 ./solasola /app/solasola
COPY --chown=65532:65532 config.yaml .

# Switch to the non-root user
USER 65532

# This section defines default volumes.
# When a user clicks "Run" in Docker Desktop, these paths will be suggested
# in the "Optional Settings", making it easy to map them to local folders.
VOLUME /app/cache
VOLUME /app/user_models

# Expose the port the app runs on. This helps Docker Desktop and other tools.
EXPOSE 5656

# Add a health check to allow Docker to monitor the application's status.
# It will try to connect every 30s, timeout after 5s, and retry 3 times before marking as unhealthy.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  # Use a Python script for healthcheck as curl is not available in distroless
  CMD ["python", "-m", "solasola.healthcheck"]

# Set the default command to run the application in production (no-debug) mode.
CMD ["python", "-m", "solasola.app", "--no-debug"]
# Trigger CI

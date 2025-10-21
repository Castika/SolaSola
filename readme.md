# SolaSola

**Your AI-powered music transcription assistant.**  
[View on GitHub](https://github.com/castika/SolaSola)
[View on Docker Hub](https://hub.docker.com/r/castika/solasola)

[English](#english) | [한국어](#한국어)

---

> **⚠️ Security Notice** 
> This application is designed for personal use on a private network. Due to potential security risks, **do not expose this application to the public internet.**

---

## English

SolaSola is a desktop application that analyzes audio files (MP3, WAV, etc.) to automatically generate instrument-specific scores (in ABC notation) and chord progressions. It runs securely on your local machine via Docker, requiring no complex setup.

### Key Features

-   **AI-Powered Instrument Separation**: Uses the Demucs model to separate up to 6 different instrument stems like vocals, drums, bass, and piano.
-   **MIDI Generation**: Converts each separated instrument stem into a MIDI file.
-   **Automatic Transcription**: Automatically converts the generated MIDI files into human-readable ABC notation scores.
-   **Chord and Structure Analysis**: Analyzes and provides the song's genre, chord progression, key, tempo, and structure.
-   **Local & Private**: All file processing and AI analysis run directly on your computer. Your files are never sent to an external server, ensuring your privacy and copyright are protected.
-   **Cache System**: The results of an analyzed file are saved as a cache, significantly reducing processing time when analyzing the same file again.

### Quickstart

SolaSola runs in a secure environment on your computer using Docker. Follow these steps to get started.

#### 1. Install Docker Desktop

If you don't have it already, download and install Docker Desktop for your operating system. This is the only software you need.

-   [Download Docker Desktop](https://www.docker.com/products/docker-desktop)

After installing, make sure Docker Desktop is running. You should see the Docker icon in your system tray or menu bar.

#### 2. Set Up and Run SolaSola

This method ensures that all your data, like downloaded AI models and analysis results, is saved in a predictable location on your computer, making it easy to manage.

1.  **Create a SolaSola Folder:** Navigate to your user's standard music folder (e.g., `Music`, `음악`) and create a new folder named `SolaSola`. This will be the central location for all your data.
    -   **macOS:** `~/Music/SolaSola`
    -   **Windows:** `C:\Users\<YourUsername>\Music\SolaSola`

2.  **Create the `docker-compose.yml` File:** Inside the `SolaSola` folder you just created, create a new file named `docker-compose.yml` and paste the following content into it:

    ```yaml
    services:
      solasola:
        # This will pull the pre-built image from Docker Hub.
        image: castika/solasola:latest
        container_name: solasola_web
        restart: unless-stopped
        ports:
          - "5656:5656"
        volumes:
          # These paths are relative to this docker-compose.yml file.
          # Docker will automatically create 'Music' and 'AI_Models' folders
          # in the same directory where you run 'docker compose up'.
          - ./Music:/app/output
          - ./AI_Models:/app/user_models
        environment:
          # Tell Hugging Face, PyTorch, and our app where the persistent model cache is.
          - HF_HOME=/app/user_models
          - TORCH_HOME=/app/user_models/torch
          - HOST_AI_MODELS_DIR=/app/user_models
          - HOST_MUSIC_DIR=/app/output
        # Always run in production mode for end-users.
        command: python -m solasola.app --no-debug
    ```

3.  **Run SolaSola:**
    -   Open a Terminal (or Command Prompt/PowerShell).
    -   Navigate to the `SolaSola` folder you created using the `cd` command.
    -   Run the following command:
        ```bash
        docker compose up -d
        ```
    The first time you run this, Docker will download the SolaSola application image, which may take a few minutes.

#### 3. Use SolaSola

-   Open your web browser and go to **http://localhost:5656**.
-   Inside the `SolaSola` folder you created, two new subfolders will be automatically created: `Music` (for analysis results) and `AI_Models` (for downloaded AI models).

#### 4. How to Stop SolaSola

-   **Via Terminal:**
    Navigate to your SolaSola folder in the terminal and run:
    ```bash
    docker compose down
    ```
-   **Via Docker Desktop:**
    You can also stop the container directly from the Docker Desktop UI.

### System Requirements

-   **Docker Environment**: Docker Desktop (Windows/macOS) or Docker Engine (Linux).
-   **RAM (Allocated to Docker)**: Minimum 4GB, **8GB+ recommended**.
-   **CPU**: 2 cores or more (4+ cores recommended).
-   **Storage**: Minimum 15GB of free space for the Docker image and AI models.

---

## 한국어

SolaSola는 오디오 파일(MP3, WAV 등)을 분석하여 악기별 악보(ABC 표기법), 코드 진행을 자동으로 생성해주는 데스크톱 애플리케이션입니다. 복잡한 설정 없이 Docker를 통해 로컬 컴퓨터에서 모든 작업을 안전하게 처리합니다.

### 주요 기능

-   **AI 기반 악기 분리**: Demucs 모델을 사용하여 보컬, 드럼, 베이스, 피아노 등 최대 6개의 다양한 악기 스템을 분리합니다.
-   **MIDI 생성**: 분리된 각 악기 스템을 MIDI 파일로 변환합니다.
-   **자동 악보 변환**: 생성된 MIDI 파일을 사람이 읽기 쉬운 ABC 표기법 악보로 자동 변환합니다.
-   **코드 및 곡 구조 분석**: 장르, 노래의 코드 진행, 조성(Key), 템포, 곡 구조 등을 분석하여 제공합니다.
-   **로컬 환경 및 개인정보 보호**: 모든 파일 처리와 AI 분석은 사용자의 컴퓨터에서 직접 실행됩니다. 파일이 외부 서버로 전송되지 않아 개인정보와 저작권을 안전하게 보호합니다.
-   **캐시 시스템**: 한번 분석한 파일의 결과는 캐시로 저장되어, 동일한 파일을 다시 분석할 때 처리 시간을 크게 단축합니다.

### 빠른 시작

SolaSola는 Docker를 사용하여 사용자의 컴퓨터에서 안전한 환경으로 실행됩니다. 아래 단계를 따라 시작하세요.

#### 1. Docker Desktop 설치

Docker Desktop이 설치되어 있지 않다면, 운영체제에 맞게 다운로드하여 설치하세요. 이 프로그램 하나만 필요합니다.

-   Docker Desktop 다운로드

설치 후, Docker Desktop이 실행 중인지 확인하세요. 시스템 트레이나 메뉴 바에 Docker 아이콘이 보여야 합니다.

#### 2. SolaSola 설정 및 실행

이 방법을 사용하면 다운로드된 AI 모델이나 분석 결과물과 같은 모든 데이터가 예측 가능한 위치에 저장되어 관리가 용이합니다.

1.  **SolaSola 폴더 만들기:** 사용자의 기본 음악 폴더(예: `Music`, `음악` 등)로 이동하여 `SolaSola`라는 이름의 새 폴더를 만듭니다. 이곳이 앞으로 모든 데이터가 저장될 중심 위치가 됩니다.
    -   **macOS:** `~/Music/SolaSola`
    -   **Windows:** `C:\Users\<사용자이름>\Music\SolaSola`

2.  **`docker-compose.yml` 파일 만들기:** `SolaSola` 폴더 안에 `docker-compose.yml`이라는 새 파일을 만들고 아래 내용을 붙여넣으세요.

    ```yaml
    services:
      solasola:
        # Docker Hub에서 사전 빌드된 이미지를 가져옵니다.
        image: castika/solasola:latest
        container_name: solasola_web
        restart: unless-stopped
        ports:
          - "5656:5656"
        volumes:
          # 이 경로는 docker-compose.yml 파일을 기준으로 합니다.
          # 'docker compose up'을 실행하면 'Music'과 'AI_Models' 폴더가 자동으로 생성됩니다.
          - ./Music:/app/output
          - ./AI_Models:/app/user_models
        environment:
          # Hugging Face, PyTorch, 그리고 앱에 모델 캐시 위치를 알려줍니다.
          - HF_HOME=/app/user_models
          - TORCH_HOME=/app/user_models/torch
          - HOST_AI_MODELS_DIR=/app/user_models
          - HOST_MUSIC_DIR=/app/output
        # 최종 사용자를 위해 항상 프로덕션 모드로 실행합니다.
        command: python -m solasola.app --no-debug
    ```

3.  **SolaSola 실행:**
    -   터미널(또는 명령 프롬프트/PowerShell)을 엽니다.
    -   `cd` 명령어를 사용하여 생성한 `SolaSola` 폴더로 이동합니다.
    -   아래 명령어를 실행합니다:
        ```bash
        docker compose up -d
        ```
    처음 실행 시 Docker가 SolaSola 애플리케이션 이미지를 다운로드하며, 몇 분 정도 소요될 수 있습니다.

#### 3. SolaSola 사용법

-   웹 브라우저를 열고 **http://localhost:5656** 주소로 이동하세요.
-   사용자가 만든 `SolaSola` 폴더 안에 `Music`(분석 결과용)과 `AI_Models`(다운로드된 AI 모델용)라는 두 개의 하위 폴더가 자동으로 생성됩니다.

#### 4. SolaSola 중지 방법

-   터미널에서 SolaSola 폴더로 이동한 후 다음 명령어를 실행하세요.
    ```bash
    docker compose down
    ```
-   또는 Docker Desktop 앱에서 직접 컨테이너를 중지할 수 있습니다.

### 시스템 요구사항

-   **Docker 환경**: Docker Desktop (Windows/macOS) 또는 Docker Engine (Linux).
-   **RAM (Docker 할당 기준)**: 최소 4GB, **8GB+ 권장**.
-   **CPU**: 2코어 이상 (4+ 코어 권장).
-   **저장 공간**: Docker 이미지 및 AI 모델을 위해 최소 15GB의 여유 공간.
import threading
import time
from pathlib import Path
import os
import logging
import math

# Manages deletion of the `.xet` cache folder created by `huggingface-hub`
# during model downloads to prevent excessive disk space usage.
# DELETION IS DISABLED BY DEFAULT FOR SAFETY in _delete_xet_cache.


logger = logging.getLogger(__name__)

class XetCacheManager:
    """Schedules deletion of the .xet cache directory."""
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs): # noqa
        with cls._lock:  # Ensure thread-safe instantiation.
            if cls._instance is None:
                cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        self._initialized = True

        self._active_downloads = 0
        self.scheduled_deletion_time = None
        self.condition = threading.Condition()
        self.xet_cache_path = Path(os.getenv("HF_HOME", "/app/user_models")) / "xet"
        self.MIN_WAIT_MINUTES = 5

    def start_download(self):
        """Notifies manager that a download has started."""
        with self.condition:
            self._active_downloads += 1
            if self.scheduled_deletion_time is not None:
                logger.info(
                    f"[XetManager] New download started. Cancelling "
                    f"pending 'xet' cache deletion scheduled for "
                    f"{time.ctime(self.scheduled_deletion_time)}.")
                self.scheduled_deletion_time = None
                self.condition.notify()
            logger.info(f"[XetManager] Download started. Active downloads: "
                        f"{self._active_downloads}")

    def finish_download(self, download_duration_seconds: float):
        """Notifies manager that a download has finished."""
        with self.condition:
            if self._active_downloads > 0:
                self._active_downloads -= 1
            logger.info(
                f"[XetManager] Download finished. Active downloads remaining: {self._active_downloads}")

            # Only schedule a deletion if this was the last active download.
            if self._active_downloads == 0:
                duration_minutes = math.ceil(download_duration_seconds / 60)

                calculated_delay_minutes = math.floor(
                    duration_minutes * 1.5)

                final_delay_minutes = max(
                    self.MIN_WAIT_MINUTES, calculated_delay_minutes)

                final_delay_seconds = final_delay_minutes * 60
                new_deletion_time = time.time() + final_delay_seconds

                if self.scheduled_deletion_time is None or new_deletion_time > self.scheduled_deletion_time:
                    logger.info(
                        f"[XetManager] All downloads complete. Scheduling 'xet' "
                        f"cache deletion for {time.ctime(new_deletion_time)} "
                        f"(in {final_delay_minutes} minutes).")
                    self.scheduled_deletion_time = new_deletion_time
                    self.condition.notify()

    def _delete_xet_cache(self):
        """Safely deletes the xet cache directory."""
        if self.xet_cache_path.exists():
            # To re-enable, uncomment the `try...except` block below.
            # try:
            #     logger.info(f"[XetManager] Deleting 'xet' cache: {self.xet_cache_path}")
            #     shutil.rmtree(self.xet_cache_path)
            #     logger.info("[XetManager] 'xet' cache deletion successful.")
            # except Exception as e:
            #     logger.error(f"[XetManager] FAILED to delete 'xet' cache: {e}")
            pass

    def run(self):
        """Main loop for the manager thread."""
        logger.info("[XetManager] Cache Manager thread started.")
        while True:
            with self.condition:
                while self.scheduled_deletion_time is None or self._active_downloads > 0:
                    self.condition.wait()

                wait_time = self.scheduled_deletion_time - time.time()

                if wait_time > 0:
                    self.condition.wait(timeout=wait_time)

            with self.condition:
                if self.scheduled_deletion_time is not None and time.time() >= self.scheduled_deletion_time and self._active_downloads == 0:
                    self._delete_xet_cache()
                    self.scheduled_deletion_time = None # Reset after deletion

# Create a single instance to be imported by other modules
xet_manager = XetCacheManager()
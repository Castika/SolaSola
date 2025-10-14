import threading
import time
import shutil
from pathlib import Path
import os
import logging
import math

# =================================================================================
# ==                         .XET CACHE MANAGER - IMPORTANT                        ==
# =================================================================================
# == PURPOSE: This manager automatically deletes the `.xet` cache folder created ==
# ==          by `huggingface-hub` during model downloads to prevent it from     ==
# ==          consuming excessive disk space over time.                          ==
# ==                                                                             ==
# == CURRENT STATUS: DELETION IS DISABLED BY DEFAULT FOR SAFETY.                 ==
# == The logic to schedule deletion is active, but the final `shutil.rmtree`     ==
# == command is commented out in the `_delete_xet_cache` method below.           ==
# ==                                                                             ==
# == TO RE-ENABLE DELETION:                                                      ==
# == 1. In the `_delete_xet_cache` method, uncomment the `try...except` block.   ==
# == 2. Comment out or remove the `pass` statement that follows it.              ==
# ==                                                                             ==
# == The folder that will be deleted is located at: `{HF_HOME}/xet`              ==
# =================================================================================

logger = logging.getLogger(__name__)

class XetCacheManager:
    """
    A thread-safe singleton manager to schedule the deletion of the .xet cache directory.
    This prevents multiple downloads from conflicting with each other's cleanup tasks.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock: # Ensure thread-safe instantiation.
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
        """
        Notifies the manager that a download has started.
        This increments the active download counter and cancels any pending deletion.
        """
        with self.condition:
            self._active_downloads += 1
            if self.scheduled_deletion_time is not None:
                logger.info(f"[XetManager] New download started. Cancelling pending 'xet' cache deletion scheduled for {time.ctime(self.scheduled_deletion_time)}.")
                self.scheduled_deletion_time = None
                self.condition.notify() # Wake up the run loop to acknowledge the cancellation.
            logger.info(f"[XetManager] Download started. Active downloads: {self._active_downloads}")

    def finish_download(self, download_duration_seconds: float):
        """
        Notifies the manager that a download has finished.
        If no other downloads are active, it schedules a new deletion task.
        """
        with self.condition:
            if self._active_downloads > 0:
                self._active_downloads -= 1
            logger.info(f"[XetManager] Download finished. Active downloads remaining: {self._active_downloads}")

            # Only schedule a deletion if this was the last active download.
            if self._active_downloads == 0:
                # Per user spec: round up duration to the nearest minute.
                duration_minutes = math.ceil(download_duration_seconds / 60)

                # Per user spec: calculate delay (1.5x) and floor to the nearest minute.
                calculated_delay_minutes = math.floor(duration_minutes * 1.5)

                # Per user spec: enforce a minimum wait time.
                final_delay_minutes = max(self.MIN_WAIT_MINUTES, calculated_delay_minutes)
                
                final_delay_seconds = final_delay_minutes * 60
                new_deletion_time = time.time() + final_delay_seconds

                # If there's an existing schedule (which shouldn't happen with this logic, but is here for safety)
                # or no schedule, set the new one. The "take the later of the two" logic is implicitly handled
                # because new schedules are only set when the download count hits zero.
                if self.scheduled_deletion_time is None or new_deletion_time > self.scheduled_deletion_time:
                    logger.info(f"[XetManager] All downloads complete. Scheduling 'xet' cache deletion for {time.ctime(new_deletion_time)} (in {final_delay_minutes} minutes).")
                    self.scheduled_deletion_time = new_deletion_time
                    self.condition.notify()

    def _delete_xet_cache(self):
        """Safely deletes the xet cache directory."""
        if self.xet_cache_path.exists():
            # --- DELETION IS CURRENTLY DISABLED BY DEFAULT FOR SAFETY ---
            # To re-enable automatic .xet cache deletion:
            # 1. Uncomment the entire `try...except` block below.
            # 2. Comment out or remove the `pass` statement that follows.
            # This will permanently delete the folder and all its contents: {self.xet_cache_path}
            # try:
            #     logger.info(f"[XetManager] Deleting 'xet' cache at: {self.xet_cache_path}")
            #     shutil.rmtree(self.xet_cache_path)
            #     logger.info("[XetManager] 'xet' cache deletion successful.")
            # except Exception as e:
            #     logger.error(f"[XetManager] FAILED to delete 'xet' cache: {e}")
            pass

    def run(self):
        """The main loop for the manager thread. It waits until a scheduled deletion time is reached."""
        logger.info("[XetManager] Cache Manager thread started.")
        while True:
            with self.condition:
                # The thread will wait here indefinitely if there's no deletion scheduled or if downloads are active.
                while self.scheduled_deletion_time is None or self._active_downloads > 0:
                    self.condition.wait()

                # A deletion is scheduled and no downloads are active. Calculate the remaining wait time.
                wait_time = self.scheduled_deletion_time - time.time()

                if wait_time > 0:
                    # Wait for the scheduled time. If notified early (e.g., by a new download starting),
                    # the loop will restart and re-evaluate all conditions.
                    self.condition.wait(timeout=wait_time)

            # After waiting, re-check conditions outside the initial lock to be absolutely sure it's time to delete.
            with self.condition:
                if self.scheduled_deletion_time is not None and time.time() >= self.scheduled_deletion_time and self._active_downloads == 0:
                    self._delete_xet_cache()
                    self.scheduled_deletion_time = None # Reset after deletion

# Create a single instance to be imported by other modules
xet_manager = XetCacheManager()
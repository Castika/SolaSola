import time
from .task_manager import TASKS


def log_to_ui(task_id: str, message: str, icon: str, type: str = 'info', target: str = 'both'): # noqa
    """
    Appends a user-facing log message to the task's log list. This is the
    centralized function for all backend UI notifications.
    """
    if task_id in TASKS:
        log_entry = {
            "message": message,
            "icon": icon,
            "type": type,
            "target": target,
            "timestamp": time.time()
        }
        if 'ui_logs' not in TASKS[task_id]:
            TASKS[task_id]['ui_logs'] = []
        TASKS[task_id]['ui_logs'].append(log_entry)
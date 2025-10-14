import time
import subprocess

# This global dictionary stores the state of all active and recently completed tasks.
# In a simple, single-worker setup like this, a global variable is sufficient.
# For a multi-worker production environment, this should be replaced with a
# more robust shared state manager like Redis or a database.
TASKS = {}

class InterruptedError(Exception):
    """Custom exception for cancelled tasks."""
    pass

def update_detailed_status(task_id, stage_index, sub_stage_index, sub_stage_progress, message, status=None):
    """Updates the status of a task with detailed progress information."""
    if task_id in TASKS:
        # Automatically transition from 'starting' to 'running' on the first real progress update.
        if TASKS[task_id]['status'] == 'starting':
            TASKS[task_id]['status'] = 'running'

        # Store the detailed progress for the dynamic progress bar UI.
        TASKS[task_id]['progress_details'] = {
            'stage_index': stage_index,
            'sub_stage_index': sub_stage_index,
            'sub_stage_progress': sub_stage_progress
        }
        TASKS[task_id]['current_step'] = message
        if status:
            TASKS[task_id]['status'] = status
        print(f"Task {task_id}: [{TASKS[task_id].get('status')}] {message}")

def update_status(task_id, progress, message, status=None):
    """
    A simplified, legacy status update function.
    It primarily updates the main message and overall status.
    """
    if task_id in TASKS:
        TASKS[task_id]['progress'] = progress
        TASKS[task_id]['current_step'] = message
        if status:
            TASKS[task_id]['status'] = status
        return TASKS[task_id]

def check_for_cancellation(task_id):
    """
    Checks if a task has been marked for cancellation by the user.
    If so, it raises a custom exception to gracefully halt the process.
    """
    if TASKS.get(task_id, {}).get('cancel_requested'):
        raise InterruptedError("Task cancelled by user.")


def log_to_ui(task_id, message, icon, type='info'):
    """Appends a user-facing log message to the task's log list."""
    if task_id in TASKS:
        log_entry = {
            'message': message,
            'icon': icon,
            'type': type,
            'timestamp': time.time()
        }
        if 'ui_logs' not in TASKS[task_id]:
            TASKS[task_id]['ui_logs'] = []
        TASKS[task_id]['ui_logs'].append(log_entry)

def cleanup_old_tasks():
    """Periodically cleans up old, completed tasks from memory."""
    while True:
        # This loop runs in a background thread, waking up every hour.
        time.sleep(3600)
        
        now = time.time()
        tasks_to_delete = []
        
        # Identify tasks that are finished (completed, failed, or cancelled)
        # and are older than 2 hours to prevent the TASKS dictionary from
        # growing indefinitely over long server sessions.
        for task_id, task in list(TASKS.items()):
            task_age = now - task.get('timestamp', now)
            if task['status'] in ['completed', 'failed', 'cancelled'] and task_age > 7200:
                tasks_to_delete.append(task_id)
        
        if tasks_to_delete:
            print(f"Cleaning up {len(tasks_to_delete)} old task(s)...")
            for task_id in tasks_to_delete:
                del TASKS[task_id]
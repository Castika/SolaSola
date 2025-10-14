import { showNotification, setTheme, getCookie, deleteCookie } from './ui-helpers.js';

const progressBarContainer = document.getElementById('progress-bar-container');
const progressText = document.getElementById('progress-text');
const cancelButton = document.getElementById('cancel-button');

let currentTaskId = null;
let pollingInterval = null;
let processStartTime = null;
let lastLogCount = 0; // Track log count within the iframe

/**
 * Builds the dynamic progress bar based on the layout provided by the backend.
 * @param {object} layout The layout object with stages and sub-stages.
 */
function buildProgressBar(layout) {
    progressBarContainer.innerHTML = ''; // Clear any existing content
    progressBarContainer.className = 'analysis-progress-container'; // Ensure the correct class is set
    if (!layout || !layout.stages) {
        console.error("Invalid layout received from backend.");
        return;
    }

    layout.stages.forEach((stageData, index) => {
        const stageEl = document.createElement('div');
        stageEl.className = 'stage';
        stageEl.id = `stage-${index + 1}`;
        stageEl.dataset.label = stageData.label;
        stageEl.dataset.weight = `${stageData.weight}%`;
        stageEl.style.flexGrow = stageData.weight;

        for (let i = 0; i < stageData.sub_stages; i++) {
            const subStageEl = document.createElement('div');
            subStageEl.className = 'sub-stage';
            subStageEl.title = `${stageData.label} - Step ${i + 1}`;
            
            const progressEl = document.createElement('div');
            progressEl.className = 'sub-stage-progress';
            subStageEl.appendChild(progressEl);
            stageEl.appendChild(subStageEl);
        }
        progressBarContainer.appendChild(stageEl);
    });
}

/**
 * Updates the UI based on the detailed progress from the backend.
 * @param {object} details The progress_details object.
 * @param {string} currentStep The current step message from the backend.
 */
function updateProgressBar(details, currentStep) {
    if (!details || typeof details.stage_index === 'undefined') return;

    const allStages = document.querySelectorAll('.stage');
    const stageIndex = details.stage_index - 1;
    const subStageIndex = details.sub_stage_index - 1;
    const subStageProgress = details.sub_stage_progress;

    // --- REFACTORED LOGIC ---

    // 1. Fill all stages before the current one to 100%
    for (let i = 0; i < stageIndex; i++) {
        if (allStages[i]) {
            allStages[i].querySelectorAll('.sub-stage-progress').forEach(p => p.style.width = '100%');
        }
    }

    // 2. Handle the current stage based on its index
    if (allStages[stageIndex]) {
        const currentStage = allStages[stageIndex];
        const subStages = currentStage.querySelectorAll('.sub-stage');

        // --- NEW: Special handling for Stage 3 (Model Preparation/Download) ---
        if (details.stage_index === 3) {
            // --- FIX: Use the `currentStep` parameter, which is passed in from pollStatus ---
            // The `details` object (progress_details) does not contain the step message.
            if (!currentStep) return; // Safeguard

            const downloadMatch = currentStep.match(/Downloading model file (\d+)/);
            if (downloadMatch) {
                const fileNumber = parseInt(downloadMatch[1], 10);
                // Fill up to the current download number.
                // This assumes the backend correctly configured the number of sub-stages for this stage.
                for (let i = 0; i < fileNumber; i++) {
                    if (subStages[i]) {
                        subStages[i].querySelector('.sub-stage-progress').style.width = '100%';
                    }
                }
            } else {
                // If it's stage 3 but not a download message, just show the percentage.
                if (subStages[subStageIndex]) {
                    subStages[subStageIndex].querySelector('.sub-stage-progress').style.width = `${subStageProgress}%`;
                }
            }
        } else { // Original logic for all other stages
            // Fill previous sub-stages of the current stage
            for (let i = 0; i < subStageIndex; i++) {
                if (subStages[i]) {
                    subStages[i].querySelector('.sub-stage-progress').style.width = '100%';
                }
            }
            // Update the current sub-stage's progress
            if (subStages[subStageIndex]) {
                subStages[subStageIndex].querySelector('.sub-stage-progress').style.width = `${subStageProgress}%`;
            }
        }
    }

    // Make ALL filled progress bars pulse together
    const allProgressBars = document.querySelectorAll('.sub-stage-progress');
    allProgressBars.forEach(bar => {
        const isFilled = parseFloat(bar.style.width) > 0;
        if (isFilled) {
            bar.classList.add('pulsing');
        } else {
            bar.classList.remove('pulsing');
        }
    });
}

/**
 * Polls the backend for the status of the current task.
 */
async function pollStatus() {
    if (!currentTaskId) return;

    try {
        const response = await fetch(`/status/${currentTaskId}`);
        if (!response.ok) {
            if (response.status === 404) {
                console.info("Task ID expired or not found on server. Stopping status polling.");
                return;
            } else {
                const errorData = await response.json().catch(() => ({ error: `Server error: ${response.statusText}` }));
                console.error(`Polling error: ${errorData.error}`);
                return;
            }
        }        
        const data = await response.json();

        progressText.textContent = data.current_step;
        updateProgressBar(data.progress_details, data.current_step);

        // Pass log data to parent window via postMessage

        // This allows the main window to display toast notifications.
        if (data.ui_logs) {
            window.parent.postMessage({ type: 'log_update', logs: data.ui_logs }, window.location.origin);
        }

        if (['completed', 'failed', 'cancelled'].includes(data.status)) {
            clearInterval(pollingInterval);
            pollingInterval = null;
            const allProgressBars = document.querySelectorAll('.sub-stage-progress');
            allProgressBars.forEach(bar => bar.classList.remove('pulsing'));

            window.parent.postMessage({
                status: data.status,
                results: data.results || null
            }, window.location.origin);
        }
    } catch (error) {
        console.error('Polling error:', error);
        clearInterval(pollingInterval);
        progressText.textContent = `Error: ${error.message}`;
        cancelButton.textContent = 'Return to Main Page';
        cancelButton.classList.remove('destructive');
        cancelButton.onclick = () => {
            // Notify parent and then attempt to go back
            window.parent.postMessage({ status: 'failed' }, window.location.origin);
        };
    }
}

/**
 * Sends a cancellation request to the backend.
 */
async function cancelTask() {
    if (!currentTaskId) return;

    progressText.textContent = 'Cancelling...';
    cancelButton.disabled = true;
    const cancelTextSpan = cancelButton.querySelector('span:last-child');
    if (cancelTextSpan) cancelTextSpan.textContent = 'Cancelling...';

    try {
        await fetch(`/cancel/${currentTaskId}`, { method: 'POST' });
        // The polling function will handle the UI update when status is 'cancelled'
    } catch (error) {
        console.error('Error cancelling task:', error);

        showNotification('Failed to send cancellation request.', 'error');
        cancelButton.disabled = false;
        if (cancelTextSpan) cancelTextSpan.textContent = 'Cancel';
    }
}

/**
 * Fetches the layout for a task, retrying a few times if it's not ready yet.
 * @param {string} taskId The ID of the task.
 * @returns {Promise<object>} A promise that resolves with the layout object.
 */
async function fetchLayoutWithRetry(taskId, retries = 5, delay = 500) {
    for (let i = 0; i < retries; i++) {
        try {
            const response = await fetch(`/api/task_layout/${taskId}`);
            if (response.ok) {
                return await response.json();
            }
            if (response.status !== 404) {
                // If it's not a 404, it's a real error, so fail fast.
                throw new Error(`Server returned status ${response.status}`);
            }
            // If it is a 404, wait and retry.
            await new Promise(resolve => setTimeout(resolve, delay));
        } catch (error) {
            // Network errors will also be caught here.
            console.warn(`Attempt ${i + 1} to fetch layout failed. Retrying...`);
        }
    }
    throw new Error('Could not fetch progress bar layout after multiple attempts.');
}

/**
 * Initializes the processing page.
 */
async function initialize() {
    // Centralized theme setting function for the iframe
    const setThemeInIframe = (theme) => {
        if (theme === 'light' || theme === 'dark') {
            document.documentElement.setAttribute('data-theme', theme);
        }
    };

    // Listen for theme changes from the parent window
    window.addEventListener('message', (event) => {
        // Security check: only accept messages from the same origin
        if (event.origin !== window.location.origin) {
            return;
        }
        if (event.data && event.data.type === 'theme_change') {
            setThemeInIframe(event.data.theme);
        }
    });

    const urlParams = new URLSearchParams(window.location.search);
    let taskIdFromUrl = urlParams.get('task_id');
    let taskIdFromCookie = getCookie('sola-active-task-id');

    currentTaskId = taskIdFromUrl || taskIdFromCookie;

    if (taskIdFromCookie) {
        deleteCookie('sola-active-task-id');
    }

    if (!currentTaskId) {
        progressText.textContent = "No active task found. Redirecting to the main page...";
        setTimeout(() => { window.location.href = '/'; }, 3000);
        return;
    }

    // Immediately apply theme from parent's localStorage to prevent FOUC
    const initialTheme = localStorage.getItem('theme') || 'dark';
    setThemeInIframe(initialTheme);

    // Store the task ID in session storage to handle page reloads
    sessionStorage.setItem('activeTaskId', currentTaskId);
    processStartTime = new Date();
    sessionStorage.setItem('processStartTime', processStartTime.toISOString());

    try {
        const layout = await fetchLayoutWithRetry(currentTaskId);
        buildProgressBar(layout);

        cancelButton.onclick = cancelTask;
        pollStatus(); // Initial poll
        pollingInterval = setInterval(pollStatus, 2000);
    } catch (error) {
        console.error("Initialization failed:", error);
        progressText.textContent = `Error: ${error.message}`;
        window.parent.postMessage({ status: 'failed' }, window.location.origin);
    }
}

document.addEventListener('DOMContentLoaded', initialize);
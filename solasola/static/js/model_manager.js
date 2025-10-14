import { showModal, closeModal, showNotification, getCookie, setCookie } from './ui-helpers.js';
import sseClient from './sse_client.js';

let hostAiModelsPath = "a folder on your computer"; // Populated from server
let hostProcessingCachePath = "a folder on your computer"; // Populated from server
let isModelManagerListenerAttached = false;

let activeInstallTask = { taskId: null, repoId: null };
const progressAnimators = new Map(); // Manages progress bar animations

function handleModelManagerClick(e) {
    const installBtn = e.target.closest('.install-btn');
    const deleteBtn = e.target.closest('.delete-btn');
    const cancelBtn = e.target.closest('.cancel-install-btn');
    if (installBtn) {
        handleInstallClick(installBtn);
    } else if (deleteBtn) {
        handleDeleteClick(deleteBtn);
    } else if (cancelBtn) {
        handleCancelClick(cancelBtn);
    }
}

export async function openModelManager(languageCodeToHighlight = null) {
    showModal({
        title: 'Manage AI Models',
        bodyContent: '<div class="loader-content" style="padding: 2rem;"><div class="loader"></div><p>Loading model status...</p></div>',
        footerButtons: [{ label: 'Close', icon: 'close', action: 'close', isPrimary: true }],
        onClose: () => {
            // The SSE connection is now global and managed by sse_client.js.
            // We don't need to disconnect here, just clean up modal-specific state if any.
        }
    });

    // --- SSE: Initialize listeners for real-time updates ---
    initializeSSEListeners();

    await refreshModelList(true, languageCodeToHighlight); // Initial full render
}

export function createModelListItem(template, modelType, repoId, data) {
    const itemClone = template.content.cloneNode(true); // This is correct
    const listItem = itemClone.querySelector('li');
    listItem.classList.add('model-list-item');

    listItem.dataset.repoId = repoId;
    listItem.dataset.modelType = modelType;

    // Store deletion path and container ID for later use
    if (data.deletion_path) listItem.dataset.deletionPath = data.deletion_path;

    if (data.installer_client_id) {
        listItem.dataset.installerClientId = data.installer_client_id;
    }

    const nameWrapper = listItem.querySelector('.model-name-wrapper');
    nameWrapper.querySelector('.model-name').textContent = data.name;
    nameWrapper.querySelector('.model-name').title = data.name;


    // Add model size
    const sizeEl = nameWrapper.querySelector('.model-size');
    if (sizeEl && data.size) {
        sizeEl.textContent = data.size;
    } else if (sizeEl) {
        sizeEl.style.display = 'none'; // Hide if no size is provided
    }
    updateListItemState(listItem, data);
    return listItem;
}

async function refreshModelList(isInitialLoad = false, languageCodeToHighlight = null) {
    const modalBody = document.getElementById('sola-modal-body');
    if (!modalBody) return;

    // If the custom model form is open, don't refresh the list in the background.

    try {
        const statusResponse = await fetch('/api/models_status');
        if (!statusResponse.ok) {
            const errorData = await statusResponse.json().catch(() => ({ error: `Server returned status ${statusResponse.status}` }));
            throw new Error(errorData.error || 'Failed to load model status.');
        }
        const newStatuses = await statusResponse.json();

        if (isInitialLoad || !document.getElementById('feature-models-list')) {
            progressAnimators.forEach(animator => animator.stop());
            progressAnimators.clear();
            const templateResponse = await fetch('/templates/model_manager.html');
            if (!templateResponse.ok) throw new Error('Failed to load UI template.');
            const templateHtml = await templateResponse.text();
            renderModelList(newStatuses, templateHtml);
        } else {
            updateExistingModelList(newStatuses);
        }

    } catch (error) {
        console.error("Error refreshing model list:", error);
        if (isInitialLoad) {
            modalBody.innerHTML = `<div class="error-message"><p>Could not load model list: ${error.message}</p></div>`;
        }
    }
}

function setGlobalInstallState(isInstalling) {
    // Disable/enable all install buttons
    document.querySelectorAll('.install-btn, .delete-btn').forEach(btn => {
        btn.disabled = isInstalling;
    });

    const refreshBtn = document.getElementById('refresh-models-btn');
    if (refreshBtn) refreshBtn.disabled = isInstalling;
}

function updateExistingModelList(statuses) {
    const allNewModels = {
        ...statuses.feature_models,
        ...statuses.separation_models
    };

    document.querySelectorAll('.model-list-item').forEach(item => {
        const repoId = item.dataset.repoId;
        const newStatus = allNewModels[repoId];
        if (newStatus) {
            updateListItemState(item, newStatus);
        }
    });

    setGlobalInstallState(Object.values(allNewModels).some(s => s.installing));
}
function resortList(listContainer) {
    const allItems = Array.from(listContainer.children);
    const dynamicItems = allItems.filter(item => item.id !== 'default-english-model-item');

    dynamicItems.sort((itemA, itemB) => {
        const aInstalled = itemA.dataset.installState === 'installed';
        const bInstalled = itemB.dataset.installState === 'installed';
        if (aInstalled !== bInstalled) return aInstalled ? -1 : 1;

        // Sort the rest alphabetically
        const aName = itemA.querySelector('.model-name').textContent;
        const bName = itemB.querySelector('.model-name').textContent;
        return aName.localeCompare(bName);
    });
    dynamicItems.forEach(item => listContainer.appendChild(item));
}

export function resortAndScroll(listContainer, listItem) {
    resortList(listContainer);
    if (listItem) {
        listItem.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
}

function _renderAlertBox(modalBody, hostAiModelsPath) {
    const alertBox = modalBody.querySelector('#model-cache-alert');
    if (!alertBox) return;

    if (getCookie('modelCacheAlertDismissed') === 'true') {
        alertBox.style.display = 'none';
    } else {
        const alertCloseBtn = alertBox.querySelector('.alert-close-btn');
        if (alertCloseBtn) {
            alertCloseBtn.addEventListener('click', () => {
                alertBox.style.display = 'none';
                setCookie('modelCacheAlertDismissed', 'true', 30);
            });
        }
    }
}

function _renderModelSection(listElement, template, models, modelType) {
    if (!listElement || !models) return;
    listElement.innerHTML = '';
    Object.entries(models).forEach(([repoId, data]) => {
        const listItem = createModelListItem(template, modelType, repoId, data);
        listElement.appendChild(listItem);
    });
}

function _setupActionButtons(modalBody) {
    const refreshBtn = modalBody.querySelector('#refresh-models-btn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', async () => {
            refreshBtn.disabled = true;
            const icon = refreshBtn.querySelector('.material-symbols-outlined');
            if (icon) icon.classList.add('spin');
            
            try {
                const response = await fetch('/api/refresh_models_status', { method: 'POST' });
                if (!response.ok) throw new Error('Failed to refresh model list.');
                await refreshModelList(true); // Then do a full re-render

                showNotification({ message: "Model list refreshed.", type: 'success', icon: 'sync', duration: 2000, target: 'toast' });
            } catch (error) {
                showNotification({ message: error.message, type: 'error', duration: 5000, target: 'toast' });
            } finally {
                refreshBtn.disabled = false;
                if (icon) icon.classList.remove('spin');
            }
        });
    }

    if (!isModelManagerListenerAttached) {
        modalBody.addEventListener('click', handleModelManagerClick);
        isModelManagerListenerAttached = true;
    }
}

function _highlightAndScroll(modalBody, languageCodeToHighlight) {
    if (!languageCodeToHighlight) return;

    const newlyInstalledItem = modalBody.querySelector(`[data-language-code="${languageCodeToHighlight}"]`);
    if (newlyInstalledItem) {
        // A small delay ensures the UI has settled before scrolling.
        setTimeout(() => {
            newlyInstalledItem.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }, 100);
    }
}

function renderModelList(statuses, templateHtml, languageCodeToHighlight = null) {
    const modalBody = document.getElementById('sola-modal-body');
    hostAiModelsPath = statuses.host_ai_models_path || hostAiModelsPath;
    hostProcessingCachePath = statuses.host_processing_cache_path || hostProcessingCachePath;
    modalBody.innerHTML = templateHtml;

    _renderAlertBox(modalBody, hostAiModelsPath);

    const featureList = modalBody.querySelector('#feature-models-list');
    const itemTemplate = modalBody.querySelector('#model-list-item-template');
    const separationList = modalBody.querySelector('#separation-models-list');

    if (!itemTemplate) {
        console.error("Could not find essential list elements in the modal body.");
        return;
    }

    _renderModelSection(featureList, itemTemplate, statuses.feature_models, 'genre');
    _renderModelSection(separationList, itemTemplate, statuses.separation_models, 'separation');

    const allStatuses = { ...statuses.feature_models };
    setGlobalInstallState(Object.values(allStatuses).some(s => s.installing));

    _setupActionButtons(modalBody);
    _highlightAndScroll(modalBody, languageCodeToHighlight);
}

function updateListItemState(listItem, status, showProgressBar = false) {
    if (!listItem) return;

    const installedEl = listItem.querySelector('.status-installed');
    const installingEl = listItem.querySelector('.status-installing');
    const installBtn = listItem.querySelector('.install-btn');
    const deleteBtn = listItem.querySelector('.delete-btn');
    const progressBarContainer = listItem.querySelector('.progress-bar-container');
    const cancelBtn = listItem.querySelector('.cancel-install-btn');
    const sizeEl = listItem.querySelector('.model-size'); // Get the size element

    if (deleteBtn) {
        deleteBtn.disabled = false;
        deleteBtn.innerHTML = '<span class="material-symbols-outlined">delete</span>';
    }

    // Reset all states first
    if (installedEl) installedEl.style.display = 'none';
    if (installingEl) installingEl.style.display = 'none';
    if (installBtn) installBtn.style.display = 'none';
    if (progressBarContainer) progressBarContainer.style.display = 'none';
    listItem.classList.remove('is-installing');

    let state;

    if (status.installing) {
        state = 'installing';
        if (installingEl) installingEl.style.display = 'flex'; // Always show "Installing..." text
        if (sizeEl) sizeEl.style.display = 'inline-block'; // Always show size when installing
        if (showProgressBar) {
            listItem.classList.add('is-installing');
            if (progressBarContainer) progressBarContainer.style.display = 'block';
            if (cancelBtn) cancelBtn.style.display = 'flex';
        } else {
            if (cancelBtn) cancelBtn.style.display = 'none';
        }    } else if (status.installed) {
        state = 'installed';
        if (installedEl) installedEl.style.display = 'flex';
        if (deleteBtn) {
            deleteBtn.style.display = 'flex';
        }
    } else {
        state = 'not-installed';
        if (sizeEl) sizeEl.style.display = 'inline-block'; // SHOW size when not installed
        if (installBtn) {
            installBtn.style.display = 'flex';
        }
    }
    listItem.dataset.installState = state;
}

class ProgressAnimator {
    constructor(listItem, modelSizeStr) {
        this.listItem = listItem;
        this.downloadBar = listItem.querySelector('.progress-bar-download');
        this.verifyBar = listItem.querySelector('.progress-bar-verify'); // This is correct
        this.textEl = listItem.querySelector('.progress-text');
        this.repoId = listItem.dataset.repoId;

        this.animationFrameId = null;
        this.phase = 'download'; // 'download', 'verifying', 'pulsing'
        this.startTime = Date.now();

        // The start method is now called externally after the object is created.
    }

    update(serverProgress, serverStep) {
        if (this.phase === 'finished') return;

        if (this.textEl.textContent !== serverStep) {
            this.textEl.classList.add('text-fade-out');
            setTimeout(() => {
                this.textEl.textContent = serverStep;
                this.textEl.classList.remove('text-fade-out');
            }, 150); // Half of the transition duration
        }

        if (serverStep.toLowerCase().includes('verifying') && this.phase !== 'verifying') {
            this.phase = 'verifying';
            // When verification starts, the download bar should be full.
            if (this.downloadBar) this.downloadBar.style.width = '100%';
        }

        if (this.phase === 'verifying') {
            if (this.verifyBar) this.verifyBar.style.width = `${serverProgress}%`;
        } else { // 'download' phase
            // During download, only the download bar should move.
            if (this.downloadBar) this.downloadBar.style.width = `${serverProgress}%`;
            if (this.verifyBar) this.verifyBar.style.width = '0%'; // Ensure verify bar is empty
        }
    }

    animate() {
        // This function is now only for fallback or pulsing if needed.
        // The main progress is driven by server `update` calls.
        this.animationFrameId = requestAnimationFrame(() => this.animate());
    }    

    stopClientAnimation() {
        if (this.animationFrameId) {
            cancelAnimationFrame(this.animationFrameId);
            this.animationFrameId = null;
        }
    }

    start() {
        this.startTime = Date.now();
        // The polling mechanism now drives the animation, so this is no longer needed.
    }

    stop() {
        if (this.animationFrameId) {
            this.stopClientAnimation();
        }
        this.phase = 'finished';
        // The reset is handled by the UI state update, not the animator itself.
        progressAnimators.delete(this.repoId);
    }

    reset() {
        if (!this.downloadBar || !this.verifyBar) return;
        // Temporarily disable transitions for an instant reset
        this.downloadBar.style.transition = 'none';
        this.verifyBar.style.transition = 'none';
        
        this.downloadBar.style.width = '0%';
        this.verifyBar.style.width = '0%';

        // Restore transitions after a short delay
        setTimeout(() => {
            if (this.downloadBar) this.downloadBar.style.transition = '';
            if (this.verifyBar) this.verifyBar.style.transition = '';
        }, 50);
    }
}

async function manageModel(payload) {
    try {
        const response = await fetch('/api/manage_model', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Client-ID': sseClient.getClientId() },
            body: JSON.stringify(payload)
        });
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ error: `Server error: ${response.statusText}` }));
            throw new Error(errorData.error || 'Request failed');
        }
        return await response.json();
    } catch (error) {
        console.error(`Error during '${payload.action}' action:`, error);

        showNotification({ message: error.message, type: 'error', duration: 5000, target: 'toast' });
        throw error; // Re-throw to be caught by the caller
    }
}

async function handleInstallClick(installBtn) {
    const listItem = installBtn.closest('.model-list-item');
    if (!listItem) return;

    installBtn.disabled = true;
    installBtn.innerHTML = '<div class="loader-small"></div>';

    const payload = {
        action: 'install',
        repo_id: listItem.dataset.repoId,
        ui_container_id: listItem.dataset.uiContainerId,
        manifest_id: "",
        deletion_path: "",
        task_id: "",
        status: "",
        progress: 0,
        message: ""
    };

    try {
        const data = await manageModel(payload);

        if (data.status === 'waiting') {
            showNotification({ message: "Another installation is in progress. Please try again later.", type: 'warning', icon: 'hourglass_top', duration: 5000, target: 'toast' });
            installBtn.disabled = false;
            installBtn.innerHTML = '<span class="material-symbols-outlined">download</span>';
        } else if (data.status === 'running') {
            activeInstallTask = { taskId: data.task_id, repoId: payload.repo_id };
            setupInstallationUI(listItem, data.task_id);
        }
    } catch (error) {
        // Error is already shown by manageModel, just revert the button
        installBtn.disabled = false;
        installBtn.innerHTML = '<span class="material-symbols-outlined">download</span>';
    }
}

async function handleDeleteClick(deleteBtn) {
    const listItem = deleteBtn.closest('.model-list-item');
    if (!listItem) return;

    deleteBtn.disabled = true;
    deleteBtn.innerHTML = '<div class="loader-small"></div>';

    const payload = {
        action: 'delete',
        deletion_path: listItem.dataset.deletionPath,
        ui_container_id: listItem.dataset.uiContainerId,
        repo_id: "",
        manifest_id: "",
        task_id: "",
        status: "",
        progress: 0,
        message: ""
    };

    try {
        await manageModel(payload);
        const modelName = listItem.querySelector('.model-name').textContent;

        showNotification({ message: `${modelName} model deleted successfully.`, type: 'success', icon: 'delete', duration: 3000 });
        // UI update will be handled by the 'refresh_all' SSE event
    } catch (error) {
        // Revert button on error
        deleteBtn.disabled = false;
        deleteBtn.innerHTML = '<span class="material-symbols-outlined">delete</span>';
    }
}

async function handleCancelClick(cancelBtn) {
    if (!activeInstallTask.taskId) return;

    cancelBtn.disabled = true;
    cancelBtn.innerHTML = '<div class="loader-small"></div>';

    try {
        await fetch(`/cancel/${activeInstallTask.taskId}`, { method: 'POST' });
        const modelName = document.querySelector(`.model-list-item[data-repo-id="${activeInstallTask.repoId}"] .model-name`)?.textContent || 'Model';

        showNotification({ message: `Installation for ${modelName} cancelled.`, type: 'warning', icon: 'cancel', duration: 4000, target: 'toast' });
        // UI update will be handled by the 'status_update' (cancelled) and 'refresh_all' SSE events
    } catch (error) {
        showNotification({ message: 'Failed to send cancellation request.', type: 'error', duration: 5000, target: 'toast' });
        cancelBtn.disabled = false;
        cancelBtn.innerHTML = '<span class="material-symbols-outlined">cancel</span>';
    }
}

export function setupInstallationUI(listItem, taskId) {
    const repoId = listItem.dataset.repoId;
    const modelName = listItem.querySelector('.model-name').textContent;

    updateListItemState(listItem, { installing: true }, true);
    setGlobalInstallState(true);

    if (progressAnimators.has(repoId)) {
        progressAnimators.get(repoId).stop();
    }
    const animator = new ProgressAnimator(listItem);
    progressAnimators.set(repoId, animator);
    
    showNotification({ message: `Installation started for ${modelName}.`, type: 'info', icon: 'download', duration: 3000, target: 'toast' });
}

export function handleInstallationError(error, listItem) {
    console.error('Error installing model:', error);

    showNotification({ message: error.message, type: 'error', duration: 5000, target: 'toast' });
    if (listItem) updateListItemState(listItem, { installed: false }, false); // Revert UI on error
    setGlobalInstallState(false);
}

// --- SSE Event Handlers ---
let areSSEListenersInitialized = false;

function initializeSSEListeners() {
    if (areSSEListenersInitialized) return;

    sseClient.subscribe('message', (message) => {
        const { action, payload } = message;
        if (!action || !payload) return;

        const isActor = payload.actor_client_id === sseClient.getClientId();
        const listItem = document.querySelector(`.model-list-item[data-repo-id="${payload.repo_id}"]`);

        switch (action) {
            case 'status_update':
                if (payload.status === 'running' && !isActor && listItem) {
                    setGlobalInstallState(true);
                    updateListItemState(listItem, { installing: true }, false);
                    const modelName = listItem.querySelector('.model-name').textContent;

                    const message = `System is busy installing the '${modelName}' model. Further actions are temporarily disabled.`;
                    showNotification({ message: message, type: 'info', icon: 'sync_lock', duration: 6000, target: 'toast' });
                } else if (['failed', 'cancelled'].includes(payload.status) && listItem) {
                    // Handle failure/cancellation for both actor and observer
                    const animator = progressAnimators.get(payload.repo_id);
                    if (animator) animator.stop();
                    
                    // If I am the actor, show a specific error message.
                    if (isActor && payload.message) {
                        showNotification({ message: `Installation failed: ${payload.message}`, type: 'error', icon: 'error', duration: 8000 });
                    }
                    // The UI will be fully corrected by the subsequent 'refresh_all' event.
                    activeInstallTask = { taskId: null, repoId: null };
                }
                break;

            case 'progress_update':
                if (isActor && listItem) {
                    const animator = progressAnimators.get(payload.repo_id);
                    if (animator) {
                        animator.update(payload.progress, payload.message);
                    }
                }
                break;

            case 'refresh_all':
                const containerToRefresh = payload.ui_container_id ? document.getElementById(payload.ui_container_id) : null;
                if (containerToRefresh) {
                    refreshModelList(false); // This will now correctly update the whole list smartly
                } else {
                    refreshModelList(true); // Fallback to full refresh if container ID is missing
                }
                break;
        }
    });

    areSSEListenersInitialized = true;
}

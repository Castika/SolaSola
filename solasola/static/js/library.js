// This script manages the UI and logic for the Results Library page (library.html).

/**
 * Formats bytes into a human-readable string (KB, MB, GB).
 * @param {number} bytes - The number of bytes.
 * @param {number} [decimals=2] - The number of decimal places.
 * @returns {string} The formatted string.
 */
function formatBytes(bytes, decimals = 2) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

const listContainer = document.getElementById('results-list-container');
const loader = document.getElementById('library-loader');
const errorContainer = document.getElementById('library-error');
const rowTemplate = document.getElementById('result-row-template'); 
const detailTemplate = document.getElementById('result-detail-template');

let isLoading = false; // Add a lock to prevent concurrent reloads.
let watcherInterval = null;
let currentStatusHash = null;

/**
 * Fetches the list of results from the server and renders them.
 */
async function loadResults() {
    if (isLoading) return; // Prevent re-entrant calls.
    isLoading = true;

    showLoading();
    try {
        const response = await fetch('/api/results');
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ error: `Server error: ${response.status}` }));
            throw new Error(errorData.error);
        }
        const results = await response.json();
        await updateStatusHash(); // Update the hash after a successful load
        renderTable(results);
        showTable();
    } catch (error) {
        console.error('Failed to load results:', error);
        showError(`Could not load results: ${error.message}`);
    } finally {
        isLoading = false; // Release the lock.
    }
}

/**
 * Renders the fetched results into the table.
 * @param {Array} results - An array of result objects from the API.
 */
function renderTable(results) {
    listContainer.innerHTML = ''; // Clear the entire list content

    if (results.length === 0) {
        listContainer.textContent = 'No analysis results found.';
        listContainer.style.textAlign = 'center';
        return;
    }
    listContainer.style.textAlign = 'left';

    results.forEach(result => {
        const item = rowTemplate.content.cloneNode(true).querySelector('.result-item');
        item.style.cursor = 'pointer';
        
        const infoCell = item.querySelector('.info-cell');

        const titleSpan = document.createElement('span');
        titleSpan.className = 'title-text';
        titleSpan.textContent = result.title;
        titleSpan.title = result.title;
        infoCell.appendChild(titleSpan);
        // Create a container for badges and other info
        const subInfoContainer = document.createElement('div');
        subInfoContainer.className = 'sub-info-container';
        infoCell.appendChild(subInfoContainer);

        const createBadge = (text, className) => {
            const badge = document.createElement('span');
            badge.className = `badge ${className}`;
            badge.textContent = text;
            return badge;
        };

        // Consistently use the 'details' object for badge information
        const details = result.details || {};
        const settings_info = details.settings_info || {};
        const input_info = details.input_info || {};

        if (settings_info) {
            const mode = settings_info.mode || '';
            if (mode.includes('Deep')) subInfoContainer.appendChild(createBadge('Deep', 'badge-deep'));
            else if (mode.includes('Fast6')) subInfoContainer.appendChild(createBadge('Fast6', 'badge-fast6'));
            else if (mode.includes('Fast')) subInfoContainer.appendChild(createBadge('Fast', 'badge-fast'));

            const device = settings_info.processing_device || '';
            if (device) subInfoContainer.appendChild(createBadge(device, device.toLowerCase() === 'gpu' ? 'badge-gpu' : 'badge-cpu'));
        }
        if (input_info.has_lyrics) {
            subInfoContainer.appendChild(createBadge('Lyrics', 'badge-lyrics'));
        }
        
        if (result.is_processing) {
            // Display a message for items currently being processed
            const processingSpan = document.createElement('span');
            processingSpan.className = 'date-text processing-text';
            processingSpan.textContent = 'Analysis in progress...';
            subInfoContainer.appendChild(processingSpan);
        } else {
            // This block only runs for non-processing items
            if (result.analyzed_at) {
            // Handle both ISO string and Unix timestamp (number)
            const dateValue = typeof result.analyzed_at === 'number' ? result.analyzed_at * 1000 : result.analyzed_at;
            const date = new Date(dateValue);

            const dateString = date.toLocaleDateString();
            const timeString = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
            const dateTextSpan = document.createElement('span');
            dateTextSpan.className = 'date-text';
            dateTextSpan.textContent = `${dateString} ${timeString}`;
            dateTextSpan.title = date.toLocaleString();
                subInfoContainer.appendChild(dateTextSpan);
            } else if (result.is_degraded) {
                const errorSpan = document.createElement('span');
                errorSpan.className = 'date-text missing-files-error';
                errorSpan.textContent = 'info.json / info.txt not found.';
                subInfoContainer.appendChild(errorSpan);
            }
            // Add folder stats only for non-processing items
            if (result.folder_stats) {
                const stats = result.folder_stats;
                const statsSpan = document.createElement('span');
                statsSpan.className = 'folder-stats-text';
                statsSpan.textContent = `(${formatBytes(stats.size)}, ${stats.file_count} files)`;
                if (result.is_degraded) {
                    statsSpan.classList.add('error-text');
                }
                subInfoContainer.appendChild(statsSpan);
            }
        }

        // If the metadata was degraded, apply a special style.
        if (result.is_degraded) {
            item.classList.add('degraded');
        }

        const actionsCell = item.querySelector('.actions-cell');
        const downloadBtn = createActionButton('download', 'Download as ZIP', () => downloadFolder(result.folder_name));
        const deleteBtn = createActionButton('delete', 'Delete Folder', (e) => handleTwoStepDelete(e.currentTarget, result.folder_name, result.deletion_token, item));

        // --- SECURITY: Store the deletion token on the button itself ---
        if (result.deletion_token) {
            deleteBtn.dataset.token = result.deletion_token;
        }

        // Disable actions if the item is being processed
        if (result.is_processing) {
            downloadBtn.disabled = true;
            deleteBtn.disabled = true;
        }
        actionsCell.appendChild(downloadBtn);
        actionsCell.appendChild(deleteBtn);

        // Add click listener to the row itself to toggle details
        item.addEventListener('click', (e) => {
            // Don't toggle if the click was on a button inside the actions cell
            if (e.target.closest('.actions-cell')) {
                return;
            }
            toggleDetailView(item, result);
        });
        listContainer.appendChild(item);
    });
}

/**
 * Toggles the visibility of the detailed information row for a result.
 * @param {HTMLTableRowElement} parentRow - The main row that was clicked.
 * @param {object} resultData - The data object for the result.
 */
function toggleDetailView(parentRow, resultData) {
    const existingDetailView = parentRow.nextElementSibling;
    const isCurrentlyOpen = existingDetailView && existingDetailView.classList.contains('detail-view');

    // Close all other open detail rows first
    closeAllDetailViews();

    if (isCurrentlyOpen) {
        // If it was already open, we just closed it, so we're done.
        return;
    }

    // Create and insert the new detail row
    const detailView = detailTemplate.content.cloneNode(true).querySelector('.detail-view');
    
    if (resultData.is_degraded) {
        detailView.innerHTML = `<div class="detail-content"><pre class="report-text-view">${resultData.details.report_text || 'No information.'}</pre></div>`;
    } else {
        detailView.innerHTML = buildDetailHtml(resultData.details);
    }

    parentRow.after(detailView);
    parentRow.classList.add('expanded');
}

/**
 * Closes any currently open detail view.
 */
function closeAllDetailViews() {
    document.querySelectorAll('.detail-view').forEach(view => view.remove());
    document.querySelectorAll('.result-item.expanded').forEach(item => item.classList.remove('expanded'));
}

/**
 * Builds the HTML content for the detail view from the result data.
 * @param {object} details - The details object from the API response.
 * @returns {string} The HTML string for the detail cell.
 */
function buildDetailHtml(details) {
    // Use the full details object passed from the backend
    const settings_info = details.settings_info || {};
    const input_info = details.input_info || {};
    const { cache_provenance, song_profile, file_counts } = details;

    const createDetailItem = (key, value) => value ? `<div class="detail-item"><span class="key">${key}</span><span class="value">${value}</span></div>` : '';
    const createBadge = (text, className) => `<span class="badge ${className}">${text}</span>`;

    let badgesHtml = '';
    if (settings_info) {
        const mode = settings_info.mode || '';
        if (mode.includes('Deep')) badgesHtml += createBadge('Deep', 'badge-deep');
        else if (mode.includes('Fast6')) badgesHtml += createBadge('Fast6', 'badge-fast6');
        else if (mode.includes('Fast')) badgesHtml += createBadge('Fast', 'badge-fast');

        const device = settings_info.processing_device || '';
        if (device) badgesHtml += createBadge(device, device.toLowerCase() === 'gpu' ? 'badge-gpu' : 'badge-cpu');
    }
    if (input_info.has_lyrics) {
        badgesHtml += createBadge('Lyrics', 'badge-lyrics');
    }

    const cacheHtml = Object.entries(cache_provenance || {}).map(([key, value]) => {
        const status = value.status.replace(/_/g, ' ');
        const count = file_counts[key] ? ` - ${file_counts[key]} file(s)` : '';
        return createDetailItem(key.charAt(0).toUpperCase() + key.slice(1), `${status}${count}`);
    }).join('');
    
    const profileHtml = Object.entries(song_profile || {}).map(([key, value]) => {
        // Exclude raw data fields from the profile view
        if (key.endsWith('_srt') || key.endsWith('_text') || key.startsWith('is_') || key.startsWith('lyrics_')) {
            return '';
        }
        return createDetailItem(key, value);
    }).join('');
    
    return `
        <div class="detail-content">
            ${badgesHtml ? `<div class="detail-section detail-badges">${badgesHtml}</div>` : ''}
            <div class="detail-section">
                <div class="detail-grid">
                    ${createDetailItem('Mode', settings_info.mode)}
                    ${createDetailItem('Processing Device', settings_info.processing_device)}
                </div>
            </div>
            <div class="detail-section"><h5>Cache Summary</h5><div class="detail-grid">${cacheHtml}</div></div>
            <div class="detail-section"><h5>Song Profile</h5><div class="detail-grid">${profileHtml}</div></div>
        </div>
    `;
}

/**
 * Helper to create an action button.
 * @param {string} iconName - The name of the Material Symbol icon.
 * @param {string} title - The tooltip text for the button.
 * @param {Function} onClick - The function to call when clicked.
 * @returns {HTMLButtonElement} The created button element.
 */
function createActionButton(iconName, title, onClick) {
    const button = document.createElement('button');
    button.className = 'icon-btn';
    button.title = title;
    button.innerHTML = `<span class="material-symbols-outlined">${iconName}</span>`;
    button.addEventListener('click', onClick);
    return button;
}

/**
 * Triggers the download for a specific result folder.
 * @param {string} folderName - The name of the folder to download.
 */
async function downloadFolder(folderName) {
    try {
        const response = await fetch(`/api/results/${folderName}/download`);

        if (!response.ok) {
            // Handle cases where the folder was not found (e.g., deleted externally)
            if (response.status === 404) {
                alert("Folder not found. It may have been renamed or deleted. The list will now be refreshed.");
                loadResults(); // Refresh the list to show the current state.
                return;
            }
            const errorData = await response.json().catch(() => ({ error: `Server error: ${response.status}` }));
            throw new Error(errorData.error);
        }

        // Create a blob from the response and trigger a download
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = url;
        a.download = `${folderName}.zip`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        a.remove();

    } catch (error) {
        alert(`Failed to download folder: ${error.message}`);
    }
}

/**
 * Handles the two-step delete process to prevent accidental deletion.
 * @param {HTMLButtonElement} button - The delete button that was clicked.
 * @param {string} folderName - The name of the folder to delete.
 * @param {HTMLElement} rowElement - The table row associated with the folder.
 */
function handleTwoStepDelete(button, folderName, token, rowElement) {
    // Prevent the global click listener from immediately resetting the button.
    event.stopPropagation();

    // If the button is already in the 'confirm' state, proceed with deletion.
    if (button.classList.contains('confirm-delete')) {
        deleteFolder(folderName, token, rowElement);
        return;
    }

    // Reset any other delete buttons that might be in the confirm state.
    resetAllDeleteConfirmations();

    // Set the current button to the 'confirm' state.
    setButtonToConfirmState(button);
}

function resetAllDeleteConfirmations() {
    // Reset any other delete buttons that might be in the confirm state.
    document.querySelectorAll('.icon-btn.confirm-delete').forEach(btn => {
        btn.classList.remove('confirm-delete');
        btn.title = 'Delete Folder';
        btn.querySelector('.material-symbols-outlined').textContent = 'delete';
    });

}

function setButtonToConfirmState(button) {
    button.classList.add('confirm-delete');
    button.title = 'Confirm Deletion';
    button.querySelector('.material-symbols-outlined').textContent = 'delete_forever';

    // If the user doesn't confirm within 5 seconds, revert the button.
    setTimeout(() => {
        if (button.classList.contains('confirm-delete')) {
            button.classList.remove('confirm-delete');
            button.title = 'Delete Folder';
            button.querySelector('.material-symbols-outlined').textContent = 'delete';
        }
    }, 5000);
}

/**
 * Handles the deletion of a result folder.
 * @param {string} folderName - The name of the folder to delete.
 * @param {HTMLElement} rowElement - The table row element to remove on success.
 */
async function deleteFolder(folderName, token, rowElement) {
    try { 
        const response = await fetch(`/api/results/${folderName}`, {
            method: 'DELETE',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ token: token })
        });
        // If the server responds with an error status (like 403, 408, 500),
        // it will render an error page. We simply reload the window to display it.
        if (!response.ok) {
            window.location.reload();
            return; // Stop further execution
        }

        // On successful deletion, immediately reload the list to reflect the change.
        // This provides clear feedback and ensures data consistency.
        loadResults();

    } catch (error) {
        // If the fetch itself fails (e.g., network error), show a toast notification
        // instead of a disruptive alert.
        showNotification({
            message: `Failed to delete folder: ${error.message}`,
            type: 'error', // Use 'error' type for styling
            icon: 'error', // Explicitly set the icon
            target: 'toast' // Ensure it appears as a toast
        });
    }
}

// --- UI State Management ---
function showLoading() { loader.style.display = 'flex'; listContainer.style.display = 'none'; errorContainer.style.display = 'none'; }
function showTable() { loader.style.display = 'none'; listContainer.style.display = 'block'; errorContainer.style.display = 'none'; }
function showError(message) { loader.style.display = 'none'; listContainer.style.display = 'none'; errorContainer.textContent = message; errorContainer.style.display = 'block'; }

// --- Initialization ---
document.addEventListener('DOMContentLoaded', () => {
    // Add a global click listener to reset delete confirmations when clicking away.
    document.addEventListener('click', (e) => {
        // If the click is not on a delete button itself, reset all confirmations.
        if (!e.target.closest('.icon-btn')) {
            resetAllDeleteConfirmations();
        }
        // If the click is outside the table, close all detail views.
        if (!e.target.closest('.results-list-container')) {
            closeAllDetailViews();
        }
    });

    // --- Folder Watcher (Polling) ---
    startWatcher();

    // When the window (iframe) is closed or navigated away from, stop the watcher.
    window.addEventListener('beforeunload', () => {
        stopWatcher();
    });

    // Expose the loadResults function to the window object so it can be called from the parent frame (main.js).
    window.loadResults = loadResults;
    loadResults(); // Initial load
});

/**
 * Starts a polling mechanism to watch for changes in the results folder.
 */
function startWatcher() {
    if (watcherInterval) return; // Already running
    console.log("Results Library: Starting folder watcher...");
    watcherInterval = setInterval(async () => {
        try {
            const response = await fetch('/api/results/status');
            if (!response.ok) return; // Silently fail
            const data = await response.json();
            if (currentStatusHash !== null && data.hash !== currentStatusHash) {
                console.log("Results Library: Change detected, reloading list...");
                loadResults();
            }
        } catch (error) {
            // Ignore fetch errors, as the server might be temporarily unavailable.
        }
    }, 30000); // Poll every 30 seconds
}

async function updateStatusHash() {
    try {
        const response = await fetch('/api/results/status');
        if (response.ok) {
            const data = await response.json();
            currentStatusHash = data.hash;
        }
    } catch (error) { /* ignore */ }
}

function stopWatcher() {
    if (watcherInterval) {
        console.log("Results Library: Stopping folder watcher.");
        clearInterval(watcherInterval);
        watcherInterval = null;
    }
}
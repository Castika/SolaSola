// This module provides UI helper functions for modals, notifications, and cookies.

// --- Cached DOM Elements ---
let solaModal, solaModalTitle, solaModalBody, solaModalFooter, solaModalCloseBtn;
let notificationContainer, viewLogButton, themeToggle, themeIcon, floatingButtonsContainer;

// --- State ---
let notificationLog = [];
let storageAvailable = false;
const MAX_LOG_ENTRIES = 500; // Cap the log size to prevent performance degradation.

const notificationQueue = [];
const visibleToasts = [];
const TOAST_CONFIG = {
    MAX_TOASTS: 5,
    LIFETIME: 3000, // 3 seconds total life for the bottom toast
    FADE_OUT_DURATION: 500, // 0.5 seconds
    ADD_INTERVAL: 1000, // 1 second between new toasts when space is available
    CASCADE_DURATION: 1000, // 1 second for the whole cascade effect
    FLY_IN_DURATION: 500, // 0.5 seconds
};
let addToastInterval = null;

// --- Cookie Helpers ---
export function setCookie(name, value, days) {
    let expires = "";
    if (days) {
        const date = new Date();
        date.setTime(date.getTime() + (days * 24 * 60 * 60 * 1000));
        expires = "; expires=" + date.toUTCString();
    }
    // Ensure the cookie is set for the root path to be accessible everywhere.
    document.cookie = name + "=" + (value || "")  + expires + "; path=/";
}

export function getCookie(name) {
    const nameEQ = name + "=";
    const ca = document.cookie.split(';');
    for(let i=0; i < ca.length; i++) {
        let c = ca[i];
        while (c.charAt(0) === ' ') c = c.substring(1, c.length);
        if (c.indexOf(nameEQ) === 0) return c.substring(nameEQ.length, c.length);
    }
    return null;
}

/**
 * Deletes a cookie by setting its expiration date to the past.
 * @param {string} name The name of the cookie to delete.
 */
export function deleteCookie(name) {
    document.cookie = name + '=; Path=/; Expires=Thu, 01 Jan 1970 00:00:01 GMT;';
}

/**
 * Truncates a filename in the middle, preserving the start and end.
 * e.g., "a_very_long_filename.wav" becomes "a_very...name.wav"
 * @param {string} filename The full filename.
 * @param {number} maxLength The maximum desired length.
 * @returns {string} The truncated filename.
 */
export function truncateFilename(filename, maxLength = 40) {
    // Safeguard for null or undefined inputs
    if (!filename || typeof filename !== 'string' || filename.length <= maxLength) {
        return filename || ''; // Return an empty string if filename is null/undefined
    }
    const extensionIndex = filename.lastIndexOf('.');
    // If there's no extension, or it's the very first character (hidden file), just truncate the end.
    if (extensionIndex <= 0) {
        return filename.substring(0, maxLength - 3) + '...';
    }

    const name = filename.substring(0, extensionIndex);
    const extension = filename.substring(extensionIndex);

    // Allot space for "..." and the extension
    const nameMaxLength = maxLength - extension.length - 3;

    // If the name part is too short to be truncated meaningfully, just truncate the whole string.
    if (nameMaxLength < 5) { // e.g., "a...b.ext" is not very useful
        return filename.substring(0, maxLength - 3) + '...';
    }

    const startLength = Math.ceil(nameMaxLength / 2);
    const endLength = Math.floor(nameMaxLength / 2);

    const start = name.substring(0, startLength);
    const end = name.substring(name.length - endLength);

    return `${start}...${end}${extension}`;
}

// --- Modal Logic ---
function openModal(onCloseCallback) {
    if (!solaModal) return;
    // Store the callback on the modal element to be retrieved by closeModal
    solaModal.onClose = onCloseCallback;
    solaModal.classList.add('visible');
    document.body.classList.add('modal-open');
    if (notificationContainer) {
        notificationContainer.classList.add('modal-open');
        setTimeout(() => {
            notificationContainer.style.zIndex = '4001';
        }, 0);
    }
}

export function closeModal() {
    if (!solaModal) return;
    // If an onClose callback was stored, execute it, then clear it.
    if (typeof solaModal.onClose === 'function') {
        solaModal.onClose();
        solaModal.onClose = null;
    }
    solaModal.classList.remove('visible');
    document.body.classList.remove('modal-open');
    if (notificationContainer) {
        notificationContainer.classList.remove('modal-open');
        // Reset z-index to be controlled by the stylesheet again.
        notificationContainer.style.zIndex = '';
    }
}

function updateNotificationContainerPosition() {
    if (!notificationContainer || !floatingButtonsContainer) return;

    // Get the computed style to find the 'bottom' value in pixels
    const fabStyles = window.getComputedStyle(floatingButtonsContainer);
    const fabBottomMargin = parseFloat(fabStyles.bottom); // e.g., 32px for 2rem

    // Get the actual rendered height of the container
    const fabHeight = floatingButtonsContainer.offsetHeight;

    // Calculate the position of the top edge of the FAB container from the viewport bottom
    const fabTopEdgePosition = fabBottomMargin + fabHeight;

    // Define a gap between the buttons and the toasts
    const gap = 16; // 1rem

    // The desired position for the toasts is above the buttons plus the gap
    const positionAboveFab = fabTopEdgePosition + gap;

    // Also calculate 20% of the viewport height
    const twentyVh = window.innerHeight * 0.20;

    // The final position is the maximum of the two calculated values.
    notificationContainer.style.bottom = `${Math.max(twentyVh, positionAboveFab)}px`;
}


export function showModal({ title, bodyContent, bodyClass = '', footerButtons = [], headerButtons = [], onOpen = null, onClose = null, isLarge = false }) {
    if (!solaModal || !solaModalTitle || !solaModalBody || !solaModalFooter) {
        return;
    }

    // Before showing a new modal, execute the onClose handler of the previous one to clean up.
    if (typeof solaModal.onClose === 'function') {
        solaModal.onClose();
    }

    // Clear previous header buttons
    const existingHeaderButtons = solaModal.querySelector('.modal-header-buttons');
    if (existingHeaderButtons) {
        existingHeaderButtons.remove();
    }
    if (headerButtons.length > 0) {
        const headerButtonsContainer = document.createElement('div');
        headerButtonsContainer.className = 'modal-header-buttons';
        headerButtons.forEach(btn => {
            const button = document.createElement('button');
            button.className = 'modal-header-btn';
            if (btn.title) button.title = btn.title;
            const iconSpan = document.createElement('span');
            iconSpan.className = 'material-symbols-outlined';
            iconSpan.textContent = btn.icon;
            button.appendChild(iconSpan);
            if (typeof btn.action === 'function') {
                button.onclick = () => btn.action(button);
            }
            headerButtonsContainer.appendChild(button);
        });
        solaModalTitle.after(headerButtonsContainer);
    }

    // Apply a specific class to the modal body if provided
    solaModalBody.className = 'modal-body'; // Reset to default first
    if (bodyClass) {
        solaModalBody.classList.add(bodyClass);
    }

    solaModalTitle.textContent = title;
    solaModalBody.innerHTML = ''; // Clear previous content
    if (typeof bodyContent === 'string') {
        solaModalBody.innerHTML = bodyContent;
    } else if (bodyContent instanceof Node) {
        solaModalBody.appendChild(bodyContent);
    }

    solaModalFooter.innerHTML = ''; // Clear previous buttons
    solaModalFooter.classList.remove('two-row-layout');

    const hasTextElement = footerButtons.some(btn => btn.type === 'text');

    // Create a two-row structure for the footer
    const footerTopRow = document.createElement('div');
    footerTopRow.className = 'modal-footer-top';
    const footerBottomRow = document.createElement('div');
    footerBottomRow.className = 'modal-footer-bottom';

    const leftGroup = document.createElement('div');
    leftGroup.className = 'modal-footer-group';
    const rightGroup = document.createElement('div');
    rightGroup.className = 'modal-footer-group';
    const centerGroup = document.createElement('div');
    centerGroup.className = 'modal-footer-group-center';

    footerButtons.forEach(btn => {
        const button = document.createElement('button');
        button.className = 'modal-footer-btn';

        if (btn.icon) {
            const iconSpan = document.createElement('span');
            iconSpan.className = 'material-symbols-outlined';
            iconSpan.textContent = btn.icon;
            button.appendChild(iconSpan);
        }

        if (btn.label) {
            const labelSpan = document.createElement('span');
            labelSpan.className = 'label';
            labelSpan.textContent = btn.label;
            button.appendChild(labelSpan);
            button.setAttribute('aria-label', btn.label);
        }

        if (btn.icon && !btn.label) {
            button.classList.add('icon-only');
            if (btn.title) button.setAttribute('title', btn.title);
        }

        if (btn.isPrimary) button.classList.add('primary');
        if (btn.isSuccess) button.classList.add('success');
        if (btn.isDestructive) button.classList.add('destructive');
        if (btn.isWarning) button.classList.add('warning');
        if (btn.disabled) button.disabled = true;

        if (btn.action === 'close') {
            button.addEventListener('click', closeModal);
        } else if (btn.action === 'copy-log') {
            button.addEventListener('click', copyLogToClipboard);
        } else if (btn.action === 'delete-log') {
            button.addEventListener('click', deleteLog);
        } else if (btn.action === 'refresh-log') {
            button.addEventListener('click', () => refreshLogView(true));
        } else if (typeof btn.action === 'function') { // Use onclick to allow it to be overwritten.
            button.onclick = () => btn.action(button);
        }

        // Handle text type and alignment for button groups
        if (btn.type === 'text') {
            const textEl = document.createElement('p');
            textEl.className = 'modal-footer-text';
            textEl.textContent = btn.label;
            centerGroup.appendChild(textEl);
        } else if (btn.align === 'left') {
            leftGroup.appendChild(button);
        } else {
            rightGroup.appendChild(button);
        }
    });

    if (hasTextElement) {
        // Build the two-row layout
        solaModalFooter.classList.add('two-row-layout');
        if (centerGroup.hasChildNodes()) {
            footerTopRow.appendChild(centerGroup);
            solaModalFooter.appendChild(footerTopRow);
        }
        if (leftGroup.hasChildNodes() || rightGroup.hasChildNodes()) {
            footerBottomRow.appendChild(leftGroup);
            footerBottomRow.appendChild(rightGroup);
            solaModalFooter.appendChild(footerBottomRow);
        }
    } else {
        // Default single-row layout
        solaModalFooter.appendChild(leftGroup);
        solaModalFooter.appendChild(rightGroup);
    }

    openModal(onClose);

    // Execute the onOpen callback after the modal is visible
    if (typeof onOpen === 'function') {
        onOpen({ title: solaModalTitle, body: solaModalBody, footer: solaModalFooter });
    }
}

/**
 * The main public function to show a notification.
 * It adds the notification to a queue and triggers the manager.
 */
export function showNotification(logObject) {
    // Ensure default values for properties that might be missing
    const defaults = { type: 'info', duration: 5000, icon: 'info', target: 'both' };
    const finalLogObject = { ...defaults, ...logObject };

    // Default to 'both' if target is not specified for backward compatibility
    const finalTarget = finalLogObject.target;

    // Add to log if target is 'log' or 'both'
    if (finalTarget === 'log' || finalTarget === 'both') {
        logNotificationToHistory(finalLogObject);
    }
    // Show a toast if target is 'toast' or 'both'
    if (finalTarget === 'toast' || finalTarget === 'both') {
        notificationQueue.push(finalLogObject);
        processToastQueue();
    }
}

/**
 * The main loop/manager for the toast system.
 * It adds new toasts from the queue if there is space.
 */
function processToastQueue() {
    if (addToastInterval) return; // An interval is already running

    addToastInterval = setInterval(() => {
        if (visibleToasts.length < TOAST_CONFIG.MAX_TOASTS && notificationQueue.length > 0) {
            addToast(notificationQueue.shift());
        } else {
            clearInterval(addToastInterval);
            addToastInterval = null;
        }
    }, TOAST_CONFIG.ADD_INTERVAL);
}

/**
 * Creates a toast element, adds it to the DOM and the visible list,
 * and manages its lifecycle.
 */
function addToast(data) {
    if (visibleToasts.length >= TOAST_CONFIG.MAX_TOASTS) { // Safeguard
        notificationQueue.unshift(data); // Safeguard: put it back if the screen is full
        return;
    }

    const toastId = `toast-${Date.now()}-${Math.random()}`;
    const toastEl = createToastElement(data, toastId);
    
    const toastObject = {
        id: toastId,
        element: toastEl,
        timer: null, // Timer for this specific toast
        height: 0,
        // A duration of 0 means the toast will persist until manually closed or pushed off
        duration: typeof data.duration === 'number' ? data.duration : TOAST_CONFIG.LIFETIME
    };

    visibleToasts.push(toastObject);
    notificationContainer.appendChild(toastEl);

    // Force a reflow to get the actual height for positioning.
    toastObject.height = toastEl.offsetHeight;

    repositionToasts();

    // If this is the only toast, it's at the bottom, so start its timer
    if (visibleToasts.length === 1) {
        startToastTimer(toastObject);
    }
}

/**
 * Starts the 3-second death timer for the bottom-most toast.
 */
function startToastTimer(toastObject) {
    if (!toastObject) return;
    if (toastObject.timer) clearTimeout(toastObject.timer);
    
    // A duration of 0 means the toast is persistent and won't auto-dismiss
    if (toastObject.duration > 0) {
        toastObject.timer = setTimeout(() => {
            removeToast(toastObject.id);
        }, toastObject.duration);
    }
}

/**
 * Removes the bottom-most toast and triggers the cascade effect.
 */
function removeToast(toastId) {
    const index = visibleToasts.findIndex(t => t.id === toastId);
    if (index === -1) return; // Toast not found

    // Check if the toast being removed is the one at the bottom
    const wasBottomToast = (index === 0);

    // Get the toast object and remove it from the array of visible toasts
    const toastObject = visibleToasts.splice(index, 1)[0];

    // Animate out (fade out)
    toastObject.element.classList.add('toast-exit');

    // Remove from DOM after the fade-out animation completes
    toastObject.element.addEventListener('animationend', () => {
        toastObject.element.remove();
    }, { once: true });

    // Reposition remaining toasts with a cascade effect
    repositionToasts();

    // Check if a new toast can be added from the queue
    processToastQueue();

    // If the bottom toast was removed and there are still toasts left,
    // start the timer for the new bottom toast.
    if (wasBottomToast && visibleToasts.length > 0) {
        startToastTimer(visibleToasts[0]);
    }
}

/**
 * Creates the DOM element for a single toast.
 */
function createToastElement(data, id) {
    const el = document.createElement('div');
    el.id = id;
    el.className = `toast is-${data.type}`;

    // Create elements programmatically to prevent XSS.
    const iconContainer = document.createElement('div');
    iconContainer.className = 'toast-icon';

    const iconSpan = document.createElement('span');
    iconSpan.className = 'material-symbols-outlined';
    iconSpan.textContent = data.icon;
    iconContainer.appendChild(iconSpan);

    const messageParagraph = document.createElement('p');
    // Truncate the message to a reasonable length for a toast
    const displayMessage = truncateFilename(data.message, 60);
    messageParagraph.textContent = displayMessage;

    messageParagraph.style.wordBreak = 'break-all';
    el.appendChild(iconContainer);
    el.appendChild(messageParagraph);

    return el;
}

/**
 * This is the core of the visual logic: it positions all visible toasts in a stack.
 */
function repositionToasts() {
    let bottomOffset = 0;
    visibleToasts.forEach((toast, index) => {
        const element = toast.element;
        element.style.bottom = `${bottomOffset}px`;
        
        // Apply cascade delay
        const delay = index * (TOAST_CONFIG.CASCADE_DURATION / 1000 / TOAST_CONFIG.MAX_TOASTS);
        element.style.transitionDelay = `${delay}s`;

        bottomOffset += toast.height + 20; // 20 is the visual gap between toasts
    });
}

/**
 * Clears all pending and visible toasts immediately.
 * Useful when transitioning to a new view where toasts are not desired.
 */
export function clearAllToasts() {
    // Clear the queue of upcoming toasts
    notificationQueue.length = 0;
    if (addToastInterval) {
        clearInterval(addToastInterval);
        addToastInterval = null;
    }

    // Immediately remove all toasts currently visible on screen
    visibleToasts.forEach(toastObject => {
        toastObject.element.remove();
        if (toastObject.timer) clearTimeout(toastObject.timer);
    });
    visibleToasts.length = 0; // Clear the array of visible toasts.
}

// --- Notification Log / History ---
function logNotificationToHistory(logObject) {
    const timestamp = new Date();
    const timeString = [
        timestamp.getHours().toString().padStart(2, '0'),
        timestamp.getMinutes().toString().padStart(2, '0'),
        timestamp.getSeconds().toString().padStart(2, '0')
    ].join(':');
    // The logObject already contains message, type, and icon
    notificationLog.push({
        ...logObject,
        time: timeString,
        message: logObject.message // Ensure message is explicitly carried over
    });

    // Enforce a maximum number of log entries
    if (notificationLog.length > MAX_LOG_ENTRIES) {
        notificationLog.splice(0, notificationLog.length - MAX_LOG_ENTRIES);
    }

    if (storageAvailable) {
        try { sessionStorage.setItem('sola-notificationLog', JSON.stringify(notificationLog)); }
        catch (e) { /* Suppress potential errors */ }
    }
    if (viewLogButton) viewLogButton.classList.add('has-new-notifications');
}

function showLog() {
    // When opening the log, clear any pending or visible toasts for a cleaner UI
    clearAllToasts();

    showModal({
        title: 'Notification Log',
        bodyContent: '<ul class="log-list"><li>Loading...</li></ul>',
        footerButtons: [
            { label: 'Delete', icon: 'delete', action: 'delete-log', isDestructive: true, align: 'left' },
            { label: 'Refresh', icon: 'refresh', action: 'refresh-log', isWarning: true },
            { label: 'Copy', icon: 'content_copy', action: 'copy-log', isSuccess: true },
            { label: 'Close', icon: 'close', action: 'close', isPrimary: true },
        ]
    });
    refreshLogView(false);
    if (viewLogButton) viewLogButton.classList.remove('has-new-notifications');
}

function deleteLog() {
    clearNotificationLog();
    refreshLogView(false);
}

export function clearNotificationLog() {
    notificationLog = [];
    if (storageAvailable) {
        try { sessionStorage.setItem('sola-notificationLog', JSON.stringify([])); }
        catch (e) { /* Suppress potential errors */ }
    }
}

function copyLogToClipboard() {
    // Ensure we are copying the most up-to-date log from storage
    const logToCopy = (storageAvailable && sessionStorage.getItem('sola-notificationLog'))
        ? JSON.parse(sessionStorage.getItem('sola-notificationLog'))
        : notificationLog;

    const header = `Notification Log - SolaSola ${document.querySelector('.version-tag')?.textContent || ''}\n========================================\n\n`;
    const logText = [...logToCopy].reverse().map(log => `[${log.time}] ${log.message}`).join('\n');
    navigator.clipboard.writeText(header + logText).then(() => {
        showNotification({ message: "Log copied to clipboard.", type: 'success', icon: 'content_copy', target: 'toast' });
    }).catch(err => {
        showNotification({ message: 'Failed to copy log.', type: 'error', icon: 'error' });
    });
}

function refreshLogView(showToast = true, logData = null) {
    const modalBody = document.getElementById('sola-modal-body');
    if (!modalBody) return;

    // If no specific log data is passed, get it from storage
    if (logData === null && storageAvailable) {
        const storedLog = sessionStorage.getItem('sola-notificationLog');
        logData = storedLog ? JSON.parse(storedLog) : [];
    }

    const logList = document.createElement('ul');
    logList.className = 'log-list';

    if (!logData || logData.length === 0) {
        const li = document.createElement('li');
        li.textContent = 'No notifications yet.';
        logList.appendChild(li);
    } else {
        // Use the provided or freshly fetched log data
        [...logData].reverse().forEach(log => {
            const li = document.createElement('li');
            li.className = log.type;

            const timeSpan = document.createElement('span');
            timeSpan.className = 'log-time';
            timeSpan.textContent = `[${log.time}]`;

            const messageSpan = document.createElement('span');
            messageSpan.className = 'log-message';
            const displayMessage = log.message;
            // Use the full detailed message for the log, but truncate if excessively long
            messageSpan.textContent = truncateFilename(displayMessage, 120);
            messageSpan.style.wordBreak = 'break-all';
            li.appendChild(timeSpan);
            li.appendChild(messageSpan);
            logList.appendChild(li);
        });
    }

    modalBody.innerHTML = '';
    modalBody.appendChild(logList);

    if (showToast) showNotification({ message: "Log refreshed.", type: 'info', icon: 'refresh', target: 'toast' });
}

// --- Other Helpers ---
export function setTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
    if (themeIcon) {
        themeIcon.textContent = theme === 'dark' ? 'light_mode' : 'dark_mode';
    }

    const iframe = document.getElementById('processing-iframe');
    if (iframe && iframe.contentWindow) {
        iframe.contentWindow.postMessage({ type: 'theme_change', theme: theme }, window.location.origin);
    }
}

function runBrowserCompatibilityChecks() {
    try {
        if (localStorage.getItem('compatWarningDismissed')) return;
    } catch (e) { /* storage not available, proceed */ }

    const failedChecks = [];
    let storageWorks = false;

    try {
        const testKey = 'sola-test-storage';
        localStorage.setItem(testKey, 'test');
        localStorage.removeItem(testKey);
        storageWorks = true;
    } catch (e) {
        failedChecks.push('Local Storage (for saving progress and logs across tabs)');
    }
    
    storageAvailable = storageWorks;

    if (!('fetch' in window)) failedChecks.push('Fetch API (for server communication)');
    if (!('DataTransfer' in window)) failedChecks.push('DataTransfer API (for file handling)');

    if (failedChecks.length > 0) {
        const warningContainer = document.getElementById('compatibility-warning');
        if (warningContainer) {
            warningContainer.innerHTML = `
                <span class="material-symbols-outlined alert-icon">warning</span>
                <div class="alert-content">
                    <p><strong>Browser Compatibility Warning:</strong> Your browser may not fully support all features of this application. The following APIs are missing:</p>
                    <ul>${failedChecks.map(f => `<li>${f}</li>`).join('')}</ul>
                </div>
                <button class="alert-close-btn" title="Dismiss">&times;</button>
            `;
            warningContainer.style.display = 'flex';
            const closeButton = warningContainer.querySelector('.alert-close-btn');
            closeButton.addEventListener('click', () => {
                warningContainer.style.display = 'none';
                if (storageWorks) {
                    try { localStorage.setItem('compatWarningDismissed', 'true'); }
                catch (e) { /* Suppress potential errors */ }
                }
            });
        }
    }
}

// --- Initialization ---
export function initializeBaseUI() {
    // Cache DOM elements for performance
    notificationContainer = document.getElementById('notification-container');
    floatingButtonsContainer = document.querySelector('.floating-action-buttons');
    viewLogButton = document.getElementById('view-log-button');
    themeToggle = document.getElementById('theme-toggle');
    themeIcon = themeToggle ? themeToggle.querySelector('.material-symbols-outlined') : null;
    solaModal = document.getElementById('sola-modal');
    solaModalTitle = document.getElementById('sola-modal-title');
    solaModalBody = document.getElementById('sola-modal-body');
    solaModalFooter = document.getElementById('sola-modal-footer');
    solaModalCloseBtn = document.getElementById('sola-modal-close-btn');

    // Setup event listeners
    if (themeToggle) {
        themeToggle.addEventListener('click', () => {
            const newTheme = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
            setTheme(newTheme);
        });
    }
    if (viewLogButton) {
        viewLogButton.addEventListener('click', showLog);
    }
    if (solaModal) {
        solaModal.addEventListener('click', (e) => {
            if (e.target === solaModal) closeModal();
        });
    }
    if (solaModalCloseBtn) {
        solaModalCloseBtn.addEventListener('click', closeModal);
    }

    // Dynamic Notification Container Positioning
    // Initial calculation on load
    updateNotificationContainerPosition();
    // Recalculate on window resize (for viewport height changes)
    window.addEventListener('resize', updateNotificationContainerPosition);
    // Also use a ResizeObserver for the button container itself, which is more efficient
    if (window.ResizeObserver && floatingButtonsContainer) {
        new ResizeObserver(updateNotificationContainerPosition).observe(floatingButtonsContainer);
    }

    runBrowserCompatibilityChecks();

    if (storageAvailable) {
        const storedLog = sessionStorage.getItem('sola-notificationLog');
        notificationLog = storedLog ? JSON.parse(storedLog) : [];
    }
}

/**
 * Efficiently gets the durations of multiple audio files using their metadata.
 * This is fast but less reliable for corrupted files.
 * @param {File[]} files An array of audio file objects.
 * @returns {Promise<number[]>} A promise that resolves with an array of durations in seconds.
 */
export function getAudioDurations(files) {
    const promises = files.map(file => {
        return new Promise((resolve, reject) => {
            const audio = new Audio();
            audio.preload = 'metadata';
            audio.src = URL.createObjectURL(file);
            audio.addEventListener('loadedmetadata', () => {
                URL.revokeObjectURL(audio.src); // Clean up the object URL
                resolve(audio.duration);
            });
            audio.addEventListener('error', (e) => {
                URL.revokeObjectURL(audio.src);
                reject(new Error(`Could not read metadata for ${file.name}`));
            });
        });
    });
    return Promise.all(promises);
}
import { initializeBaseUI, showNotification, clearNotificationLog, clearAllToasts, getAudioDurations, getCookie, deleteCookie, truncateFilename } from './ui-helpers.js';
import { renderResults } from './results.js';
import { openModelManager } from './model_manager.js';
import { initializeFormHandlers, fileStore, renderAllFileLists } from './form-handler.js';
import sseClient from './sse_client.js';
import { DURATION_THRESHOLD_SECONDS } from './constants.js';

function initializeApp() {
	const versionTag = document.querySelector('.version-tag');
	const version = versionTag?.dataset.version || 'v0.0.0';
	const build = versionTag?.dataset.build || '0';
	const timestamp = versionTag?.dataset.timestamp || 'N/A';
	const commit = versionTag?.dataset.commit || 'N/A';
	const fullVersionString = `${version} build ${build} (${timestamp} @ ${commit})`;
	console.log(`--- SolaSola Frontend --- Version: ${fullVersionString} ---`);

	// getTimezoneOffset() returns the difference in minutes between UTC and local time.
	// The sign is inverted (e.g., KST is UTC+9, but offset is -540).
	// We want the offset in seconds to ADD to a UTC time to get local time.
	const timeZoneOffsetMinutes = new Date().getTimezoneOffset();
	const serverTimeOffset = -1 * timeZoneOffsetMinutes * 60; // Convert to seconds and invert sign
	console.log(`Client time offset calculated: ${serverTimeOffset} seconds.`);

	let clientOS = 'unknown';
	const userAgent = window.navigator.userAgent;
	if (userAgent.indexOf("Win") !== -1) clientOS = "windows";
	if (userAgent.indexOf("Mac") !== -1) clientOS = "macos";
	if (userAgent.indexOf("Linux") !== -1) clientOS = "linux";
	if (userAgent.indexOf("X11") !== -1 && userAgent.indexOf("Linux") === -1) clientOS = "unix";

	console.log(`Client OS detected: ${clientOS}`);

	// Prevent browser from opening dropped files anywhere outside the drop zones
	window.addEventListener('dragover', (e) => e.preventDefault(), false);
	window.addEventListener('drop', (e) => e.preventDefault(), false);
	const uploadForm = document.getElementById('upload-form');

	const formView = document.getElementById('form-view');
	const loadingView = document.getElementById('loading-view'); // The container for the iframe
	const resultsView = document.getElementById('results-view');
	const resultsContainer = document.getElementById('results-container');
	const resetButton = document.getElementById('reset-button');
	const viewResultsButton = document.getElementById('view-results-button');
	const floatingReturnButton = document.getElementById('floating-return-button');
	const manageModelsBtn = document.getElementById('manage-models-button');


	let displayedLogCount = parseInt(sessionStorage.getItem('displayedLogCount') || '0', 10);
	
	function updateFloatingButtonsState() {
        if (!viewResultsButton || !floatingReturnButton) return;
        const lastResults = sessionStorage.getItem('lastResults');
        const isFormViewActive = formView.style.display !== 'none';
        const isResultsViewActive = resultsView.style.display !== 'none';

        // View Results button is visible on form view if there are results
        if (lastResults && isFormViewActive) {
            viewResultsButton.classList.add('visible');
        } else {
            viewResultsButton.classList.remove('visible');
        }

        // Floating Return button is visible on results view
        if (isResultsViewActive) {
            floatingReturnButton.classList.add('visible');
        } else {
            floatingReturnButton.classList.remove('visible');
        }
    }
	function showView(viewName) {
		formView.style.display = 'none';
		loadingView.style.display = 'none'; // Hide iframe container
		resultsView.style.display = 'none';
		if (viewName === 'form') {
			formView.style.display = 'block';
		} else if (viewName === 'loading') {
            loadingView.style.display = 'flex';
        } else if (viewName === 'results') {
			resultsView.style.display = 'block';
		}
        updateFloatingButtonsState();
	}
	

	const forceProcessButton = document.getElementById('force-process-button');
	const convertButton = document.getElementById('convert-button');

	forceProcessButton.addEventListener('click', () => {
		uploadForm.dataset.force = 'true';
		uploadForm.requestSubmit(convertButton);
	});

	/**
	 * Performs a high-reliability check on audio files using the Web Audio API.
	 * This is slower but can detect corrupted files that the faster method might miss.
	 * @param {File[]} files An array of audio file objects.
	 * @returns {Promise<number[]>} A promise that resolves with an array of verified durations.
	 */
	function verifyAudioFileIntegrity(files) {
		const promises = files.map(file => {
			return new Promise((resolve, reject) => {
				if (file.type.includes('midi')) {
					// MIDI files don't need this level of verification, resolve immediately.
					return resolve(null);
				}
				const reader = new FileReader();
				reader.onload = (e) => {
					const audioContext = new (window.AudioContext || window.webkitAudioContext)();
					audioContext.decodeAudioData(e.target.result)
						.then(buffer => resolve(buffer.duration))
						.catch(err => reject(new Error(`File "${file.name}" appears to be corrupted or is not a valid audio file.`)));
				};
				reader.onerror = () => reject(new Error(`Could not read file "${file.name}".`));
				reader.readAsArrayBuffer(file);
			});
		});
		return Promise.all(promises);
	}

	function displayNewLogs(data) {

		if (!data || !data.ui_logs) return;

		if (data.ui_logs.length > displayedLogCount) {
			const newLogs = data.ui_logs.slice(displayedLogCount);
			newLogs.forEach(originalLogObject => {
				// --- FIX: Pass the entire original log object to preserve the 'target' property ---
				showNotification(originalLogObject);
			});
			displayedLogCount = data.ui_logs.length;
		}
		sessionStorage.setItem('displayedLogCount', displayedLogCount);
	}

	function returnToForm() {
		fileStore.music.clear();
		fileStore.lyrics.clear();
		renderAllFileLists();
		showView('form');
		const header = document.querySelector('.header');
		if (header) {
			setTimeout(() => {
				header.scrollIntoView({ behavior: 'smooth' });
			}, 100);
		}
	}

	function viewLastResults() {
		const lastResults = sessionStorage.getItem('lastResults');
		if (lastResults) {
			const resultsData = JSON.parse(lastResults);
			renderResults(resultsData);
			showView('results');
		}
	}

	function _setupEventListeners() {
		// Listen for messages from the iframe (e.g., when processing is done)
		window.addEventListener('message', (event) => {
			// Basic security check
			if (event.origin !== window.location.origin) {
				return;
			}
	
			const { status, results, type, logs } = event.data;
	
			if (type === 'log_update' && logs) {

				displayNewLogs({ ui_logs: logs });
				return; // This is a log update, not a status change.
			}
	
			if (status === 'completed') {
				if (results) {
					clearAllToasts();
	
					const startTimeStr = sessionStorage.getItem('processStartTime');
					if (startTimeStr) {
						const startTime = new Date(startTimeStr);
						const endTime = new Date();
						const durationSeconds = (endTime - startTime) / 1000;
						const minutes = Math.floor(durationSeconds / 60);
						const seconds = Math.round(durationSeconds % 60);
						const durationMessage = `Total processing time: ${minutes}m ${seconds}s`;

						showNotification({ message: durationMessage, type: 'info', icon: 'timer', target: 'log' });
					}
	
					sessionStorage.setItem('lastResults', JSON.stringify(results));
					renderResults(results);
					showView('results');
				} else {
					showNotification({ message: "Processing completed, but no results were generated.", type: 'error' });
					showView('form');
				}
				sessionStorage.removeItem('activeTaskId');
			} else if (status === 'failed' || status === 'cancelled') {
				resultsContainer.innerHTML = `<div class="error-message"><h2>Processing ${status}</h2></div>`;
				showView('results');
				sessionStorage.removeItem('activeTaskId');
			}
		});

		// Button event listeners
		resetButton.addEventListener('click', returnToForm);
		floatingReturnButton.addEventListener('click', returnToForm);
		if (viewResultsButton) {
			viewResultsButton.addEventListener('click', viewLastResults);
		}
		if (manageModelsBtn) {
			manageModelsBtn.addEventListener('click', openModelManager);
		}
	}

	// --- DEFINITIVE FIX: Use 'pageshow' for robust session restoration ---
	// The 'pageshow' event fires on initial load AND when the page is restored
	// from the browser's back-forward cache (bfcache). This ensures that if a user
	// navigates away during processing and then returns, the application state
	// is correctly restored. The `event.persisted` property is true only for
	// bfcache restorations.
	window.addEventListener('pageshow', function(event) {
		console.log(`Page show event: persisted=${event.persisted}`);
		// Always run startup checks to ensure the UI is in the correct state,
		// especially after bfcache restoration.
		_runStartupChecks();
	});

	function _runStartupChecks() {
		function restoreSessionState() {
			const activeTaskId = sessionStorage.getItem('activeTaskId');
			if (activeTaskId) {
				showView('loading');
				const iframe = document.getElementById('processing-iframe');
				iframe.src = `/processing?task_id=${activeTaskId}`;
				loadingView.style.display = 'flex';
				return true; // Indicates a session was restored.
			}
			const lastResults = sessionStorage.getItem('lastResults');
			if (lastResults) {
				showNotification({ message: "Found previous results. Click the history button to view.", type: 'success', icon: 'history', duration: 5000, target: 'toast' });
			}
			return false;
		}

		fetch('/health')
			.then(response => {
				if (!response.ok) {
					throw new Error(`Health check failed with status: ${response.status}`);
				}
				return response.json();
			})
			.then(data => {
				if (data.status !== 'ok') {
					console.warn('Backend health check indicates a degraded state:', data.checks);
					const errorMessages = Object.values(data.checks)
						.filter(check => check.status !== 'ok' && check.status !== 'loaded')
						.map(check => check.message);
	
					if (errorMessages.length > 0) {
						const fullMessage = `Warning: Backend setup is incomplete. ${errorMessages.join(' ')}`;

						showNotification({ message: fullMessage, type: 'error', duration: 3600000 });
					}
				}
			})
			.catch(error => {
				console.error('Could not perform backend health check:', error);
				showNotification({ message: 'Could not connect to the SolaSola backend. Please ensure it is running correctly.', type: 'error', duration: 3600000 });
			});
	
		// Check if we need to reconnect to an existing task or show previous results
		const sessionRestored = restoreSessionState();
		if (!sessionRestored) {
			showView('form');
		}
	}

	function _handleSubmissionUIStart() {
		const verifyingIndicator = document.getElementById('verifying-indicator');
		const verifyingText = document.getElementById('verifying-text');
		verifyingText.textContent = 'Checking Files...'; // Set initial text
		verifyingIndicator.style.display = 'flex';
		convertButton.style.display = 'none';
		forceProcessButton.style.display = 'none';
	}

	function _handleSubmissionUIEnd(errorOccurred = false) {
		const verifyingIndicator = document.getElementById('verifying-indicator');
		verifyingIndicator.style.display = 'none';
		convertButton.style.display = 'inline-flex';
		convertButton.disabled = fileStore.music.size === 0;
	}

	async function _runFinalValidation(isForced) {
		if (isForced) return { success: true };

		const musicFiles = Array.from(fileStore.music.values());
		const audioFilesToVerify = musicFiles.filter(f => !f.name.toLowerCase().endsWith('.mid'));

		try {
			if (audioFilesToVerify.length > 0) {
				const durations = await verifyAudioFileIntegrity(audioFilesToVerify);

				const hasMidi = musicFiles.some(f => f.name.toLowerCase().endsWith('.mid'));
				if (hasMidi && audioFilesToVerify.length > 0) {
					throw new Error("Mixing MIDI and other audio files is not supported.");
				}

				if (durations.length > 1) {
					const validDurations = durations.filter(d => d !== null);
					if (validDurations.length > 1 && (Math.max(...validDurations) - Math.min(...validDurations) > DURATION_THRESHOLD_SECONDS.MISMATCH_TOLERANCE)) {
						return { success: false, reason: 'duration_mismatch' };
					}
				}
			}
			return { success: true };
		} catch (err) {
			return { success: false, reason: 'validation_error', error: err };
		}
	}

	async function _submitToServer() {
		const verifyingText = document.getElementById('verifying-text');
		verifyingText.textContent = 'Initializing...';

		const formData = new FormData(uploadForm);
		formData.delete('music_files');
		formData.delete('lyrics_file');
		formData.append('client_time_offset', serverTimeOffset);
		formData.append('client_os', clientOS);

		for (const file of fileStore.music.values()) {
			formData.append('music_files', file, file.name);
		}
		if (fileStore.lyrics.size > 0) {
			const lyricsFile = fileStore.lyrics.values().next().value;
			formData.append('lyrics_file', lyricsFile, lyricsFile.name);
		}

		const response = await fetch("/start_processing", {
			method: 'POST',
			body: formData,
		});

		if (!response.ok) {
			const errorData = await response.json().catch(() => ({ error: `Server error: ${response.statusText}` }));
			throw new Error(errorData.error);
		}

		const data = await response.json();
		if (data.error) {
			throw new Error(data.error);
		}
		return data;
	}

	function _handleSubmissionSuccess(data) {
		const currentTaskId = data.task_id;
		sessionStorage.setItem('activeTaskId', currentTaskId);
		sessionStorage.setItem('processStartTime', new Date().toISOString());
		showView('loading');
		const iframe = document.getElementById('processing-iframe');
		iframe.src = `/processing?task_id=${currentTaskId}`;
	}

	function _handleSubmissionError(error) {
		console.error('Error starting process:', error);

		showNotification({ message: `Failed to start the process: ${error.message}`, type: 'error' });
		_handleSubmissionUIEnd(true);
		showView('form');
	}

	uploadForm.addEventListener('submit', async (e) => {
		e.preventDefault();
		_handleSubmissionUIStart();

		try { // This will catch errors from validation, submission, and success handling
			// --- Stage 2: High-Reliability Verification ---
			const isForced = uploadForm.dataset.force === 'true';
			if (isForced) {
				delete uploadForm.dataset.force;
			}

			const validationResult = await _runFinalValidation(isForced);
			if (!validationResult.success) {
				if (validationResult.reason === 'duration_mismatch') {
					showNotification({ message: "File durations differ significantly. Process Anyway if you are sure they are related.", type: 'warning', duration: 3600000 });
					document.getElementById('verifying-indicator').style.display = 'none';
					forceProcessButton.style.display = 'inline-flex';
				} else { // validation_error
					showNotification({ message: validationResult.error.message, type: 'error', duration: 10000 });
					_handleSubmissionUIEnd(true);
				}
				return; // Stop submission if validation fails
			}

			// --- Stage 3: Clear old session and submit to server ---
			try {
				sessionStorage.removeItem('lastResults');
				sessionStorage.removeItem('processStartTime');

				sessionStorage.removeItem('activeTaskId');
			} catch (e) { /* Suppress potential errors */ }
			displayedLogCount = 0;
			clearNotificationLog();

			// Submit to server and handle success
			const serverResponse = await _submitToServer();
			_handleSubmissionSuccess(serverResponse);
		} catch (error) {
			_handleSubmissionError(error);
		}
	});

	initializeBaseUI();
	initializeFormHandlers();
	_setupEventListeners(); // Keep this here for initial setup
	sseClient.connect(); // Connect to SSE for real-time updates
}


document.addEventListener('DOMContentLoaded', initializeApp);

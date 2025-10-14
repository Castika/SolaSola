// This module handles all interactions with the main upload form,
// including file selection, drag & drop, and UI controls like sliders and toggles.

import { showNotification, showModal, getAudioDurations, truncateFilename } from './ui-helpers.js';
import { DURATION_THRESHOLD_SECONDS } from './constants.js';

// --- File Management ---

// We manage files in JS Maps and sync them to the hidden inputs.
// This allows us to easily add/remove files.
export const fileStore = {
	music: new Map(),
	lyrics: new Map()
};

let isClientFileProcessing = false; // Global flag to prevent concurrent processing
const getFileKey = (file) => `${file.name}-${file.lastModified}`;

function syncFilesToInput(inputElement, fileMap) {
	const dataTransfer = new DataTransfer();
	for (const file of fileMap.values()) {
		dataTransfer.items.add(file);
	}
	inputElement.files = dataTransfer.files;
}

function _renderSingleFileList(inputElement, listEl, uploadArea, fileMap) {
    listEl.innerHTML = '';
    for (const [key, file] of fileMap.entries()) {
        const listItem = document.createElement('li');
        listItem.className = 'file-list-item';
        listItem.title = file.name;

        const fileNameSpan = document.createElement('span');
        fileNameSpan.className = 'file-name-text';
        const TRUNCATE_LENGTH = 40;
        fileNameSpan.textContent = truncateFilename(file.name, TRUNCATE_LENGTH);
        listItem.appendChild(fileNameSpan);

        const removeBtn = document.createElement('button');
        removeBtn.className = 'file-remove-btn';
        removeBtn.innerHTML = '&times;';
        removeBtn.type = 'button';
        removeBtn.setAttribute('aria-label', `Remove ${file.name}`);
        removeBtn.onclick = (e) => {
            e.preventDefault();
            fileMap.delete(key);
            renderAllFileLists();
        };
        listItem.appendChild(removeBtn);
        listEl.appendChild(listItem);
    }

    if (fileMap.size > 0) {
        uploadArea.classList.add('has-files');
        listEl.style.display = 'flex';
    } else {
        uploadArea.classList.remove('has-files');
        listEl.style.display = 'none';
    }
}

function _updateWarningCardState() {
    const musicFiles = Array.from(fileStore.music.values());
    const showWarning = musicFiles.length > 1;
    const warningCard = document.getElementById('mixed-files-warning');
    if (warningCard) {
        warningCard.style.display = showWarning ? 'flex' : 'none';
    }
}

function _updateConvertButtonState() {
    const convertButton = document.getElementById('convert-button');
    const isLyricsMode = document.getElementById('lyrics-only-mode')?.checked;
    const isButtonDisabled = isLyricsMode
        ? fileStore.lyrics.size === 0
        : fileStore.music.size === 0;
    convertButton.disabled = isButtonDisabled;
}

export function renderAllFileLists() {
    const musicFilesInput = document.getElementById('music_files');
	const musicFileList = document.getElementById('music-file-list');
	const musicUploadArea = document.querySelector('label[for="music_files"]');
	const lyricsFileInput = document.getElementById('lyrics_file');
	const lyricsFileList = document.getElementById('lyrics-file-list');
	const lyricsUploadArea = document.querySelector('label[for="lyrics_file"]');
    const forceProcessButton = document.getElementById('force-process-button');

    // Validate for mixed full-mix and stem files
    const musicFiles = Array.from(fileStore.music.values());
    let warningCard = document.getElementById('mixed-files-warning');

    // Create the warning card if it doesn't exist
    if (!warningCard) {
        warningCard = document.createElement('div');
        warningCard.id = 'mixed-files-warning';
        warningCard.className = 'file-list-warning';
        warningCard.style.display = 'none';
        warningCard.innerHTML = `
            <span class="material-symbols-outlined">warning</span>
            <p><strong>Multiple Files Selected:</strong> To process multiple files, please provide all related instrument stems (e.g., vocals, bass, drums) from a single song. Mixing unrelated songs or incomplete stems may cause errors.</p>
        `;
        musicUploadArea.parentNode.insertBefore(warningCard, musicUploadArea.nextSibling);
    }

    _renderSingleFileList(musicFilesInput, musicFileList, musicUploadArea, fileStore.music);
    _renderSingleFileList(lyricsFileInput, lyricsFileList, lyricsUploadArea, fileStore.lyrics);
    _updateWarningCardState();
    _updateConvertButtonState();

	// Also, reset the visibility of the "Process Anyway" button.
	// This ensures that if the user modifies the file list after a duration warning,
	// the UI returns to the normal state for the next submission attempt.
    const wasWarningVisible = forceProcessButton.style.display !== 'none';
    const verifyingIndicator = document.getElementById('verifying-indicator');

    const convertButton = document.getElementById('convert-button');
    if (forceProcessButton.style.display !== 'none' || verifyingIndicator.style.display !== 'none') {
        forceProcessButton.style.display = 'none';
        verifyingIndicator.style.display = 'none';
        convertButton.style.display = 'inline-flex';
    }

    if (wasWarningVisible) {

        showNotification("File list updated. The duration warning has been cleared.", "success", 4000, "playlist_add_check");
    }
}

/**
 * Performs fast, non-blocking validation on the selected music files and shows informational warnings.
 * This function uses the fast `new Audio()` method for quick feedback.
 */
async function validateMusicFiles() {
    const musicFiles = Array.from(fileStore.music.values());
    if (musicFiles.length === 0) return;

    // 1. Check for mixed file types (MIDI and other audio)
    const hasMidi = musicFiles.some(f => f.name.toLowerCase().endsWith('.mid'));
    const hasOtherAudio = musicFiles.some(f => !f.name.toLowerCase().endsWith('.mid'));
    if (hasMidi && hasOtherAudio) {

        showNotification("Mixing MIDI and other audio files is not supported. Please upload them separately.", "error", 8000, "error");
        // This is a hard error, so we can disable the button.
        document.getElementById('convert-button').disabled = true;
        return; // Stop further validation
    }

    // 2. Check durations for long files and mismatches (only for non-MIDI audio files)
    const audioFilesToAnalyse = musicFiles.filter(f => !f.name.toLowerCase().endsWith('.mid'));
    if (audioFilesToAnalyse.length === 0) return;

    try {
        const durations = await getAudioDurations(audioFilesToAnalyse);

        // Check for long files
        const hasLongFile = durations.some(duration => duration > DURATION_THRESHOLD_SECONDS.LONG_FILE_WARNING);
        if (hasLongFile) {

            showNotification("A file is over 10 minutes long. Processing may be very slow.", "warning", 8000, "hourglass_top");
        }

        // Check for duration mismatch if multiple files are present
        if (durations.length > 1) {
            const durationDifference = Math.max(...durations) - Math.min(...durations);
            if (durationDifference > DURATION_THRESHOLD_SECONDS.MISMATCH_TOLERANCE) {

                showNotification("File durations differ significantly. They may be from different songs, which could lead to incorrect results.", "warning", 8000, "warning");
            }
        }
    } catch (error) {
        // This is a non-blocking warning. The more reliable check will happen in main.js
        console.warn("Initial file validation (fast check) failed:", error);

        showNotification("Could not quickly verify all audio files. A more thorough check will be performed upon starting.", "warning", 5000, "help");
    }
}

function setProcessingState(uploadArea, isProcessing) {
    const icon = uploadArea.querySelector('.material-symbols-outlined');
    if (isProcessing) {
        uploadArea.classList.add('processing');
        if (icon) {
            icon.style.position = 'relative';
            icon.style.zIndex = '11';
        }
    } else {
        uploadArea.classList.remove('processing');
        if (icon) icon.style.cssText = '';
    }
}

async function handleZipFile(zipFile, type) {
    if (typeof JSZip === 'undefined') {
        console.error("JSZip not loaded. Cannot handle zip files on client-side.");

        showNotification("Could not process ZIP file because a required library is missing.", "error");
        return;
    }

    try {
        const zip = await JSZip.loadAsync(zipFile);
        // showNotification(`Unzipping ${zipFile.name}...`, 'info', 3000);
        let lyricsFileFound = false;
        let lyricsFileIgnored = false;
        const filePromises = []; // This will hold all promises for file processing

        zip.forEach((relativePath, zipEntry) => {
            if (zipEntry.dir || relativePath.startsWith('__MACOSX/')) return;

            const promise = zipEntry.async('blob').then(blob => {
                const file = new File([blob], zipEntry.name, { type: blob.type, lastModified: zipEntry.date ? zipEntry.date.getTime() : Date.now() });
                const extension = zipEntry.name.split('.').pop().toLowerCase();

            if (['txt', 'lrc', 'srt'].includes(extension)) {
                    if (type === 'music') {
                        // If the zip was dropped in the music area, IGNORE lyrics files inside it.
                        lyricsFileIgnored = true;
                    } else { // type === 'lyrics'
                        // The lyrics section should only ever have one file.
                        // We clear it here to ensure only the last found lyrics file from the zip is used.
                        fileStore.lyrics.clear(); 
                        fileStore.lyrics.set(getFileKey(file), file);
                        lyricsFileFound = true;
                    }
                } else if (['mp3', 'wav', 'mid', 'flac', 'm4a', 'aac'].includes(extension)) {
                    const key = getFileKey(file);
                    if (!fileStore.music.has(key)) {
                        fileStore.music.set(key, file);
                    }
                }
            });
            filePromises.push(promise); // Add the promise to the array
        });

        // Wait for all files to be processed before continuing
        await Promise.all(filePromises);

        if (lyricsFileIgnored) {

            showNotification(`Note: Lyrics files inside a ZIP are ignored when dropped in the music area.`, 'info', 7000);
        } else if (lyricsFileFound) {
            showNotification(`Unzipped ${zipFile.name}. A lyrics file was found and moved to the lyrics section.`, 'success');
        } else {
            // showNotification(`Finished unzipping ${zipFile.name}.`, 'success');
        }

    } catch (e) {

        showNotification(`Error: Could not unzip ${zipFile.name}.`, 'error');
        const key = getFileKey(zipFile);
        // If unzipping fails, add the zip file itself to the music store so the user sees it.
        if (!fileStore.music.has(key)) {
            fileStore.music.set(key, zipFile);
        }
    }
}

async function handleFileSelection(files, type) {
    // Prevent concurrent file processing
    if (isClientFileProcessing) {

        showNotification("Please wait for the current files to be processed.", "warning", 3000, "hourglass_empty");
        return;
    }
    isClientFileProcessing = true;

    const newFiles = files ? Array.from(files) : [];
    if (newFiles.length === 0) {
        isClientFileProcessing = false;
        return;
    }

    // Client-side file extension validation
    const SUPPORTED_MUSIC_EXTENSIONS = ['.mp3', '.wav', '.mid', '.zip', '.flac', '.m4a', '.aac'];
    const SUPPORTED_LYRICS_EXTENSIONS = ['.txt', '.lrc', '.srt'];

    const allowedExtensions = type === 'music' ? SUPPORTED_MUSIC_EXTENSIONS : SUPPORTED_LYRICS_EXTENSIONS;
    const filteredFiles = [];
    let rejectedCount = 0;

    for (const file of newFiles) {
        const extension = `.${file.name.split('.').pop().toLowerCase()}`;
        if (allowedExtensions.includes(extension)) {
            filteredFiles.push(file);
        } else {
            rejectedCount++;
        }
    }

    if (filteredFiles.length === 0) {
        isClientFileProcessing = false; // Stop if no valid files are left
        return;
    }

    const musicUploadArea = document.querySelector('label[for="music_files"]');
    const lyricsUploadArea = document.querySelector('label[for="lyrics_file"]');
    const musicFilesInput = document.getElementById('music_files');
    const lyricsFileInput = document.getElementById('lyrics_file');

    const uploadArea = type === 'music' ? musicUploadArea : lyricsUploadArea;
    setProcessingState(uploadArea, true);

    const processingPromises = [];

    try {
        if (type === 'music') {
            for (const file of filteredFiles) {
                if (file.name.toLowerCase().endsWith('.zip')) {
                    processingPromises.push(handleZipFile(file, 'music'));
                } else if (!fileStore.music.has(getFileKey(file))) {
                    fileStore.music.set(getFileKey(file), file);
                }
            }
        } else { // lyrics
            fileStore.lyrics.clear();
            const file = filteredFiles[0]; // Lyrics section only allows one file
            fileStore.lyrics.set(getFileKey(file), file);
        }

        await Promise.all(processingPromises);

    } catch (error) {

        showNotification("An error occurred while processing files.", "error");
    } finally {
        // Run all initial validations after files are processed.
        await validateMusicFiles();

        renderAllFileLists();
        setProcessingState(uploadArea, false);
        // Clear both inputs to allow re-selection
        musicFilesInput.value = '';
        lyricsFileInput.value = '';
        isClientFileProcessing = false; // Re-enable file selection
    }
}

// --- UI Controls Setup ---

function setupProcessingModeToggles() {
    const modeRadios = document.querySelectorAll('input[name="mode"]');
	const radioOptions = document.querySelectorAll('.radio-option');

	function updateProcessingModeStyles() {
		// This function now only handles the visual selection style of the radio options.
		// The visibility of sub-options (like sliders or toggles) is now handled by CSS or is always visible.
		radioOptions.forEach(option => {
			const radio = option.querySelector('input[type="radio"]');
			if (radio && radio.checked) {
				option.classList.add('is-selected');
				option.classList.remove('is-inactive');
			} else {
				option.classList.remove('is-selected');
				option.classList.add('is-inactive');
			}
		});
        renderAllFileLists();
	}

	modeRadios.forEach(radio => {
		radio.addEventListener('change', updateProcessingModeStyles);
	});

	const scoreRadio = document.getElementById('score-mode');
	if (scoreRadio) scoreRadio.value = 'abc'; // Set a static value

    // Initial style update
    updateProcessingModeStyles();
}

class DemucsSlider {
    constructor(sliderElement) {
        this.slider = sliderElement;
        if (!this.slider) return;

        this.sliderContainer = this.slider.closest('.slider-container');
        this.scoreModeRadio = document.getElementById('score-mode');
        this.labels = [
            document.getElementById('demucs-label-0'),
            document.getElementById('demucs-label-1'),
            document.getElementById('demucs-label-2')
        ];
        this.hiddenInput = document.getElementById('demucs_model_hidden');
        this.tooltip = document.getElementById('demucs-tooltip');
        this.tooltipDesc = document.getElementById('demucs-desc');
        this.selectedDesc = document.getElementById('demucs-selected-description');

        if (!this.sliderContainer || !this.scoreModeRadio || this.labels.some(el => !el) || !this.hiddenInput || !this.tooltip || !this.tooltipDesc || !this.selectedDesc) {
            console.error("Demucs slider is missing required DOM elements.");
            return;
        }

        this.qualityLevels = [
            { value: 'htdemucs', tooltip: "Good quality 4-stem separation.", description: "Producing good quality separation for vocals, drums, bass and other stems (Recommended)" },
            { value: 'htdemucs_6s', tooltip: "Good quality 6-stem separation including piano/guitar.", description: "Producing good quality separation for piano, guitar, vocals, drums, bass and other stems" },
            { value: 'htdemucs_ft', tooltip: "Multi-analyzed 4-stem separation.", description: "Performs multiple analyses for more accurate separation of vocals, drums, bass, and other stems. This process takes significantly longer." }
        ];
        this.isDragging = false;

        this._setupEventListeners();
        this.updateSelectedQuality();
        setTimeout(() => this._positionTooltipOnThumb(), 0);
    }

    _setupEventListeners() {
        this.slider.addEventListener('input', () => { this.updateSelectedQuality(); this._positionTooltipOnThumb(); });
        this.slider.addEventListener('mousemove', (e) => this._updateTooltipOnHover(e));
        this.slider.addEventListener('mouseleave', () => this._positionTooltipOnThumb());
        this.slider.addEventListener('mousedown', () => { this.isDragging = true; this._selectScoreMode(); });
        window.addEventListener('mouseup', () => { this.isDragging = false; });
        window.addEventListener('resize', () => this._positionTooltipOnThumb());

        this.labels.forEach((label, index) => {
            label.addEventListener('click', () => {
                this.slider.value = index;
                this.slider.dispatchEvent(new Event('input'));
                this._selectScoreMode();
            });
        });
    }

    _selectScoreMode() {
        if (!this.scoreModeRadio.checked) {
            this.scoreModeRadio.checked = true;
            this.scoreModeRadio.dispatchEvent(new Event('change', { bubbles: true }));
        }
    }

    updateSelectedQuality() {
        const level = parseInt(this.slider.value, 10);
        this.labels.forEach((label, index) => {
            label.classList.toggle('selected', index === level);
        });
        this.hiddenInput.value = this.qualityLevels[level].value;
        this.selectedDesc.textContent = this.qualityLevels[level].description;
    }

    _positionTooltipOnThumb() {
        const level = parseInt(this.slider.value, 10);
        this.tooltipDesc.textContent = this.qualityLevels[level].tooltip;

        const containerWidth = this.sliderContainer.offsetWidth;
        if (containerWidth === 0) return;

        const sliderStyles = getComputedStyle(this.slider);
        const thumbWidth = parseFloat(sliderStyles.getPropertyValue('--thumb-size')) || 20;
        const horizontalPadding = parseFloat(sliderStyles.getPropertyValue('--track-padding')) || 8;

        const trackWidth = containerWidth - thumbWidth - (horizontalPadding * 2);
        const percent = (this.slider.max > this.slider.min) ? (level - this.slider.min) / (this.slider.max - this.slider.min) : 0;
        const handlePosition = (percent * trackWidth) + (thumbWidth / 2) + horizontalPadding;

        this._updateTooltipPosition(handlePosition, handlePosition);
    }

    _updateTooltipOnHover(event) {
        if (this.isDragging) return;

        const containerRect = this.sliderContainer.getBoundingClientRect();
        let mouseX = event.clientX - containerRect.left;
        const containerWidth = this.sliderContainer.offsetWidth;

        const sliderStyles = getComputedStyle(this.slider);
        const horizontalPadding = parseFloat(sliderStyles.getPropertyValue('--track-padding')) || 8;

        const clampedMouseX = Math.max(horizontalPadding, Math.min(mouseX, containerWidth - horizontalPadding));

        const effectiveTrackWidth = containerWidth - (horizontalPadding * 2);
        const positionOnTrack = clampedMouseX - horizontalPadding;
        const percentOnTrack = effectiveTrackWidth > 0 ? positionOnTrack / effectiveTrackWidth : 0;
        const hoverLevel = Math.round(percentOnTrack * (this.qualityLevels.length - 1));
        
        this.tooltipDesc.textContent = this.qualityLevels[hoverLevel].tooltip;
        this._updateTooltipPosition(mouseX, clampedMouseX);
    }

    _updateTooltipPosition(tooltipCenterX, arrowCenterX) {
        const tooltipWidth = this.tooltip.offsetWidth;
        let tooltipLeft = tooltipCenterX - (tooltipWidth / 2);

        const parentWidth = this.sliderContainer.offsetWidth;
        if (tooltipLeft < 0) tooltipLeft = 0;
        if (tooltipLeft + tooltipWidth > parentWidth) tooltipLeft = parentWidth - tooltipWidth;
        this.tooltip.style.left = `${tooltipLeft}px`;

        const arrow = this.tooltip.querySelector('.tooltip-arrow');
        if (arrow) arrow.style.left = `${arrowCenterX - tooltipLeft}px`;
    }
}

function setupDemucsSlider() {
    const demucsSlider = document.getElementById('demucs-quality-slider');
    if (demucsSlider) {
        new DemucsSlider(demucsSlider);
    }
}

function setupDragAndDrop() {
    const musicUploadArea = document.querySelector('label[for="music_files"]');
	const lyricsUploadArea = document.querySelector('label[for="lyrics_file"]');

    [musicUploadArea, lyricsUploadArea].forEach(area => {
		['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
			area.addEventListener(eventName, e => {
				e.preventDefault();
				e.stopPropagation();
			}, false);
		});
		['dragenter', 'dragover'].forEach(eventName => area.addEventListener(eventName, () => area.classList.add('drag-over')));
		['dragleave', 'drop'].forEach(eventName => area.addEventListener(eventName, () => area.classList.remove('drag-over')));
	});

	musicUploadArea.addEventListener('drop', (e) => {
		handleFileSelection(e.dataTransfer.files, 'music');
	});

	lyricsUploadArea.addEventListener('drop', (e) => {
		handleFileSelection(e.dataTransfer.files, 'lyrics');
	});
}

export function initializeFormHandlers() {
    setupProcessingModeToggles();
    setupDemucsSlider();
    setupDragAndDrop();

    // Attach event listeners directly to file inputs
    const musicFilesInput = document.getElementById('music_files');
    const lyricsFileInput = document.getElementById('lyrics_file');

    const forceProcessButton = document.getElementById('force-process-button');
    const uploadForm = document.getElementById('upload-form');

    musicFilesInput.addEventListener('change', () => handleFileSelection(musicFilesInput.files, 'music'));
    lyricsFileInput.addEventListener('change', () => handleFileSelection(lyricsFileInput.files, 'lyrics'));
    if (forceProcessButton && uploadForm) {
        forceProcessButton.addEventListener('click', () => uploadForm.dispatchEvent(new Event('submit', { cancelable: true })));
    }
}

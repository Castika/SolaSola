// Handles rendering and interaction for the results view.
import { showNotification, showModal, closeModal, truncateFilename } from './ui-helpers.js';

const songInfoTemplate = document.getElementById('song-info-template');
const chordChartTemplate = document.getElementById('chord-chart-template');
const scoreCardTemplate = document.getElementById('score-card-template');
const lyricsCardTemplate = document.getElementById('lyrics-card-template');
const resultsContainer = document.getElementById('results-container');
let currentResultsData = null; // Module-level variable to hold the full results object
let textViewModal = null;
let textViewTitle = null;
let textViewBody = null;

function showCopyFeedback(buttonElement) {
    const originalIcon = buttonElement.innerHTML;
    buttonElement.innerHTML = '<span class="material-symbols-outlined">check</span>';
    buttonElement.classList.add('copied');
    buttonElement.disabled = true;
    setTimeout(() => {
        buttonElement.innerHTML = originalIcon;
        buttonElement.classList.remove('copied');
        buttonElement.disabled = false;
    }, 2000);
}

function copyToClipboard(textAreaElement, buttonElement) {
    if (!textAreaElement || !textAreaElement.value) return;

    navigator.clipboard.writeText(textAreaElement.value).then(() => {
        showNotification({ message: "Copied to clipboard.", type: 'success', icon: 'content_copy', duration: 2000, target: 'toast' });
        showCopyFeedback(buttonElement);
    }).catch(err => {
        showNotification({ message: 'Failed to copy text.', type: 'error' });
    });
}

// This function updates the content of the already-visible score modal.
function updateChartModalContent(newIndex, songTitle, dataKey, instruments, isChordChart) {
    const modal = document.getElementById('sola-modal'); // This is correct
    if (!modal || !modal.classList.contains('visible')) return; // Exit if modal isn't open

    if (newIndex < 0) {
        newIndex = instruments.length - 1; // Go to the last item
    } else if (newIndex >= instruments.length) {
        newIndex = 0; // Go to the first item
    }

    const instrumentName = instruments[newIndex];
    let content = '';
    const dataObject = currentResultsData?.[songTitle]?.[dataKey];
    if (dataObject) {
        // Find the key in a case-insensitive way to handle 'Mix' vs 'mix'
        const actualKey = Object.keys(dataObject).find(k => k.toLowerCase() === instrumentName.toLowerCase());
        if (actualKey) {
            content = dataObject[actualKey];
        }
    }

    // Get modal elements
    const titleEl = modal.querySelector('#sola-modal-title');
    const bodyEl = modal.querySelector('#sola-modal-body');
    const footerEl = modal.querySelector('#sola-modal-footer');

    const displayName = instrumentName.charAt(0).toUpperCase() + instrumentName.slice(1);
    titleEl.textContent = isChordChart ? displayName : `${displayName} Score`;

    const pre = document.createElement('pre');
    pre.textContent = content || 'No score data available for this instrument.';
    bodyEl.innerHTML = '';
    bodyEl.appendChild(pre);

    // Update Footer button states and actions without rebuilding them
    const prevBtn = footerEl.querySelector('[title="Previous"]');
    const nextBtn = footerEl.querySelector('[title="Next"]');
    const copyBtn = footerEl.querySelector('[aria-label="Copy"]');

    if (prevBtn) {
        prevBtn.disabled = false; // Always enabled for circular navigation
        prevBtn.onclick = () => updateChartModalContent(newIndex - 1, songTitle, dataKey, instruments, isChordChart);
    }
    if (nextBtn) {
        nextBtn.disabled = false; // Always enabled for circular navigation
        nextBtn.onclick = () => updateChartModalContent(newIndex + 1, songTitle, dataKey, instruments, isChordChart);
    }
    if (copyBtn) {
        // Re-assign onclick to capture the new `content` in the closure
        copyBtn.onclick = () => {
            navigator.clipboard.writeText(content).then(() => {
                showNotification({ message: "Copied to clipboard.", type: 'success', icon: 'content_copy', duration: 2000, target: 'toast' });
            }).catch(() => showNotification({ message: 'Failed to copy text.', type: 'error' }));
        };
    }
}

function openChartModal(initialIndex, songTitle, dataKey, instruments, isChordChart) {
    const instrumentName = instruments[initialIndex] || "Item";

    const displayName = instrumentName.charAt(0).toUpperCase() + instrumentName.slice(1);
    
    let content = '';
    const dataObject = currentResultsData?.[songTitle]?.[dataKey];
    if (dataObject) {
        // Find the key in a case-insensitive way to handle 'Mix' vs 'mix'
        const actualKey = Object.keys(dataObject).find(k => k.toLowerCase() === instrumentName.toLowerCase());
        if (actualKey) {
            content = dataObject[actualKey];
        }
    }

    const pre = document.createElement('pre');
    pre.textContent = content;

    showModal({
        title: isChordChart ? displayName : `${displayName} Score`,
        bodyContent: pre,
        footerButtons: [
            {
                icon: 'chevron_left',
                title: 'Previous',
                action: () => updateChartModalContent(initialIndex - 1, songTitle, dataKey, instruments, isChordChart),
                disabled: instruments.length <= 1,
                align: 'left'
            },
            {
                icon: 'chevron_right',
                title: 'Next',
                action: () => updateChartModalContent(initialIndex + 1, songTitle, dataKey, instruments, isChordChart),
                disabled: instruments.length <= 1,
                align: 'left'
            },
            {
                label: 'Copy',
                icon: 'content_copy',
                action: (btn) => copyToClipboard({ value: content }, btn),
                isSuccess: true
            },
            { label: 'Close', icon: 'close', action: 'close', isPrimary: true }

        ]
    });
}

function _createSongInfoCard(title, result) {
    const songProfile = result.song_profile || {};
    const hasInfo = !songProfile.is_lyrics_only_split && Object.keys(songProfile).length > 0;
    if (!hasInfo) return null;

    const card = songInfoTemplate.content.cloneNode(true);
    const titleEl = card.querySelector('.song-title');
    const copyBtn = card.querySelector('.copy-btn');

    titleEl.textContent = truncateFilename(title, 50);

    if (copyBtn) {
        copyBtn.addEventListener('click', () => {
            let profileText = '';
            const profileData = { ...songProfile };

            const orderedKeys = [
                'Genre - AI Estimated', 'Duration', 'Song Structure',
                'Key', 'Time Signature', 'Tempo', 'Pitch Range', 'Note Count', 'Vocal Activity', 'Lyric Density'
            ];
            const processedKeys = new Set();
            
            orderedKeys.forEach(key => {
                if (profileData.hasOwnProperty(key)) {
                    profileText += `${key} : ${profileData[key]}\n`;
                    processedKeys.add(key);
                }
            });

            for (const key in profileData) {
                if (!processedKeys.has(key)) {
                    const isInternalData = key.endsWith('_srt') || key === 'chord_grid_text' ||
                                           key === 'is_lyrics_only_split' || key === 'lyrics_source_method';
                    if (!isInternalData) {
                        profileText += `${key} : ${profileData[key]}\n`;
                    }
                }
            }

            navigator.clipboard.writeText(profileText.trim()).then(() => {
                showNotification({ message: "Profile copied to clipboard.", type: 'success', icon: 'content_copy', duration: 2000, target: 'toast' });
                showCopyFeedback(copyBtn);
            }).catch(err => {
                showNotification({ message: 'Failed to copy profile.', type: 'error' });
            });
        });
    }

    const profileResultEl = card.querySelector('.song-profile');
    const profilePillsContainer = profileResultEl.querySelector('.profile-pills');
    
    profileResultEl.style.display = 'block';
    profilePillsContainer.innerHTML = '';

    const orderedKeys = [
        'Genre - AI Estimated', 'Duration', 'Song Structure',
        'Key', 'Time Signature', 'Tempo', 'Pitch Range', 'Note Count', 'Vocal Activity', 'Lyric Density'
    ];
    const processedKeys = new Set();

    const createPill = (key, value) => {
        const itemContainer = document.createElement('div');
        itemContainer.className = 'profile-item';
        const keyBadge = document.createElement('span');
        keyBadge.className = 'profile-key-badge';
        keyBadge.textContent = key;
        itemContainer.appendChild(keyBadge);
        const valueText = document.createElement('span');
        valueText.className = 'profile-value-text';
        valueText.textContent = value;
        itemContainer.appendChild(valueText);
        if (key === 'Genre - AI Estimated') {
            const wrapper = document.createElement('div');
            wrapper.className = 'genre-pill-wrapper';
            wrapper.appendChild(itemContainer);
            profilePillsContainer.appendChild(wrapper);
        } else {
            profilePillsContainer.appendChild(itemContainer);
        }
    };

    orderedKeys.forEach(key => {
        if (songProfile.hasOwnProperty(key)) {
            createPill(key, songProfile[key]);
            processedKeys.add(key);
        }
    });

    for (const key in songProfile) {
        const isInternalData = key.endsWith('_srt') || key === 'chord_grid_text' ||
                               key === 'is_lyrics_only_split' || key === 'lyrics_source_method';
        if (!processedKeys.has(key) && !isInternalData) {
            createPill(key, songProfile[key]);
        }
    }

    return card;
}

class ScoreSlider {
    constructor(card, sortedInstruments, abcFiles, onTabChange) {
        this.card = card;
        this.sortedInstruments = sortedInstruments;
        this.abcFiles = abcFiles;
        this.onTabChange = onTabChange;
        this.numTabs = this.sortedInstruments.length;

        this.slider = this.card.querySelector('.quality-slider');
        this.sliderContainer = this.card.querySelector('.slider-container');
        this.tabNav = this.card.querySelector('.tab-nav');
        this.textarea = this.card.querySelector('.result-output');
        this.scoreTooltip = this.card.querySelector('.score-tooltip');
        this.tooltipDesc = this.card.querySelector('.score-tooltip-desc');
        this.tooltipArrow = this.card.querySelector('.tooltip-arrow');

        this.isDragging = false;
        this.tabButtons = [];

        this._setupUI();
        this._setupEventListeners();

        setTimeout(() => this.activateTab(0, true), 100);
    }

    _setupUI() {
        this.sortedInstruments.forEach((instrument) => {
            const tabButton = document.createElement('button');
            tabButton.className = 'tab-btn';
            tabButton.textContent = instrument.charAt(0).toUpperCase() + instrument.slice(1);
            tabButton.setAttribute('data-instrument', tabButton.textContent);
            this.tabNav.appendChild(tabButton);
            this.tabButtons.push(tabButton);
        });

        if (this.numTabs <= 1) {
            this.slider.disabled = true;
            if (this.sliderContainer) this.sliderContainer.style.display = 'none';
        } else {
            this.slider.min = 0;
            this.slider.max = this.numTabs - 1;
            this.slider.step = 1;
            this.slider.value = 0;
            this.slider.disabled = false;
            if (this.sliderContainer) this.sliderContainer.style.display = 'block';
        }
    }

    _setupEventListeners() {
        this.tabButtons.forEach((button, index) => button.addEventListener('click', () => this.activateTab(index, false)));
        this.slider.addEventListener('input', () => this.activateTab(parseInt(this.slider.value, 10), false));

        this.sliderContainer.addEventListener('mousemove', (e) => this._updateTooltipOnHover(e));
        this.sliderContainer.addEventListener('mouseleave', () => { if (!this.isDragging) this._positionTooltipOnThumb(); });
        this.slider.addEventListener('mousedown', () => { this.isDragging = true; });
        window.addEventListener('mouseup', () => { if (this.isDragging) { this.isDragging = false; this._positionTooltipOnThumb(); } });
    }

    activateTab(index, isInitial = false) {
        if (index < 0 || index >= this.numTabs) return;
        const targetButton = this.tabButtons[index];
        const instrumentName = this.sortedInstruments[index];
        const abcContent = this.abcFiles[instrumentName];

        this.tabButtons.forEach(btn => btn.classList.remove('active'));
        targetButton.classList.add('active');
        if (!this.slider.disabled) this.slider.value = index;

        this.onTabChange(abcContent, targetButton.getAttribute('data-instrument'));
        targetButton.scrollIntoView({ behavior: isInitial ? 'auto' : 'smooth', inline: 'center', block: 'nearest' });
        this._positionTooltipOnThumb();
    }

    _positionTooltipOnThumb() {
        if (!this.scoreTooltip.style.opacity || this.scoreTooltip.style.opacity === "0" || this.isDragging) return;
        const level = parseInt(this.slider.value, 10);
        const sliderWidth = this.slider.offsetWidth;
        const thumbWidth = 20;
        const trackWidth = sliderWidth - thumbWidth;
        const percent = (this.slider.max > this.slider.min) ? (level - this.slider.min) / (this.slider.max - this.slider.min) : 0;
        const handlePosition = (percent * trackWidth) + (thumbWidth / 2);
        this._updateTooltipPosition(handlePosition, this.sortedInstruments[level].charAt(0).toUpperCase() + this.sortedInstruments[level].slice(1));
    }

    _updateTooltipOnHover(event) {
        if (this.isDragging) return;
        const sliderRect = this.slider.getBoundingClientRect();
        const mouseX = event.clientX - sliderRect.left;
        const percent = Math.max(0, Math.min(1, mouseX / this.slider.offsetWidth));
        const hoverIndex = Math.round(percent * (this.numTabs - 1));
        const instrumentName = this.sortedInstruments[hoverIndex];
        this._updateTooltipPosition(mouseX, instrumentName.charAt(0).toUpperCase() + instrumentName.slice(1));
    }

    _updateTooltipPosition(xPosition, text) {
        if (!this.tooltipDesc || !this.tooltipArrow) return;
        this.tooltipDesc.textContent = text;
        const tooltipWidth = this.scoreTooltip.offsetWidth;
        const parentCard = this.sliderContainer.closest('.song-result-card');
        if (!parentCard) return;
        const parentRect = parentCard.getBoundingClientRect();
        const containerRect = this.sliderContainer.getBoundingClientRect();
        let tooltipLeftInContainer = xPosition - (tooltipWidth / 2);
        let absoluteTooltipLeft = containerRect.left + tooltipLeftInContainer;
        if (absoluteTooltipLeft < parentRect.left) absoluteTooltipLeft = parentRect.left;
        if (absoluteTooltipLeft + tooltipWidth > parentRect.right) absoluteTooltipLeft = parentRect.right - tooltipWidth;
        tooltipLeftInContainer = absoluteTooltipLeft - containerRect.left;
        this.scoreTooltip.style.left = `${tooltipLeftInContainer}px`;
        const arrowLeftInTooltip = xPosition - tooltipLeftInContainer;
        this.tooltipArrow.style.left = `${arrowLeftInTooltip}px`;
    }
}

function _createScoreCard(title, result) {
    const abcFiles = result.abc_notation;
    const hasScore = abcFiles && typeof abcFiles === 'object' && Object.keys(abcFiles).length > 0;
    if (!hasScore) return null;

    const card = scoreCardTemplate.content.cloneNode(true);
    card.querySelector('.song-title').textContent = `Score`;
    const textarea = card.querySelector('.result-output');
    const copyBtn = card.querySelector('.copy-btn');
    const copyAllBtn = card.querySelector('.copy-all-btn');
    const viewBtn = card.querySelector('.view-btn');

    const getInstrumentScore = (instrumentName) => {
        const lowerCaseName = instrumentName.toLowerCase();
        if (lowerCaseName === 'mix') return 0;
        if (lowerCaseName.includes('vocals')) return 1;
        if (lowerCaseName === 'bass') return 2;
        if (lowerCaseName === 'drums') return 3;
        if (lowerCaseName === 'other') return 5;
        return 4;
    };

    const sortedInstruments = Object.keys(abcFiles || {}).sort((a, b) => {
        const scoreA = getInstrumentScore(a);
        const scoreB = getInstrumentScore(b);
        if (scoreA !== scoreB) return scoreA - scoreB;
        return a.localeCompare(b);
    });

    if (sortedInstruments.length > 0) {
        new ScoreSlider(card, sortedInstruments, abcFiles, (abcContent, activeInstrument) => {
            textarea.value = abcContent;
            textarea.setAttribute('data-active-instrument', activeInstrument);
        });

        copyBtn.onclick = () => copyToClipboard(textarea, copyBtn);
        copyAllBtn.onclick = () => {
            const allAbcContent = sortedInstruments.map(instrument => abcFiles[instrument] || '').join('\n\n');
            navigator.clipboard.writeText(allAbcContent).then(() => {
                showNotification({ message: "All scores copied to clipboard.", type: 'success', icon: 'library_books', duration: 2000, target: 'toast' });
                showCopyFeedback(copyAllBtn);
            }).catch(() => showNotification({ message: 'Failed to copy all scores.', type: 'error' }));
        };
        viewBtn.onclick = () => {
            const currentInstrument = textarea.getAttribute('data-active-instrument');
            const currentIndex = sortedInstruments.findIndex(inst => (inst.charAt(0).toUpperCase() + inst.slice(1)) === currentInstrument);
            if (currentIndex !== -1) openChartModal(currentIndex, title, 'abc_notation', sortedInstruments, false);
        };
    } else {
        textarea.value = "No instrument scores available.";
        copyBtn.disabled = true;
        copyAllBtn.disabled = true;
        viewBtn.disabled = true;
        const sliderContainer = card.querySelector('.slider-container');
        if (sliderContainer) sliderContainer.style.display = 'none';
    }
    
    return card;
}

function _createChordCard(title, result) {
    const chordData = result.chord_chart;
    const hasChords = chordData && typeof chordData === 'object' && Object.keys(chordData).length > 0;
    if (!hasChords) return null;

    const card = chordChartTemplate.content.cloneNode(true);
    card.querySelector('.song-title').textContent = 'Chords';
    const tabNav = card.querySelector('.tab-nav');
    const textarea = card.querySelector('.result-output');
    const copyBtn = card.querySelector('.copy-btn');
    const viewBtn = card.querySelector('.view-btn');

    const chordOrder = { "Chord Grid": 0, "Detailed Sync (SRT)": 1, "Simple Sync (SRT)": 2 };
    const chordTypes = Object.keys(chordData).sort((a, b) => (chordOrder[a] ?? 99) - (chordOrder[b] ?? 99));
    const tabButtons = [];

    chordTypes.forEach(type => {
        const tabButton = document.createElement('button');
        tabButton.className = 'tab-btn';
        tabButton.textContent = type;
        tabButton.dataset.type = type;
        tabNav.appendChild(tabButton);
        tabButtons.push(tabButton);
    });

    function activateChordTab(index) {
        if (index < 0 || index >= chordTypes.length) return;
        const targetButton = tabButtons[index];
        const chordType = chordTypes[index];
        const chordContent = chordData[chordType];
        tabButtons.forEach(btn => btn.classList.remove('active'));
        targetButton.classList.add('active');
        textarea.value = chordContent;
        textarea.dataset.activeTabTitle = chordType;
    }

    tabButtons.forEach((button, index) => button.addEventListener('click', () => activateChordTab(index)));
    copyBtn.onclick = () => copyToClipboard(textarea, copyBtn);
    if (viewBtn) viewBtn.onclick = () => {
        const activeTabIndex = tabButtons.findIndex(btn => btn.classList.contains('active'));
        openChartModal(activeTabIndex >= 0 ? activeTabIndex : 0, title, 'chord_chart', chordTypes, true);
    };

    activateChordTab(0);
    return card;
}

function _createLyricsCard(title, result) {
    const srtContent = result.lyrics?.generated_lyrics;
    const hasLyrics = srtContent && srtContent.trim().length > 0;
    if (!hasLyrics) return null;

    const card = lyricsCardTemplate.content.cloneNode(true);
    card.querySelector('.song-title').textContent = `Lyrics (SRT)`;
    const cardEl = card.querySelector('.song-result-card');

    const parseSRT = (srtText) => {
        if (!srtText) return [];
        const blocks = srtText.trim().split(/\n\s*\n/);
        const segments = [];
        const timePattern = /(\d{2}):(\d{2}):(\d{2}),(\d{3})/;
        for (const block of blocks) {
            const lines = block.split('\n');
            if (lines.length < 2) continue;
            const timeMatch = lines[1].match(/(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})/);
            if (!timeMatch) continue;
            const parseTime = (timeStr) => {
                const match = timeStr.match(timePattern);
                if (!match) return 0;
                const [, h, m, s, ms] = match.map(Number);
                return h * 3600 + m * 60 + s + ms / 1000;
            };
            segments.push({ start: parseTime(timeMatch[1]), end: parseTime(timeMatch[2]), text: lines.slice(2).join(' ').trim() });
        }
        return segments;
    };
    cardEl.srtData = parseSRT(srtContent);

    const srtTextarea = card.querySelector('.result-output');
    srtTextarea.value = srtContent;
    const srtCopyBtn = card.querySelector('.copy-btn');
    const srtViewBtn = card.querySelector('.view-btn');
    srtCopyBtn.onclick = (e) => copyToClipboard(srtTextarea, srtCopyBtn);
    srtViewBtn.onclick = () => {
        const pre = document.createElement('pre');
        pre.textContent = srtTextarea.value;
        showModal({
            title: `${title} - Lyrics (SRT)`,
            bodyContent: pre,
            footerButtons: [
                { label: 'Copy', icon: 'content_copy', action: () => copyToClipboard(srtTextarea, null), isSuccess: true },
                { label: 'Close', icon: 'close', action: 'close', isPrimary: true }
            ]
        });
    };

    const methodNotice = card.querySelector('.lyrics-method-notice');
    if (methodNotice && result.lyrics_source_method === 'simple_split') methodNotice.style.display = 'flex';

    return card;
}

export function renderResults(resultsData) {
    // A local variable to hold the data for rendering.
    currentResultsData = resultsData;

    // The data from sessionStorage might be unwrapped, while data from a fresh conversion is wrapped.
    // This check normalizes the data structure before rendering.
    if (currentResultsData && !Object.values(currentResultsData).some(val => val && typeof val === 'object' && val.hasOwnProperty('song_profile'))) {
        // This handles the case where unwrapped data is passed from sessionStorage.
        currentResultsData = { "Previous Result": currentResultsData };
    }

    // Initialize modal elements once, the first time results are rendered.
    // This ensures the DOM is ready.
    if (!textViewModal) {
        textViewModal = document.getElementById('text-view-modal');
        textViewTitle = document.getElementById('text-view-title');
        textViewBody = document.getElementById('text-view-body');
    }

    // Clear only the song cards, not the title and notice, which are now static in the HTML.
    const existingCards = resultsContainer.querySelectorAll('.song-result-card');
    existingCards.forEach(card => card.remove());
    
    if (currentResultsData) {
        for (const [title, result] of Object.entries(currentResultsData)) {
            if (result === null) {
                continue;
            }
            const infoCard = _createSongInfoCard(title, result);
            if (infoCard) resultsContainer.appendChild(infoCard);

            const scoreCard = _createScoreCard(title, result);
            if (scoreCard) resultsContainer.appendChild(scoreCard);

            const chordCard = _createChordCard(title, result);
            if (chordCard) resultsContainer.appendChild(chordCard);

            const lyricsCard = _createLyricsCard(title, result);
            if (lyricsCard) resultsContainer.appendChild(lyricsCard);
        }
    }
}

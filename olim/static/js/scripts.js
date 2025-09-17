function update_url(param, value) {
    var base_url = window.location.href.split("?")[0];
    var param_txt = [param, value].join('=');

    if (window.location.href.split("?").length > 1) {
        var params = window.location.href.split("?")[1].split("&");
        var found = false;
        for (i in params) {
            if (params[i].split("=")[0] == param) {
                if (value === undefined)
                    params.splice(i, 1);
                else
                    params[i] = param_txt;
                found = true;
            }
        }
        if (!found)
            if (!(value === undefined))
                params = params.concat([param_txt]);
    } else {
        if ((value === undefined))
            var params = [];
        else
            var params = [param_txt];
    }
    var new_url = [base_url, params.join('&')].join('?');
    history.pushState(null, "", new_url);
}



//// Backend communication functions
// Sends a command to the backend
function run_command(cmd, args) {
    var URL = "/commands?cmd=" + cmd;

    for (i in args) {
        URL = URL + "&" + args[i];
    }

    fetch(URL)
        .then(response => response.json())
        .then((data) => {
            console.log(data);
            if (data.type == 'OK') {
                //M.toast({ html: data.text, displayLength: 2000, classes: 'teal darken-3' });
                if (data.callback) {
                    console.log(data.callback)
                    eval(data.callback);
                }
            }
            else if (data.type == 'silentOK') {
                if (data.callback) {
                    console.log(data.callback)
                    eval(data.callback);
                }
            }
            else {
                M.toast({ html: "ERROR: " + data.text, displayLength: 20000, classes: 'red darken-4' });
                if (data.fail_callback) {
                    eval(data.fail_callback);
                }
            }
        })
}

// Entry page specific functionality
function initEntryPage() {
    // Initialize date pickers if they exist
    initEntryDatePickers();

    // Initialize highlights if highlight data is available
    if (window.highlightData) {
        try {
            if (window.highlightData) {
                initEntryHighlight(window.highlightData);
            }
        } catch (e) {
            console.warn('Highlight initialization failed:', e);
        }
    }

    // Add keyboard shortcuts
    document.addEventListener('keydown', function (e) {
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

        // Arrow keys for queue navigation
        if (e.key === 'ArrowLeft') {
            e.preventDefault();
            navigateEntryQueue(-1);
        } else if (e.key === 'ArrowRight') {
            e.preventDefault();
            navigateEntryQueue(1);
        }

        // Enter to load entry
        if (e.key === 'Enter') {
            e.preventDefault();
            loadEntry();
        }
    });
}

// Date picker initialization for entry page
function initEntryDatePickers() {
    const startDateInput = document.getElementById('start-date');
    const endDateInput = document.getElementById('end-date');

    if (startDateInput) {
        startDateInput.type = 'date';
    }

    if (endDateInput) {
        endDateInput.type = 'date';
    }
}

// Highlight functionality for entry page
function initEntryHighlight(highlightData) {
    if (!highlightData || !Array.isArray(highlightData)) return;

    const container = document.getElementById('highlights-list');
    const input = document.getElementById('highlight-input');

    if (!container || !input) return;

    // Initialize existing highlights
    highlightData.forEach(term => {
        addHighlightChip(term);
        highlightText(term);
    });

    // Handle adding new highlights
    input.addEventListener('keypress', function (e) {
        if (e.key === 'Enter' && this.value.trim()) {
            e.preventDefault();
            const term = this.value.trim();
            addHighlightChip(term);
            highlightText(term);
            updateHighlightSession();
            this.value = '';
        }
    });
}

function addHighlightChip(term) {
    const container = document.getElementById('highlights-list');
    if (!container) return;

    const chip = document.createElement('div');
    chip.className = 'inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-yellow-100 text-yellow-800 border border-yellow-300';
    chip.innerHTML = `
        <span>${escapeHtml(term)}</span>
        <button type="button" onclick="removeHighlight('${escapeHtml(term)}')" class="ml-2 text-yellow-600 hover:text-yellow-800">
            <i class="bi bi-x"></i>
        </button>
    `;
    chip.dataset.term = term;
    container.appendChild(chip);
}

function removeHighlight(term) {
    const container = document.getElementById('highlights-list');
    const chip = container.querySelector(`[data-term="${term}"]`);
    if (chip) {
        chip.remove();
        unhighlightText(term);
        updateHighlightSession();
    }
}

function highlightText(term) {
    const contentArea = document.querySelector('.prose');
    if (!contentArea || !term) return;

    const regex = new RegExp(`(${escapeRegExp(term)})`, 'gi');
    const walker = document.createTreeWalker(
        contentArea,
        NodeFilter.SHOW_TEXT,
        null,
        false
    );

    const textNodes = [];
    let node;
    while (node = walker.nextNode()) {
        if (regex.test(node.textContent)) {
            textNodes.push(node);
        }
    }

    textNodes.forEach(textNode => {
        const parent = textNode.parentNode;
        if (parent.tagName !== 'MARK') {
            const highlightedHTML = textNode.textContent.replace(regex, '<mark class="bg-yellow-300 text-yellow-900 px-1 rounded">$1</mark>');
            const temp = document.createElement('div');
            temp.innerHTML = highlightedHTML;

            while (temp.firstChild) {
                parent.insertBefore(temp.firstChild, textNode);
            }
            parent.removeChild(textNode);
        }
    });
}

function unhighlightText(term) {
    const contentArea = document.querySelector('.prose');
    if (!contentArea) return;

    const highlights = contentArea.querySelectorAll('mark');
    highlights.forEach(mark => {
        if (mark.textContent.toLowerCase().includes(term.toLowerCase())) {
            const parent = mark.parentNode;
            parent.replaceChild(document.createTextNode(mark.textContent), mark);
            parent.normalize();
        }
    });
}

function updateHighlightSession() {
    const chips = document.querySelectorAll('#highlights-list [data-term]');
    const data = Array.from(chips).map(chip => chip.dataset.term);

    // Send update to server
    fetch('/update-session', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            parameter: 'highlight',
            data: data
        })
    }).catch(console.error);
}

// Entry navigation functions
function loadEntry() {
    const entryId = document.getElementById('id').value;
    const datasetSelect = document.getElementById('dataset_id');

    if (!entryId) {
        showNotification(window.translations?.pleaseEnterEntryId || 'Please enter an entry ID', 'warning');
        return;
    }

    let url = `/${window.projectId}/entry`;
    if (datasetSelect) {
        url += `/${datasetSelect.value}/${encodeURIComponent(entryId)}`;
    } else if (window.defaultDatasetId) {
        url += `/${window.defaultDatasetId}/${encodeURIComponent(entryId)}`;
    }

    window.location.href = url;
}

function navigateEntryQueue(direction) {
    if (window.queueId && window.queuePos && window.queueLen) {
        const newPos = window.queuePos + direction;
        if (newPos >= 1 && newPos <= window.queueLen) {
            window.location.href = `/${window.projectId}/queue/${window.queueId}/${newPos}`;
        }
    }
}

// Label management functions
function applyToAll(labelStr, apply) {
    const selector = apply ? `[id^="${labelStr.replace(' ', '_')}_sel_"]:not(.hidden)` : `[id^="${labelStr.replace(' ', '_')}_unsel_"]:not(.hidden)`;
    const buttons = document.querySelectorAll(selector);

    buttons.forEach(button => {
        if (button.style.display !== 'none') {
            button.click();
        }
    });
}

function toggleHidden(show) {
    const hiddenEntries = document.querySelectorAll('.hidden-entry');
    const showBtn = document.getElementById('show_hidden_btn');
    const hideBtn = document.getElementById('hide_hidden_btn');

    hiddenEntries.forEach(entry => {
        entry.style.display = show ? 'block' : 'none';
    });

    if (show) {
        showBtn.classList.add('hidden');
        hideBtn.classList.remove('hidden');
        update_url('show-hidden', 'True');
    } else {
        showBtn.classList.remove('hidden');
        hideBtn.classList.add('hidden');
        update_url('show-hidden', 'False');
    }
}

function expandAll(expand) {
    const buttons = document.querySelectorAll(expand ? '.btn-expand:not(.hidden)' : '.btn-retract:not(.hidden)');
    buttons.forEach(button => {
        if (button.style.display !== 'none') {
            button.click();
        }
    });
}

function retractAll() {
    expandAll(false);
}

// Entry-specific label management functions
function addEntryLabel(entryId, labelId, value) {
    run_command('add-label', [
        'entry_id=' + entryId,
        'label_id=' + labelId,
        'value=' + value,
        'callback=markLabel("' + labelId + '", "' + value + '");'
    ]);
}

function hideLabel(label, labelId) {
    run_command('manage-label', [
        'label=' + label,
        'label_id=' + labelId,
        'mode=add',
        'callback=hideById("' + labelId + '");'
    ]);
}

function unhideLabel(label, labelId) {
    run_command('manage-label', [
        'label=' + label,
        'label_id=' + labelId,
        'mode=remove',
        'callback=unhideById("' + labelId + '");'
    ]);
}

function hideById(id) {
    const hiddenSelBtn = document.getElementById('hidden_sel_btn');
    if (!hiddenSelBtn || !hiddenSelBtn.style.visibility === 'visible') {
        const labelElement = document.getElementById('label_' + id);
        if (labelElement) {
            labelElement.style.display = 'none';
        }
    }
    const labelElement = document.getElementById('label_' + id);
    if (labelElement) {
        labelElement.classList.add('hidden-entry');
    }
    const hideSelElement = document.getElementById('hide_sel_' + id);
    if (hideSelElement) {
        hideSelElement.classList.remove('hidden');
    }
    const hideElement = document.getElementById('hide_' + id);
    if (hideElement) {
        hideElement.classList.add('hidden');
    }
}

function unhideById(id) {
    const labelElement = document.getElementById('label_' + id);
    if (labelElement) {
        labelElement.classList.remove('hidden-entry');
    }
    const hideSelElement = document.getElementById('hide_sel_' + id);
    if (hideSelElement) {
        hideSelElement.classList.add('hidden');
    }
    const hideElement = document.getElementById('hide_' + id);
    if (hideElement) {
        hideElement.classList.remove('hidden');
    }
}

function markLabel(labelId, value) {
    // Unselect all first
    const LABELS = window.LABELS || ['YES', 'NO', 'MAYBE'];
    LABELS.forEach(label => {
        const unselElement = document.getElementById(label + '_unsel_' + labelId);
        const selElement = document.getElementById(label + '_sel_' + labelId);
        if (unselElement) unselElement.classList.add('hidden');
        if (selElement) selElement.classList.remove('hidden');
    });

    // Select back according to value
    value = value.replace(' ', '_');
    const unselElement = document.getElementById(value + '_unsel_' + labelId);
    const selElement = document.getElementById(value + '_sel_' + labelId);
    if (unselElement) unselElement.classList.remove('hidden');
    if (selElement) selElement.classList.add('hidden');
}

// Utility functions
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function escapeRegExp(string) {
    return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    const colors = {
        success: 'bg-green-100 border-green-500 text-green-700',
        error: 'bg-red-100 border-red-500 text-red-700',
        info: 'bg-blue-100 border-blue-500 text-blue-700',
        warning: 'bg-yellow-100 border-yellow-500 text-yellow-700'
    };

    notification.className = `fixed top-4 right-4 px-4 py-3 border-l-4 rounded shadow-lg ${colors[type] || colors.info} transform transition-all duration-300 translate-x-full opacity-0 z-50`;
    notification.innerHTML = `
        <div class="flex items-center">
            <i class="bi bi-info-circle mr-2"></i>
            <span class="text-sm font-medium">${message}</span>
            <button onclick="this.parentElement.parentElement.remove()" class="ml-2 text-current hover:text-gray-600">
                <i class="bi bi-x-lg"></i>
            </button>
        </div>
    `;

    document.body.appendChild(notification);

    setTimeout(() => {
        notification.classList.remove('translate-x-full', 'opacity-0');
    }, 100);

    setTimeout(() => {
        if (notification.parentElement) {
            notification.classList.add('translate-x-full', 'opacity-0');
            setTimeout(() => {
                if (notification.parentElement) {
                    notification.remove();
                }
            }, 300);
        }
    }, 4000);
}

// Hidden page specific functionality
let currentAction = null;
let currentTextId = null;

function initHiddenPage() {
    // Add keyboard shortcuts
    document.addEventListener('keydown', function(e) {
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

        // Escape to close modal
        if (e.key === 'Escape') {
            closeConfirmModal();
        }
    });
}

// Remove individual hidden entry
function removeFromHidden(textId) {
    currentAction = 'single';
    currentTextId = textId;

    const modalMessage = window.translations?.confirmRemoveSingle || 'Are you sure you want to remove this entry from hidden entries?';
    document.getElementById('modal-message').textContent = modalMessage;
    document.getElementById('confirmModal').classList.remove('hidden');
}

// Remove all hidden entries
function removeAllHidden() {
    currentAction = 'all';
    currentTextId = null;

    const modalMessage = window.translations?.confirmRemoveAll || 'Are you sure you want to remove ALL entries from hidden entries? This action cannot be undone.';
    document.getElementById('modal-message').textContent = modalMessage;
    document.getElementById('confirmModal').classList.remove('hidden');
}

// Execute the confirmed action
function executeAction() {
    if (currentAction === 'single' && currentTextId) {
        // Call backend to remove single entry
        run_command('remove-hidden', [
            'text_id=' + currentTextId,
            'callback=removeEntryFromDOM("text_' + currentTextId + '");'
        ]);
    } else if (currentAction === 'all') {
        // Call backend to remove all entries
        run_command('remove-all-hidden', [
            'callback=reloadPage();'
        ]);
    }

    closeConfirmModal();
}

// Close confirmation modal
function closeConfirmModal() {
    document.getElementById('confirmModal').classList.add('hidden');
    currentAction = null;
    currentTextId = null;
}

// Toggle full text display
function toggleFullText(textId, buttonElement) {
    const fullTextDiv = document.getElementById('full-text-' + textId);
    const button = buttonElement || event.target;

    if (fullTextDiv.classList.contains('hidden')) {
        fullTextDiv.classList.remove('hidden');
        button.textContent = window.translations?.showLess || 'Show less...';
    } else {
        fullTextDiv.classList.add('hidden');
        button.textContent = window.translations?.showMore || 'Show more...';
    }
}

// View entry details (placeholder for future implementation)
function viewEntryDetails(textId) {
    console.log('Viewing entry details for:', textId);
    const message = window.translations?.entryDetailsComingSoon || 'Entry details view coming soon!';
    showNotification(message, 'info');
    // In the future, this could open a modal or navigate to entry details
}

// DOM manipulation callbacks
function removeEntryFromDOM(elementId) {
    const element = document.getElementById(elementId);
    if (element) {
        element.style.transition = 'all 0.3s ease-out';
        element.style.transform = 'translateX(100%)';
        element.style.opacity = '0';

        setTimeout(() => {
            element.remove();
            checkEmptyState();
        }, 300);

        const message = window.translations?.entryRemovedSuccess || 'Entry removed successfully!';
        showNotification(message, 'success');
    }
}

function reloadPage() {
    const message = window.translations?.allEntriesRemovedSuccess || 'All entries removed successfully!';
    showNotification(message, 'success');
    setTimeout(() => {
        window.location.reload();
    }, 1000);
}

// Check if we need to show empty state
function checkEmptyState() {
    const entries = document.querySelectorAll('[id^="text_"]');
    if (entries.length === 0) {
        setTimeout(() => {
            window.location.reload();
        }, 500);
    }
}

// Search page specific functionality
class ChipManager {
    constructor(containerId, inputId, fieldId, color = 'blue') {
        this.container = document.getElementById(`${containerId}-chips`);
        this.input = document.getElementById(`${inputId}-input`);
        this.field = document.getElementById(fieldId);
        this.color = color;
        this.chips = [];

        this.init();
    }

    init() {
        // Initialize with existing data if any
        const existingData = this.field.value ? JSON.parse(this.field.value) : [];
        existingData.forEach(text => this.addChip(text, false));

        // Set up event listeners
        this.input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ',') {
                e.preventDefault();
                this.addChipFromInput();
            }
        });

        this.input.addEventListener('blur', () => {
            this.addChipFromInput();
        });

        // Update field on initialization
        this.updateField();
    }

    addChipFromInput() {
        const text = this.input.value.trim();
        if (text && !this.chips.includes(text)) {
            this.addChip(text);
            this.input.value = '';
            this.input.focus();
        }
    }

    addChip(text, updateField = true) {
        if (!text || this.chips.includes(text)) return;

        this.chips.push(text);

        const chip = document.createElement('div');
        chip.className = `inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-${this.color}-100 text-${this.color}-800 border border-${this.color}-200`;
        chip.innerHTML = `
            <span>${text}</span>
            <button type="button" class="ml-2 text-${this.color}-600 hover:text-${this.color}-800 focus:outline-none" onclick="this.parentElement.remove(); window.chipManagers.get('${this.container.id.replace('-chips', '')}').removeChip('${text}')">
                <i class="bi bi-x text-sm"></i>
            </button>
        `;

        this.container.appendChild(chip);

        if (updateField) {
            this.updateField();
        }
    }

    removeChip(text) {
        const index = this.chips.indexOf(text);
        if (index > -1) {
            this.chips.splice(index, 1);
            this.updateField();
        }
    }

    updateField() {
        this.field.value = JSON.stringify(this.chips);
    }
}

function initSearchPage() {
    // Global chip managers registry
    window.chipManagers = new Map();

    // Initialize chip managers
    const includeManager = new ChipManager('include', 'include', 'include_field', 'green');
    const excludeManager = new ChipManager('exclude', 'exclude', 'exclude_field', 'red');

    window.chipManagers.set('include', includeManager);
    window.chipManagers.set('exclude', excludeManager);

    // Parse URL parameters to restore form state
    const urlParams = new URLSearchParams(window.location.search);

    // Restore number field from URL
    const numberParam = urlParams.get('number');
    if (numberParam) {
        document.getElementById('number').value = numberParam;
    }

    // Restore include terms from URL first, then fallback to backend data
    let includeTerms = [];
    try {
        const includeParam = urlParams.get('include');
        if (includeParam) {
            // Parse from URL parameter
            includeTerms = JSON.parse(decodeURIComponent(includeParam));
        } else {
            // Fallback to backend data - handle the {"tag": "value"} format
            const includeDataRaw = window.searchData?.include;
            if (includeDataRaw && Array.isArray(includeDataRaw)) {
                includeTerms = includeDataRaw.map(item => {
                    if (typeof item === 'object' && item.tag) {
                        return item.tag;
                    }
                    return item;
                }).filter(Boolean);
            }
        }
        if (Array.isArray(includeTerms)) {
            includeTerms.forEach(term => includeManager.addChip(term, false));
        }
    } catch(e) {
        console.warn('Failed to parse include data:', e);
    }

    // Restore exclude terms from URL first, then fallback to backend data
    let excludeTerms = [];
    try {
        const excludeParam = urlParams.get('exclude');
        if (excludeParam) {
            // Parse from URL parameter
            excludeTerms = JSON.parse(decodeURIComponent(excludeParam));
        } else {
            // Fallback to backend data - handle the {"tag": "value"} format
            const excludeDataRaw = window.searchData?.exclude;
            if (excludeDataRaw && Array.isArray(excludeDataRaw)) {
                excludeTerms = excludeDataRaw.map(item => {
                    if (typeof item === 'object' && item.tag) {
                        return item.tag;
                    }
                    return item;
                }).filter(Boolean);
            }
        }
        if (Array.isArray(excludeTerms)) {
            excludeTerms.forEach(term => excludeManager.addChip(term, false));
        }
    } catch(e) {
        console.warn('Failed to parse exclude data:', e);
    }

    // Form submission handler
    const form = document.getElementById('form');
    if (form) {
        form.addEventListener('submit', function(e) {
            includeManager.updateField();
            excludeManager.updateField();
        });
    }

    // Initialize highlighting if data exists
    try {
        const highlightDataRaw = window.searchData?.highlight;
        if (highlightDataRaw && Array.isArray(highlightDataRaw)) {
            initSearchHighlight(highlightDataRaw);
        }
    } catch(e) {
        console.warn('Highlight initialization failed:', e);
    }

    // Form validation
    const numberInput = document.getElementById('number');
    if (numberInput) {
        numberInput.addEventListener('input', function() {
            // Only allow numbers
            this.value = this.value.replace(/[^0-9]/g, '');
        });
    }

    // Keyboard shortcuts
    document.addEventListener('keydown', function(e) {
        // Don't trigger shortcuts when typing in input fields
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

        // Press 's' to focus search
        if (e.key === 's' || e.key === 'S') {
            e.preventDefault();
            const includeInput = document.getElementById('include-input');
            if (includeInput) includeInput.focus();
        }

        // Press 'Enter' on form to submit
        if (e.key === 'Enter' && e.ctrlKey) {
            e.preventDefault();
            if (form) form.submit();
        }
    });

    // Auto-focus first input
    const includeInput = document.getElementById('include-input');
    if (includeInput) includeInput.focus();
}

// Custom highlight function for search (replaces jQuery highlight)
function initSearchHighlight(highlightData) {
    if (!highlightData || !Array.isArray(highlightData)) return;

    const contentAreas = document.querySelectorAll('.prose, .search-content');

    highlightData.forEach(term => {
        contentAreas.forEach(area => {
            highlightSearchText(area, term, 'search-highlight');
        });
    });
}

function highlightSearchText(element, searchText, className = 'highlight') {
    if (!searchText || !element) return;

    const walker = document.createTreeWalker(
        element,
        NodeFilter.SHOW_TEXT,
        null,
        false
    );

    const textNodes = [];
    let node;

    while (node = walker.nextNode()) {
        textNodes.push(node);
    }

    textNodes.forEach(textNode => {
        const parent = textNode.parentNode;
        const text = textNode.textContent;
        const regex = new RegExp(`(${searchText.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');

        if (regex.test(text)) {
            const highlightedHTML = text.replace(regex, `<mark class="${className}">$1</mark>`);
            const temp = document.createElement('div');
            temp.innerHTML = highlightedHTML;

            while (temp.firstChild) {
                parent.insertBefore(temp.firstChild, textNode);
            }
            parent.removeChild(textNode);
        }
    });
}

// AL Entry page specific functionality
function initAlEntryPage() {
    // Initialize highlighting functionality
    if (window.alEntryData?.highlight) {
        try {
            init_highlight(window.alEntryData.highlight);
        } catch(e) {
            console.warn('Highlight initialization failed:', e);
        }
    }

    // Add keyboard shortcuts for quick labeling
    document.addEventListener('keydown', function(e) {
        // Only trigger shortcuts when not in an input field
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

        const labelForms = document.querySelectorAll('[id^="label_form_"]');

        // Number keys 1-9 for quick label selection
        if (e.key >= '1' && e.key <= '9') {
            const index = parseInt(e.key);
            if (labelForms[index - 1]) {
                e.preventDefault();
                labelForms[index - 1].submit();
            }
        }

        // 'r' key for refresh
        if (e.key === 'r' || e.key === 'R') {
            e.preventDefault();
            location.reload();
        }

        // Escape key to go back
        if (e.key === 'Escape') {
            e.preventDefault();
            window.history.back();
        }

        // '?' key to show help
        if (e.key === '?' || (e.shiftKey && e.key === '/')) {
            e.preventDefault();
            toggleShortcutsModal();
        }
    });

    // Add visual feedback when hovering over content
    const contentArea = document.querySelector('.prose');
    if (contentArea) {
        contentArea.addEventListener('mouseenter', function() {
            this.style.backgroundColor = '#f8fafc';
        });
        contentArea.addEventListener('mouseleave', function() {
            this.style.backgroundColor = '';
        });
    }

    // Smooth scroll to top when content is long
    const scrollToTopBtn = document.createElement('button');
    scrollToTopBtn.innerHTML = '<i class="bi bi-arrow-up"></i>';
    scrollToTopBtn.className = 'fixed bottom-4 right-4 w-12 h-12 bg-cyan-600 text-white rounded-full shadow-lg hover:bg-cyan-700 focus:outline-none focus:ring-4 focus:ring-cyan-300 transition-all opacity-0 pointer-events-none';
    scrollToTopBtn.style.zIndex = '1000';
    scrollToTopBtn.title = window.translations?.scrollToTop || 'Scroll to top';
    document.body.appendChild(scrollToTopBtn);

    window.addEventListener('scroll', function() {
        if (window.scrollY > 300) {
            scrollToTopBtn.style.opacity = '1';
            scrollToTopBtn.style.pointerEvents = 'auto';
        } else {
            scrollToTopBtn.style.opacity = '0';
            scrollToTopBtn.style.pointerEvents = 'none';
        }
    });

    scrollToTopBtn.addEventListener('click', function() {
        window.scrollTo({ top: 0, behavior: 'smooth' });
    });

    // Auto-hide status messages after clicking
    const statusMessages = document.querySelector('.status-messages');
    if (statusMessages) {
        statusMessages.addEventListener('click', function() {
            this.style.transition = 'all 0.3s ease-out';
            this.style.transform = 'translateY(-10px)';
            this.style.opacity = '0';
            setTimeout(() => {
                this.style.display = 'none';
            }, 300);
        });
    }
}

// Initialize highlighting function (compatibility with existing code)
function init_highlight(highlightData) {
    if (!highlightData) return;

    try {
        // Show highlights section if there's highlight data
        const highlightsSection = document.getElementById('highlights');
        if (highlightsSection && highlightData) {
            highlightsSection.classList.remove('hidden');
            // Add highlight functionality here based on your existing implementation
        }
    } catch(e) {
        console.warn('Highlight display failed:', e);
    }
}

// Shortcuts modal functions
function toggleShortcutsModal() {
    const modal = document.getElementById('shortcutsModal');
    if (modal) {
        modal.classList.toggle('hidden');
    }
}

function closeShortcutsModal() {
    const modal = document.getElementById('shortcutsModal');
    if (modal) {
        modal.classList.add('hidden');
    }
}

// Projects page specific functionality
let deleteUrl = '';

function initProjectsPage() {
    // Set up delete confirmation handlers
    const confirmDeleteBtn = document.getElementById('confirmDeleteBtn');
    const deleteModal = document.getElementById('deleteModal');

    if (confirmDeleteBtn) {
        confirmDeleteBtn.addEventListener('click', function() {
            if (deleteUrl) {
                window.location.href = deleteUrl;
            }
        });
    }

    // Close modal when clicking outside
    if (deleteModal) {
        deleteModal.addEventListener('click', function(e) {
            if (e.target === this) {
                closeDeleteModal();
            }
        });
    }
}

function confirmDelete(projectName, url) {
    deleteUrl = url;
    const deleteMessage = document.getElementById('deleteMessage');
    if (deleteMessage) {
        const message = (window.translations?.confirmDeleteProject || 'Are you sure you want to delete project') +
                       ' "' + projectName + '"? ' +
                       (window.translations?.cannotBeUndone || 'This action cannot be undone.');
        deleteMessage.textContent = message;
    }

    const deleteModal = document.getElementById('deleteModal');
    if (deleteModal) {
        deleteModal.classList.remove('hidden');
    }
}

function closeDeleteModal() {
    const deleteModal = document.getElementById('deleteModal');
    if (deleteModal) {
        deleteModal.classList.add('hidden');
    }
    deleteUrl = '';
}

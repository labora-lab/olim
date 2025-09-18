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
            if (data.type == 'OK') {
                if (data.text && data.text.trim()) {
                    showToast(data.text, 'success', 2000);
                }
                if (data.callback) {
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
                showToast("ERROR: " + data.text, 'error', 20000);
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

// Entry highlighting is now handled by macros/highlights.html macro

// Mobile sidebar functionality
function initMobileSidebar() {
    const sidebarToggle = document.getElementById('sidebar-toggle');
    const sidebar = document.getElementById('sidebar');
    const backdrop = document.getElementById('sidebar-backdrop');

    if (sidebarToggle && sidebar && backdrop) {
        // Toggle sidebar on mobile
        sidebarToggle.addEventListener('click', function() {
            const isHidden = sidebar.classList.contains('-translate-x-full');

            if (isHidden) {
                // Show sidebar
                sidebar.classList.remove('-translate-x-full');
                sidebar.classList.add('translate-x-0');
                backdrop.classList.remove('hidden');
            } else {
                // Hide sidebar
                sidebar.classList.add('-translate-x-full');
                sidebar.classList.remove('translate-x-0');
                backdrop.classList.add('hidden');
            }
        });

        // Hide sidebar when clicking backdrop
        backdrop.addEventListener('click', function() {
            sidebar.classList.add('-translate-x-full');
            sidebar.classList.remove('translate-x-0');
            backdrop.classList.add('hidden');
        });

        // Hide sidebar on window resize to desktop size
        window.addEventListener('resize', function() {
            if (window.innerWidth >= 640) { // sm breakpoint
                sidebar.classList.remove('-translate-x-full');
                sidebar.classList.add('translate-x-0');
                backdrop.classList.add('hidden');
            } else {
                // Reset to hidden state on mobile
                if (!sidebar.classList.contains('-translate-x-full')) {
                    sidebar.classList.add('-translate-x-full');
                    sidebar.classList.remove('translate-x-0');
                    backdrop.classList.add('hidden');
                }
            }
        });
    }
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
        // Check if the button and its label container are actually visible to the user
        const labelContainer = button.closest('[id^="label_"]');

        // Check if the label container is visible (considering both display and visibility)
        const isContainerVisible = labelContainer &&
            labelContainer.offsetWidth > 0 &&
            labelContainer.offsetHeight > 0 &&
            window.getComputedStyle(labelContainer).display !== 'none' &&
            window.getComputedStyle(labelContainer).visibility !== 'hidden';

        // Check if the button itself is visible
        const isButtonVisible = button.style.display !== 'none' &&
            window.getComputedStyle(button).display !== 'none' &&
            button.offsetWidth > 0 &&
            button.offsetHeight > 0;

        // Only click if both button and container are actually visible
        if (isButtonVisible && isContainerVisible) {
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
    const unhideElement = document.getElementById('unhide_btn_' + id);
    if (unhideElement) {
        unhideElement.classList.remove('hidden');
    }
    const hideElement = document.getElementById('hide_btn_' + id);
    if (hideElement) {
        hideElement.classList.add('hidden');
    }
}

function unhideById(id) {
    const labelElement = document.getElementById('label_' + id);
    if (labelElement) {
        labelElement.classList.remove('hidden-entry');
    }
    const unhideElement = document.getElementById('unhide_btn_' + id);
    if (unhideElement) {
        unhideElement.classList.add('hidden');
    }
    const hideElement = document.getElementById('hide_btn_' + id);
    if (hideElement) {
        hideElement.classList.remove('hidden');
    }
}

function markLabel(labelId, value) {
    // Find all buttons for this label by looking in the label container
    const labelContainer = document.getElementById('label_' + labelId);
    if (!labelContainer) {
        return;
    }

    // Find all unsel and sel buttons for this label - exclude apply-all buttons
    const unselButtons = labelContainer.querySelectorAll('[id$="_unsel_' + labelId + '"]:not(.apply-all-btn)');
    const selButtons = labelContainer.querySelectorAll('[id$="_sel_' + labelId + '"]:not(.apply-all-btn)');

    // Unselect all first (hide selected buttons, show unselected buttons)
    unselButtons.forEach(btn => btn.classList.add('hidden'));
    selButtons.forEach(btn => btn.classList.remove('hidden'));

    // If value is not empty, select the specific value
    if (value && value.trim() !== '') {
        const valueKey = value.replace(' ', '_');
        const unselElement = document.getElementById(valueKey + '_unsel_' + labelId);
        const selElement = document.getElementById(valueKey + '_sel_' + labelId);

        if (unselElement) unselElement.classList.remove('hidden');
        if (selElement) selElement.classList.add('hidden');
    }
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

// =============================================================================
// BASE LAYOUT FUNCTIONALITY (moved from scripts.html)
// =============================================================================

// Sidebar functionality
function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    const collapseBtn = document.getElementById('collapse-btn');
    const collapseIcon = collapseBtn.querySelector('.collapse-icon');
    const mainContent = document.getElementById('main-content');

    sidebar.classList.toggle('w-64');
    sidebar.classList.toggle('w-16');
    sidebar.classList.toggle('sidebar-collapsed');

    // Ajusta a margem do conteúdo principal
    if (sidebar.classList.contains('sidebar-collapsed')) {
        mainContent.classList.remove('sm:ml-64');
        mainContent.classList.add('sm:ml-16');
    } else {
        mainContent.classList.remove('sm:ml-16');
        mainContent.classList.add('sm:ml-64');
    }

    // Alterna o ícone
    if (sidebar.classList.contains('sidebar-collapsed')) {
        collapseIcon.classList.remove('bi-chevron-bar-left');
        collapseIcon.classList.add('bi-chevron-bar-right');
    } else {
        collapseIcon.classList.remove('bi-chevron-bar-right');
        collapseIcon.classList.add('bi-chevron-bar-left');
    }

    // Salva o estado no localStorage
    localStorage.setItem('sidebarCollapsed', sidebar.classList.contains('sidebar-collapsed'));
}

function expandSidebar() {
    const sidebar = document.getElementById('sidebar');
    const collapseBtn = document.getElementById('collapse-btn');
    const collapseIcon = collapseBtn?.querySelector('.collapse-icon');
    const mainContent = document.getElementById('main-content');

    sidebar.classList.remove('sidebar-collapsed', 'w-16');
    sidebar.classList.add('w-64');

    // Ajusta a margem do conteúdo principal
    if (mainContent) {
        mainContent.classList.remove('sm:ml-16');
        mainContent.classList.add('sm:ml-64');
    }

    if (collapseIcon) {
        collapseIcon.classList.remove('bi-chevron-bar-right');
        collapseIcon.classList.add('bi-chevron-bar-left');
    }

    localStorage.setItem('sidebarCollapsed', 'false');
}

// Function to update task counter
function updateTaskCounter() {
    const taskList = document.getElementById('task-list');
    const taskCounterButton = document.querySelector('.task-counter-collapsed button');
    const taskCounterContainer = document.querySelector('.task-counter-collapsed .relative');
    const sidebar = document.getElementById('sidebar');

    if (taskList && taskCounterButton && taskCounterContainer) {
        const runningCount = parseInt(taskList.querySelector('[data-running-count]')?.getAttribute('data-running-count') || '0');
        const isCollapsed = sidebar.classList.contains('sidebar-collapsed');

        // Remove existing badge
        const existingBadge = taskCounterContainer.querySelector('.absolute');
        if (existingBadge) {
            existingBadge.remove();
        }

        // Update colors and badge based on running jobs count
        if (runningCount > 0) {
            // With running jobs - blue background and show badge
            taskCounterButton.className = taskCounterButton.className
                .replace(/bg-gray-\d+/g, 'bg-blue-600')
                .replace(/hover:bg-gray-\d+/g, 'hover:bg-blue-700');

            // Create new badge
            const badge = document.createElement('div');
            badge.className = 'absolute -top-2 -right-2 inline-flex items-center justify-center w-6 h-6 text-xs font-bold text-white bg-red-500 border-2 border-gray-800 rounded-full';
            badge.textContent = runningCount;
            taskCounterContainer.appendChild(badge);
        } else {
            // No running jobs - gray background and no badge
            taskCounterButton.className = taskCounterButton.className
                .replace(/bg-blue-\d+/g, 'bg-gray-700')
                .replace(/hover:bg-blue-\d+/g, 'hover:bg-gray-600');
        }
    }
}

// Toast notification system (replaces M.toast)
function showToast(message, type = 'success', duration = 3000) {
    // Get or create toast container
    let container = document.querySelector('.fixed.top-20');
    if (!container) {
        container = document.createElement('div');
        container.className = 'fixed top-20 sm:top-4 right-4 z-50 w-96 space-y-2';
        document.body.appendChild(container);
    }

    // Create toast element
    const toast = document.createElement('div');
    const toastId = 'toast-' + Date.now();
    toast.id = toastId;

    const styles = {
        success: {
            classes: 'text-green-800 border-green-300 bg-green-50',
            icon: 'bi-check-circle-fill',
            buttonClasses: 'bg-green-50 text-green-500 hover:bg-green-200 focus:ring-green-400'
        },
        error: {
            classes: 'text-red-800 border-red-300 bg-red-50',
            icon: 'bi-exclamation-circle-fill',
            buttonClasses: 'bg-red-50 text-red-500 hover:bg-red-200 focus:ring-red-400'
        },
        warning: {
            classes: 'text-yellow-800 border-yellow-300 bg-yellow-50',
            icon: 'bi-exclamation-triangle-fill',
            buttonClasses: 'bg-yellow-50 text-yellow-500 hover:bg-yellow-200 focus:ring-yellow-400'
        },
        info: {
            classes: 'text-blue-800 border-blue-300 bg-blue-50',
            icon: 'bi-info-circle-fill',
            buttonClasses: 'bg-blue-50 text-blue-500 hover:bg-blue-200 focus:ring-blue-400'
        }
    };

    const style = styles[type] || styles.success;

    toast.className = `flex items-center p-4 mb-4 text-sm border rounded-lg ${style.classes} opacity-0 transition-opacity duration-300`;
    toast.setAttribute('role', 'alert');
    toast.innerHTML = `
        <i class="bi ${style.icon} flex-shrink-0 inline w-4 h-4 me-3"></i>
        <div class="flex-1">
            <p class="mb-0">${message}</p>
        </div>
        <button type="button" onclick="
            this.parentElement.style.opacity = '0';
            this.parentElement.style.transition = 'opacity 0.3s ease-out';
            setTimeout(() => this.parentElement.remove(), 300);
        "
            class="ms-auto -mx-1.5 -my-1.5 rounded-lg focus:ring-2 p-1.5 inline-flex items-center justify-center h-8 w-8 ${style.buttonClasses}"
            aria-label="Close">
            <span class="sr-only">Close</span>
            <i class="bi bi-x text-lg"></i>
        </button>
    `;

    container.appendChild(toast);

    // Fade in
    setTimeout(() => {
        toast.style.opacity = '1';
    }, 10);

    // Auto remove after duration
    if (duration > 0) {
        setTimeout(() => {
            if (toast.parentNode) {
                toast.style.opacity = '0';
                toast.style.transition = 'opacity 0.3s ease-out';
                setTimeout(() => toast.remove(), 300);
            }
        }, duration);
    }
}

// LaTeX rendering with KaTeX
function loadKaTeXIfNeeded() {
    const content = document.querySelectorAll('.latex-content');
    let hasLatex = false;

    content.forEach(el => {
        if (el.textContent.includes('$$') || el.textContent.includes('\\(')) {
            hasLatex = true;
        }
    });

    if (hasLatex) {
        // Load KaTeX CSS
        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = 'https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css';
        document.head.appendChild(link);

        // Load KaTeX JS
        const script = document.createElement('script');
        script.src = 'https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js';
        script.onload = () => renderLatex();
        document.head.appendChild(script);
    }
}

function renderLatex() {
    document.querySelectorAll('.latex-content').forEach(el => {
        let html = el.textContent;

        // Replace $$ display math
        html = html.replace(/\$\$(.*?)\$\$/g, (match, formula) => {
            try {
                return katex.renderToString(formula, {displayMode: true});
            } catch (e) {
                return match; // fallback to original text
            }
        });

        // Replace \( \) inline math
        html = html.replace(/\\\((.*?)\\\)/g, (match, formula) => {
            try {
                return katex.renderToString(formula, {displayMode: false});
            } catch (e) {
                return match; // fallback to original text
            }
        });

        el.innerHTML = html;
    });
}

// Error modal functions (without translations - those stay in template)
function showErrorModalFromData(element) {
    const taskName = element.getAttribute('data-task-name');
    const errorText = element.getAttribute('data-error-text');
    showErrorModal(taskName, errorText);
}

function showErrorModal(taskName, errorText) {
    // Parse error text to separate user message from technical details
    const { userMessage, technicalDetails } = parseErrorMessage(errorText);

    // Set task name
    document.getElementById('modalTaskName').textContent = taskName;

    // Set user-friendly error message
    document.getElementById('modalErrorMessage').textContent = userMessage;

    // Handle technical details
    const technicalSection = document.getElementById('technicalDetailsSection');
    const technicalContent = document.getElementById('modalTechnicalDetails');

    if (technicalDetails && technicalDetails.trim()) {
        technicalContent.textContent = technicalDetails;
        technicalSection.classList.remove('hidden');
    } else {
        technicalSection.classList.add('hidden');
    }

    // Reset technical details to collapsed state
    document.getElementById('technicalDetailsContent').classList.add('hidden');
    document.getElementById('technicalChevron').classList.remove('rotate-180');
    if (typeof updateToggleButtonText === 'function') {
        updateToggleButtonText(false);
    }

    // Show modal
    document.getElementById('errorModal').classList.remove('hidden');

    // Prevent body scroll
    document.body.style.overflow = 'hidden';
}

function closeErrorModal() {
    document.getElementById('errorModal').classList.add('hidden');
    document.body.style.overflow = '';
}

function toggleTechnicalDetails() {
    const content = document.getElementById('technicalDetailsContent');
    const chevron = document.getElementById('technicalChevron');

    if (content.classList.contains('hidden')) {
        content.classList.remove('hidden');
        chevron.classList.add('rotate-180');
        if (typeof updateToggleButtonText === 'function') {
            updateToggleButtonText(true);
        }
    } else {
        content.classList.add('hidden');
        chevron.classList.remove('rotate-180');
        if (typeof updateToggleButtonText === 'function') {
            updateToggleButtonText(false);
        }
    }
}

function parseErrorMessage(errorText) {
    const translations = window.errorTranslations || {};

    if (!errorText || !errorText.trim()) {
        return { userMessage: translations.unknownError || 'Unknown error occurred', technicalDetails: '' };
    }

    // Check if it contains traceback/technical information
    const hasTraceback = errorText.includes('Traceback') ||
        errorText.includes('File "') ||
        errorText.includes('.py:') ||
        errorText.includes('  File ') ||
        errorText.includes('line ');

    if (!hasTraceback) {
        // It's already a clean user message
        return { userMessage: errorText.trim(), technicalDetails: '' };
    }

    // Try to extract user message from the end of the traceback
    const lines = errorText.split('\n');
    let userMessage = translations.processingFailed || 'Processing failed';

    // Look for the final exception message (usually after "Exception:" or similar)
    for (let i = lines.length - 1; i >= 0; i--) {
        const line = lines[i].trim();
        if (line && !line.startsWith(' ') && line.includes(':')) {
            const parts = line.split(':', 2);
            if (parts.length === 2) {
                const message = parts[1].trim();
                // Check if it looks like a user message (not technical)
                if (message && !message.includes('File "') && !message.includes('.py') && !message.includes('line ')) {
                    userMessage = message;
                    break;
                }
            }
        }
    }

    return {
        userMessage: userMessage,
        technicalDetails: errorText
    };
}

// Initialize base functionality when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    // Sidebar initialization
    const isCollapsed = localStorage.getItem('sidebarCollapsed') === 'true';
    const sidebar = document.getElementById('sidebar');
    const collapseBtn = document.getElementById('collapse-btn');

    if (sidebar && collapseBtn) {
        const collapseIcon = collapseBtn.querySelector('.collapse-icon');

        if (isCollapsed) {
            const mainContent = document.getElementById('main-content');

            // Remove preload class and apply full collapsed state
            document.documentElement.classList.remove('sidebar-preload-collapsed');

            // Disable transitions temporarily
            sidebar.style.transition = 'none';
            if (mainContent) {
                mainContent.style.transition = 'none';
            }

            sidebar.classList.add('w-16', 'sidebar-collapsed');
            sidebar.classList.remove('w-64');
            collapseIcon.classList.remove('bi-chevron-bar-left');
            collapseIcon.classList.add('bi-chevron-bar-right');

            // Adjust main content margin
            if (mainContent) {
                mainContent.classList.remove('sm:ml-64');
                mainContent.classList.add('sm:ml-16');
            }

            // Re-enable transitions after a small delay
            setTimeout(() => {
                sidebar.style.transition = '';
                if (mainContent) {
                    mainContent.style.transition = '';
                }
            }, 50);
        } else {
            // Remove preload class if not collapsed
            document.documentElement.classList.remove('sidebar-preload-collapsed');
        }

        // Add event listener to collapse button
        collapseBtn.addEventListener('click', toggleSidebar);
    }

    // Dropdown functionality
    const projectDropdownBtn = document.getElementById('project-dropdown-btn');
    const projectDropdown = document.getElementById('project-dropdown');

    projectDropdownBtn?.addEventListener('click', () => {
        projectDropdown.classList.toggle('hidden');
    });

    const settingsDropdownBtn = document.getElementById('settings-dropdown-btn');
    const settingsDropdown = document.getElementById('settings-dropdown');

    settingsDropdownBtn?.addEventListener('click', () => {
        settingsDropdown.classList.toggle('hidden');
    });

    // Close dropdowns when clicking outside
    document.addEventListener('click', (event) => {
        if (projectDropdownBtn && projectDropdown &&
            !projectDropdownBtn.contains(event.target) &&
            !projectDropdown.contains(event.target)) {
            projectDropdown.classList.add('hidden');
        }

        if (settingsDropdownBtn && settingsDropdown &&
            !settingsDropdownBtn.contains(event.target) &&
            !settingsDropdown.contains(event.target)) {
            settingsDropdown.classList.add('hidden');
        }
    });

    // Auto close flash messages after 5 seconds
    setTimeout(() => {
        const alerts = document.querySelectorAll('[role="alert"]');
        alerts.forEach(alert => {
            if (alert.style.display !== 'none') {
                alert.style.opacity = '0';
                alert.style.transition = 'opacity 0.3s ease-out';
                setTimeout(() => alert.style.display = 'none', 300);
            }
        });
    }, 5000);

    // Initialize base window.init function
    if (typeof window.init === 'undefined') {
        window.init = function() {
            loadKaTeXIfNeeded();
            initMobileSidebar();
            if (typeof showFlashMessages === 'function') {
                showFlashMessages();
            }
        };
    } else {
        const originalInit = window.init;
        window.init = function() {
            originalInit();
            loadKaTeXIfNeeded();
            initMobileSidebar();
            if (typeof showFlashMessages === 'function') {
                showFlashMessages();
            }
        };
    }

    // Error modal event listeners
    const errorModal = document.getElementById('errorModal');
    if (errorModal) {
        // Close modal when clicking outside
        errorModal.addEventListener('click', function (e) {
            if (e.target === this) {
                closeErrorModal();
            }
        });

        // Close modal with Escape key
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') {
                closeErrorModal();
            }
        });
    }

    // Queue management functions
    window.deleteQueue = function(queueId) {
        if (!confirm('Are you sure you want to delete this queue? This action cannot be undone.')) {
            return;
        }

        const projectId = window.projectId || document.querySelector('[data-project-id]')?.getAttribute('data-project-id');
        if (!projectId) {
            showToast('Project ID not found', 'error');
            return;
        }

        fetch(`/${projectId}/data-navigation/queue/${queueId}/delete`, {
            method: 'DELETE',
            headers: {
                'Content-Type': 'application/json',
            }
        })
        .then(response => {
            if (response.ok) {
                // Refresh the queue management component if we're currently viewing it
                const activeTab = document.querySelector('.tab-button.active');
                if (activeTab && activeTab.dataset.tab === 'queue-management') {
                    htmx.ajax('GET', `/${projectId}/data-navigation/component/queue-management`, {
                        target: '#tab-content',
                        swap: 'innerHTML'
                    });
                }
                showToast('Queue deleted successfully', 'success');
            } else {
                showToast('Failed to delete queue', 'error');
            }
        })
        .catch(error => {
            console.error('Error deleting queue:', error);
            showToast('Error deleting queue', 'error');
        });
    };
});

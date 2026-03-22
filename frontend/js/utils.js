/* ============================================================
   utils.js — Shared utility functions for The Nesting Sandbox
   ============================================================ */

/**
 * Escape HTML special characters to prevent XSS.
 * @param {string} str
 * @returns {string}
 */
function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

/**
 * Format a dollar amount to two decimal places.
 * @param {number} amount
 * @returns {string}
 */
function formatCost(amount) {
    return '$' + (amount || 0).toFixed(2);
}

/**
 * Format large numbers with K/M suffixes.
 * @param {number} n
 * @returns {string}
 */
function formatNumber(n) {
    n = n || 0;
    if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
    if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
    return n.toString();
}

/**
 * Simple markdown-to-HTML renderer.
 * Supports: headers (h2–h4), bold, italic, inline code, ordered/unordered lists,
 * paragraph breaks, and line breaks.
 * @param {string} text
 * @returns {string} HTML string
 */
function renderMarkdown(text) {
    if (!text) return '';
    let html = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/^### (.+)$/gm, '<h4>$1</h4>')
        .replace(/^## (.+)$/gm, '<h3>$1</h3>')
        .replace(/^# (.+)$/gm, '<h2>$1</h2>')
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        .replace(/`([^`]+)`/g, '<code>$1</code>')
        .replace(/^\d+\.\s+(.+)$/gm, '<li>$1</li>')
        .replace(/^[-*]\s+(.+)$/gm, '<li>$1</li>')
        .replace(/\n\n/g, '</p><p>')
        .replace(/\n/g, '<br>');
    return '<p>' + html + '</p>';
}

/**
 * Debounce a function by the given number of milliseconds.
 * @param {Function} fn
 * @param {number} ms
 * @returns {Function}
 */
function debounce(fn, ms) {
    let timer;
    return function (...args) {
        clearTimeout(timer);
        timer = setTimeout(() => fn.apply(this, args), ms);
    };
}

/**
 * Smoothly animate a number inside an element using requestAnimationFrame.
 * Uses ease-out cubic easing.
 * @param {HTMLElement} element   Target element whose textContent will be updated
 * @param {number}      from     Starting value
 * @param {number}      to       Ending value
 * @param {number}      duration Animation duration in ms (default 500)
 * @param {Function}    formatter Formatting function (default formatCost)
 */
function animateNumber(element, from, to, duration = 500, formatter = formatCost) {
    if (element._animFrame) cancelAnimationFrame(element._animFrame);
    const start = performance.now();
    const diff = to - from;

    function update(now) {
        const elapsed = now - start;
        const progress = Math.min(elapsed / duration, 1);
        const eased = 1 - Math.pow(1 - progress, 3); // ease-out cubic
        const current = from + diff * eased;
        element.textContent = formatter(current);
        if (progress < 1) {
            element._animFrame = requestAnimationFrame(update);
        } else {
            element._animFrame = null;
        }
    }
    element._animFrame = requestAnimationFrame(update);
}

/**
 * Return the CSS color class token for a given box ID.
 * @param {string} boxId
 * @returns {string}
 */
function getBoxColorClass(boxId) {
    if (boxId === 'box1') return 'box1';
    if (boxId === 'box2') return 'box2';
    if (boxId === 'user') return 'user';
    if (boxId.startsWith('system:')) return 'system';
    return 'specialist';
}

/**
 * Return a human-readable display name for a box.
 * @param {string} boxId
 * @returns {string}
 */
function getBoxDisplayName(boxId) {
    const mode = (typeof App !== 'undefined' && App.mode) ? App.mode : 'solve';
    return getBoxDisplayNameForMode(boxId, mode);
}

/**
 * Return a short label suitable for the live feed.
 * @param {string} boxId
 * @returns {string}
 */
function getBoxShortName(boxId) {
    if (boxId === 'box1') return 'box1';
    if (boxId === 'box2') return 'box2';
    if (boxId === 'user') return 'you';
    if (boxId === 'system:conflict_detector') return 'conflict';
    if (boxId === 'system:debate') return 'debate';
    if (boxId === 'system:spawn') return 'system';
    if (boxId === 'system:history') return 'history';
    if (boxId.startsWith('system:')) return 'system';
    if (boxId.startsWith('specialist:')) return boxId.replace('specialist:', '').toLowerCase().split(' ')[0];
    if (boxId.startsWith('gate:')) return 'gate';
    return boxId;
}

/**
 * Generate a short unique ID (good enough for client-side keying).
 * @returns {string}
 */
function uid() {
    return Date.now().toString(36) + Math.random().toString(36).slice(2);
}

/**
 * Truncate text to a maximum length, appending an ellipsis if needed.
 * @param {string} text
 * @param {number} maxLen
 * @returns {string}
 */
function truncate(text, maxLen = 200) {
    if (text.length <= maxLen) return text;
    return text.substring(0, maxLen) + '...';
}

/**
 * Map an event type string to a human-readable label.
 * @param {string} type
 * @returns {string}
 */
function eventTypeLabel(type) {
    const labels = {
        hypothesis: 'Hypothesis',
        evidence: 'Evidence',
        conclusion: 'Conclusion',
        dead_end: 'Dead End',
        question: 'Question',
        connection: 'Connection',
        done: 'Done',
        // Explore
        discovery: 'Discovery',
        constraint: 'Constraint',
        approach: 'Approach',
        failure_analysis: 'Failure Analysis',
        partial_solution: 'Partial Solution',
        assumption: 'Assumption',
        unexpected: 'Unexpected',
        boundary: 'Boundary',
        pattern: 'Pattern',
        frontier: 'Frontier',
        impossibility_analysis: 'Impossibility Analysis',
        territory_map: 'Territory Map',
        emergence: 'Emergence',
        // Human
        user_input: 'User Input',
        // Conflict
        conflict: 'Conflict',
        debate_prompt: 'Debate',
        resolution: 'Resolution',
        rebuttal: 'Rebuttal',
        // Spawn
        spawn_specialist: 'Spawn Request',
        specialist_spawned: 'Specialist Spawned',
    };
    return labels[type] || type;
}

/**
 * Return a CSS class for coloring an event type badge in the feed.
 * @param {string} type
 * @returns {string}
 */
function eventTypeColorClass(type) {
    const positive = ['conclusion', 'evidence', 'discovery', 'partial_solution', 'pattern', 'emergence'];
    const negative = ['dead_end', 'failure_analysis', 'constraint', 'impossibility_analysis'];
    const mapping = ['connection', 'unexpected', 'boundary', 'frontier', 'territory_map'];
    if (positive.includes(type)) return 'etype-positive';
    if (negative.includes(type)) return 'etype-negative';
    if (mapping.includes(type)) return 'etype-mapping';
    return 'etype-neutral';
}

/**
 * Mode-aware display name for a box in reports and headings.
 * @param {string} boxId
 * @param {string} mode  'solve' | 'explore' | 'freeform'
 * @returns {string}
 */
function getBoxDisplayNameForMode(boxId, mode) {
    const names = {
        solve:    { box1: 'Box 1 \u2014 Solver',      box2: 'Box 2 \u2014 Extrapolator' },
        explore:  { box1: 'Box 1 \u2014 Explorer',     box2: 'Box 2 \u2014 Cartographer' },
        freeform: { box1: 'Box 1 \u2014 Analyst',      box2: 'Box 2 \u2014 Meta-Analyst' },
    };
    if (boxId === 'box1' || boxId === 'box2') {
        return (names[mode] || names.solve)[boxId];
    }
    if (boxId === 'user') return 'You';
    if (boxId.startsWith('system:')) return 'System';
    if (boxId.startsWith('specialist:')) return boxId.replace('specialist:', '');
    if (boxId.startsWith('gate:')) return 'Gate';
    return boxId;
}

/**
 * Mode-aware short labels for the nested box visualization.
 * @param {string} boxId
 * @param {string} mode
 * @returns {{ label: string, sub: string }}
 */
function getBoxVizLabels(boxId, mode) {
    const labels = {
        solve:    { box1: { label: 'Box 1', sub: 'Solver' },      box2: { label: 'Box 2', sub: 'Extrapolator' } },
        explore:  { box1: { label: 'Box 1', sub: 'Explorer' },     box2: { label: 'Box 2', sub: 'Cartographer' } },
        freeform: { box1: { label: 'Box 1', sub: 'Analyst' },      box2: { label: 'Box 2', sub: 'Meta-Analyst' } },
    };
    return (labels[mode] || labels.solve)[boxId] || { label: boxId, sub: '' };
}

/**
 * Read a File object as text via the FileReader API.
 * @param {File} file
 * @returns {Promise<string>}
 */
function readFileAsText(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = reject;
        reader.readAsText(file);
    });
}

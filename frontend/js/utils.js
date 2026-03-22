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
    return 'specialist';
}

/**
 * Return a human-readable display name for a box.
 * @param {string} boxId
 * @returns {string}
 */
function getBoxDisplayName(boxId) {
    if (boxId === 'box1') return 'Box 1 \u2014 Solver';
    if (boxId === 'box2') return 'Box 2 \u2014 Extrapolator';
    if (boxId.startsWith('specialist:')) return boxId.replace('specialist:', '');
    if (boxId.startsWith('gate:')) return 'Gate';
    return boxId;
}

/**
 * Return a short label suitable for the live feed.
 * @param {string} boxId
 * @returns {string}
 */
function getBoxShortName(boxId) {
    if (boxId === 'box1') return 'box1';
    if (boxId === 'box2') return 'box2';
    if (boxId.startsWith('specialist:')) return boxId.replace('specialist:', '').toLowerCase().split(' ')[0];
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
    };
    return labels[type] || type;
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

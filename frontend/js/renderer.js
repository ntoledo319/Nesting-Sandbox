/* ============================================================
   renderer.js — DOM rendering for setup, running, and results
   ============================================================ */

class Renderer {
    constructor() {
        /** @type {string|null} Active feed filter (box ID or null for "all") */
        this.feedFilter = null;
        /** @type {Map<string, string>} Full content cache for expandable feed items */
        this._fullContent = new Map();
    }

    /* --------------------------------------------------------
       SETUP STATE
       -------------------------------------------------------- */

    /**
     * Create a specialist card element.
     * @param {object} spec  { name, description }
     * @returns {HTMLElement}
     */
    renderSpecialistCard(spec) {
        const card = document.createElement('div');
        card.className = 'specialist-card';
        card.dataset.name = spec.name;
        card.innerHTML = `
            <div class="specialist-card-header">
                <span class="specialist-dot">\u25c8</span>
                <span class="specialist-name">${escapeHtml(spec.name)}</span>
                <button class="specialist-remove" data-name="${escapeHtml(spec.name)}" title="Remove">\u2715</button>
            </div>
            <p class="specialist-desc">${escapeHtml(truncate(spec.description, 100))}</p>
        `;
        return card;
    }

    /**
     * Replace the contents of the specialist list container.
     * @param {object[]} specialists
     */
    renderSpecialistList(specialists) {
        const container = document.getElementById('specialistList');
        container.innerHTML = '';
        specialists.forEach(spec => {
            container.appendChild(this.renderSpecialistCard(spec));
        });
    }

    /**
     * Show or update the cost/complexity estimate card.
     * Pass null to show the loading spinner.
     * @param {object|null} estimate
     */
    renderEstimate(estimate) {
        const card = document.getElementById('estimateCard');
        const loading = document.getElementById('estimateLoading');
        const content = document.getElementById('estimateContent');

        card.classList.remove('hidden');

        if (!estimate) {
            loading.classList.remove('hidden');
            content.classList.add('hidden');
            return;
        }

        loading.classList.add('hidden');
        content.classList.remove('hidden');

        // Complexity dots
        const dotsEl = document.getElementById('complexityDots');
        let dots = '';
        for (let i = 1; i <= 10; i++) {
            dots += `<span class="complexity-dot ${i <= estimate.complexity_score ? 'filled' : ''}">${i <= estimate.complexity_score ? '\u25cf' : '\u25cb'}</span>`;
        }
        dots += `<span class="complexity-label">${estimate.complexity_score}/10</span>`;
        dotsEl.innerHTML = dots;

        document.getElementById('estCycles').textContent =
            `${Math.round(estimate.estimated_cycles * 0.6)}\u2013${Math.round(estimate.estimated_cycles * 1.2)}`;
        document.getElementById('estCost').textContent =
            `${formatCost(estimate.cost_low)} \u2013 ${formatCost(estimate.cost_high)}`;

        // Warnings
        const warningsEl = document.getElementById('estimateWarnings');
        if (estimate.warnings && estimate.warnings.length > 0) {
            warningsEl.innerHTML = estimate.warnings.map(w => `<div class="estimate-warning">\u26a0 ${escapeHtml(w)}</div>`).join('');
        } else {
            warningsEl.innerHTML = '';
        }
    }

    /**
     * Create a file list item element.
     * @param {File} file
     * @returns {HTMLElement}
     */
    renderFileItem(file) {
        const item = document.createElement('div');
        item.className = 'file-item';
        item.dataset.name = file.name;
        const size = file.size < 1024
            ? file.size + 'B'
            : (file.size / 1024).toFixed(1) + 'KB';
        item.innerHTML = `
            <span class="file-icon">\ud83d\udcc4</span>
            <span class="file-name">${escapeHtml(file.name)}</span>
            <span class="file-size">(${size})</span>
            <button class="file-remove" data-name="${escapeHtml(file.name)}">\u2715</button>
        `;
        return item;
    }

    /* --------------------------------------------------------
       RUNNING STATE
       -------------------------------------------------------- */

    /**
     * Create a live-feed item element from a reasoning event.
     * Long content is truncated with a "Show more" button.
     * @param {object} event
     * @returns {HTMLElement}
     */
    renderFeedItem(event) {
        const item = document.createElement('div');
        const colorClass = getBoxColorClass(event.source_box);
        const shortName = getBoxShortName(event.source_box);
        item.className = 'feed-item feed-item-enter';
        item.dataset.source = event.source_box;

        // Special CSS classes based on event type and source
        if (event.event_type === 'user_input') item.classList.add('feed-item-user');
        if (event.event_type === 'conflict') item.classList.add('feed-item-conflict');
        if (event.event_type === 'resolution') item.classList.add('feed-item-resolution');
        if (event.event_type === 'rebuttal') item.classList.add('feed-item-rebuttal');
        if (event.event_type === 'specialist_spawned') item.classList.add('feed-item-spawn');
        if (event.metadata && event.metadata.source === 'web_search') item.classList.add('feed-item-web');

        const content = event.content || '';
        const expanded = content.length > 300;
        const displayContent = expanded ? truncate(content, 300) : content;

        item.innerHTML = `
            <div class="feed-item-header">
                <span class="feed-dot color-${colorClass}"></span>
                <span class="feed-source color-${colorClass}">${escapeHtml(shortName)}</span>
                <span class="feed-type-badge ${eventTypeColorClass(event.event_type)}">${eventTypeLabel(event.event_type)}</span>
            </div>
            <div class="feed-item-content">${renderMarkdown(displayContent)}</div>
            ${expanded ? `<button class="feed-expand" data-event-id="${escapeHtml(event.id)}">Show more</button>` : ''}
        `;

        if (expanded) {
            this._fullContent.set(event.id, content);
        }

        // Remove enter animation class after animation completes
        setTimeout(() => item.classList.remove('feed-item-enter'), 500);

        return item;
    }

    /**
     * Append a single event to the live feed, respecting the current filter.
     * @param {object} event
     */
    addFeedItem(event) {
        const feed = document.getElementById('liveFeed');
        if (!feed) return;

        // Apply filter
        if (this.feedFilter && event.source_box !== this.feedFilter) return;

        const item = this.renderFeedItem(event);
        feed.appendChild(item);

        // Bind expand button if present
        const expandBtn = item.querySelector('.feed-expand');
        if (expandBtn) {
            expandBtn.addEventListener('click', () => {
                const full = this._fullContent.get(event.id);
                if (full) {
                    item.querySelector('.feed-item-content').innerHTML = renderMarkdown(full);
                    expandBtn.remove();
                }
            });
        }

        // Auto-scroll
        feed.scrollTop = feed.scrollHeight;
    }

    /**
     * Render the feed filter buttons for all active boxes.
     * @param {string[]} boxIds
     */
    renderFeedFilters(boxIds) {
        const container = document.getElementById('feedFilters');
        if (!container) return;

        let html = '<button class="filter-btn active" data-filter="all">All</button>';
        for (const id of boxIds) {
            if (id.startsWith('gate:')) continue;
            const colorClass = getBoxColorClass(id);
            const name = getBoxShortName(id);
            html += `<button class="filter-btn color-${colorClass}" data-filter="${escapeHtml(id)}">${escapeHtml(name)}</button>`;
        }
        container.innerHTML = html;
    }

    /**
     * Update the status text bar from the current box states.
     * @param {object} boxes  Map of boxId -> { status, current_cycle|cycle }
     */
    updateStatus(boxes) {
        const statusEl = document.getElementById('statusText');
        if (!statusEl) return;
        const mode = (typeof App !== 'undefined' && App.mode) ? App.mode : 'solve';

        const parts = [];
        for (const [id, box] of Object.entries(boxes)) {
            if (id.startsWith('gate:')) continue;
            const name = id.startsWith('specialist:') ? getBoxShortName(id) : getBoxVizLabels(id, mode).sub || getBoxShortName(id);
            const status = box.status || 'waiting';
            const cycle = box.current_cycle || box.cycle || 0;
            parts.push(`${name}: ${status}${status === 'thinking' ? ` (cycle ${cycle})` : ''}`);
        }
        statusEl.textContent = parts.join(' \u00b7 ');
    }

    /**
     * Render a history item for the history modal.
     * @param {object} run
     * @returns {string} HTML string
     */
    renderHistoryItem(run) {
        return `
            <label class="history-item" data-total-cost="${run.total_cost || 0}">
                <input type="checkbox" value="${escapeHtml(run.run_id)}">
                <div class="history-item-info">
                    <div class="history-item-question">${escapeHtml(truncate(run.question, 120))}</div>
                    <div class="history-item-meta">
                        ${formatCost(run.total_cost)} · ${run.completed_at ? new Date(run.completed_at).toLocaleDateString() : ''}
                        ${run.specialists && run.specialists.length ? ' · ' + run.specialists.length + ' specialists' : ''}
                    </div>
                </div>
            </label>
        `;
    }

    /**
     * Render a seed run card for the setup view.
     * @param {object} run
     * @returns {HTMLElement}
     */
    renderSeedRunCard(run) {
        const card = document.createElement('div');
        card.className = 'seed-run-card';
        card.dataset.runId = run.run_id;
        card.innerHTML = `
            <span class="seed-question">${escapeHtml(truncate(run.question, 80))}</span>
            <span class="seed-cost">${formatCost(run.total_cost)}</span>
            <button class="seed-remove" data-run-id="${escapeHtml(run.run_id)}">✕</button>
        `;
        return card;
    }

    /* --------------------------------------------------------
       RESULTS STATE
       -------------------------------------------------------- */

    /**
     * Create an expandable report card for a single box's results.
     * @param {object} report
     * @returns {HTMLElement}
     */
    renderReportCard(report) {
        const card = document.createElement('div');
        const colorClass = getBoxColorClass(report.box_id);
        const displayName = report.display_name || getBoxDisplayName(report.box_id);

        const stats = [];
        if (report.finding_counts) {
            for (const [type, count] of Object.entries(report.finding_counts)) {
                if (count > 0) stats.push(`${eventTypeLabel(type)}: ${count}`);
            }
        }

        card.className = 'report-card';
        card.innerHTML = `
            <div class="report-card-header color-${colorClass}-border">
                <div class="report-card-title">
                    <span class="report-dot color-${colorClass}"></span>
                    <h3>${escapeHtml(displayName)}</h3>
                </div>
                <div class="report-card-stats">
                    <span class="mono">${formatCost(report.cost || 0)}</span>
                    <span class="mono">${formatNumber((report.input_tokens || 0) + (report.output_tokens || 0))} tokens</span>
                    <span class="mono">${report.cycles || 0} cycles</span>
                </div>
                <span class="report-card-toggle">\u25be</span>
            </div>
            <div class="report-card-body">
                <div class="report-card-meta">${stats.join(' \u00b7 ')}</div>
                <div class="report-card-content">${renderMarkdown(report.report_markdown || '')}</div>
                <button class="btn-ghost btn-sm report-download" data-box="${escapeHtml(report.box_id)}">Download Report</button>
            </div>
        `;

        return card;
    }

    /**
     * Render the full results view: summary stats, per-box report cards,
     * and the cost receipt table.
     * @param {object} report  Final run report from the server
     */
    renderResults(report) {
        const container = document.getElementById('reportCards');
        if (!container) return;
        container.innerHTML = '';

        // Mode-aware title
        const mode = (typeof App !== 'undefined' && App.mode) ? App.mode : 'solve';
        const titleEl = document.getElementById('resultsTitle');
        if (titleEl) {
            const titles = {
                solve: 'RUN COMPLETE',
                explore: 'EXPLORATION COMPLETE',
                freeform: 'ANALYSIS COMPLETE',
            };
            titleEl.textContent = titles[mode] || 'RUN COMPLETE';
        }

        // Summary stats
        const statsEl = document.getElementById('resultsSummaryStats');
        if (statsEl && report.receipt) {
            const r = report.receipt;
            const modeLabels = { solve: 'Solve', explore: 'Explore', freeform: 'Freeform' };
            statsEl.innerHTML = `
                <span class="results-mode-badge mode-badge-${mode}">${modeLabels[mode] || mode}</span>
                <span>\u00b7</span>
                <span>${formatCost(r.total_cost)}</span>
                <span>\u00b7</span>
                <span>${r.cycles_completed} cycles</span>
                <span>\u00b7</span>
                <span>${formatNumber((r.total_tokens?.input || 0) + (r.total_tokens?.output || 0))} tokens</span>
                <span>\u00b7</span>
                <span>${r.cache_hit_rate || 0}% cache</span>
            `;
        }

        // Box reports
        for (const boxReport of (report.box_reports || [])) {
            container.appendChild(this.renderReportCard(boxReport));
        }

        // Cost receipt
        if (report.receipt) {
            const receiptCard = document.createElement('div');
            receiptCard.className = 'report-card expanded';
            receiptCard.innerHTML = `
                <div class="report-card-header">
                    <div class="report-card-title">
                        <span class="report-dot" style="background: var(--cost-color)"></span>
                        <h3>Cost Receipt</h3>
                    </div>
                    <span class="report-card-toggle">\u25be</span>
                </div>
                <div class="report-card-body">
                    <table class="receipt-table">
                        <thead><tr><th>Box</th><th>Input</th><th>Output</th><th>Reasoning</th><th>Cached</th><th>Cost</th></tr></thead>
                        <tbody>
                            ${(report.receipt.per_box_breakdown || []).map(b => `
                                <tr>
                                    <td class="mono">${escapeHtml(getBoxShortName(b.box_id))}</td>
                                    <td class="mono">${formatNumber(b.input_tokens)}</td>
                                    <td class="mono">${formatNumber(b.output_tokens)}</td>
                                    <td class="mono">${formatNumber(b.reasoning_tokens)}</td>
                                    <td class="mono">${formatNumber(b.cached_tokens)}</td>
                                    <td class="mono">${formatCost(b.cost)}</td>
                                </tr>
                            `).join('')}
                        </tbody>
                        <tfoot>
                            <tr>
                                <td><strong>Total</strong></td>
                                <td class="mono">${formatNumber(report.receipt.total_tokens?.input)}</td>
                                <td class="mono">${formatNumber(report.receipt.total_tokens?.output)}</td>
                                <td class="mono">${formatNumber(report.receipt.total_tokens?.reasoning)}</td>
                                <td></td>
                                <td class="mono"><strong>${formatCost(report.receipt.total_cost)}</strong></td>
                            </tr>
                        </tfoot>
                    </table>
                    ${report.receipt.duration_seconds ? `<p class="receipt-duration">Duration: ${Math.round(report.receipt.duration_seconds)}s</p>` : ''}
                </div>
            `;
            container.appendChild(receiptCard);
        }
    }
}

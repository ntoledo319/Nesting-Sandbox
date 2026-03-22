/* ============================================================
   app.js — Main application state machine
   Ties together WSManager, CostDisplay, BoxVisualization, and
   Renderer across three states: setup, running, results.
   ============================================================ */

const App = {
    state: 'setup', // 'setup' | 'running' | 'results'
    ws: new WSManager(),
    costDisplay: new CostDisplay(),
    viz: new BoxVisualization('boxVisualization'),
    renderer: new Renderer(),

    // State data
    runId: null,
    specialists: [],
    documents: [],
    documentTexts: [],
    events: [],
    boxStates: {},
    estimateTimer: null,
    currentReport: null,
    mode: 'solve', // 'solve' | 'explore' | 'freeform'
    seedRunIds: [],
    seedRuns: [],  // Full run data for display

    /**
     * Bootstrap the application. Call once after DOMContentLoaded.
     */
    init() {
        this.costDisplay.init();
        this.bindEvents();
        this.bindWSHandlers();
    },

    /* --------------------------------------------------------
       DOM Event Bindings
       -------------------------------------------------------- */

    bindEvents() {
        // Question input — trigger estimate on change
        const questionInput = document.getElementById('questionInput');
        questionInput.addEventListener('input', debounce(() => {
            this.updateLaunchButton();
            this.requestEstimate();
        }, 800));

        // Auto-expand textarea
        questionInput.addEventListener('input', function () {
            this.style.height = 'auto';
            this.style.height = this.scrollHeight + 'px';
        });

        // File upload — drop zone
        const dropZone = document.getElementById('dropZone');
        const fileInput = document.getElementById('fileInput');

        dropZone.addEventListener('click', () => fileInput.click());
        dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropZone.classList.add('drag-over');
        });
        dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropZone.classList.remove('drag-over');
            this.handleFiles(e.dataTransfer.files);
        });
        fileInput.addEventListener('change', (e) => this.handleFiles(e.target.files));

        // Specialist modal — open
        document.getElementById('addSpecialist').addEventListener('click', () => {
            document.getElementById('specialistModal').classList.remove('hidden');
            document.getElementById('specialistName').value = '';
            document.getElementById('specialistDesc').value = '';
        });

        // Specialist modal — cancel
        document.getElementById('cancelSpecialist').addEventListener('click', () => {
            document.getElementById('specialistModal').classList.add('hidden');
        });

        // Specialist modal — confirm
        document.getElementById('confirmSpecialist').addEventListener('click', () => {
            const name = document.getElementById('specialistName').value.trim();
            const desc = document.getElementById('specialistDesc').value.trim();
            if (name && desc) {
                this.specialists.push({ name, description: desc });
                this.renderer.renderSpecialistList(this.specialists);
                document.getElementById('specialistModal').classList.add('hidden');
                this.updateLaunchButton();
                this.requestEstimate();
                this.bindSpecialistRemove();
            }
        });

        // Preset buttons (pre-fill specialist name/description)
        document.querySelectorAll('.preset-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.getElementById('specialistName').value = btn.dataset.name;
                document.getElementById('specialistDesc').value = btn.dataset.desc;
            });
        });

        // Budget slider
        const slider = document.getElementById('budgetSlider');
        slider.addEventListener('input', () => {
            document.getElementById('budgetValue').textContent = formatCost(parseFloat(slider.value));
            this.requestEstimate();
        });

        // Launch button
        document.getElementById('launchBtn').addEventListener('click', () => this.startRun());

        // Stop button
        document.getElementById('headerStop').addEventListener('click', () => this.stopRun());

        // API key toggle
        document.getElementById('apiKeyToggle').addEventListener('click', () => {
            const input = document.getElementById('apiKeyInput');
            input.type = input.type === 'password' ? 'text' : 'password';
        });

        // Mode selector
        document.querySelectorAll('.mode-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                this.mode = btn.dataset.mode;
                // Update placeholder text based on mode
                const placeholder = {
                    solve: 'Ask something conventionally impossible...',
                    explore: 'Pose a problem to explore — the journey IS the output...',
                    freeform: 'Throw something at the wall and see what sticks...',
                };
                document.getElementById('questionInput').placeholder = placeholder[this.mode] || placeholder.solve;
                this.requestEstimate();
            });
        });

        // Feed filters (delegated)
        const feedFilters = document.getElementById('feedFilters');
        if (feedFilters) {
            feedFilters.addEventListener('click', (e) => {
                const btn = e.target.closest('.filter-btn');
                if (!btn) return;
                document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                const filter = btn.dataset.filter;
                this.renderer.feedFilter = filter === 'all' ? null : filter;
                this.refreshFeed();
            });
        }

        // Results actions
        const newRunBtn = document.getElementById('newRunBtn');
        if (newRunBtn) newRunBtn.addEventListener('click', () => this.resetToSetup());

        const downloadAllBtn = document.getElementById('downloadAllBtn');
        if (downloadAllBtn) downloadAllBtn.addEventListener('click', () => this.downloadAll());

        // Specialist remove (delegated from list container)
        document.getElementById('specialistList').addEventListener('click', (e) => {
            const removeBtn = e.target.closest('.specialist-remove');
            if (removeBtn) {
                const name = removeBtn.dataset.name;
                this.specialists = this.specialists.filter(s => s.name !== name);
                this.renderer.renderSpecialistList(this.specialists);
                this.updateLaunchButton();
                this.requestEstimate();
            }
        });

        // File remove (delegated from list container)
        document.getElementById('fileList').addEventListener('click', (e) => {
            const removeBtn = e.target.closest('.file-remove');
            if (removeBtn) {
                const name = removeBtn.dataset.name;
                const idx = this.documents.findIndex(d => d.name === name);
                if (idx !== -1) {
                    this.documents.splice(idx, 1);
                    this.documentTexts.splice(idx, 1);
                }
                this.renderFileList();
            }
        });

        // Report card expand/collapse and individual download (delegated)
        document.getElementById('reportCards')?.addEventListener('click', (e) => {
            const header = e.target.closest('.report-card-header');
            if (header) {
                header.parentElement.classList.toggle('expanded');
            }

            const dlBtn = e.target.closest('.report-download');
            if (dlBtn && this.currentReport) {
                const boxId = dlBtn.dataset.box;
                const boxReport = this.currentReport.box_reports?.find(r => r.box_id === boxId);
                if (boxReport) {
                    const blob = new Blob([boxReport.report_markdown || JSON.stringify(boxReport, null, 2)], { type: 'text/markdown' });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = `${boxId.replace(/[^a-z0-9]/gi, '-')}-report.md`;
                    a.click();
                    URL.revokeObjectURL(url);
                }
            }
        });

        // User injection (Feature 2)
        document.getElementById('feedSendBtn')?.addEventListener('click', () => this.injectInput());
        document.getElementById('feedInput')?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.injectInput();
            }
        });

        // History modal (Feature 3)
        document.getElementById('loadHistoryBtn')?.addEventListener('click', () => this.showHistoryModal());
        document.getElementById('cancelHistory')?.addEventListener('click', () => {
            document.getElementById('historyModal').classList.add('hidden');
        });
        document.getElementById('confirmHistory')?.addEventListener('click', () => this.confirmHistorySelection());

        // Seed run removal (delegated)
        document.getElementById('seedRunList')?.addEventListener('click', (e) => {
            const removeBtn = e.target.closest('.seed-remove');
            if (removeBtn) {
                const runId = removeBtn.dataset.runId;
                this.seedRunIds = this.seedRunIds.filter(id => id !== runId);
                this.seedRuns = this.seedRuns.filter(r => r.run_id !== runId);
                this.renderSeedRuns();
            }
        });

        // Escape key closes modals
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                document.getElementById('specialistModal')?.classList.add('hidden');
                document.getElementById('historyModal')?.classList.add('hidden');
            }
        });

        // Drop zone keyboard accessibility (Enter/Space to open file picker)
        document.getElementById('dropZone')?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                document.getElementById('fileInput')?.click();
            }
        });
    },

    bindSpecialistRemove() {
        // Handled by delegated event above — no-op kept for clarity
    },

    /* --------------------------------------------------------
       User Injection
       -------------------------------------------------------- */

    injectInput() {
        const input = document.getElementById('feedInput');
        if (!input) return;
        const content = input.value.trim();
        if (!content || !this.ws.connected) return;
        this.ws.send('user_input', { content });
        input.value = '';
    },

    /* --------------------------------------------------------
       History Modal
       -------------------------------------------------------- */

    async showHistoryModal() {
        const modal = document.getElementById('historyModal');
        const list = document.getElementById('historyList');
        if (!modal || !list) return;

        list.innerHTML = '<div class="estimate-loading"><div class="shimmer-bar"></div></div>';
        modal.classList.remove('hidden');

        try {
            const resp = await fetch('/api/history');
            if (!resp.ok) { list.innerHTML = '<p style="color:var(--text-tertiary)">No history available.</p>'; return; }
            const runs = await resp.json();

            if (!runs.length) {
                list.innerHTML = '<p style="color:var(--text-tertiary)">No previous runs found.</p>';
                return;
            }

            list.innerHTML = runs.map(r => this.renderer.renderHistoryItem(r)).join('');

            // Pre-check already selected
            this.seedRunIds.forEach(id => {
                const cb = list.querySelector(`input[value="${id}"]`);
                if (cb) cb.checked = true;
            });
        } catch (e) {
            list.innerHTML = '<p style="color:var(--text-tertiary)">Failed to load history.</p>';
        }
    },

    confirmHistorySelection() {
        const list = document.getElementById('historyList');
        const modal = document.getElementById('historyModal');
        if (!list) return;

        const checked = list.querySelectorAll('input[type="checkbox"]:checked');
        const selectedIds = Array.from(checked).map(cb => cb.value);

        // Fetch summary info for selected runs
        this.seedRunIds = selectedIds;
        this.seedRuns = [];

        // Get run info from the DOM
        checked.forEach(cb => {
            const item = cb.closest('.history-item');
            const question = item?.querySelector('.history-item-question')?.textContent || '';
            const meta = item?.querySelector('.history-item-meta')?.textContent || '';
            const total_cost = parseFloat(item?.dataset?.totalCost) || 0;
            this.seedRuns.push({ run_id: cb.value, question, meta, total_cost });
        });

        this.renderSeedRuns();
        modal.classList.add('hidden');
    },

    renderSeedRuns() {
        const container = document.getElementById('seedRunList');
        if (!container) return;
        container.innerHTML = '';
        this.seedRuns.forEach(run => {
            container.appendChild(this.renderer.renderSeedRunCard(run));
        });
    },

    /* --------------------------------------------------------
       WebSocket Event Handlers
       -------------------------------------------------------- */

    bindWSHandlers() {
        this.ws.on('connected', () => {
            const statusEl = document.getElementById('statusText');
            if (statusEl) statusEl.textContent = 'Connected — waiting for boxes to start...';
        });

        this.ws.on('initial_state', (data) => {
            // Restore mode from server state (handles reconnects)
            if (data.mode) this.mode = data.mode;
            this.boxStates = data.boxes || {};
            if (data.events) {
                data.events.forEach(e => this.addEvent(e));
            }
            if (data.cost) {
                this.costDisplay.update(data.cost);
            }
            const boxIds = Object.keys(this.boxStates);
            this.viz.init(boxIds);
            this.renderer.renderFeedFilters(boxIds);
        });

        this.ws.on('event', (data) => {
            this.addEvent(data);
            this.viz.flashBox(data.source_box);
            // Flash all boxes for user input
            if (data.source_box === 'user') {
                this.viz.flashAll();
            }
        });

        this.ws.on('box_status', (data) => {
            if (this.boxStates[data.box_id]) {
                this.boxStates[data.box_id].status = data.status;
                this.boxStates[data.box_id].current_cycle = data.cycle;
            } else {
                this.boxStates[data.box_id] = { status: data.status, current_cycle: data.cycle };
            }
            this.viz.updateBox(data.box_id, data.status, data.cycle);
            this.renderer.updateStatus(this.boxStates);
        });

        this.ws.on('cost_update', (data) => {
            this.costDisplay.update(data);
            // Update aria
            const progressBar = document.querySelector('.cost-progress');
            if (progressBar) {
                progressBar.setAttribute('aria-valuenow', Math.round(data.budget_pct || 0));
            }
        });

        this.ws.on('box_spawned', (data) => {
            this.boxStates[data.box_id] = { status: 'waiting', current_cycle: 0 };
            const boxIds = Object.keys(this.boxStates);
            this.viz.init(boxIds);
            this.renderer.renderFeedFilters(boxIds);
        });

        this.ws.on('run_complete', (data) => {
            if (this._stopFallback) {
                clearTimeout(this._stopFallback);
                this._stopFallback = null;
            }
            this.fetchResults();
        });

        this.ws.on('disconnected', () => {
            // Check if run completed while we were disconnected
            if (this.runId) {
                setTimeout(() => this.checkRunStatus(), 2000);
            }
        });
    },

    /* --------------------------------------------------------
       Event & Feed Helpers
       -------------------------------------------------------- */

    addEvent(event) {
        this.events.push(event);
        this.renderer.addFeedItem(event);
    },

    refreshFeed() {
        const feed = document.getElementById('liveFeed');
        if (!feed) return;
        feed.innerHTML = '';
        this.events.forEach(e => this.renderer.addFeedItem(e));
    },

    /* --------------------------------------------------------
       File Handling
       -------------------------------------------------------- */

    async handleFiles(files) {
        for (const file of files) {
            try {
                const text = await readFileAsText(file);
                this.documents.push(file);
                this.documentTexts.push(text);
            } catch (e) {
                console.error('Error reading file:', e);
            }
        }
        this.renderFileList();
    },

    renderFileList() {
        const container = document.getElementById('fileList');
        container.innerHTML = '';
        this.documents.forEach(file => {
            container.appendChild(this.renderer.renderFileItem(file));
        });
    },

    /* --------------------------------------------------------
       Launch / Estimate
       -------------------------------------------------------- */

    updateLaunchButton() {
        const btn = document.getElementById('launchBtn');
        const question = document.getElementById('questionInput').value.trim();
        btn.disabled = !question;
    },

    async requestEstimate() {
        const question = document.getElementById('questionInput').value.trim();
        if (!question) {
            document.getElementById('estimateCard').classList.add('hidden');
            return;
        }

        this.renderer.renderEstimate(null); // Show loading

        try {
            const apiKey = document.getElementById('apiKeyInput').value.trim();
            const body = {
                question,
                documents: this.documentTexts,
                specialists: this.specialists,
                budget_cap: parseFloat(document.getElementById('budgetSlider').value),
                mode: this.mode,
                web_search_enabled: document.getElementById('webSearchToggle')?.checked ?? true,
                conflict_detection: document.getElementById('conflictToggle')?.checked ?? true,
                allow_spawning: document.getElementById('spawningToggle')?.checked ?? true,
                seed_run_ids: this.seedRunIds,
            };
            if (apiKey) body.api_key = apiKey;

            const resp = await fetch('/api/estimate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });

            if (resp.ok) {
                const estimate = await resp.json();
                this.renderer.renderEstimate(estimate);
            } else {
                document.getElementById('estimateCard').classList.add('hidden');
            }
        } catch (e) {
            console.error('Estimate error:', e);
            document.getElementById('estimateCard').classList.add('hidden');
        }
    },

    /* --------------------------------------------------------
       Run Lifecycle
       -------------------------------------------------------- */

    async startRun() {
        const question = document.getElementById('questionInput').value.trim();
        if (!question) return;

        const launchBtn = document.getElementById('launchBtn');
        if (launchBtn) launchBtn.disabled = true;

        const apiKey = document.getElementById('apiKeyInput').value.trim();
        const budget = parseFloat(document.getElementById('budgetSlider').value);

        const config = {
            question,
            documents: this.documentTexts,
            specialists: this.specialists,
            budget_cap: budget,
            mode: this.mode,
            web_search_enabled: document.getElementById('webSearchToggle')?.checked ?? true,
            conflict_detection: document.getElementById('conflictToggle')?.checked ?? true,
            allow_spawning: document.getElementById('spawningToggle')?.checked ?? true,
            seed_run_ids: this.seedRunIds,
        };
        if (apiKey) config.api_key = apiKey;

        try {
            const resp = await fetch('/api/runs', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(config),
            });

            if (!resp.ok) {
                let detail = 'Failed to start run';
                try {
                    const err = await resp.json();
                    detail = err.detail || detail;
                } catch {}
                alert(detail);
                if (launchBtn) launchBtn.disabled = false;
                return;
            }

            const data = await resp.json();
            this.runId = data.run_id;
            this.events = [];
            this.boxStates = {};

            // Switch to running state
            this.switchView('running');

            // Connect WebSocket
            this.ws.connect(this.runId);

            // Show stop button, cost, and mode badge
            document.getElementById('headerStop').classList.remove('hidden');
            const modeBadge = document.getElementById('headerModeBadge');
            const modeLabels = { solve: 'Solve', explore: 'Explore', freeform: 'Freeform' };
            modeBadge.textContent = modeLabels[this.mode] || this.mode;
            modeBadge.className = `header-mode-badge mode-badge-${this.mode}`;
            this.costDisplay.setBudget(budget);

        } catch (e) {
            console.error('Start run error:', e);
            alert('Failed to start run: ' + e.message);
            if (launchBtn) launchBtn.disabled = false;
        }
    },

    async stopRun() {
        if (!this.runId) return;
        try {
            await fetch(`/api/runs/${this.runId}/stop`, { method: 'POST' });
            // Don't call fetchResults immediately — wait for run_complete WS message
            // Add a fallback timeout in case WS message never arrives
            this._stopFallback = setTimeout(() => this.fetchResults(), 5000);
        } catch (e) {
            console.error('Stop error:', e);
        }
    },

    async checkRunStatus() {
        if (!this.runId) return;
        try {
            const resp = await fetch(`/api/runs/${this.runId}`);
            const data = await resp.json();
            if (data.status === 'completed' || data.status === 'stopped') {
                this.fetchResults();
            }
        } catch (e) {
            console.error('Status check error:', e);
        }
    },

    /* --------------------------------------------------------
       Results
       -------------------------------------------------------- */

    async fetchResults() {
        if (!this.runId) return;
        try {
            const resp = await fetch(`/api/runs/${this.runId}/report`);
            if (!resp.ok) {
                console.error('Failed to fetch results:', resp.status);
                // Retry after delay
                setTimeout(() => this.fetchResults(), 3000);
                return;
            }
            const report = await resp.json();
            this.currentReport = report;
            this.showResults(report);
        } catch (e) {
            console.error('Fetch results error:', e);
        }
    },

    showResults(report) {
        this.ws.disconnect();
        document.getElementById('headerStop').classList.add('hidden');
        this.switchView('results');
        this.renderer.renderResults(report);
    },

    resetToSetup() {
        this.runId = null;
        this.events = [];
        this.boxStates = {};
        this.currentReport = null;
        this.mode = 'solve';
        this.seedRunIds = [];
        this.seedRuns = [];
        this.renderer.feedFilter = null;
        this.renderer._fullContent?.clear();
        this.costDisplay.reset();
        document.getElementById('headerStop').classList.add('hidden');
        document.getElementById('headerModeBadge').className = 'header-mode-badge hidden';
        document.getElementById('liveFeed').innerHTML = '';
        const seedList = document.getElementById('seedRunList');
        if (seedList) seedList.innerHTML = '';
        // Reset mode selector UI
        document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
        const defaultMode = document.querySelector('.mode-btn[data-mode="solve"]');
        if (defaultMode) defaultMode.classList.add('active');
        document.getElementById('questionInput').placeholder = 'Ask something conventionally impossible...';
        this.switchView('setup');
    },

    async downloadAll() {
        if (!this.runId) return;
        try {
            const resp = await fetch(`/api/runs/${this.runId}/report/download`);
            if (!resp.ok) {
                console.error('Download failed:', resp.status);
                return;
            }
            const blob = await resp.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `nesting-sandbox-${this.runId.substring(0, 8)}.json`;
            a.click();
            URL.revokeObjectURL(url);
        } catch (e) {
            console.error('Download error:', e);
        }
    },

    /* --------------------------------------------------------
       View Switching
       -------------------------------------------------------- */

    switchView(view) {
        this.state = view;
        document.getElementById('setupView').classList.toggle('hidden', view !== 'setup');
        document.getElementById('runningView').classList.toggle('hidden', view !== 'running');
        document.getElementById('resultsView').classList.toggle('hidden', view !== 'results');
    },
};

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => App.init());

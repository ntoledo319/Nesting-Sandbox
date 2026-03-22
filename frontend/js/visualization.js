/* ============================================================
   visualization.js — Nested concentric box CSS visualization
   ============================================================ */

class BoxVisualization {
    /**
     * @param {string} containerId  ID of the DOM element to render into
     */
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        this.boxes = {};
        this.specialists = [];
        this._flashTimers = {};
    }

    /**
     * Initialize the visualization with a list of box IDs.
     * Separates core boxes (box1, box2) from specialist boxes.
     * @param {string[]} boxIds
     */
    init(boxIds) {
        this.boxes = {};
        this.specialists = [];

        for (const id of boxIds) {
            if (id === 'box1' || id === 'box2') {
                this.boxes[id] = { status: 'waiting', cycle: 0 };
            } else if (id.startsWith('specialist:')) {
                this.specialists.push({
                    id,
                    name: id.replace('specialist:', ''),
                    status: 'waiting',
                    cycle: 0,
                });
            }
        }

        this.render();
    }

    /**
     * Update a single box's status and cycle count, then re-render.
     * @param {string} boxId
     * @param {string} status
     * @param {number} cycle
     */
    updateBox(boxId, status, cycle) {
        if (boxId === 'box1' || boxId === 'box2') {
            if (this.boxes[boxId]) {
                this.boxes[boxId].status = status;
                this.boxes[boxId].cycle = cycle;
            }
        } else {
            const spec = this.specialists.find(s => s.id === boxId);
            if (spec) {
                spec.status = status;
                spec.cycle = cycle;
            }
        }
        this.render();
    }

    /**
     * Briefly flash a box element to indicate activity.
     * @param {string} boxId
     */
    flashBox(boxId) {
        // Set flash state and re-render
        this._flashTimers[boxId] = true;
        this.render();
        setTimeout(() => {
            delete this._flashTimers[boxId];
            this.render();
        }, 600);
    }

    /**
     * Full re-render of the nested box visualization.
     */
    render() {
        const hasSpecs = this.specialists.length > 0;
        const box1 = this.boxes['box1'] || { status: 'waiting', cycle: 0 };
        const box2 = this.boxes['box2'] || { status: 'waiting', cycle: 0 };

        let specsHtml = '';

        if (hasSpecs) {
            const specPills = this.specialists.map(s => {
                const statusClass = s.status === 'thinking' ? 'spec-thinking' :
                                    s.status === 'done' ? 'spec-done' : '';
                return `<span class="spec-pill ${statusClass}" data-box="${s.id}" title="${s.name}: ${s.status} (cycle ${s.cycle})">
                    <span class="spec-dot"></span>
                    ${s.name}
                    ${s.status === 'done' ? ' \u2713' : ''}
                </span>`;
            }).join('');

            specsHtml = `
                <div class="viz-outer ${this._statusAnim('specialist')}" data-box="specialists">
                    <div class="viz-outer-label">Specialists</div>
                    <div class="viz-middle ${this._boxAnim(box2.status, 'box2')}" data-box="box2">
                        <div class="viz-middle-label">Box 2 \u00b7 Extrapolator</div>
                        <div class="viz-middle-meta">cycle ${box2.cycle} \u00b7 ${box2.status}</div>
                        <div class="viz-inner ${this._boxAnim(box1.status, 'box1')}" data-box="box1">
                            <div class="viz-inner-icon">\u25c8</div>
                            <div class="viz-inner-label">Box 1 \u00b7 Solver</div>
                            <div class="viz-inner-meta">cycle ${box1.cycle}</div>
                            <div class="viz-inner-status">${this._statusDots(box1)}</div>
                        </div>
                    </div>
                    <div class="spec-pills-row">${specPills}</div>
                </div>
            `;
        } else {
            specsHtml = `
                <div class="viz-middle no-outer ${this._boxAnim(box2.status, 'box2')}" data-box="box2">
                    <div class="viz-middle-label">Box 2 \u00b7 Extrapolator</div>
                    <div class="viz-middle-meta">cycle ${box2.cycle} \u00b7 ${box2.status}</div>
                    <div class="viz-inner ${this._boxAnim(box1.status, 'box1')}" data-box="box1">
                        <div class="viz-inner-icon">\u25c8</div>
                        <div class="viz-inner-label">Box 1 \u00b7 Solver</div>
                        <div class="viz-inner-meta">cycle ${box1.cycle}</div>
                        <div class="viz-inner-status">${this._statusDots(box1)}</div>
                    </div>
                </div>
            `;
        }

        this.container.innerHTML = specsHtml;
    }

    /**
     * Return the animation CSS class for a box status.
     * @private
     * @param {string} status
     * @returns {string}
     */
    _boxAnim(status, boxId) {
        let classes = '';
        if (boxId && this._flashTimers[boxId]) classes += ' box-flash';
        if (status === 'thinking') return 'box-thinking' + classes;
        if (status === 'concluding') return 'box-concluding' + classes;
        if (status === 'done') return 'box-done' + classes;
        if (status === 'error') return 'box-error' + classes;
        return 'box-idle' + classes;
    }

    /**
     * Return the animation CSS class for the specialist outer ring,
     * based on whether any specialist is currently thinking.
     * @private
     * @param {string} type
     * @returns {string}
     */
    _statusAnim(type) {
        const anyThinking = this.specialists.some(s => s.status === 'thinking');
        if (anyThinking) return 'box-thinking';
        const allDone = this.specialists.length > 0 && this.specialists.every(s => s.status === 'done');
        if (allDone) return 'box-done';
        return 'box-idle';
    }

    /**
     * Render cycle-progress dots (filled/unfilled) for a box.
     * @private
     * @param {object} box
     * @returns {string}
     */
    _statusDots(box) {
        const max = 10;
        const filled = Math.min(box.cycle, max);
        let dots = '';
        for (let i = 0; i < max; i++) {
            dots += i < filled ? '\u25cf' : '\u25cb';
        }
        return dots;
    }
}

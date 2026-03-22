/* ============================================================
   cost-display.js — Cost tracker UI with smooth animations
   ============================================================ */

class CostDisplay {
    constructor() {
        this.currentCost = 0;
        this.elements = {};
    }

    /**
     * Cache all cost-related DOM elements.
     * Must be called after DOMContentLoaded.
     */
    init() {
        this.elements = {
            current: document.getElementById('costCurrent'),
            budget: document.getElementById('costBudget'),
            pct: document.getElementById('costPct'),
            bar: document.getElementById('costBar'),
            burnRate: document.getElementById('burnRate'),
            projected: document.getElementById('projectedCost'),
            boxBars: document.getElementById('boxCostBars'),
            headerCost: document.getElementById('headerCost'),
            concludeBanner: document.getElementById('concludeBanner'),
        };
    }

    /**
     * Update the entire cost display from a cost_update payload.
     * @param {object} data  Server cost_update message data
     */
    update(data) {
        if (!this.elements.current) return;

        // Animate main cost number
        const prevCost = this.currentCost;
        this.currentCost = data.total_cost || 0;
        animateNumber(this.elements.current, prevCost, this.currentCost, 400);

        // Header cost
        this.elements.headerCost.textContent = formatCost(data.total_cost);
        this.elements.headerCost.classList.remove('hidden');

        // Budget
        this.elements.budget.textContent = formatCost(data.budget_cap);

        // Percentage
        this.elements.pct.textContent = (data.budget_pct || 0).toFixed(1) + '%';

        // Progress bar width
        const pct = Math.min(data.budget_pct || 0, 100);
        this.elements.bar.style.width = pct + '%';

        // Color the bar based on budget usage
        this.elements.bar.className = 'cost-bar';
        if (pct >= 95) this.elements.bar.classList.add('cost-bar-critical');
        else if (pct >= 80) this.elements.bar.classList.add('cost-bar-danger');
        else if (pct >= 60) this.elements.bar.classList.add('cost-bar-warning');
        else this.elements.bar.classList.add('cost-bar-ok');

        // Burn rate & projected total
        this.elements.burnRate.textContent = formatCost(data.burn_rate) + '/min';
        this.elements.projected.textContent = formatCost(data.projected_total);

        // Conclude banner
        if (data.should_conclude) {
            this.elements.concludeBanner.classList.remove('hidden');
        } else {
            this.elements.concludeBanner.classList.add('hidden');
        }

        // Per-box cost bars
        this.renderBoxBars(data.boxes, data.budget_cap);
    }

    /**
     * Render per-box cost breakdown bars.
     * @param {object} boxes   Map of boxId -> { total_cost }
     * @param {number} budget  Overall budget cap
     */
    renderBoxBars(boxes, budget) {
        if (!this.elements.boxBars || !boxes) return;

        let html = '';
        for (const [boxId, box] of Object.entries(boxes)) {
            if (boxId.startsWith('gate:')) continue; // Skip gate costs from display
            const pct = Math.min((box.total_cost / Math.max(budget, 0.01)) * 100, 100);
            const colorClass = getBoxColorClass(boxId);
            const name = getBoxShortName(boxId);
            html += `
                <div class="box-cost-row">
                    <span class="box-cost-label color-${colorClass}">${name}</span>
                    <div class="box-cost-track">
                        <div class="box-cost-fill color-${colorClass}-bg" style="width: ${pct}%"></div>
                    </div>
                    <span class="box-cost-value">${formatCost(box.total_cost)}</span>
                </div>
            `;
        }
        this.elements.boxBars.innerHTML = html;
    }

    /**
     * Set the budget label without running a full update.
     * @param {number} budget
     */
    setBudget(budget) {
        if (this.elements.budget) {
            this.elements.budget.textContent = formatCost(budget);
        }
    }

    /**
     * Reset all cost UI elements to their initial state.
     */
    reset() {
        this.currentCost = 0;
        if (this.elements.current) this.elements.current.textContent = '$0.00';
        if (this.elements.pct) this.elements.pct.textContent = '0%';
        if (this.elements.bar) this.elements.bar.style.width = '0%';
        if (this.elements.boxBars) this.elements.boxBars.innerHTML = '';
        if (this.elements.headerCost) this.elements.headerCost.classList.add('hidden');
        if (this.elements.concludeBanner) this.elements.concludeBanner.classList.add('hidden');
    }
}

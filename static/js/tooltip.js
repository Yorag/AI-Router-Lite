/**
 * Tooltip.js - A reusable, event-driven tooltip component
 */
const Tooltip = {
    tooltipEl: null,
    currentTarget: null,
    
    /**
     * Initializes the tooltip system by creating the tooltip element
     * and adding global event listeners.
     */
    init() {
        if (this.tooltipEl) return;

        // Create the main tooltip element and append it to the body
        this.tooltipEl = document.createElement('div');
        this.tooltipEl.className = 'tooltip-box';
        document.body.appendChild(this.tooltipEl);

        // Use event delegation for efficiency
        document.addEventListener('mouseover', this.handleMouseOver.bind(this));
        document.addEventListener('mouseout', this.handleMouseOut.bind(this));
        document.addEventListener('mousemove', this.handleMouseMove.bind(this));
    },

    handleMouseOver(event) {
        const target = event.target.closest('[data-tooltip-content]');
        if (target) {
            this.currentTarget = target;
            const content = target.getAttribute('data-tooltip-content');
            this.show(content);
        }
    },

    handleMouseOut(event) {
        if (this.currentTarget) {
            this.hide();
            this.currentTarget = null;
        }
    },

    handleMouseMove(event) {
        if (this.tooltipEl && this.tooltipEl.classList.contains('visible')) {
            this.position(event.clientX, event.clientY);
        }
    },

    /**
     * Shows the tooltip with the given content.
     * @param {string} content - The HTML content to display in the tooltip.
     */
    show(content) {
        if (!this.tooltipEl || !content) return;
        this.tooltipEl.innerHTML = content;
        this.tooltipEl.classList.add('visible');
    },

    /**
     * Hides the tooltip.
     */
    hide() {
        if (!this.tooltipEl) return;
        this.tooltipEl.classList.remove('visible');
    },

    /**
     * Positions the tooltip element near the specified coordinates.
     * @param {number} x - The x-coordinate (typically from mouse event).
     * @param {number} y - The y-coordinate (typically from mouse event).
     */
    position(x, y) {
        if (!this.tooltipEl) return;

        const offset = 10; // Distance from the cursor
        const { innerWidth, innerHeight } = window;
        const { offsetWidth, offsetHeight } = this.tooltipEl;

        let top = y + offset;
        let left = x + offset;

        // Adjust position to keep the tooltip within the viewport
        if (left + offsetWidth > innerWidth) {
            left = x - offsetWidth - offset;
        }
        if (top + offsetHeight > innerHeight) {
            top = y - offsetHeight - offset;
        }

        this.tooltipEl.style.left = `${left}px`;
        this.tooltipEl.style.top = `${top}px`;
    },

    /**
     * A special method for Chart.js integration.
     * @param {object} context - The Chart.js tooltip context.
     */
    externalTooltipHandler(context) {
        const tooltipModel = context.tooltip;

        if (tooltipModel.opacity === 0) {
            Tooltip.hide();
            return;
        }

        const titleLines = tooltipModel.title || [];
        const bodyLines = tooltipModel.body.map(b => b.lines);

        let innerHtml = '';

        titleLines.forEach(title => {
            innerHtml += `<div style="font-weight: 600; margin-bottom: 4px;">${title}</div>`;
        });

        bodyLines.forEach(body => {
            const lines = Array.isArray(body) ? body.join('\n').split('\n') : body.split('\n');
            lines.forEach(line => {
                if (line.trim()) {
                    innerHtml += `<div>${line}</div>`;
                }
            });
        });
        
        Tooltip.show(innerHtml);

        const position = context.chart.canvas.getBoundingClientRect();
        const x = position.left + tooltipModel.caretX;
        const y = position.top + tooltipModel.caretY;
        Tooltip.position(x, y);
    }
};
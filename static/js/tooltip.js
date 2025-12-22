/**
 * Tooltip.js - A reusable, event-driven tooltip component
 *
 * Tooltip定位策略：
 * - 普通元素hover: 固定显示在目标元素正上方（居中对齐）
 * - Chart.js图表: 跟随鼠标位置显示
 */
const Tooltip = {
    tooltipEl: null,
    currentTarget: null,
    isChartTooltip: false, // 标记当前是否为Chart.js tooltip
    
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
        // 添加mousemove监听，用于Chart.js tooltip跟随鼠标
        document.addEventListener('mousemove', this.handleMouseMove.bind(this));
    },

    handleMouseOver(event) {
        const target = event.target.closest('[data-tooltip-content]');
        if (target) {
            this.currentTarget = target;
            const content = target.getAttribute('data-tooltip-content');
            this.show(content);
            // 定位到目标元素正上方
            this.positionAboveElement(target);
        }
    },

    handleMouseOut(event) {
        const target = event.target.closest('[data-tooltip-content]');
        // 只有当离开的是当前tooltip绑定的元素时才隐藏
        if (target && target === this.currentTarget) {
            this.hide();
            this.currentTarget = null;
        }
    },

    handleMouseMove(event) {
        // 只有Chart.js tooltip需要跟随鼠标
        if (this.isChartTooltip && this.tooltipEl && this.tooltipEl.classList.contains('visible')) {
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
        this.isChartTooltip = false; // 重置Chart.js tooltip标记
    },

    /**
     * Positions the tooltip above the target element (centered horizontally).
     * @param {HTMLElement} element - The target element to position above.
     */
    positionAboveElement(element) {
        if (!this.tooltipEl || !element) return;

        const rect = element.getBoundingClientRect();
        const tooltipWidth = this.tooltipEl.offsetWidth;
        const tooltipHeight = this.tooltipEl.offsetHeight;
        const gap = 8; // 与元素的间距

        // 计算元素中心点（视口坐标）
        const elementCenterX = rect.left + rect.width / 2;
        const elementTop = rect.top;

        // tooltip居中于元素上方
        let left = elementCenterX - tooltipWidth / 2;
        let top = elementTop - tooltipHeight - gap;

        // 转换为页面坐标（加上滚动偏移）
        left += window.scrollX;
        top += window.scrollY;

        // 边界检查 - 水平方向
        const margin = 8;
        if (left < margin) {
            left = margin;
        }
        if (left + tooltipWidth > document.documentElement.scrollWidth - margin) {
            left = document.documentElement.scrollWidth - tooltipWidth - margin;
        }

        // 边界检查 - 如果上方空间不够，显示在下方
        if (top < window.scrollY + margin) {
            top = rect.bottom + gap + window.scrollY;
        }

        this.tooltipEl.style.left = `${left}px`;
        this.tooltipEl.style.top = `${top}px`;
    },

    /**
     * Positions the tooltip element near the specified coordinates (for Chart.js).
     * Uses the original positioning logic: offset from cursor position.
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
     * Tooltip will follow mouse position.
     * @param {object} context - The Chart.js tooltip context.
     */
    externalTooltipHandler(context) {
        const tooltipModel = context.tooltip;

        if (tooltipModel.opacity === 0) {
            Tooltip.hide();
            return;
        }

        // 标记为Chart.js tooltip，以便mousemove可以更新位置
        Tooltip.isChartTooltip = true;

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

        // 初始位置使用caretX/caretY，之后会由mousemove更新
        const position = context.chart.canvas.getBoundingClientRect();
        const x = position.left + tooltipModel.caretX;
        const y = position.top + tooltipModel.caretY;
        Tooltip.position(x, y);
    }
};
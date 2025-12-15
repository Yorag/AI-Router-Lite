/**
 * 日志监控模块
 */

const Logs = {
    logs: [],
    eventSource: null,
    isRealtime: false,

    async init() {
        await this.load();
    },

    async load() {
        await this.applyFilters();
    },

    async applyFilters() {
        const limit = document.getElementById('filter-limit')?.value || 100;
        const level = document.getElementById('filter-level')?.value || '';
        const type = document.getElementById('filter-type')?.value || '';
        const model = document.getElementById('filter-model')?.value || '';
        
        try {
            const data = await API.getLogs({
                limit: parseInt(limit),
                level: level || undefined,
                type: type || undefined,
                model: model || undefined
            });
            
            this.logs = data.logs || [];
            this.render();
        } catch (error) {
            console.error('Load logs error:', error);
            Toast.error('加载日志失败');
        }
    },

    render() {
        const container = document.getElementById('logs-container');
        
        if (this.logs.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">📜</div>
                    <div class="empty-state-text">暂无日志</div>
                </div>
            `;
            return;
        }

        container.innerHTML = this.logs.map(log => this.renderLogEntry(log)).join('');
    },

    renderLogEntry(log) {
        const levelClass = log.level || 'info';
        
        // 构建主消息
        let mainMessage = '';
        const keyLabel = log.api_key_name ? `[${log.api_key_name}]` : '';
        
        if (log.type === 'response' && log.model && log.provider && log.actual_model) {
            // 响应日志: [密钥] 请求模型 ==> Provider:实际模型, {token信息}
            let tokenInfo = '';
            if (log.total_tokens) {
                if (log.request_tokens || log.response_tokens) {
                    tokenInfo = `Tokens: ${log.total_tokens} ↑${log.request_tokens || 0} ↓${log.response_tokens || 0}`;
                } else {
                    tokenInfo = `Tokens: ${log.total_tokens}`;
                }
            }
            const durationInfo = log.duration_ms ? `${Math.round(log.duration_ms)}ms` : '';
            const infoItems = [tokenInfo, durationInfo].filter(Boolean).join(', ');
            mainMessage = `${keyLabel} ${log.model} ==> ${log.provider}:${log.actual_model}${infoItems ? `, {${infoItems}}` : ''}`;
        } else if (log.type === 'error') {
            // 错误日志: [密钥] 请求模型 错误信息
            mainMessage = `${keyLabel} ${log.model || ''} ${log.error || log.message || ''}`;
        } else {
            // 其他日志
            mainMessage = log.message || '';
        }
        
        if (log.error && log.type !== 'error') {
            mainMessage += ` <span style="color: var(--danger-color);">[错误: ${log.error}]</span>`;
        }
        
        // 构建元信息（仅显示未在主消息中展示的信息）
        const meta = [];
        
        // 对于非 response 类型，显示额外信息
        if (log.type !== 'response' && log.type !== 'error') {
            if (log.api_key_name) meta.push(`密钥: ${log.api_key_name}`);
            if (log.model) meta.push(`模型: ${log.model}`);
            if (log.provider) meta.push(`服务站: ${log.provider}`);
            if (log.total_tokens) {
                let tokenInfo = `Tokens: ${log.total_tokens}`;
                if (log.request_tokens || log.response_tokens) {
                    tokenInfo = `Tokens: ${log.total_tokens} ↑${log.request_tokens || 0} ↓${log.response_tokens || 0}`;
                }
                meta.push(tokenInfo);
            }
            if (log.duration_ms) meta.push(`耗时: ${Math.round(log.duration_ms)}ms`);
        }
        
        // 状态码始终显示（如果有）
        if (log.status_code && log.status_code !== 200) meta.push(`状态: ${log.status_code}`);
        
        return `
            <div class="log-entry level-${levelClass}">
                <span class="log-time">${log.timestamp_str || ''}</span>
                <span class="log-level ${levelClass}">${log.level}</span>
                <span class="log-type">${log.type}</span>
                <span class="log-message">${mainMessage}</span>
                ${meta.length > 0 ? `
                    <div class="log-meta">
                        ${meta.map(m => `<span>${m}</span>`).join('')}
                    </div>
                ` : ''}
            </div>
        `;
    },

    async refresh() {
        await this.applyFilters();
    },

    clear() {
        this.logs = [];
        this.render();
    },

    toggleRealtime() {
        const checkbox = document.getElementById('realtime-logs');
        this.isRealtime = checkbox.checked;
        
        if (this.isRealtime) {
            this.startRealtime();
        } else {
            this.stopRealtime();
        }
    },

    startRealtime() {
        if (this.eventSource) {
            this.eventSource.close();
        }
        
        this.eventSource = new EventSource('/api/logs/stream');
        
        this.eventSource.onmessage = (event) => {
            try {
                const log = JSON.parse(event.data);
                this.addRealtimeLog(log);
            } catch (error) {
                console.error('Parse log error:', error);
            }
        };
        
        this.eventSource.onerror = (error) => {
            console.error('SSE error:', error);
            Toast.error('实时日志连接断开');
            this.stopRealtime();
            document.getElementById('realtime-logs').checked = false;
        };
        
    },

    stopRealtime() {
        if (this.eventSource) {
            this.eventSource.close();
            this.eventSource = null;
        }
    },

    addRealtimeLog(log) {
        // 添加到顶部
        this.logs.unshift(log);
        
        // 限制数量
        const limit = parseInt(document.getElementById('filter-limit')?.value || 100);
        if (this.logs.length > limit) {
            this.logs = this.logs.slice(0, limit);
        }
        
        // 检查过滤条件
        const level = document.getElementById('filter-level')?.value || '';
        const type = document.getElementById('filter-type')?.value || '';
        const model = document.getElementById('filter-model')?.value || '';
        
        if (level && log.level !== level) return;
        if (type && log.type !== type) return;
        if (model && log.model !== model) return;
        
        // 添加新日志到页面顶部
        const container = document.getElementById('logs-container');
        const emptyState = container.querySelector('.empty-state');
        if (emptyState) {
            container.innerHTML = '';
        }
        
        const logHtml = this.renderLogEntry(log);
        container.insertAdjacentHTML('afterbegin', logHtml);
        
        // 移除多余的日志条目
        const entries = container.querySelectorAll('.log-entry');
        if (entries.length > limit) {
            for (let i = limit; i < entries.length; i++) {
                entries[i].remove();
            }
        }
        
        // 高亮新日志
        const newEntry = container.querySelector('.log-entry');
        if (newEntry) {
            newEntry.style.animation = 'highlight 1s ease';
        }
    }
};

// 添加高亮动画（使用 IIFE 避免变量名冲突）
(function() {
    const highlightStyle = document.createElement('style');
    highlightStyle.textContent = `
        @keyframes highlight {
            0% {
                background-color: rgba(99, 102, 241, 0.3);
            }
            100% {
                background-color: transparent;
            }
        }
    `;
    document.head.appendChild(highlightStyle);
})();
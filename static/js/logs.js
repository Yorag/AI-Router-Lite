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
        const keyword = document.getElementById('filter-keyword')?.value || '';
        
        try {
            const data = await API.getLogs({
                limit: parseInt(limit),
                level: level || undefined,
                type: type || undefined,
                keyword: keyword || undefined
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
                <tr>
                    <td colspan="7" class="empty-state-cell">
                        <div class="empty-state">
                            <div class="empty-state-icon">📜</div>
                            <div class="empty-state-text">暂无日志</div>
                        </div>
                    </td>
                </tr>
            `;
            return;
        }

        container.innerHTML = this.logs.map(log => this.renderLogEntry(log)).join('');
    },

    renderLogEntry(log) {
        const levelClass = log.level || 'info';
        
        // Time
        const time = log.timestamp_str || '';
        
        // Level
        const levelHtml = `<span class="log-level-badge ${levelClass}">${(log.level || 'INFO').toUpperCase()}</span>`;
        
        // Source/Type
        const typeHtml = `<span class="log-type-text">${log.type}</span>`;
        
        // Protocol
        const protocolHtml = log.protocol ? `<span class="log-protocol-tag" title="协议类型">${log.protocol}</span>` : '';
        
        // Content
        let contentHtml = '';
        const keyLabel = log.api_key_name ? `<span class="log-key-tag" title="密钥: ${log.api_key_name}">${log.api_key_name}</span>` : '';
        
        if (log.type === 'response' && log.model && log.provider && log.actual_model) {
             contentHtml = `
                <div class="log-content-row">
                    ${keyLabel}
                    ${protocolHtml}
                    <span class="log-model" title="请求模型">${log.model}</span>
                    <span class="log-arrow">⟹</span>
                    <span class="log-provider" title="服务站">${log.provider}</span>
                    <span class="log-divider">:</span>
                    <span class="log-actual-model" title="实际模型">${log.actual_model}</span>
                </div>
             `;
        } else if (log.type === 'error') {
            // 如果有路由信息（provider 和 actual_model），显示完整路由
            if (log.provider && log.actual_model) {
                contentHtml = `
                    <div class="log-content-row">
                        ${keyLabel}
                        <span class="log-model" title="请求模型">${log.model || ''}</span>
                        <span class="log-arrow">⟹</span>
                        <span class="log-provider" title="服务站">${log.provider}</span>
                        <span class="log-divider">:</span>
                        <span class="log-actual-model" title="实际模型">${log.actual_model}</span>
                        <span class="log-error-msg">${log.error || log.message || ''}</span>
                    </div>
                `;
            } else {
                // 没有路由信息时，保持原有显示
                contentHtml = `
                    <div class="log-content-row">
                        ${keyLabel}
                        <span class="log-model">${log.model || ''}</span>
                        <span class="log-error-msg">${log.error || log.message || ''}</span>
                    </div>
                `;
            }
        } else if (log.type === 'circuit_breaker') {
            contentHtml = `
                <div class="log-content-row">
                    <span class="log-msg">${log.message || ''}</span>
                    ${log.error ? `<span class="log-error-detail">${log.error}</span>` : ''}
                </div>
            `;
        } else if (log.type === 'sync') {
            // 同步日志：服务站更新显示provider，模型映射同步显示统一ID
            const syncLabel = log.path === '/provider-models' && log.provider
                ? `<span class="log-provider" title="服务站">${log.provider}</span>`
                : log.path === '/model-mapping' && log.model
                    ? `<span class="log-model" title="统一模型">${log.model}</span>`
                    : '';
            contentHtml = `
                <div class="log-content-row">
                    ${syncLabel}
                    <span class="log-msg">${log.message || ''}</span>
                </div>
            `;
        } else {
             contentHtml = `<div class="log-message-text">${log.message || ''}</div>`;
             if (log.error) {
                 contentHtml += `<div class="log-error-detail">${log.error}</div>`;
             }
        }

        // Tokens
        let tokensHtml = '<span class="text-muted">-</span>';
        if (log.total_tokens) {
            tokensHtml = `<div class="token-stats">
                <span class="token-total">${log.total_tokens.toLocaleString()}</span>
                <div class="token-details">
                    ${log.request_tokens ? `<span class="token-up" title="Input">↑${log.request_tokens.toLocaleString()}</span>` : ''}
                    ${log.response_tokens ? `<span class="token-down" title="Output">↓${log.response_tokens.toLocaleString()}</span>` : ''}
                </div>
            </div>`;
        }

        // Latency
        const latencyHtml = log.duration_ms ? `<span class="latency-tag">${Math.round(log.duration_ms)}ms</span>` : '<span class="text-muted">-</span>';

        // Status
        let statusClass = 'status-default';
        if (log.status_code) {
            if (log.status_code >= 200 && log.status_code < 300) statusClass = 'status-success';
            else if (log.status_code >= 400) statusClass = 'status-error';
        }
        const statusHtml = log.status_code ? `<span class="log-status ${statusClass}">${log.status_code}</span>` : '<span class="text-muted">-</span>';

        return `
            <tr class="log-row level-${levelClass}">
                <td class="col-time">${time}</td>
                <td class="col-level">${levelHtml}</td>
                <td class="col-type">${typeHtml}</td>
                <td class="col-content">${contentHtml}</td>
                <td class="col-tokens">${tokensHtml}</td>
                <td class="col-latency">${latencyHtml}</td>
                <td class="col-status">${statusHtml}</td>
            </tr>
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
        const keyword = document.getElementById('filter-keyword')?.value || '';
        
        if (level && log.level !== level) return;
        if (type && log.type !== type) return;
        // 关键词过滤：在消息、模型、provider、error 等字段中搜索
        if (keyword) {
            const searchText = keyword.toLowerCase();
            const matchFields = [
                log.message,
                log.model,
                log.provider,
                log.actual_model,
                log.error,
                log.api_key_name
            ].filter(Boolean).join(' ').toLowerCase();
            if (!matchFields.includes(searchText)) return;
        }
        
        // 添加新日志到页面顶部
        const container = document.getElementById('logs-container');
        const emptyState = container.querySelector('.empty-state');
        if (emptyState) {
            container.innerHTML = '';
        }
        
        const logHtml = this.renderLogEntry(log);
        container.insertAdjacentHTML('afterbegin', logHtml);
        
        // 移除多余的日志条目
        const entries = container.querySelectorAll('.log-row');
        if (entries.length > limit) {
            for (let i = limit; i < entries.length; i++) {
                entries[i].remove();
            }
        }
        
        // 高亮新日志
        const newEntry = container.querySelector('.log-row');
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
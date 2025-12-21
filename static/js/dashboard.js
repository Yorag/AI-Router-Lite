/**
 * 仪表板模块
 */

const Dashboard = {
    requestsChart: null,
    modelUsageChart: null,
    currentRange: 'day', // 'week' or 'day'
    selectedDate: null,   // YYYY-MM-DD
    selectedTag: '',      // 选中的标签（API Key Name）
 
    async init() {
        // 从后端获取"今天"的日期（确保时区一致）
        try {
            const sysStats = await API.getSystemStats();
            this.selectedDate = sysStats.today || new Date().toISOString().split('T')[0];
        } catch {
            this.selectedDate = new Date().toISOString().split('T')[0];
        }
        document.getElementById('stats-date-picker').value = this.selectedDate;
        
        // 默认显示今天，需要显示日期选择器并更新按钮状态
        document.getElementById('btn-range-week').classList.remove('active');
        document.getElementById('btn-range-day').classList.add('active');
        document.getElementById('date-picker-wrapper').style.display = 'block';

        // 加载标签列表
        await this.loadTags();
 
        await this.load();
        this.initCharts();
    },

    async loadTags() {
        try {
            const data = await API.listAPIKeys();
            const select = document.getElementById('stats-tag-select');
            
            select.innerHTML = '<option value="">全部密钥</option>';
            
            if (data && data.keys) {
                data.keys.forEach(key => {
                    const option = document.createElement('option');
                    option.value = key.name;
                    option.textContent = key.name;
                    select.appendChild(option);
                });
            }
        } catch (error) {
            console.error('Failed to load tags:', error);
        }
    },
 
    async load() {
        try {
            // 集中获取所有数据，避免重复 API 调用
            // 注意：getStats 也需要支持 tag 参数，以便获取过滤后的 Provider 统计
            const [sysStats, baseData, rangeData] = await Promise.all([
                API.getSystemStats(),
                API.getStats(this.selectedTag),
                this.currentRange === 'week'
                    ? API.getDailyStats(7, this.selectedTag)
                    : API.getLogStats(this.selectedDate, this.selectedTag)
            ]);
            
            // 使用获取的数据渲染各组件
            this.renderStats(sysStats, rangeData);
            this.renderProviderStatus(baseData, rangeData);
            this.renderCharts(rangeData);
        } catch (error) {
            console.error('Dashboard load error:', error);
            Toast.error('加载仪表板数据失败');
        }
    },

    async refresh() {
        await this.load();
    },

    // 切换统计范围
    switchRange(range) {
        this.currentRange = range;
        
        // 更新按钮状态
        document.getElementById('btn-range-week').classList.toggle('active', range === 'week');
        document.getElementById('btn-range-day').classList.toggle('active', range === 'day');
        
        // 显示/隐藏日期选择器
        document.getElementById('date-picker-wrapper').style.display = range === 'day' ? 'block' : 'none';

        // 刷新数据
        this.refresh();
    },

    // 日期变更
    onDateChange() {
        const date = document.getElementById('stats-date-picker').value;
        if (date) {
            this.selectedDate = date;
            this.refresh();
        }
    },

    // 标签变更
    onTagChange() {
        const tag = document.getElementById('stats-tag-select').value;
        this.selectedTag = tag;
        this.refresh();
    },

    // 渲染统计卡片
    renderStats(sysStats, rangeData) {
        // 活跃服务站
        document.getElementById('stat-providers').textContent =
            `${sysStats.providers.available_providers}/${sysStats.providers.total_providers}`;

        // 计算请求统计
        let requestStats;
        if (this.currentRange === 'week') {
            requestStats = rangeData.reduce((acc, day) => {
                acc.total_requests += day.total_requests;
                acc.successful_requests += day.successful_requests;
                acc.total_tokens += day.total_tokens || 0;
                return acc;
            }, { total_requests: 0, successful_requests: 0, total_tokens: 0 });
        } else {
            requestStats = {
                total_requests: rangeData.total_requests || 0,
                successful_requests: rangeData.successful_requests || 0,
                total_tokens: rangeData.total_tokens || 0
            };
        }
        
        document.getElementById('stat-requests').textContent = requestStats.total_requests.toLocaleString();
        document.getElementById('stat-tokens').textContent = requestStats.total_tokens.toLocaleString();
        
        const total = requestStats.total_requests || 0;
        const success = requestStats.successful_requests || 0;
        const rate = total > 0 ? ((success / total) * 100).toFixed(1) : '100';
        document.getElementById('stat-success-rate').textContent = `${rate}%`;
    },

    // 渲染服务站状态
    renderProviderStatus(baseData, rangeData) {
        const container = document.getElementById('provider-status-list');
        
        if (!baseData.providers || Object.keys(baseData.providers).length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon"><i class="ri-signal-tower-line"></i></div>
                    <div class="empty-state-text">暂无服务站</div>
                </div>
            `;
            return;
        }

        // 获取 provider_model_stats
        const rangeStats = this.currentRange === 'week'
            ? this.aggregateDailyStats(rangeData)
            : (rangeData.provider_model_stats || {});
        
        // 聚合每个服务站的统计
        const providerRangeStats = {};
        Object.entries(rangeStats).forEach(([providerName, models]) => {
            let total = 0, successful = 0;
            Object.values(models).forEach(stats => {
                total += stats.total || 0;
                successful += stats.successful || 0;
            });
            providerRangeStats[providerName] = { total, successful };
        });
        
        container.innerHTML = Object.entries(baseData.providers)
            .sort((a, b) => {
                const aStats = providerRangeStats[a[1].name || a[0]] || { total: 0 };
                const bStats = providerRangeStats[b[1].name || b[0]] || { total: 0 };
                return bStats.total - aStats.total;
            })
            .map(([id, info]) => {
            const providerName = info.name || id;
            const providerModelsStats = rangeStats[providerName];
            const currentStats = providerRangeStats[providerName] || { total: 0, successful: 0 };
            
            const tooltip = this.getProviderStatsTooltip(providerModelsStats);
            const tooltipAttr = tooltip ? `data-tooltip="${tooltip}"` : '';
            
            // 生成健康状态圆点
            const healthDotHtml = ProviderHealth.renderDot(info);

            const total = currentStats.total;
            const success = currentStats.successful;
            const rate = total > 0 ? ((success / total) * 100).toFixed(1) : '-';
            
            let rateClass = 'rate-neutral';
            if (total > 0) {
                const rateNum = (success / total) * 100;
                if (rateNum >= 95) rateClass = 'rate-success';
                else if (rateNum >= 80) rateClass = 'rate-warning';
                else rateClass = 'rate-danger';
            }

            return `
            <div class="provider-status-item compact" ${tooltipAttr}>
                <div class="provider-main">
                    ${healthDotHtml}
                    <span class="provider-name">${providerName}</span>
                </div>
                <div class="provider-meta">
                    <span class="provider-rate ${rateClass}">${rate}%</span>
                    <span class="provider-count">${total.toLocaleString()}</span>
                </div>
            </div>
        `}).join('');
    },

    /**
     * 渲染健康状态圆点 (Dashboard 专用版本)
     * @param {Object} info - Provider 统计信息对象
     * @returns {string} HTML 字符串
     */
    renderHealthDot(info) {
        const isEnabled = info.enabled !== false; // 默认为 true
        const status = info.status;
        
        // 手动禁用优先级最高
        if (!isEnabled) {
            return `<span class="provider-health-dot disabled" data-tooltip="已禁用"></span>`;
        }
        
        // 检查运行时状态
        if (status === 'permanently_disabled') {
            const reason = this.formatCooldownReason(info.cooldown_reason);
            const error = info.last_error ? `&#10;错误: ${info.last_error}` : '';
            return `<span class="provider-health-dot permanently_disabled" data-tooltip="已熔断: ${reason}${error}"></span>`;
        }
        
        if (status === 'cooling') {
            const reason = this.formatCooldownReason(info.cooldown_reason);
            const remaining = info.cooldown_remaining || '0s';
            return `<span class="provider-health-dot cooling" data-tooltip="冷却中: ${reason} (${remaining})"></span>`;
        }
        
        // 健康状态
        return `<span class="provider-health-dot healthy" data-tooltip="运行正常"></span>`;
    },

    /**
     * 格式化冷却原因
     */
    formatCooldownReason(reason) {
        const reasonMap = {
            'rate_limited': '触发限流',
            'server_error': '服务器错误',
            'timeout': '请求超时',
            'auth_failed': '认证失败',
            'network_error': '网络错误',
            'model_not_found': '模型不存在',
            'health_check_failed': '健康检测失败'
        };
        return reasonMap[reason] || reason || '未知原因';
    },

    // 聚合每日统计数据
    aggregateDailyStats(dailyStats) {
        const aggregated = {}; // provider -> model -> stats
        
        dailyStats.forEach(day => {
            const dayStats = day.provider_model_stats || {};
            Object.entries(dayStats).forEach(([provider, models]) => {
                if (!aggregated[provider]) aggregated[provider] = {};
                
                Object.entries(models).forEach(([model, stats]) => {
                    if (!aggregated[provider][model]) {
                        aggregated[provider][model] = {
                            total: 0, successful: 0, failed: 0, tokens: 0
                        };
                    }
                    
                    aggregated[provider][model].total += stats.total || 0;
                    aggregated[provider][model].successful += stats.successful || 0;
                    aggregated[provider][model].failed += stats.failed || 0;
                    aggregated[provider][model].tokens += stats.tokens || 0;
                });
            });
        });
        
        return aggregated;
    },

    getStatusText(status) {
        const statusMap = {
            'healthy': '健康',
            'cooling': '冷却中',
            'permanently_disabled': '已禁用'
        };
        return statusMap[status] || status;
    },

    // 生成服务站统计信息 Tooltip 内容
    getProviderStatsTooltip(providerModelsStats) {
        if (!providerModelsStats) return '';

        const statsList = [];
        
        Object.entries(providerModelsStats).forEach(([modelName, stat]) => {
            if (stat.total > 0) {
                const successRate = stat.total > 0
                    ? ((stat.successful / stat.total) * 100).toFixed(1) + '%'
                    : '0.0%';
                
                statsList.push({
                    name: modelName,
                    total: stat.total,
                    successRate: successRate,
                    tokens: stat.tokens
                });
            }
        });

        if (statsList.length === 0) return '';

        // 格式化每一行
        return statsList.map(m =>
            `${m.name} 请求: ${m.total} 成功率: ${m.successRate} Tokens: ${Utils.formatNumber(m.tokens || 0)}`
        ).join('&#10;');
    },

    initCharts() {
        // 请求趋势图
        const requestsCtx = document.getElementById('requestsChart');
        if (requestsCtx) {
            this.requestsChart = new Chart(requestsCtx, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [{
                        label: '请求数',
                        data: [],
                        borderColor: '#6366f1',
                        backgroundColor: 'rgba(99, 102, 241, 0.1)',
                        fill: true,
                        tension: 0.4
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            display: false
                        }
                    },
                    scales: {
                        x: {
                            grid: {
                                color: 'rgba(255, 255, 255, 0.1)'
                            },
                            ticks: {
                                color: '#94a3b8'
                            }
                        },
                        y: {
                            beginAtZero: true,
                            grid: {
                                color: 'rgba(255, 255, 255, 0.1)'
                            },
                            ticks: {
                                color: '#94a3b8'
                            }
                        }
                    }
                }
            });
        }

        // 模型使用分布图
        const modelUsageCtx = document.getElementById('modelUsageChart');
        if (modelUsageCtx) {
            this.modelUsageChart = new Chart(modelUsageCtx, {
                type: 'doughnut',
                data: {
                    labels: [],
                    datasets: [{
                        data: [],
                        backgroundColor: [
                            '#6366f1',
                            '#22c55e',
                            '#f59e0b',
                            '#ef4444',
                            '#3b82f6',
                            '#8b5cf6',
                            '#ec4899',
                            '#14b8a6'
                        ]
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            position: 'right',
                            labels: {
                                color: '#94a3b8',
                                padding: 16
                            }
                        },
                        // 使用外部 Tooltip
                        tooltip: {
                            enabled: false,
                            external: function(context) {
                                // Tooltip Element
                                let tooltipEl = document.getElementById('chartjs-tooltip');

                                // Create element on first render
                                if (!tooltipEl) {
                                    tooltipEl = document.createElement('div');
                                    tooltipEl.id = 'chartjs-tooltip';
                                    tooltipEl.classList.add('custom-tooltip');
                                    document.body.appendChild(tooltipEl);
                                }

                                // Hide if no tooltip
                                const tooltipModel = context.tooltip;
                                if (tooltipModel.opacity === 0) {
                                    tooltipEl.style.opacity = 0;
                                    return;
                                }

                                // Set Text
                                if (tooltipModel.body) {
                                    const titleLines = tooltipModel.title || [];
                                    const bodyLines = tooltipModel.body.map(b => b.lines);

                                    let innerHtml = '';

                                    titleLines.forEach(function(title) {
                                        innerHtml += '<div style="font-weight: 600; margin-bottom: 4px;">' + title + '</div>';
                                    });

                                    bodyLines.forEach(function(body, i) {
                                        // Chart.js may return body as an array of strings if callbacks.label returns an array
                                        // But here callbacks.label returns an array of strings (one per provider),
                                        // so bodyLines is an array of arrays if we have multiple datasets, or just an array of strings.
                                        // Let's handle it safely.
                                        // Handle potential string or array, and split by our custom separator
                                        const rawLines = Array.isArray(body) ? body : [body];
                                        const lines = rawLines.flatMap(l => l.split('|||'));
                                        
                                        lines.forEach(line => {
                                            if (line.trim()) {
                                                innerHtml += '<div>' + line + '</div>';
                                            }
                                        });
                                    });

                                    tooltipEl.innerHTML = innerHtml;
                                }

                                const position = context.chart.canvas.getBoundingClientRect();

                                // Display, position, and set styles for font
                                tooltipEl.style.opacity = 1;
                                tooltipEl.style.position = 'absolute';
                                tooltipEl.style.left = position.left + window.pageXOffset + tooltipModel.caretX + 'px';
                                tooltipEl.style.top = position.top + window.pageYOffset + tooltipModel.caretY + 'px';
                                tooltipEl.style.pointerEvents = 'none';
                            },
                            callbacks: {
                                label: () => ''
                            }
                        }
                    }
                }
            });
        }

        // 初始加载时需要单独获取数据
        this.load();
    },

    // 渲染图表
    renderCharts(rangeData) {
        if (this.currentRange === 'week') {
            this.renderWeekCharts(rangeData);
        } else {
            this.renderDayCharts(rangeData);
        }
    },

    // 渲染周视图图表
    renderWeekCharts(dailyStats) {
        // 趋势图
        if (this.requestsChart) {
            const labels = dailyStats.map(d => d.date.slice(5));
            const data = dailyStats.map(d => d.total_requests);
            this.requestsChart.data.labels = labels;
            this.requestsChart.data.datasets[0].label = '日请求量';
            this.requestsChart.data.datasets[0].data = data;
            this.requestsChart.update();
        }

        // 模型分布图
        if (this.modelUsageChart) {
            const aggregatedUsage = {};
            const aggregatedModelProviderStats = {};

            dailyStats.forEach(day => {
                if (day.model_usage) {
                    Object.entries(day.model_usage).forEach(([model, count]) => {
                        aggregatedUsage[model] = (aggregatedUsage[model] || 0) + count;
                    });
                }
                if (day.model_provider_stats) {
                    Object.entries(day.model_provider_stats).forEach(([model, providers]) => {
                        if (!aggregatedModelProviderStats[model]) aggregatedModelProviderStats[model] = {};
                        Object.entries(providers).forEach(([provider, stats]) => {
                            if (!aggregatedModelProviderStats[model][provider]) {
                                aggregatedModelProviderStats[model][provider] = { total: 0, successful: 0, failed: 0 };
                            }
                            aggregatedModelProviderStats[model][provider].total += stats.total || 0;
                            aggregatedModelProviderStats[model][provider].successful += stats.successful || 0;
                            aggregatedModelProviderStats[model][provider].failed += stats.failed || 0;
                        });
                    });
                }
            });
            this.updateModelChart(aggregatedUsage, aggregatedModelProviderStats);
        }
    },

    // 渲染日视图图表
    renderDayCharts(logStats) {
        // 趋势图
        if (this.requestsChart) {
            const hours = [];
            const counts = [];
            for (let i = 0; i < 24; i++) {
                const hour = i.toString().padStart(2, '0');
                hours.push(`${hour}:00`);
                counts.push(logStats.hourly_requests ? (logStats.hourly_requests[hour] || 0) : 0);
            }
            this.requestsChart.data.labels = hours;
            this.requestsChart.data.datasets[0].label = '小时请求量';
            this.requestsChart.data.datasets[0].data = counts;
            this.requestsChart.update();
        }

        // 模型分布图
        if (this.modelUsageChart) {
            this.updateModelChart(logStats.model_usage || {}, logStats.model_provider_stats || {});
        }
    },

    // 辅助：更新模型分布图
    updateModelChart(usageData, modelProviderStats = {}) {
        if (!this.modelUsageChart) return;

        const models = Object.keys(usageData);
        const counts = Object.values(usageData);

        // 如果没有数据，清空图表
        if (models.length === 0) {
            this.modelUsageChart.data.labels = [];
            this.modelUsageChart.data.datasets[0].data = [];
        } else {
            this.modelUsageChart.data.labels = models;
            this.modelUsageChart.data.datasets[0].data = counts;
        }
        
        // 更新 Tooltip 回调所需的数据
        this.modelUsageChart.options.plugins.tooltip.displayColors = false;
        this.modelUsageChart.options.plugins.tooltip.callbacks.title = (context) => {
            const first = context && context.length ? context[0] : null;
            const modelName = first ? first.label : '';
            const total = first ? first.raw : 0;
            return modelName ? [`${modelName} (Total: ${total})`] : [];
        };
        this.modelUsageChart.options.plugins.tooltip.callbacks.label = (context) => {
            const modelName = context.label;
            const total = context.raw;
            const providers = modelProviderStats[modelName] || {};
            
            const providerList = Object.entries(providers)
                .sort((a, b) => b[1].total - a[1].total); // 按调用量降序
            
            return providerList.map(([providerName, stats]) => {
                const percentage = total > 0 ? ((stats.total / total) * 100).toFixed(1) : '0.0';
                const successRate = stats.total > 0 ? ((stats.successful / stats.total) * 100).toFixed(1) : '0.0';
                return `- ${providerName}: ${stats.total} (${percentage}%, Success: ${successRate}%)`;
            }).join('|||'); // Join with special separator to ensure single string passed to external tooltip, then split there
        };
        
        this.modelUsageChart.update();
    }
};
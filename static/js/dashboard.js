/**
 * 仪表板模块
 */

const Dashboard = {
    requestsChart: null,
    modelUsageChart: null,
    currentRange: 'day', // 'week' or 'day'
    selectedDate: null,   // YYYY-MM-DD

    async init() {
        // 初始化日期选择器为今天
        this.selectedDate = new Date().toISOString().split('T')[0];
        document.getElementById('stats-date-picker').value = this.selectedDate;
        
        // 默认显示今天，需要显示日期选择器并更新按钮状态
        document.getElementById('btn-range-week').classList.remove('active');
        document.getElementById('btn-range-day').classList.add('active');
        document.getElementById('date-picker-wrapper').style.display = 'block';

        await this.load();
        this.initCharts();
    },

    async load() {
        try {
            await Promise.all([
                this.loadStats(),
                this.loadProviderStatus()
            ]);
        } catch (error) {
            console.error('Dashboard load error:', error);
            Toast.error('加载仪表板数据失败');
        }
    },

    async refresh() {
        await this.load();
        await this.loadChartData();
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

    async loadStats() {
        try {
            // 获取系统基础状态（活跃服务站）- 这个是全局的，不受日期影响
            const sysStats = await API.getSystemStats();
            document.getElementById('stat-providers').textContent =
                `${sysStats.providers.available_providers}/${sysStats.providers.total_providers}`;

            // 根据当前模式获取统计数据
            let requestStats = {};

            if (this.currentRange === 'week') {
                // 近一周：获取过去7天的聚合数据
                const dailyStats = await API.getDailyStats(7);
                
                // 聚合数据
                requestStats = dailyStats.reduce((acc, day) => {
                    acc.total_requests += day.total_requests;
                    acc.successful_requests += day.successful_requests;
                    acc.total_tokens += day.total_tokens || 0;
                    return acc;
                }, { total_requests: 0, successful_requests: 0, total_tokens: 0 });

            } else {
                // 指定日期：获取单日数据
                const logStats = await API.getLogStats(this.selectedDate);
                requestStats = {
                    total_requests: logStats.total_requests || 0,
                    successful_requests: logStats.successful_requests || 0,
                    total_tokens: logStats.total_tokens || 0
                };
            }
            
            // 更新请求统计卡片
            document.getElementById('stat-requests').textContent = requestStats.total_requests.toLocaleString();
            
            // 更新 Tokens 统计卡片
            document.getElementById('stat-tokens').textContent = requestStats.total_tokens.toLocaleString();
            
            // 计算成功率
            const total = requestStats.total_requests || 0;
            const success = requestStats.successful_requests || 0;
            const rate = total > 0 ? ((success / total) * 100).toFixed(1) : '100';
            document.getElementById('stat-success-rate').textContent = `${rate}%`;
            
        } catch (error) {
            console.error('Load stats error:', error);
        }
    },

    async loadProviderStatus() {
        try {
            // 获取基础状态（用于显示状态标签和冷却信息）
            const baseData = await API.getStats();
            const container = document.getElementById('provider-status-list');
            
            if (!baseData.providers || Object.keys(baseData.providers).length === 0) {
                container.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-state-icon">📡</div>
                        <div class="empty-state-text">暂无服务站</div>
                    </div>
                `;
                return;
            }

            // 获取当前时间范围的统计数据（用于 Tooltip）
            let rangeStats = {};
            if (this.currentRange === 'week') {
                const dailyStats = await API.getDailyStats(7);
                // 聚合7天的数据
                rangeStats = this.aggregateDailyStats(dailyStats);
            } else {
                const logStats = await API.getLogStats(this.selectedDate);
                rangeStats = logStats.provider_model_stats || {};
            }
            
            container.innerHTML = Object.entries(baseData.providers).map(([id, info]) => {
                // 使用当前时间范围的统计数据生成 Tooltip
                // 注意：rangeStats 是按 providerName 索引的，而 info.name 是 providerName
                const providerName = info.name || id;
                const providerModelsStats = rangeStats[providerName];
                
                const tooltip = this.getProviderStatsTooltip(providerModelsStats);
                const tooltipAttr = tooltip ? `data-tooltip="${tooltip}"` : '';
                
                return `
                <div class="provider-status-item" ${tooltipAttr}>
                    <div class="provider-status-info">
                        <h4>${info.name || id}</h4>
                        <div class="stats">
                            成功: ${info.successful_requests.toLocaleString()} / 总计: ${info.total_requests.toLocaleString()}
                            ${info.cooldown_remaining ? ` | 冷却中: ${info.cooldown_remaining}` : ''}
                        </div>
                    </div>
                    <span class="status-badge ${info.status}">${this.getStatusText(info.status)}</span>
                </div>
            `}).join('');
            
        } catch (error) {
            console.error('Load provider status error:', error);
        }
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
            `${m.name} 请求: ${m.total} 成功率: ${m.successRate} Tokens: ${(m.tokens || 0).toLocaleString()}`
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
                        // 预留 tooltip 对象，便于后续在 updateModelChart 中覆盖回调
                        tooltip: {
                            callbacks: {
                                label: () => ''
                            }
                        }
                    }
                }
            });
        }

        // 加载图表数据
        this.loadChartData();
    },

    async loadChartData() {
        try {
            if (this.currentRange === 'week') {
                await this.loadWeekChartData();
            } else {
                await this.loadDayChartData();
            }
        } catch (error) {
            console.error('Load chart data error:', error);
        }
    },

    // 加载近一周图表数据
    async loadWeekChartData() {
        const dailyStats = await API.getDailyStats(7);
        
        // 1. 更新趋势图 (按天)
        if (this.requestsChart) {
            const labels = dailyStats.map(d => d.date.slice(5)); // MM-DD
            const data = dailyStats.map(d => d.total_requests);

            this.requestsChart.data.labels = labels;
            this.requestsChart.data.datasets[0].label = '日请求量';
            this.requestsChart.data.datasets[0].data = data;
            this.requestsChart.update();
        }

        // 2. 更新模型分布图 (聚合7天)
        if (this.modelUsageChart) {
            const aggregatedUsage = {};
            const aggregatedModelProviderStats = {}; // unified_model -> provider -> stats

            dailyStats.forEach(day => {
                if (day.model_usage) {
                    Object.entries(day.model_usage).forEach(([model, count]) => {
                        aggregatedUsage[model] = (aggregatedUsage[model] || 0) + count;
                    });
                }
                
                // 聚合 model_provider_stats
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

    // 加载单日图表数据
    async loadDayChartData() {
        const logStats = await API.getLogStats(this.selectedDate);

        // 1. 更新趋势图 (按小时)
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

        // 2. 更新模型分布图
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
            });
        };
        
        this.modelUsageChart.update();
    }
};
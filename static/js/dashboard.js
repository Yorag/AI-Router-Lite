/**
 * 仪表板模块
 */

const Dashboard = {
    requestsChart: null,
    modelUsageChart: null,

    async init() {
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
        Toast.info('正在刷新...');
        await this.load();
        await this.loadChartData();
        Toast.success('刷新完成');
    },

    async loadStats() {
        try {
            const stats = await API.getSystemStats();
            
            // 更新统计卡片
            document.getElementById('stat-providers').textContent = 
                `${stats.providers.available_providers}/${stats.providers.total_providers}`;
            document.getElementById('stat-keys').textContent = 
                stats.api_keys.enabled_keys || 0;
            document.getElementById('stat-requests').textContent = 
                stats.logs.total_requests || 0;
            
            // 计算成功率
            const total = stats.logs.total_requests || 0;
            const success = stats.logs.successful_requests || 0;
            const rate = total > 0 ? ((success / total) * 100).toFixed(1) : '100';
            document.getElementById('stat-success-rate').textContent = `${rate}%`;
            
        } catch (error) {
            console.error('Load stats error:', error);
        }
    },

    async loadProviderStatus() {
        try {
            const data = await API.getStats();
            const container = document.getElementById('provider-status-list');
            
            if (!data.providers || Object.keys(data.providers).length === 0) {
                container.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-state-icon">📡</div>
                        <div class="empty-state-text">暂无服务站</div>
                    </div>
                `;
                return;
            }
            
            container.innerHTML = Object.entries(data.providers).map(([name, info]) => `
                <div class="provider-status-item">
                    <div class="provider-status-info">
                        <h4>${name}</h4>
                        <div class="stats">
                            成功: ${info.successful_requests} / 总计: ${info.total_requests}
                            ${info.cooldown_remaining ? ` | 冷却中: ${info.cooldown_remaining}` : ''}
                        </div>
                    </div>
                    <span class="status-badge ${info.status}">${this.getStatusText(info.status)}</span>
                </div>
            `).join('');
            
        } catch (error) {
            console.error('Load provider status error:', error);
        }
    },

    getStatusText(status) {
        const statusMap = {
            'healthy': '健康',
            'cooling': '冷却中',
            'permanently_disabled': '已禁用'
        };
        return statusMap[status] || status;
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
            // 加载日志统计
            const logStats = await API.getLogStats();
            
            // 更新请求趋势图（按小时）
            if (this.requestsChart && logStats.hourly_requests) {
                const hours = [];
                const counts = [];
                
                for (let i = 0; i < 24; i++) {
                    const hour = i.toString().padStart(2, '0');
                    hours.push(`${hour}:00`);
                    counts.push(logStats.hourly_requests[hour] || 0);
                }
                
                this.requestsChart.data.labels = hours;
                this.requestsChart.data.datasets[0].data = counts;
                this.requestsChart.update();
            }
            
            // 更新模型使用分布图
            if (this.modelUsageChart && logStats.model_usage) {
                const models = Object.keys(logStats.model_usage);
                const usage = Object.values(logStats.model_usage);
                
                if (models.length > 0) {
                    this.modelUsageChart.data.labels = models;
                    this.modelUsageChart.data.datasets[0].data = usage;
                    this.modelUsageChart.update();
                }
            }
            
        } catch (error) {
            console.error('Load chart data error:', error);
        }
    }
};
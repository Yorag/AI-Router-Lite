/**
 * Provider 管理模块
 */

const Providers = {
    providers: [],
    testResults: {},
    autoRefreshInterval: null,

    async init() {
        await this.load();
    },

    async load() {
        try {
            const data = await API.listProviders();
            this.providers = data.providers || [];
            
            // 加载测试结果
            const results = await API.getTestResults();
            this.testResults = results.results || {};
            
            this.render();
        } catch (error) {
            console.error('Load providers error:', error);
            Toast.error('加载服务站列表失败');
        }
    },

    render() {
        const container = document.getElementById('providers-list');
        
        if (this.providers.length === 0) {
            container.innerHTML = `
                <div class="empty-state" style="grid-column: 1 / -1;">
                    <div class="empty-state-icon">🌐</div>
                    <div class="empty-state-text">暂无服务站</div>
                    <div class="empty-state-hint">点击"添加服务站"按钮添加第一个服务站</div>
                </div>
            `;
            return;
        }

        container.innerHTML = this.providers.map(provider => this.renderProviderCard(provider)).join('');
    },

    renderProviderCard(provider) {
        const models = provider.supported_models || [];
        const testResults = provider.test_results || [];
        
        // 创建模型标签（带测试结果）
        const modelTags = models.map(model => {
            const result = testResults.find(r => r.model === model);
            let statusClass = '';
            let latencyText = '';
            
            if (result) {
                statusClass = result.success ? 'success' : 'error';
                if (result.latency_ms) {
                    latencyText = `<span class="latency">${Math.round(result.latency_ms)}ms</span>`;
                }
            }
            
            return `<span class="model-tag ${statusClass}">${model}${latencyText}</span>`;
        }).join('');

        return `
            <div class="provider-card">
                <div class="provider-card-header">
                    <div>
                        <h3>${provider.name}</h3>
                        <div class="url">${provider.base_url}</div>
                    </div>
                    <span class="status-badge info">权重: ${provider.weight}</span>
                </div>
                
                <div class="provider-models">
                    <h4>支持的模型 (${models.length})</h4>
                    <div class="model-tags">
                        ${modelTags || '<span class="model-tag">暂无模型</span>'}
                    </div>
                </div>
                
                <div class="provider-card-actions">
                    <button class="btn btn-sm btn-secondary" onclick="Providers.test('${provider.name}')">
                        🧪 测试
                    </button>
                    <button class="btn btn-sm btn-secondary" onclick="Providers.showEditModal('${provider.name}')">
                        ✏️ 编辑
                    </button>
                    <button class="btn btn-sm btn-secondary" onclick="Providers.reset('${provider.name}')">
                        🔄 重置状态
                    </button>
                    <button class="btn btn-sm btn-danger" onclick="Providers.confirmDelete('${provider.name}')">
                        🗑️ 删除
                    </button>
                </div>
            </div>
        `;
    },

    showCreateModal() {
        const content = `
            <form onsubmit="Providers.create(event)">
                <div class="form-group">
                    <label>服务站名称</label>
                    <input type="text" id="provider-name" required placeholder="例如：OpenAI-Main">
                </div>
                <div class="form-group">
                    <label>API 基础 URL</label>
                    <input type="url" id="provider-url" required placeholder="https://api.example.com/v1">
                    <div class="hint">OpenAI 兼容的 API 地址</div>
                </div>
                <div class="form-group">
                    <label>API Key</label>
                    <input type="text" id="provider-key" required placeholder="sk-...">
                </div>
                <div class="form-group">
                    <label>权重</label>
                    <input type="number" id="provider-weight" value="1" min="1" max="100">
                    <div class="hint">权重越高，被选中的概率越大</div>
                </div>
                <div class="form-group">
                    <label>超时时间 (秒)</label>
                    <input type="number" id="provider-timeout" placeholder="使用全局默认值">
                    <div class="hint">留空则使用全局配置</div>
                </div>
                <div class="form-group">
                    <label>支持的模型</label>
                    <textarea id="provider-models" rows="4" placeholder="每行一个模型名称&#10;例如：&#10;gpt-4&#10;gpt-3.5-turbo"></textarea>
                    <div class="hint">每行输入一个模型名称</div>
                </div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="Modal.close()">取消</button>
                    <button type="submit" class="btn btn-primary">添加服务站</button>
                </div>
            </form>
        `;
        Modal.show('添加服务站', content);
    },

    async create(event) {
        event.preventDefault();
        
        const name = document.getElementById('provider-name').value.trim();
        const baseUrl = document.getElementById('provider-url').value.trim();
        const apiKey = document.getElementById('provider-key').value.trim();
        const weight = parseInt(document.getElementById('provider-weight').value) || 1;
        const timeout = document.getElementById('provider-timeout').value;
        const modelsText = document.getElementById('provider-models').value.trim();
        
        const models = modelsText ? modelsText.split('\n').map(m => m.trim()).filter(m => m) : [];
        
        const data = {
            name,
            base_url: baseUrl,
            api_key: apiKey,
            weight,
            supported_models: models
        };
        
        if (timeout) {
            data.timeout = parseFloat(timeout);
        }
        
        try {
            await API.addProvider(data);
            Modal.close();
            Toast.success('服务站已添加');
            await this.load();
            
            // 提示重新加载配置
            this.showReloadHint();
        } catch (error) {
            Toast.error('添加失败: ' + error.message);
        }
    },

    showEditModal(name) {
        const provider = this.providers.find(p => p.name === name);
        if (!provider) return;
        
        const modelsText = (provider.supported_models || []).join('\n');
        
        const content = `
            <form onsubmit="Providers.update(event, '${name}')">
                <div class="form-group">
                    <label>服务站名称</label>
                    <input type="text" value="${provider.name}" disabled>
                    <div class="hint">名称不可修改</div>
                </div>
                <div class="form-group">
                    <label>API 基础 URL</label>
                    <input type="url" id="edit-provider-url" value="${provider.base_url}" required>
                </div>
                <div class="form-group">
                    <label>API Key</label>
                    <input type="text" id="edit-provider-key" value="${provider.api_key}" required>
                </div>
                <div class="form-group">
                    <label>权重</label>
                    <input type="number" id="edit-provider-weight" value="${provider.weight}" min="1" max="100">
                </div>
                <div class="form-group">
                    <label>超时时间 (秒)</label>
                    <input type="number" id="edit-provider-timeout" value="${provider.timeout || ''}" placeholder="使用全局默认值">
                </div>
                <div class="form-group">
                    <label>支持的模型</label>
                    <textarea id="edit-provider-models" rows="4">${modelsText}</textarea>
                    <div class="hint">每行输入一个模型名称</div>
                </div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="Modal.close()">取消</button>
                    <button type="submit" class="btn btn-primary">保存</button>
                </div>
            </form>
        `;
        Modal.show('编辑服务站', content);
    },

    async update(event, name) {
        event.preventDefault();
        
        const baseUrl = document.getElementById('edit-provider-url').value.trim();
        const apiKey = document.getElementById('edit-provider-key').value.trim();
        const weight = parseInt(document.getElementById('edit-provider-weight').value) || 1;
        const timeout = document.getElementById('edit-provider-timeout').value;
        const modelsText = document.getElementById('edit-provider-models').value.trim();
        
        const models = modelsText ? modelsText.split('\n').map(m => m.trim()).filter(m => m) : [];
        
        const data = {
            base_url: baseUrl,
            api_key: apiKey,
            weight,
            supported_models: models
        };
        
        if (timeout) {
            data.timeout = parseFloat(timeout);
        }
        
        try {
            await API.updateProvider(name, data);
            Modal.close();
            Toast.success('服务站已更新');
            await this.load();
            this.showReloadHint();
        } catch (error) {
            Toast.error('更新失败: ' + error.message);
        }
    },

    confirmDelete(name) {
        Modal.confirm(
            '确认删除',
            `确定要删除服务站 "${name}" 吗？此操作不可恢复。`,
            () => this.delete(name)
        );
    },

    async delete(name) {
        try {
            await API.deleteProvider(name);
            Toast.success('服务站已删除');
            await this.load();
            this.showReloadHint();
        } catch (error) {
            Toast.error('删除失败: ' + error.message);
        }
    },

    async test(name) {
        Toast.info(`正在测试 ${name}...`);
        
        try {
            const result = await API.testProvider(name);
            
            const successCount = result.results.filter(r => r.success).length;
            const totalCount = result.results.length;
            
            if (successCount === totalCount) {
                Toast.success(`${name} 测试通过 (${successCount}/${totalCount})`);
            } else if (successCount > 0) {
                Toast.warning(`${name} 部分通过 (${successCount}/${totalCount})`);
            } else {
                Toast.error(`${name} 测试失败`);
            }
            
            await this.load();
        } catch (error) {
            Toast.error('测试失败: ' + error.message);
        }
    },

    async testAll() {
        Toast.info('正在测试所有服务站...');
        
        try {
            const result = await API.testAllProviders();
            
            const successCount = result.results.filter(r => r.success).length;
            const totalCount = result.results.length;
            
            Toast.success(`测试完成 (${successCount}/${totalCount} 通过)`);
            await this.load();
        } catch (error) {
            Toast.error('测试失败: ' + error.message);
        }
    },

    async reset(name) {
        try {
            await API.resetProvider(name);
            Toast.success(`${name} 状态已重置`);
            await this.load();
        } catch (error) {
            Toast.error('重置失败: ' + error.message);
        }
    },

    toggleAutoRefresh() {
        const checkbox = document.getElementById('auto-refresh-providers');
        
        if (checkbox.checked) {
            this.startAutoRefresh();
        } else {
            this.stopAutoRefresh();
        }
    },

    startAutoRefresh() {
        if (this.autoRefreshInterval) return;
        
        this.autoRefreshInterval = setInterval(async () => {
            await this.testAll();
        }, 60000); // 每60秒
        
        Toast.info('已开启自动刷新测试');
    },

    stopAutoRefresh() {
        if (this.autoRefreshInterval) {
            clearInterval(this.autoRefreshInterval);
            this.autoRefreshInterval = null;
            Toast.info('已停止自动刷新测试');
        }
    },

    showReloadHint() {
        Modal.confirm(
            '配置已更新',
            '配置文件已更新。是否立即重新加载配置使更改生效？',
            async () => {
                try {
                    await API.reloadConfig();
                    Toast.success('配置已重新加载');
                } catch (error) {
                    Toast.error('重新加载失败: ' + error.message);
                }
            }
        );
    }
};
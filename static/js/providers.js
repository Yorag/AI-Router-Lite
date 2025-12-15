/**
 * Provider 管理模块
 */

// 从后端同步的常量配置
const PROVIDER_CONSTANTS = {
    // 自动更新模型间隔（毫秒）- 6小时
    AUTO_UPDATE_MODELS_INTERVAL_MS: 6 * 60 * 60 * 1000
};

const Providers = {
    providers: [],
    autoUpdateInterval: null,
    isUpdatingAll: false,  // 防止重复点击"更新全部渠道"按钮

    async init() {
        await this.load();
    },

    async load() {
        try {
            const data = await API.listProviders();
            this.providers = data.providers || [];
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

    // 模型显示阈值
    MODEL_DISPLAY_LIMIT: 5,

    renderProviderCard(provider) {
        const models = provider.supported_models || [];
        const providerName = provider.name;
        const providerId = this.escapeId(providerName);
        
        // 创建模型标签（带能力提示）
        const createModelTag = (model) => {
            const tooltip = this.getModelTooltip(providerName, model);
            const titleAttr = tooltip ? `title="${tooltip}"` : '';
            return `<span class="model-tag" ${titleAttr}>${model}</span>`;
        };

        let modelTagsHtml = '';
        if (models.length === 0) {
            modelTagsHtml = '<span class="model-tag">暂无模型</span>';
        } else if (models.length <= this.MODEL_DISPLAY_LIMIT) {
            // 模型数量不超过阈值，全部显示
            modelTagsHtml = models.map(createModelTag).join('');
        } else {
            // 超过阈值，显示前N个 + "more"按钮
            const visibleModels = models.slice(0, this.MODEL_DISPLAY_LIMIT);
            const hiddenModels = models.slice(this.MODEL_DISPLAY_LIMIT);
            const hiddenCount = hiddenModels.length;
            
            modelTagsHtml = `
                <div class="model-tags-visible">
                    ${visibleModels.map(createModelTag).join('')}
                    <span class="model-tag model-more-btn" onclick="Providers.toggleModelExpand('${providerId}')">
                        +${hiddenCount} more
                    </span>
                </div>
                <div class="model-tags-hidden" id="models-hidden-${providerId}" style="display: none;">
                    ${hiddenModels.map(createModelTag).join('')}
                    <span class="model-tag model-less-btn" onclick="Providers.toggleModelExpand('${providerId}')">
                        收起
                    </span>
                </div>
            `;
        }

        const isEnabled = provider.enabled !== false;
        const statusBadgeClass = isEnabled ? 'info' : 'warning';
        const statusText = isEnabled ? `权重: ${provider.weight}` : '已禁用';
        const toggleBtnText = isEnabled ? '⏸️ 禁用' : '▶️ 启用';
        const toggleBtnClass = isEnabled ? 'btn-warning' : 'btn-success';

        return `
            <div class="provider-card ${!isEnabled ? 'disabled' : ''}" id="provider-${providerId}">
                <div class="provider-card-header">
                    <div>
                        <h3>${provider.name}</h3>
                        <div class="url">${provider.base_url}</div>
                    </div>
                    <span class="status-badge ${statusBadgeClass}">${statusText}</span>
                </div>
                
                <div class="provider-models">
                    <h4>支持的模型 (${models.length})</h4>
                    <div class="model-tags">
                        ${modelTagsHtml}
                    </div>
                </div>
                
                <div class="provider-card-actions">
                    <button class="btn btn-sm ${toggleBtnClass}" onclick="Providers.toggleEnabled('${provider.name}', ${!isEnabled})">
                        ${toggleBtnText}
                    </button>
                    <button class="btn btn-sm btn-secondary" onclick="Providers.fetchModels('${provider.name}')">
                        📥 更新模型
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

    // 将服务站名称转换为安全的ID
    escapeId(name) {
        return name.replace(/[^a-zA-Z0-9]/g, '_');
    },

    // 切换模型列表展开/收起
    toggleModelExpand(providerId) {
        const hiddenContainer = document.getElementById(`models-hidden-${providerId}`);
        const providerCard = document.getElementById(`provider-${providerId}`);
        if (!hiddenContainer || !providerCard) return;

        const visibleContainer = providerCard.querySelector('.model-tags-visible');
        const moreBtn = visibleContainer?.querySelector('.model-more-btn');

        if (hiddenContainer.style.display === 'none') {
            // 展开
            hiddenContainer.style.display = 'flex';
            if (moreBtn) moreBtn.style.display = 'none';
        } else {
            // 收起
            hiddenContainer.style.display = 'none';
            if (moreBtn) moreBtn.style.display = 'inline-flex';
        }
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
                    <div class="hint">💡 模型列表会在添加后通过"📥 更新模型"按钮自动获取</div>
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
        
        // 模型列表不再在此处提交，通过"更新模型"按钮同步获取
        const data = {
            name,
            base_url: baseUrl,
            api_key: apiKey,
            weight
        };
        
        try {
            await API.addProvider(data);
            Modal.close();
            Toast.success('服务站已添加，请点击"📥 更新模型"按钮同步模型列表');
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
        
        const modelCount = (provider.supported_models || []).length;
        
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
                    <label>当前模型数量</label>
                    <div class="hint">📦 ${modelCount} 个模型（通过"📥 更新模型"按钮管理）</div>
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
        
        // 模型列表不再在此处提交，通过"更新模型"按钮同步获取
        const data = {
            base_url: baseUrl,
            api_key: apiKey,
            weight
        };
        
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

    async reset(name) {
        try {
            await API.resetProvider(name);
            Toast.success(`${name} 状态已重置`);
            await this.load();
        } catch (error) {
            Toast.error('重置失败: ' + error.message);
        }
    },

    async toggleEnabled(name, enabled) {
        try {
            await API.updateProvider(name, { enabled });
            Toast.success(`${name} 已${enabled ? '启用' : '禁用'}`);
            await this.load();
            this.showReloadHint();
        } catch (error) {
            Toast.error('操作失败: ' + error.message);
        }
    },

    // 存储模型详细信息（包含能力类型）
    modelDetails: {},

    async fetchModels(name) {
        // 获取对应的按钮用于防重复控制
        const providerId = this.escapeId(name);
        const providerCard = document.getElementById(`provider-${providerId}`);
        const btn = providerCard?.querySelector('.provider-card-actions .btn-secondary');
        
        // 防止重复点击
        if (btn && btn.disabled) {
            return;
        }
        
        const originalText = btn?.innerHTML;
        
        try {
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = '⏳ 更新中...';
            }
            
            const result = await API.fetchProviderModels(name);
            const models = result.models || [];
            const syncStats = result.sync_stats || {};
            
            if (models.length === 0) {
                Toast.warning('未获取到任何模型');
                return;
            }
            
            // 存储模型详细信息
            this.modelDetails[name] = {};
            models.forEach(m => {
                this.modelDetails[name][m.id] = m;
            });
            
            // 模型已自动保存到 provider_models.json，无需再调用 updateProvider
            const statsMsg = syncStats.added !== undefined
                ? `(新增: ${syncStats.added}, 更新: ${syncStats.updated}, 移除: ${syncStats.removed})`
                : '';
            Toast.success(`已同步 ${models.length} 个模型 ${statsMsg}`);
            await this.load();
            this.showReloadHint();
        } catch (error) {
            Toast.error('获取模型失败: ' + error.message);
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = originalText;
            }
        }
    },

    getModelTooltip(providerName, modelId) {
        const details = this.modelDetails[providerName]?.[modelId];
        if (!details || !details.owned_by) {
            return '';
        }
        return `owned_by: ${details.owned_by}`;
    },

    toggleAutoUpdate() {
        const checkbox = document.getElementById('auto-refresh-providers');
        
        if (checkbox.checked) {
            this.startAutoUpdateModels();
        } else {
            this.stopAutoUpdateModels();
        }
    },

    startAutoUpdateModels() {
        if (this.autoUpdateInterval) return;
        
        // 立即执行一次自动更新模型
        this.updateAllModels();
        
        this.autoUpdateInterval = setInterval(async () => {
            await this.updateAllModels();
        }, PROVIDER_CONSTANTS.AUTO_UPDATE_MODELS_INTERVAL_MS);
        
    },

    stopAutoUpdateModels() {
        if (this.autoUpdateInterval) {
            clearInterval(this.autoUpdateInterval);
            this.autoUpdateInterval = null;
        }
    },

    // 手动触发更新全部渠道（带防重复控制）
    async updateAllChannels() {
        // 防止重复点击
        if (this.isUpdatingAll) {
            Toast.warning('正在更新中，请稍候...');
            return;
        }
        
        const btn = document.getElementById('btn-update-all-channels');
        const originalText = btn?.innerHTML;
        
        try {
            this.isUpdatingAll = true;
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = '⏳ 更新中...';
            }
            
            // 复用现有的 updateAllModels 逻辑
            await this.updateAllModels();
            
        } finally {
            this.isUpdatingAll = false;
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = originalText;
            }
        }
    },

    async updateAllModels() {
        // 批量更新所有服务站的模型列表
        
        try {
            let updatedCount = 0;
            let totalModels = 0;
            
            for (const provider of this.providers) {
                try {
                    const result = await API.fetchProviderModels(provider.name);
                    const models = result.models || [];
                    
                    if (models.length > 0) {
                        // 存储模型详细信息
                        this.modelDetails[provider.name] = {};
                        models.forEach(m => {
                            this.modelDetails[provider.name][m.id] = m;
                        });
                        
                        // 模型已自动保存到 provider_models.json，无需再调用 updateProvider
                        updatedCount++;
                        totalModels += models.length;
                    }
                } catch (err) {
                    console.error(`更新 ${provider.name} 模型失败:`, err);
                }
            }
            
            Toast.success(`已同步 ${updatedCount} 个服务站，共 ${totalModels} 个模型`);
            await this.load();
            this.showReloadHint();
        } catch (error) {
            Toast.error('更新模型失败: ' + error.message);
        }
    },

    async showReloadHint() {
        try {
            await API.reloadConfig();
        } catch (error) {
            Toast.error('重新加载失败: ' + error.message);
        }
    }
};
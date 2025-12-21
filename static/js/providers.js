/**
 * Provider 管理模块
 */

const Providers = {
    providers: [],
    isUpdatingAll: false,  // 防止重复点击"更新全部渠道"按钮
    availableProtocols: [],  // 可用协议类型缓存
    
    // 排序相关
    sortMode: 'weight', // 'weight' (权重递减) | 'default' (默认排序)
    
    async init() {
        await this.loadProtocols();  // 加载协议类型
        await this.load();
        // 页面初始化时从后端加载模型详情缓存（支持 ToolTip 显示）
        await this.loadModelDetailsCache();
    },

    /**
     * 加载可用协议类型
     */
    async loadProtocols() {
        try {
            const result = await API.getAvailableProtocols();
            this.availableProtocols = result.protocols || [];
        } catch (err) {
            console.warn('加载协议类型失败:', err);
            // 使用默认值
            this.availableProtocols = [
                { value: 'openai', label: 'openai', description: 'OpenAI Chat Completions API' },
                { value: 'openai-response', label: 'openai-response', description: 'OpenAI Responses API' },
                { value: 'anthropic', label: 'anthropic', description: 'Anthropic Messages API' },
                { value: 'gemini', label: 'gemini', description: 'Google Gemini API' }
            ];
        }
    },

    /**
     * 从后端加载模型详情缓存
     * 用于页面刷新后恢复 ToolTip 数据
     */
    async loadModelDetailsCache() {
        try {
            const allModelsData = await API.fetchAllProviderModels();
            const providerModels = allModelsData.provider_models || {};
            
            // 更新本地模型详情缓存
            for (const [providerId, providerData] of Object.entries(providerModels)) {
                const models = providerData.models || [];
                if (models.length > 0) {
                    this.modelDetails[providerId] = {};
                    models.forEach(m => {
                        this.modelDetails[providerId][m.id] = {
                            id: m.id,
                            owned_by: m.owned_by || '',
                            supported_endpoint_types: m.supported_endpoint_types || []
                        };
                    });
                }
            }
        } catch (err) {
            // 静默失败，不影响页面加载
            console.warn('加载模型详情缓存失败:', err);
        }
    },

    async load() {
        try {
            const providersData = await API.listProviders();
            this.providers = providersData.providers || [];
            this.render();
        } catch (error) {
            console.error('Load providers error:', error);
            Toast.error('加载服务站列表失败');
        }
    },

    /**
     * 切换排序模式
     */
    toggleSortMode(mode) {
        if (this.sortMode === mode) return;
        this.sortMode = mode;
        
        // 更新按钮状态
        document.querySelectorAll('.sort-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.mode === mode);
        });
        
        this.render();
    },

    /**
     * 获取排序后的列表
     */
    getSortedProviders() {
        const list = [...this.providers];
        if (this.sortMode === 'weight') {
            // 权重递减排序
            return list.sort((a, b) => (b.weight || 0) - (a.weight || 0));
        }
        // 默认排序（保持 API 返回的原始顺序，即 config.json 中的顺序）
        return list;
    },

    render() {
        const container = document.getElementById('providers-list');
        
        // 渲染排序控件（如果还没渲染过）
        this.renderSortControls();
        
        if (this.providers.length === 0) {
            container.innerHTML = `
                <div class="empty-state" style="grid-column: 1 / -1;">
                    <div class="empty-state-icon"><i class="ri-server-line"></i></div>
                    <div class="empty-state-text">暂无服务站</div>
                    <div class="empty-state-hint">点击"添加服务站"按钮添加第一个服务站</div>
                </div>
            `;
            return;
        }

        const sortedProviders = this.getSortedProviders();
        container.innerHTML = sortedProviders.map(provider => this.renderProviderCard(provider)).join('');
    },

    renderSortControls() {
        const headerActions = document.querySelector('#page-providers .header-actions');
        if (!headerActions) return;
        
        // 检查是否已存在排序控件
        if (headerActions.querySelector('.sort-control')) return;
        
        const sortControlHtml = `
            <div class="sort-control toggle-group">
                <button class="toggle-btn sort-btn active" data-mode="weight" onclick="Providers.toggleSortMode('weight')">
                    权重排序
                </button>
                <button class="toggle-btn sort-btn" data-mode="default" onclick="Providers.toggleSortMode('default')">
                    默认排序
                </button>
            </div>
        `;
        
        // 插入到第一个位置
        headerActions.insertAdjacentHTML('afterbegin', sortControlHtml);
    },
    // 模型显示阈值
    MODEL_DISPLAY_LIMIT: 5,

    renderProviderCard(provider) {
        const supportedModels = provider.supported_models || [];
        const mappedSet = new Set(provider.mapped_models || []);
        
        // 构造模型对象列表用于排序和渲染
        const models = supportedModels.map(id => ({
            id: id,
            is_mapped: mappedSet.has(id)
        }));

        // 排序：已映射的模型排在前面，然后按字母顺序排序
        models.sort((a, b) => {
            if (a.is_mapped && !b.is_mapped) return -1;
            if (!a.is_mapped && b.is_mapped) return 1;
            return a.id.localeCompare(b.id);
        });

        const providerName = provider.name;
        const providerUuid = provider.id;  // UUID 用于 API 调用
        const providerDomId = this.escapeId(providerUuid);  // DOM ID 使用转义后的 UUID
        const allowModelUpdate = provider.allow_model_update !== false;
        
        // 创建模型标签（带能力提示）
        const createModelTag = (modelObj) => {
            const modelId = modelObj.id;
            const isMapped = modelObj.is_mapped;
            const tooltip = this.getModelTooltip(providerUuid, modelId);
            const tooltipAttr = tooltip ? `data-tooltip="${tooltip}"` : '';
            const mappedClass = isMapped ? 'mapped-model' : '';
            
            return `<span class="model-tag ${mappedClass}" ${tooltipAttr}>${modelId}</span>`;
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
                    <span class="model-tag model-more-btn" onclick="Providers.toggleModelExpand('${providerDomId}')">
                        +${hiddenCount} more
                    </span>
                </div>
                <div class="model-tags-hidden" id="models-hidden-${providerDomId}" style="display: none;">
                    ${hiddenModels.map(createModelTag).join('')}
                    <span class="model-tag model-less-btn" onclick="Providers.toggleModelExpand('${providerDomId}')">
                        收起
                    </span>
                </div>
            `;
        }

        const isEnabled = provider.enabled !== false;
        const statusText = `权重: ${provider.weight}`;
        
        // 如果禁止更新模型，则不显示更新模型按钮（或者显示为禁用）
        // 这里选择不渲染该按钮，因为通过编辑窗口手动管理
        const updateModelBtn = allowModelUpdate
            ? `<button class="btn btn-sm btn-secondary btn-fetch-models" onclick="Providers.fetchModels('${providerUuid}')">更新模型</button>`
            : '';
        
        // 生成健康状态圆点
        const healthDotHtml = ProviderHealth.renderDot(provider, { showHealthyTooltip: false });
        
        return `
            <div class="provider-card ${!isEnabled ? 'disabled' : ''}" id="provider-${providerDomId}" data-provider-id="${providerUuid}">
                <div class="provider-card-header">
                    <div>
                        <div class="provider-name-row">
                            ${healthDotHtml}
                            <h3>${providerName}</h3>
                        </div>
                        <div class="url">${provider.base_url}</div>
                    </div>
                    <div class="provider-badges">
                        <span class="status-badge info">${statusText}</span>
                        ${Utils.renderProtocolTag(provider.default_protocol)}
                    </div>
                </div>
                
                <div class="provider-models">
                    <div class="provider-models-header">
                        <h4>支持的模型 (${models.length})</h4>
                        ${provider.models_updated_at ? `<span class="last-updated" title="模型列表上次更新时间">${Utils.formatDateTime(new Date(provider.models_updated_at))}</span>` : ''}
                    </div>
                    <div class="model-tags">
                        ${modelTagsHtml}
                    </div>
                </div>
                
                <div class="provider-card-actions">
                    <label class="toggle-switch" title="${isEnabled ? '点击禁用' : '点击启用'}">
                        <input type="checkbox" ${isEnabled ? 'checked' : ''} onchange="Providers.toggleEnabled('${providerUuid}', this.checked)">
                        <span class="toggle-slider"></span>
                    </label>
                    <button class="btn btn-sm btn-secondary" onclick="Providers.showEditModal('${providerUuid}')">
                        编辑
                    </button>
                    ${updateModelBtn}
                    <button class="btn btn-sm btn-secondary" onclick="Providers.reset('${providerUuid}')">
                        重置状态
                    </button>
                    <button class="btn btn-sm btn-danger" onclick="Providers.confirmDelete('${providerUuid}')">
                        删除
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

    /**
     * 生成协议选择下拉框的选项 HTML
     */
    renderProtocolOptions(selectedValue = '') {
        const options = this.availableProtocols.map(p => {
            const selected = p.value === selectedValue ? 'selected' : '';
            return `<option value="${p.value}" ${selected}>${p.label}</option>`;
        }).join('');
        
        // 添加"Empty"选项（空值）
        const mixedSelected = !selectedValue ? 'selected' : '';
        return `<option value="" ${mixedSelected}>Empty (Not Specified)</option>${options}`;
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
                    <label>默认协议</label>
                    <select id="provider-protocol">
                        ${this.renderProtocolOptions('')}
                    </select>
                    <div class="hint">指定该渠道支持的 API 协议类型。如果指定，该渠道仅会被用于处理对应协议的请求（如 /v1/chat/completions 或 /v1/messages）。</div>
                </div>
                
                <div class="collapsible-section" id="advanced-settings-create">
                    <div class="collapsible-header" onclick="Providers.toggleAdvancedSettings('create')">
                        <h4><span class="collapsible-icon"><i class="ri-arrow-right-s-line"></i></span> 高级设置</h4>
                    </div>
                    <div class="collapsible-content">
                        <div class="collapsible-body">
                            <div class="form-group">
                                <label>超时时间 (秒)</label>
                                <input type="number" id="provider-timeout" placeholder="默认使用全局配置">
                                <div class="hint">请求超时时间，留空则使用全局设置</div>
                            </div>
                            <div class="checkbox-group">
                                <label class="checkbox-label">
                                    <input type="checkbox" id="provider-health-check" checked>
                                    允许模型健康检测
                                    <span class="hint-inline">（取消勾选将禁用自动和手动健康检测）</span>
                                </label>
                            </div>
                            <div class="checkbox-group">
                                <label class="checkbox-label">
                                    <input type="checkbox" id="provider-model-update" checked onchange="Providers.toggleModelUpdateMode(this.checked, 'create')">
                                    允许更新模型
                                    <span class="hint-inline">（取消勾选将启用手动输入模型列表）</span>
                                </label>
                            </div>
                            
                            <div id="manual-models-container-create" style="display: none; margin-top: 16px;">
                                <label>手动输入模型列表</label>
                                <div class="tag-input-container" id="tag-input-create">
                                    <div class="tag-input-tags" id="tag-input-tags-create"></div>
                                    <input type="text" class="tag-input-field" id="tag-input-field-create"
                                           placeholder="输入模型 ID 后按 Enter 添加"
                                           onkeydown="Providers.handleTagInput(event, 'create')">
                                </div>
                                <div class="tag-input-hint">按 Enter 添加模型，点击标签上的 × 删除</div>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="Modal.close()">取消</button>
                    <button type="submit" class="btn btn-primary">添加服务站</button>
                </div>
            </form>
        `;
        Modal.show('添加服务站', content);
    },

    // 存储手动输入的模型标签
    manualModelTags: {
        create: [],
        edit: []
    },

    toggleModelUpdateMode(allowed, mode) {
        const containerId = mode === 'create' ? 'manual-models-container-create' : 'manual-models-container-edit';
        const container = document.getElementById(containerId);
        if (container) {
            container.style.display = allowed ? 'none' : 'block';
        }
    },

    toggleAdvancedSettings(mode) {
        const sectionId = mode === 'create' ? 'advanced-settings-create' : 'advanced-settings-edit';
        const section = document.getElementById(sectionId);
        if (section) {
            section.classList.toggle('expanded');
        }
    },

    /**
     * 处理标签输入框的按键事件
     */
    handleTagInput(event, mode) {
        if (event.key === 'Enter') {
            event.preventDefault();
            const input = event.target;
            const value = input.value.trim();
            
            if (value) {
                this.addModelTag(value, mode);
                input.value = '';
            }
        }
    },

    /**
     * 添加模型标签
     */
    addModelTag(modelId, mode) {
        // 去重检查
        if (this.manualModelTags[mode].includes(modelId)) {
            return;
        }
        
        this.manualModelTags[mode].push(modelId);
        this.renderModelTags(mode);
    },

    /**
     * 删除模型标签
     */
    removeModelTag(modelId, mode) {
        const index = this.manualModelTags[mode].indexOf(modelId);
        if (index > -1) {
            this.manualModelTags[mode].splice(index, 1);
            this.renderModelTags(mode);
        }
    },

    /**
     * 渲染模型标签
     */
    renderModelTags(mode) {
        const container = document.getElementById(`tag-input-tags-${mode}`);
        if (!container) return;
        
        const tags = this.manualModelTags[mode];
        
        if (tags.length === 0) {
            container.innerHTML = '<span class="tag-input-empty">暂无模型，请在下方输入添加</span>';
            return;
        }
        
        container.innerHTML = tags.map(tag => `
            <span class="tag-input-tag">
                ${Utils.escapeHtml(tag)}
                <button type="button" class="tag-remove" onclick="Providers.removeModelTag('${Utils.escapeHtml(tag)}', '${mode}')" title="删除">×</button>
            </span>
        `).join('');
    },

    /**
     * 初始化标签输入（用于编辑模式）
     */
    initModelTags(mode, models) {
        this.manualModelTags[mode] = [...models];
        this.renderModelTags(mode);
    },

    async create(event) {
        event.preventDefault();
        
        const name = document.getElementById('provider-name').value.trim();
        const baseUrl = document.getElementById('provider-url').value.trim();
        const apiKey = document.getElementById('provider-key').value.trim();
        const weight = parseInt(document.getElementById('provider-weight').value) || 1;
        const protocol = document.getElementById('provider-protocol').value || null;
        
        const timeoutVal = document.getElementById('provider-timeout').value;
        const timeout = timeoutVal ? parseFloat(timeoutVal) : null;
        
        const allowHealthCheck = document.getElementById('provider-health-check').checked;
        const allowModelUpdate = document.getElementById('provider-model-update').checked;
        
        let manualModels = null;
        if (!allowModelUpdate) {
            manualModels = [...this.manualModelTags.create];
        }
        
        // 清理标签数据
        this.manualModelTags.create = [];
        
        const data = {
            name,
            base_url: baseUrl,
            api_key: apiKey,
            weight,
            timeout,
            allow_health_check: allowHealthCheck,
            allow_model_update: allowModelUpdate,
            default_protocol: protocol,
            manual_models: manualModels
        };
        
        try {
            await API.addProvider(data);
            Modal.close();
            await this.load();
            
        } catch (error) {
            Toast.error('添加失败: ' + error.message);
        }
    },

    showEditModal(providerId) {
        const provider = this.providers.find(p => p.id === providerId);
        if (!provider) return;
        
        const currentProtocol = provider.default_protocol || '';
        const timeoutValue = provider.timeout !== undefined && provider.timeout !== null ? provider.timeout : '';
        const allowHealthCheck = provider.allow_health_check !== false; // 默认为 true
        const allowModelUpdate = provider.allow_model_update !== false; // 默认为 true
        
        // 获取当前模型列表（如果有），用于手动编辑填充

        const content = `
            <form onsubmit="Providers.update(event, '${providerId}')">
                <div class="form-group">
                    <label>服务站名称</label>
                    <input type="text" id="edit-provider-name" value="${provider.name}" required>
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
                    <label>默认协议</label>
                    <select id="edit-provider-protocol">
                        ${this.renderProtocolOptions(currentProtocol)}
                    </select>
                    <div class="hint">指定该渠道支持的 API 协议类型。如果指定，该渠道仅会被用于处理对应协议的请求（如 /v1/chat/completions 或 /v1/messages）。</div>
                </div>
                
                <div class="collapsible-section" id="advanced-settings-edit">
                    <div class="collapsible-header" onclick="Providers.toggleAdvancedSettings('edit')">
                        <h4><span class="collapsible-icon"><i class="ri-arrow-right-s-line"></i></span> 高级设置</h4>
                    </div>
                    <div class="collapsible-content">
                        <div class="collapsible-body">
                            <div class="form-group">
                                <label>超时时间 (秒)</label>
                                <input type="number" id="edit-provider-timeout" value="${timeoutValue}" placeholder="默认使用全局配置">
                                <div class="hint">请求超时时间，留空则使用全局设置</div>
                            </div>
                            <div class="checkbox-group">
                                <label class="checkbox-label">
                                    <input type="checkbox" id="edit-provider-health-check" ${allowHealthCheck ? 'checked' : ''}>
                                    允许模型健康检测
                                    <span class="hint-inline">（取消勾选将禁用自动和手动健康检测）</span>
                                </label>
                            </div>
                            <div class="checkbox-group">
                                <label class="checkbox-label">
                                    <input type="checkbox" id="edit-provider-model-update" ${allowModelUpdate ? 'checked' : ''} onchange="Providers.toggleModelUpdateMode(this.checked, 'edit')">
                                    允许更新模型
                                    <span class="hint-inline">（取消勾选将启用手动输入模型列表）</span>
                                </label>
                            </div>
                            
                            <div id="manual-models-container-edit" style="display: ${allowModelUpdate ? 'none' : 'block'}; margin-top: 16px;">
                                <label>手动输入模型列表</label>
                                <div class="tag-input-container" id="tag-input-edit">
                                    <div class="tag-input-tags" id="tag-input-tags-edit"></div>
                                    <input type="text" class="tag-input-field" id="tag-input-field-edit"
                                           placeholder="输入模型 ID 后按 Enter 添加"
                                           onkeydown="Providers.handleTagInput(event, 'edit')">
                                </div>
                                <div class="tag-input-hint">按 Enter 添加模型，点击标签上的 × 删除</div>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="Modal.close()">取消</button>
                    <button type="submit" class="btn btn-primary">保存</button>
                </div>
            </form>
        `;
        Modal.show('编辑服务站', content);
        
        // 初始化编辑模式的标签
        // 当 `allow_model_update` 为 false 时，`supported_models` 包含手动输入的模型列表
        // 直接使用该列表，并过滤掉可能的 null/undefined 值
        const existingModels = provider.supported_models ? provider.supported_models.filter(m => m) : [];
        setTimeout(() => {
            this.initModelTags('edit', existingModels);
        }, 50);
    },

    async update(event, providerId) {
        event.preventDefault();
        
        const name = document.getElementById('edit-provider-name').value.trim();
        const baseUrl = document.getElementById('edit-provider-url').value.trim();
        const apiKey = document.getElementById('edit-provider-key').value.trim();
        const weight = parseInt(document.getElementById('edit-provider-weight').value) || 1;
        const protocol = document.getElementById('edit-provider-protocol').value || null;
        
        const timeoutVal = document.getElementById('edit-provider-timeout').value;
        const timeout = timeoutVal ? parseFloat(timeoutVal) : null;
        
        const allowHealthCheck = document.getElementById('edit-provider-health-check').checked;
        const allowModelUpdate = document.getElementById('edit-provider-model-update').checked;
        
        let manualModels = null;
        if (!allowModelUpdate) {
            manualModels = [...this.manualModelTags.edit];
        }
        
        // 清理标签数据
        this.manualModelTags.edit = [];
        
        const data = {
            name,  // 允许修改名称
            base_url: baseUrl,
            api_key: apiKey,
            weight,
            timeout,
            allow_health_check: allowHealthCheck,
            allow_model_update: allowModelUpdate,
            default_protocol: protocol,
            manual_models: manualModels
        };
        
        try {
            await API.updateProvider(providerId, data);
            Modal.close();
            await this.load();
        } catch (error) {
            Toast.error('更新失败: ' + error.message);
        }
    },

    confirmDelete(providerId) {
        const provider = this.providers.find(p => p.id === providerId);
        const displayName = provider ? provider.name : providerId;
        Modal.confirm(
            '确认删除',
            `确定要删除服务站 "${displayName}" 吗？此操作不可恢复。`,
            () => this.delete(providerId)
        );
    },

    async delete(providerId) {
        try {
            await API.deleteProvider(providerId);
            Toast.success('服务站已删除');
            await this.load();
        } catch (error) {
            Toast.error('删除失败: ' + error.message);
        }
    },

    async reset(providerId) {
        try {
            await API.resetProvider(providerId);
            const provider = this.providers.find(p => p.id === providerId);
            const displayName = provider ? provider.name : providerId;
            Toast.success(`${displayName} 状态已重置`);
            await this.load();
        } catch (error) {
            Toast.error('重置失败: ' + error.message);
        }
    },

    async toggleEnabled(providerId, enabled) {
        try {
            await API.updateProvider(providerId, { enabled });
            const provider = this.providers.find(p => p.id === providerId);
            const displayName = provider ? provider.name : providerId;
            Toast.success(`${displayName} 已${enabled ? '启用' : '禁用'}`);
            await this.load();
        } catch (error) {
            Toast.error('操作失败: ' + error.message);
        }
    },

    // 存储模型详细信息（包含能力类型）
    modelDetails: {},

    async fetchModels(providerId) {
        // 获取对应的按钮用于防重复控制
        const providerDomId = this.escapeId(providerId);
        const providerCard = document.getElementById(`provider-${providerDomId}`);
        const btn = providerCard?.querySelector('.provider-card-actions .btn-fetch-models');
        
        // 防止重复点击
        if (btn && btn.disabled) {
            return;
        }
        
        const originalText = btn?.innerHTML;
        
        try {
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = '更新中...';
            }
            
            const result = await API.fetchProviderModels(providerId);
            const models = result.models || [];
            const syncStats = result.sync_stats || {};
            
            // 存储模型详细信息，使用 providerId 作为 key
            this.modelDetails[providerId] = {};
            models.forEach(m => {
                this.modelDetails[providerId][m.id] = m;
            });
            
            const statsMsg = `(新增: ${syncStats.added}, 更新: ${syncStats.updated}, 移除: ${syncStats.removed})`;
            Toast.success(`已同步 ${models.length} 个模型 ${statsMsg}`);
            await this.load();
        } catch (error) {
            Toast.error('获取模型失败: ' + error.message);
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = originalText;
            }
        }
    },

    getModelTooltip(providerId, modelId) {
        const details = this.modelDetails[providerId]?.[modelId];
        if (!details) {
            return '';
        }
        
        const parts = [];
        if (details.owned_by) {
            parts.push(`owned_by: ${details.owned_by}`);
        }
        if (details.supported_endpoint_types && details.supported_endpoint_types.length > 0) {
            parts.push(`endpoints: ${details.supported_endpoint_types.join(', ')}`);
        }
        
        return parts.join('\n');
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
                btn.innerHTML = '更新中...';
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
        // 使用后端并发API批量更新所有服务站的模型列表
        
        try {
            // 调用后端并发同步API（后端使用 asyncio.gather 并发请求）
            const result = await API.syncAllProviderModels();
            
            // 一次性获取所有模型详情（从 provider_models.json 读取，无需再次网络请求各中转站）
            try {
                const allModelsData = await API.fetchAllProviderModels();
                const providerModels = allModelsData.provider_models || {};
                
                // 更新本地模型详情缓存
                for (const [providerId, providerData] of Object.entries(providerModels)) {
                    const models = providerData.models || [];
                    if (models.length > 0) {
                        this.modelDetails[providerId] = {};
                        models.forEach(m => {
                            this.modelDetails[providerId][m.id] = m;
                        });
                    }
                }
            } catch (err) {
                // 缓存更新失败不影响整体流程
                console.warn('更新模型详情缓存失败:', err);
            }
            
            Toast.success(`已并发同步 ${result.synced_count || 0} 个服务站，共 ${result.total_models || 0} 个模型`);
            await this.load();
        } catch (error) {
            Toast.error('更新模型失败: ' + error.message);
        }
    },

};
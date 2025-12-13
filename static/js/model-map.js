/**
 * 模型映射管理模块（增强型）
 * 
 * 支持规则匹配、手动包含/排除、自动同步
 */

const ModelMap = {
    mappings: {},           // 映射配置
    syncConfig: {},         // 同步配置
    providerModels: {},     // 缓存各中转站的模型列表
    currentProviderModels: [], // 当前选中的中转站模型
    previewResult: {},      // 预览结果缓存
    healthResults: {},      // 健康检测结果缓存 {provider:model -> result}

    // 规则类型选项
    RULE_TYPES: [
        { value: 'keyword', label: '关键字匹配', hint: '模型名包含该关键字即匹配' },
        { value: 'regex', label: '正则表达式', hint: '使用正则表达式匹配' },
        { value: 'prefix', label: '前缀匹配', hint: '模型名以该前缀开头即匹配' },
        { value: 'exact', label: '精确匹配', hint: '模型名完全相同才匹配' }
    ],

    async init() {
        await this.load();
    },

    async load() {
        try {
            const data = await API.getModelMappings();
            this.mappings = data.mappings || {};
            this.syncConfig = data.sync_config || {};
            
            // 加载健康检测结果
            await this.loadHealthResults();
            
            this.render();
        } catch (error) {
            console.error('Load model mappings error:', error);
            Toast.error('加载模型映射失败');
        }
    },

    async loadHealthResults() {
        try {
            const data = await API.getAllHealthResults();
            this.healthResults = data.results || {};
        } catch (error) {
            console.error('Load health results error:', error);
            this.healthResults = {};
        }
    },

    render() {
        const container = document.getElementById('model-map-list');
        const entries = Object.entries(this.mappings);
        
        // 渲染同步配置
        this.renderSyncConfig();
        
        if (entries.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">🔄</div>
                    <div class="empty-state-text">暂无模型映射</div>
                    <div class="empty-state-hint">点击"添加映射"按钮创建模型映射规则</div>
                </div>
            `;
            return;
        }

        container.innerHTML = entries.map(([unifiedName, mapping]) => {
            const rulesText = this.formatRules(mapping.rules || []);
            const totalModels = this.countModels(mapping.resolved_models || {});
            const providerCount = Object.keys(mapping.resolved_models || {}).length;
            const lastSync = mapping.last_sync ? new Date(mapping.last_sync).toLocaleString() : '未同步';
            const excludedProviders = mapping.excluded_providers || [];
            
            return `
                <div class="model-map-item">
                    <div class="model-map-header">
                        <div class="model-map-title">
                            <h4>📌 ${unifiedName}</h4>
                            ${mapping.description ? `<span class="model-map-desc">${mapping.description}</span>` : ''}
                        </div>
                        <div class="actions">
                            <button class="btn btn-sm btn-primary" onclick="ModelMap.syncSingle('${unifiedName}')" title="同步此映射">
                                🔄 同步
                            </button>
                            <button class="btn btn-sm btn-secondary" onclick="ModelMap.testMappingHealth('${unifiedName}')" title="检测此映射下所有模型的健康状态">
                                🔬 检测健康
                            </button>
                            <button class="btn btn-sm btn-secondary" onclick="ModelMap.showEditModal('${unifiedName}')">
                                编辑
                            </button>
                            <button class="btn btn-sm btn-danger" onclick="ModelMap.confirmDelete('${unifiedName}')">
                                删除
                            </button>
                        </div>
                    </div>
                    <div class="model-map-info">
                        <div class="info-row">
                            <span class="info-label">匹配规则:</span>
                            <span class="info-value">${rulesText || '<em>无规则</em>'}</span>
                        </div>
                        <div class="info-row">
                            <span class="info-label">匹配结果:</span>
                            <span class="info-value">${totalModels} 个模型 来自 ${providerCount} 个渠道</span>
                        </div>
                        ${excludedProviders.length > 0 ? `
                        <div class="info-row">
                            <span class="info-label">排除渠道:</span>
                            <span class="info-value excluded-providers-list">${excludedProviders.map(p => `<span class="excluded-provider-tag">🚫 ${p}</span>`).join(' ')}</span>
                        </div>
                        ` : ''}
                        ${(mapping.manual_excludes || []).length > 0 ? `
                        <div class="info-row">
                            <span class="info-label">手动排除:</span>
                            <span class="info-value">${mapping.manual_excludes.join(', ')}</span>
                        </div>
                        ` : ''}
                        ${(mapping.manual_includes || []).length > 0 ? `
                        <div class="info-row">
                            <span class="info-label">手动包含:</span>
                            <span class="info-value">${mapping.manual_includes.join(', ')}</span>
                        </div>
                        ` : ''}
                        <div class="info-row">
                            <span class="info-label">上次同步:</span>
                            <span class="info-value">${lastSync}</span>
                        </div>
                    </div>
                    ${this.renderResolvedModels(mapping.resolved_models || {})}
                </div>
            `;
        }).join('');
    },

    renderSyncConfig() {
        const configContainer = document.getElementById('sync-config-area');
        if (!configContainer) return;
        
        const { auto_sync_enabled, auto_sync_interval_hours, last_full_sync } = this.syncConfig;
        const lastSyncText = last_full_sync ? new Date(last_full_sync).toLocaleString() : '从未';
        
        configContainer.innerHTML = `
            <div class="sync-config-bar">
                <div class="sync-config-item">
                    <label>
                        <input type="checkbox" id="auto-sync-enabled" 
                            ${auto_sync_enabled ? 'checked' : ''} 
                            onchange="ModelMap.toggleAutoSync(this.checked)">
                        自动同步
                    </label>
                </div>
                <div class="sync-config-item">
                    <label>间隔:</label>
                    <select id="sync-interval" onchange="ModelMap.updateSyncInterval(this.value)" 
                        ${!auto_sync_enabled ? 'disabled' : ''}>
                        <option value="1" ${auto_sync_interval_hours === 1 ? 'selected' : ''}>1小时</option>
                        <option value="3" ${auto_sync_interval_hours === 3 ? 'selected' : ''}>3小时</option>
                        <option value="6" ${auto_sync_interval_hours === 6 ? 'selected' : ''}>6小时</option>
                        <option value="12" ${auto_sync_interval_hours === 12 ? 'selected' : ''}>12小时</option>
                        <option value="24" ${auto_sync_interval_hours === 24 ? 'selected' : ''}>24小时</option>
                    </select>
                </div>
                <div class="sync-config-item">
                    <span class="sync-status">上次全量同步: ${lastSyncText}</span>
                </div>
            </div>
        `;
    },

    formatRules(rules) {
        if (!rules || rules.length === 0) return '';
        return rules.map(r => {
            const typeLabel = this.RULE_TYPES.find(t => t.value === r.type)?.label || r.type;
            return `<span class="rule-tag" title="${typeLabel}">${r.type}:${r.pattern}</span>`;
        }).join(' ');
    },

    countModels(resolvedModels) {
        let count = 0;
        for (const models of Object.values(resolvedModels)) {
            count += models.length;
        }
        return count;
    },

    renderResolvedModels(resolvedModels) {
        const entries = Object.entries(resolvedModels);
        if (entries.length === 0) {
            return '<div class="resolved-models"><em>无匹配模型，请配置规则后同步</em></div>';
        }
        
        return `
            <div class="resolved-models collapsed" id="resolved-models-toggle">
                <div class="resolved-toggle" onclick="ModelMap.toggleResolved(this)">
                    <span>▶ 展开匹配详情</span>
                </div>
                <div class="resolved-content" style="display: none;">
                    ${entries.map(([provider, models]) => `
                        <div class="provider-models">
                            <span class="provider-name">${provider}:</span>
                            <div class="model-tags">
                                ${models.map(model => this.renderModelTag(provider, model)).join('')}
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    },

    renderModelTag(provider, model) {
        const key = `${provider}:${model}`;
        const result = this.healthResults[key];
        
        let healthClass = 'health-unknown';
        let tooltipContent = '点击检测';
        let latencyText = '';
        let clickAction = `ModelMap.testSingleModelSilent('${provider}', '${model}')`;
        
        if (result) {
            healthClass = result.success ? 'health-success' : 'health-error';
            latencyText = result.latency_ms ? ` (${Math.round(result.latency_ms)}ms)` : '';
            
            if (result.success) {
                // 健康的模型：无提示，点击无动作
                tooltipContent = '';
                clickAction = '';
            } else {
                // 失败的模型：显示完整响应体JSON
                try {
                    let jsonStr = JSON.stringify(result.response_body, null, 2);
                    if (result.error) {
                        tooltipContent = `错误: ${result.error}\n\n响应:\n${jsonStr}`;
                    } else {
                        tooltipContent = jsonStr;
                    }
                } catch (e) {
                    tooltipContent = result.error || '检测失败';
                }
                // 失败的模型点击也可以重新检测
                clickAction = `ModelMap.testSingleModelSilent('${provider}', '${model}')`;
            }
        }
        
        return `
            <span class="model-tag ${healthClass}"
                data-provider="${provider}"
                data-model="${model}"
                ${clickAction ? `onclick="${clickAction}"` : ''}
                ${tooltipContent ? `title="${this.escapeHtml(tooltipContent)}"` : ''}>
                ${model}${latencyText}
            </span>
        `;
    },

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },

    // 静默检测单个模型（点击灰色/红色模型标签时触发）
    async testSingleModelSilent(provider, model) {
        Toast.info(`正在检测 ${model}...`);
        
        try {
            const result = await API.testSingleModelHealth(provider, model);
            
            const key = `${provider}:${model}`;
            this.healthResults[key] = result;
            
            if (result.success) {
                Toast.success(`${model} 健康 (${Math.round(result.latency_ms)}ms)`);
            } else {
                Toast.error(`${model} 异常: ${result.error}`);
            }
            
            // 重新渲染以更新状态颜色
            this.render();
        } catch (error) {
            Toast.error('检测失败: ' + error.message);
        }
    },

    toggleResolved(el) {
        const container = el.parentElement;
        const content = container.querySelector('.resolved-content');
        const isCollapsed = container.classList.contains('collapsed');
        
        if (isCollapsed) {
            container.classList.remove('collapsed');
            content.style.display = 'block';
            el.querySelector('span').textContent = '▼ 收起匹配详情';
        } else {
            container.classList.add('collapsed');
            content.style.display = 'none';
            el.querySelector('span').textContent = '▶ 展开匹配详情';
        }
    },

    // ==================== 同步操作 ====================

    async syncAll() {
        Toast.info('正在同步所有映射...');
        try {
            const result = await API.syncModelMappings();
            Toast.success(`同步完成，共 ${result.synced_count} 个映射`);
            await this.load();
        } catch (error) {
            Toast.error('同步失败: ' + error.message);
        }
    },

    async syncSingle(unifiedName) {
        Toast.info(`正在同步映射 "${unifiedName}"...`);
        try {
            const result = await API.syncModelMappings(unifiedName);
            Toast.success('同步完成');
            await this.load();
        } catch (error) {
            Toast.error('同步失败: ' + error.message);
        }
    },

    async toggleAutoSync(enabled) {
        try {
            await API.updateSyncConfig({ auto_sync_enabled: enabled });
            this.syncConfig.auto_sync_enabled = enabled;
            document.getElementById('sync-interval').disabled = !enabled;
            Toast.success(enabled ? '已启用自动同步' : '已禁用自动同步');
        } catch (error) {
            Toast.error('更新失败: ' + error.message);
        }
    },

    async updateSyncInterval(hours) {
        try {
            await API.updateSyncConfig({ auto_sync_interval_hours: parseInt(hours) });
            Toast.success(`同步间隔已设置为 ${hours} 小时`);
        } catch (error) {
            Toast.error('更新失败: ' + error.message);
        }
    },

    // ==================== 健康检测 ====================

    async testMappingHealth(unifiedName) {
        Toast.info(`正在检测映射 "${unifiedName}" 下的所有模型...`);
        
        try {
            const result = await API.testMappingHealth(unifiedName);
            
            if (result.tested_count === 0) {
                Toast.warning(result.message || '没有可检测的模型');
                return;
            }
            
            const successRate = Math.round((result.success_count / result.tested_count) * 100);
            
            if (result.success_count === result.tested_count) {
                Toast.success(`检测完成: ${result.tested_count} 个模型全部健康`);
            } else if (result.success_count > 0) {
                Toast.warning(`检测完成: ${result.success_count}/${result.tested_count} 个模型健康 (${successRate}%)`);
            } else {
                Toast.error(`检测完成: 所有 ${result.tested_count} 个模型均异常`);
            }
            
            // 更新健康结果缓存并重新渲染
            for (const r of result.results) {
                const key = `${r.provider}:${r.model}`;
                this.healthResults[key] = r;
            }
            
            this.render();
        } catch (error) {
            Toast.error('健康检测失败: ' + error.message);
        }
    },

    async testSingleModel(provider, model) {
        Toast.info(`正在检测 ${provider}:${model}...`);
        
        try {
            const result = await API.testSingleModelHealth(provider, model);
            
            const key = `${provider}:${model}`;
            this.healthResults[key] = result;
            
            if (result.success) {
                Toast.success(`${model} 健康检测通过 (${Math.round(result.latency_ms)}ms)`);
            } else {
                Toast.error(`${model} 健康检测失败: ${result.error}`);
            }
            
            // 关闭模态框并重新渲染
            Modal.close();
            this.render();
        } catch (error) {
            Toast.error('检测失败: ' + error.message);
        }
    },

    // ==================== 创建/编辑模态框 ====================

    async showCreateModal() {
        try {
            const data = await API.fetchAllProviderModels();
            this.providerModels = data.provider_models || {};
        } catch (error) {
            console.error('Fetch provider models error:', error);
            this.providerModels = {};
        }

        const content = this.buildModalContent(null);
        Modal.show('添加模型映射', content, { width: '800px' });
    },

    async showEditModal(unifiedName) {
        const mapping = this.mappings[unifiedName];
        if (!mapping) {
            Toast.error('映射不存在');
            return;
        }

        try {
            const data = await API.fetchAllProviderModels();
            this.providerModels = data.provider_models || {};
        } catch (error) {
            console.error('Fetch provider models error:', error);
            this.providerModels = {};
        }

        const content = this.buildModalContent(unifiedName, mapping);
        Modal.show('编辑模型映射', content, { width: '800px' });
        
        // 初始化预览
        this.refreshPreview();
    },

    buildModalContent(unifiedName, mapping = null) {
        const isEdit = !!mapping;
        const rules = mapping?.rules || [];
        const manualIncludes = mapping?.manual_includes || [];
        const manualExcludes = mapping?.manual_excludes || [];
        const excludedProviders = mapping?.excluded_providers || [];

        const providerOptions = Object.keys(this.providerModels).map(name =>
            `<option value="${name}">${name} (${this.providerModels[name].length} 个模型)</option>`
        ).join('');

        // 生成排除渠道的checkbox列表
        const excludedProvidersCheckboxes = Object.keys(this.providerModels).map(name => {
            const isExcluded = excludedProviders.includes(name);
            return `
                <label class="provider-checkbox ${isExcluded ? 'excluded' : ''}">
                    <input type="checkbox" name="excluded-provider" value="${name}" ${isExcluded ? 'checked' : ''}>
                    <span class="provider-name">${name}</span>
                    <span class="model-count">(${this.providerModels[name].length})</span>
                </label>
            `;
        }).join('');

        return `
            <form onsubmit="ModelMap.${isEdit ? 'update' : 'create'}(event${isEdit ? `, '${unifiedName}'` : ''})">
                <div class="modal-form-grid">
                    <div class="form-left">
                        <div class="form-group">
                            <label>统一模型名称 <span class="required">*</span></label>
                            <input type="text" id="mapping-unified-name"
                                value="${unifiedName || ''}"
                                ${isEdit ? 'disabled' : 'required'}
                                placeholder="例如：gpt-4">
                            ${isEdit ? '<div class="hint">名称不可修改</div>' : '<div class="hint">用户调用时使用的模型名称</div>'}
                        </div>
                        
                        <div class="form-group">
                            <label>描述</label>
                            <input type="text" id="mapping-description"
                                value="${mapping?.description || ''}"
                                placeholder="例如：GPT-4 系列模型">
                        </div>
                        
                        <div class="form-group">
                            <label>匹配规则 <button type="button" class="btn btn-sm btn-secondary" onclick="ModelMap.addRule()">+ 添加规则</button></label>
                            <div id="rules-container">
                                ${rules.length === 0 ? '<div class="hint">点击上方按钮添加匹配规则</div>' : ''}
                            </div>
                        </div>
                        
                        <div class="form-group">
                            <label>排除渠道 <span class="hint-inline">(勾选的渠道将被完全跳过)</span></label>
                            <div id="excluded-providers-container" class="excluded-providers-checkboxes">
                                ${excludedProvidersCheckboxes || '<div class="hint">暂无可用渠道</div>'}
                            </div>
                        </div>
                        
                        <div class="form-group">
                            <label>手动排除的模型</label>
                            <textarea id="mapping-manual-excludes" rows="2"
                                placeholder="每行一个，格式: model_id 或 provider:model_id">${manualExcludes.join('\n')}</textarea>
                            <div class="hint">即使规则匹配也会被排除（模型级别）</div>
                        </div>
                        
                        <div class="form-group">
                            <label>手动包含的模型</label>
                            <textarea id="mapping-manual-includes" rows="2"
                                placeholder="每行一个，格式: model_id 或 provider:model_id">${manualIncludes.join('\n')}</textarea>
                            <div class="hint">不匹配规则也会被包含</div>
                        </div>
                    </div>
                    
                    <div class="form-right">
                        <div class="form-group">
                            <label>从中转站选择模型</label>
                            <select id="mapping-provider-select" onchange="ModelMap.onProviderChange()">
                                <option value="">-- 选择中转站 --</option>
                                ${providerOptions}
                            </select>
                        </div>
                        
                        <div class="form-group">
                            <label>关键字筛选</label>
                            <input type="text" id="mapping-keyword" placeholder="输入关键字筛选" oninput="ModelMap.filterModels()">
                        </div>
                        
                        <div class="form-group">
                            <label>可选模型 <span id="model-count">(0)</span></label>
                            <div id="available-models" class="model-selector">
                                <div class="hint">请先选择中转站</div>
                            </div>
                        </div>
                        
                        <div class="form-group">
                            <label>预览匹配结果 <button type="button" class="btn btn-sm btn-secondary" onclick="ModelMap.refreshPreview()">🔄 刷新</button></label>
                            <div id="preview-result" class="preview-container">
                                <div class="hint">配置规则后点击刷新预览</div>
                            </div>
                        </div>
                    </div>
                </div>
                
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="Modal.close()">取消</button>
                    <button type="submit" class="btn btn-primary">${isEdit ? '保存' : '添加映射'}</button>
                </div>
            </form>
        `;
    },

    // 初始化规则（用于编辑时）
    initRules(rules) {
        const container = document.getElementById('rules-container');
        container.innerHTML = '';
        rules.forEach((rule, index) => {
            this.addRule(rule);
        });
    },

    addRule(rule = null) {
        const container = document.getElementById('rules-container');
        
        // 移除空提示
        const hint = container.querySelector('.hint');
        if (hint) hint.remove();
        
        const ruleId = Date.now();
        const ruleHtml = `
            <div class="rule-item" data-rule-id="${ruleId}">
                <select class="rule-type" onchange="ModelMap.onRuleTypeChange(this)">
                    ${this.RULE_TYPES.map(t => `
                        <option value="${t.value}" ${rule?.type === t.value ? 'selected' : ''}>${t.label}</option>
                    `).join('')}
                </select>
                <input type="text" class="rule-pattern" placeholder="匹配值" value="${rule?.pattern || ''}">
                <label class="rule-case-sensitive" title="区分大小写">
                    <input type="checkbox" ${rule?.case_sensitive ? 'checked' : ''}>
                    Aa
                </label>
                <button type="button" class="btn btn-sm btn-danger" onclick="ModelMap.removeRule(${ruleId})">×</button>
            </div>
        `;
        container.insertAdjacentHTML('beforeend', ruleHtml);
    },

    removeRule(ruleId) {
        const ruleEl = document.querySelector(`[data-rule-id="${ruleId}"]`);
        if (ruleEl) ruleEl.remove();
    },

    onRuleTypeChange(selectEl) {
        const type = selectEl.value;
        const typeInfo = this.RULE_TYPES.find(t => t.value === type);
        const patternInput = selectEl.parentElement.querySelector('.rule-pattern');
        patternInput.placeholder = typeInfo?.hint || '匹配值';
    },

    collectRules() {
        const rules = [];
        document.querySelectorAll('.rule-item').forEach(item => {
            const type = item.querySelector('.rule-type').value;
            const pattern = item.querySelector('.rule-pattern').value.trim();
            const caseSensitive = item.querySelector('.rule-case-sensitive input').checked;
            
            if (pattern) {
                rules.push({ type, pattern, case_sensitive: caseSensitive });
            }
        });
        return rules;
    },

    // ==================== 中转站模型选择 ====================

    onProviderChange() {
        const providerName = document.getElementById('mapping-provider-select').value;
        const providerData = this.providerModels[providerName] || [];
        this.currentProviderModels = providerData.map(m => typeof m === 'string' ? m : m.id);
        this.filterModels();
    },

    filterModels() {
        const keyword = document.getElementById('mapping-keyword').value.toLowerCase();
        const container = document.getElementById('available-models');
        const countEl = document.getElementById('model-count');
        
        let models = this.currentProviderModels;
        if (keyword) {
            models = models.filter(m => m.toLowerCase().includes(keyword));
        }
        
        countEl.textContent = `(${models.length})`;
        
        if (models.length === 0) {
            container.innerHTML = '<div class="hint">没有匹配的模型</div>';
            return;
        }
        
        container.innerHTML = models.map(model => `
            <span class="model-tag clickable" 
                onclick="ModelMap.addToManualInclude('${model}')" 
                title="点击添加到手动包含">
                ${model}
            </span>
        `).join('');
    },

    addToManualInclude(model) {
        const textarea = document.getElementById('mapping-manual-includes');
        const currentModels = textarea.value.split('\n').map(m => m.trim()).filter(m => m);
        
        const providerName = document.getElementById('mapping-provider-select').value;
        const fullRef = providerName ? `${providerName}:${model}` : model;
        
        if (!currentModels.includes(fullRef) && !currentModels.includes(model)) {
            currentModels.push(fullRef);
            textarea.value = currentModels.join('\n');
            Toast.success(`已添加: ${fullRef}`);
        } else {
            Toast.info('该模型已在列表中');
        }
    },

    addToManualExclude(model) {
        const textarea = document.getElementById('mapping-manual-excludes');
        const currentModels = textarea.value.split('\n').map(m => m.trim()).filter(m => m);
        
        if (!currentModels.includes(model)) {
            currentModels.push(model);
            textarea.value = currentModels.join('\n');
            Toast.success(`已排除: ${model}`);
        }
    },

    // ==================== 预览功能 ====================

    collectExcludedProviders() {
        const checkboxes = document.querySelectorAll('input[name="excluded-provider"]:checked');
        return Array.from(checkboxes).map(cb => cb.value);
    },

    async refreshPreview() {
        const rules = this.collectRules();
        const manualIncludes = document.getElementById('mapping-manual-includes').value
            .split('\n').map(m => m.trim()).filter(m => m);
        const manualExcludes = document.getElementById('mapping-manual-excludes').value
            .split('\n').map(m => m.trim()).filter(m => m);
        const excludedProviders = this.collectExcludedProviders();
        
        const container = document.getElementById('preview-result');
        container.innerHTML = `
            <div class="loading-state">
                <span class="loading-spinner"></span>
                <span class="loading-text">正在预览...</span>
            </div>
        `;
        
        try {
            const result = await API.previewModelMapping({
                rules,
                manual_includes: manualIncludes,
                manual_excludes: manualExcludes,
                excluded_providers: excludedProviders
            });
            
            this.previewResult = result.matched_models || {};
            this.renderPreview(result);
        } catch (error) {
            container.innerHTML = `<div class="hint" style="color: var(--danger-color);">预览失败: ${error.message}</div>`;
        }
    },

    renderPreview(result) {
        const container = document.getElementById('preview-result');
        const { matched_models, total_count, provider_count } = result;
        
        if (total_count === 0) {
            container.innerHTML = '<div class="hint">无匹配结果，请调整规则</div>';
            return;
        }
        
        let html = `<div class="preview-summary">共 ${total_count} 个模型，来自 ${provider_count} 个渠道</div>`;
        
        for (const [provider, models] of Object.entries(matched_models)) {
            html += `
                <div class="preview-provider">
                    <div class="provider-header">${provider} (${models.length})</div>
                    <div class="provider-models">
                        ${models.map(m => `
                            <span class="model-tag" 
                                onclick="ModelMap.addToManualExclude('${m}')" 
                                title="点击排除此模型">
                                ${m}
                            </span>
                        `).join('')}
                    </div>
                </div>
            `;
        }
        
        container.innerHTML = html;
    },

    // ==================== CRUD 操作 ====================

    async create(event) {
        event.preventDefault();
        
        const unifiedName = document.getElementById('mapping-unified-name').value.trim();
        const description = document.getElementById('mapping-description').value.trim();
        const rules = this.collectRules();
        const manualIncludes = document.getElementById('mapping-manual-includes').value
            .split('\n').map(m => m.trim()).filter(m => m);
        const manualExcludes = document.getElementById('mapping-manual-excludes').value
            .split('\n').map(m => m.trim()).filter(m => m);
        const excludedProviders = this.collectExcludedProviders();
        
        if (!unifiedName) {
            Toast.warning('请输入统一模型名称');
            return;
        }
        
        if (rules.length === 0 && manualIncludes.length === 0) {
            Toast.warning('请至少添加一个规则或手动包含一个模型');
            return;
        }
        
        try {
            await API.createModelMapping({
                unified_name: unifiedName,
                description,
                rules,
                manual_includes: manualIncludes,
                manual_excludes: manualExcludes,
                excluded_providers: excludedProviders
            });
            
            Modal.close();
            Toast.success('模型映射已创建');
            
            // 立即同步
            await this.syncSingle(unifiedName);
        } catch (error) {
            Toast.error('创建失败: ' + error.message);
        }
    },

    async update(event, unifiedName) {
        event.preventDefault();
        
        const description = document.getElementById('mapping-description').value.trim();
        const rules = this.collectRules();
        const manualIncludes = document.getElementById('mapping-manual-includes').value
            .split('\n').map(m => m.trim()).filter(m => m);
        const manualExcludes = document.getElementById('mapping-manual-excludes').value
            .split('\n').map(m => m.trim()).filter(m => m);
        const excludedProviders = this.collectExcludedProviders();
        
        if (rules.length === 0 && manualIncludes.length === 0) {
            Toast.warning('请至少添加一个规则或手动包含一个模型');
            return;
        }
        
        try {
            await API.updateModelMapping(unifiedName, {
                description,
                rules,
                manual_includes: manualIncludes,
                manual_excludes: manualExcludes,
                excluded_providers: excludedProviders
            });
            
            Modal.close();
            Toast.success('模型映射已更新');
            
            // 立即同步
            await this.syncSingle(unifiedName);
        } catch (error) {
            Toast.error('更新失败: ' + error.message);
        }
    },

    confirmDelete(unifiedName) {
        Modal.confirm(
            '确认删除',
            `确定要删除模型映射 "${unifiedName}" 吗？`,
            () => this.delete(unifiedName)
        );
    },

    async delete(unifiedName) {
        try {
            await API.deleteModelMapping(unifiedName);
            Toast.success('模型映射已删除');
            await this.load();
        } catch (error) {
            Toast.error('删除失败: ' + error.message);
        }
    }
};

// 页面加载后初始化规则列表（如果是编辑模式）
document.addEventListener('DOMContentLoaded', () => {
    // 监听模态框打开事件，如果是编辑模式则初始化规则
    const observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
            if (mutation.addedNodes.length) {
                const rulesContainer = document.getElementById('rules-container');
                if (rulesContainer && rulesContainer.dataset.initialized !== 'true') {
                    const unifiedName = document.getElementById('mapping-unified-name')?.value;
                    if (unifiedName && ModelMap.mappings[unifiedName]) {
                        const mapping = ModelMap.mappings[unifiedName];
                        ModelMap.initRules(mapping.rules || []);
                        rulesContainer.dataset.initialized = 'true';
                    }
                }
            }
        });
    });
    
    observer.observe(document.body, { childList: true, subtree: true });
});
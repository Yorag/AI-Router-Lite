/**
 * 模型映射管理模块（增强型）
 *
 * 支持规则匹配、手动包含/排除、自动同步、拖拽排序
 */

const ModelMap = {
    mappings: {},           // 映射配置
    syncConfig: {},         // 同步配置
    providerModels: {},     // 缓存各中转站的模型列表 (key: provider_id)
    providerIdNameMap: {},  // provider_id -> provider_name 映射
    providerDefaultProtocols: {},  // provider_id -> default_protocol 映射
    providerEnabledStatus: {},     // provider_id -> enabled 状态映射
    providerWeights: {},           // provider_id -> weight 映射
    currentProviderId: '',  // 当前选中的 provider_id
    currentProviderModels: [], // 当前选中的中转站模型
    previewResult: {},      // 预览结果缓存
    healthResults: {},      // 健康检测结果缓存 {provider_id:model -> result}
    runtimeStates: {},      // 运行时熔断状态缓存 {provider_id:model -> state}
    availableProtocols: [], // 可用协议类型缓存
    expandedMappings: new Set(), // 记录已展开的映射卡片 (unifiedName)
    draggedItem: null,      // 当前拖拽的元素

    // 规则类型选项
    RULE_TYPES: [
        { value: 'keyword', label: '关键字匹配', hint: '模型名包含该关键字即匹配' },
        { value: 'regex', label: '正则表达式', hint: '使用正则表达式匹配' },
        { value: 'prefix', label: '前缀匹配', hint: '模型名以该前缀开头即匹配' },
        { value: 'exact', label: '精确匹配', hint: '模型名完全相同才匹配' },
        { value: 'keyword_exclude', label: '关键字排除', hint: '模型名包含该关键字时排除' }
    ],

    async init() {
        await this.loadProtocols();  // 加载协议类型
        await this.loadProviderProtocols();  // 加载 Provider 默认协议
        await this.load();
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
            this.availableProtocols = [
                { value: 'openai', label: 'openai', description: 'OpenAI Chat Completions API' },
                { value: 'openai-response', label: 'openai-response', description: 'OpenAI Responses API' },
                { value: 'anthropic', label: 'anthropic', description: 'Anthropic Messages API' },
                { value: 'gemini', label: 'gemini', description: 'Google Gemini API' }
            ];
        }
    },

    /**
     * 加载 Provider 默认协议配置和启用状态
     */
    async loadProviderProtocols() {
        try {
            const result = await API.listProviders();
            const providers = result.providers || [];
            this.providerDefaultProtocols = {};
            this.providerEnabledStatus = {};
            this.providerWeights = {};
            for (const p of providers) {
                if (p.id) {
                    this.providerDefaultProtocols[p.id] = p.default_protocol || null;
                    // 默认为 true，只有明确为 false 时才是禁用
                    this.providerEnabledStatus[p.id] = p.enabled !== false;
                    this.providerWeights[p.id] = p.weight !== undefined ? p.weight : 0;
                }
            }
        } catch (err) {
            console.warn('加载 Provider 协议配置失败:', err);
            this.providerDefaultProtocols = {};
            this.providerEnabledStatus = {};
            this.providerWeights = {};
        }
    },

    async load() {
        try {
            // 先加载 provider 的 ID -> Name 映射，用于渲染时显示名称
            await this.loadProviderIdNameMap();
            
            const data = await API.getModelMappings();
            this.mappings = data.mappings || {};
            this.syncConfig = data.sync_config || {};
            
            // 并行加载健康检测结果和运行时熔断状态
            await Promise.all([
                this.loadHealthResults(),
                this.loadRuntimeStates()
            ]);
            
            this.render();
        } catch (error) {
            console.error('Load model mappings error:', error);
            Toast.error('加载模型映射失败');
        }
    },

    async loadProviderIdNameMap() {
        try {
            const data = await API.fetchAllProviderModels();
            this.processProviderModelsData(data.provider_models || {});
        } catch (error) {
            console.error('Load provider ID-Name map error:', error);
            // 不阻塞后续流程，只是显示 ID 而非名称
            this.providerIdNameMap = {};
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

    async loadRuntimeStates() {
        try {
            const data = await API.getRuntimeStates();
            this.runtimeStates = data.models || {};
        } catch (error) {
            console.error('Load runtime states error:', error);
            this.runtimeStates = {};
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
                    <div class="empty-state-icon"><i class="ri-git-merge-line"></i></div>
                    <div class="empty-state-text">暂无模型映射</div>
                    <div class="empty-state-hint">点击"添加映射"按钮创建模型映射规则</div>
                </div>
            `;
            return;
        }

        // 按order_index 排序
        entries.sort((a, b) => (a[1].order_index || 0) - (b[1].order_index || 0));

        container.innerHTML = entries.map(([unifiedName, mapping]) => {
            const rulesText = this.formatRules(mapping.rules || []);
            
            // 计算模型统计信息
            const stats = this.calculateModelStats(mapping.resolved_models || {});
            const availableCount = stats.available;
            const totalCount = stats.total;
            const providerCount = Object.keys(mapping.resolved_models || {}).length;
            
            const lastSync = mapping.last_sync ? Utils.formatDateTime(new Date(mapping.last_sync)) : '未同步';
            const excludedProviders = mapping.excluded_providers || [];
            
            // 将 excluded_providers (provider_id) 转换为显示名称
            const excludedProviderNames = excludedProviders.map(pid =>
                this.providerIdNameMap[pid] || pid
            );
            
            // 计算支持的协议并集及其模型数量
            const protocolCounts = {};
            if (mapping.resolved_models) {
                for (const [providerId, models] of Object.entries(mapping.resolved_models)) {
                    // 跳过被禁用的 Provider
                    if (this.providerEnabledStatus[providerId] === false) continue;
                    
                    for (const model of models) {
                        const status = this.getModelProtocolStatus(unifiedName, providerId, model);
                        if (status.isConfigured && status.protocol) {
                            protocolCounts[status.protocol] = (protocolCounts[status.protocol] || 0) + 1;
                        }
                    }
                }
            }
            const sortedProtocols = Object.keys(protocolCounts).sort();
            
            const escapedName = unifiedName.replace(/"/g, '"');
            const isEnabled = mapping.enabled !== false;  // 默认为启用
            const disabledClass = isEnabled ? '' : 'mapping-disabled';
            return `
                <div class="model-map-card ${disabledClass}"
                     data-unified-name="${escapedName}"
                     ondragover="ModelMap.handleDragOver(event)"
                     ondrop="ModelMap.handleDrop(event)">
                    <div class="card-header">
                        <div class="header-main">
                            <span class="drag-handle"
                                  title="拖拽排序"
                                  draggable="true"
                                  ondragstart="ModelMap.handleDragStart(event)"
                                  ondragend="ModelMap.handleDragEnd(event)">⋮⋮</span>
                            <h4 class="unified-name" title="${unifiedName}">${unifiedName}</h4>
                            <label class="toggle-switch" title="${isEnabled ? '点击禁用此映射' : '点击启用此映射'}">
                                <input type="checkbox"
                                       ${isEnabled ? 'checked' : ''}
                                       onchange="ModelMap.toggleEnabled('${escapedName}', this.checked)">
                                <span class="toggle-slider"></span>
                            </label>
                        </div>
                        <div class="model-map-actions">
                            <button class="btn-icon-mini" onclick="ModelMap.syncSingle('${unifiedName}')" title="同步" ${!isEnabled ? 'disabled' : ''}>
                                <i class="ri-refresh-line"></i>
                            </button>
                            <button class="btn-icon-mini" onclick="ModelMap.testMappingHealth('${unifiedName}')" title="检测健康" ${!isEnabled ? 'disabled' : ''}>
                                <i class="ri-stethoscope-line"></i>
                            </button>
                            <button class="btn-icon-mini" onclick="ModelMap.showEditModal('${unifiedName}')" title="编辑">
                                <i class="ri-edit-line"></i>
                            </button>
                            <button class="btn-icon-mini danger" onclick="ModelMap.confirmDelete('${unifiedName}')" title="删除">
                                <i class="ri-delete-bin-line"></i>
                            </button>
                        </div>
                    </div>
                    
                    <div class="card-body">
                        <div class="info-group">
                            <div class="map-badges">
                                <span class="match-count-badge ${availableCount > 0 ? 'active' : 'inactive'}" title="可用模型/总匹配模型">
                                    ${availableCount}/${totalCount}
                                </span>
                                ${sortedProtocols.length > 0
                                    ? sortedProtocols.map(p => `<span class="protocol-tag-mini">${p} (${protocolCounts[p]})</span>`).join('')
                                    : '<span class="protocol-tag-mini empty">无协议</span>'}
                            </div>
                        </div>
                        
                        <div class="meta-row">
                            <span class="meta-item" title="来源渠道数"><i class="ri-signal-tower-line"></i> ${providerCount}</span>
                            ${excludedProviders.length > 0 ?
                                `<span class="meta-item warning" title="排除渠道: ${excludedProviders.length} 个\n${excludedProviderNames.join(', ')}"><i class="ri-forbid-line"></i> ${excludedProviders.length}</span>` : ''}
                            ${mapping.manual_includes && mapping.manual_includes.length > 0 ?
                                `<span class="meta-item info" title="手动包含: ${mapping.manual_includes.length} 个\n${mapping.manual_includes.join('\n')}"><i class="ri-pushpin-line"></i> ${mapping.manual_includes.length}</span>` : ''}
                            <span class="meta-spacer"></span>
                            <span class="meta-item time" title="上次同步时间">${lastSync}</span>
                        </div>
                    </div>

                    ${this.renderResolvedModels(mapping.resolved_models || {}, unifiedName)}
                </div>
            `;
        }).join('');
    },

    /**
     * 计算模型统计信息 (可用/总数)
     */
    calculateModelStats(resolvedModels) {
        let total = 0;
        let available = 0;

        for (const [providerId, models] of Object.entries(resolvedModels)) {
            // 如果 Provider 被禁用，则该 Provider 下的所有模型都不可用
            const isProviderDisabled = this.providerEnabledStatus[providerId] === false;
            
            for (const model of models) {
                total++;
                
                if (isProviderDisabled) continue;

                const key = `${providerId}:${model}`;
                const runtimeState = this.runtimeStates[key];
                
                // 检查是否永久禁用
                if (runtimeState && runtimeState.status === 'permanently_disabled') {
                    continue;
                }
                
                // 暂时将 cooling 视为可用（或者你可以决定它不可用，这里假设只要不是永久禁用且渠道开启就算可用）
                // 如果想要更严格的"可用"，可以排除 cooling
                
                available++;
            }
        }
        return { total, available };
    },

    renderSyncConfig() {
        const configContainer = document.getElementById('sync-config-area');
        if (!configContainer) return;
        
        const { auto_sync_enabled, auto_sync_interval_hours, last_full_sync } = this.syncConfig;
        const lastSyncText = last_full_sync ? Utils.formatDateTime(new Date(last_full_sync)) : '从未';
        
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

    renderResolvedModels(resolvedModels, unifiedName = null) {
        // resolvedModels 的 key 是 provider_id
        const entries = Object.entries(resolvedModels);
        if (entries.length === 0) {
            return '<div class="resolved-models"><em>无匹配模型，请配置规则后同步</em></div>';
        }
        
        const escapedUnifiedName = unifiedName ? unifiedName.replace(/'/g, "\\'") : '';
        
        // 根据 expandedMappings 决定初始状态
        const isExpanded = unifiedName && this.expandedMappings.has(unifiedName);
        const collapsedClass = isExpanded ? '' : 'collapsed';
        const contentDisplay = isExpanded ? 'block' : 'none';
        const toggleText = isExpanded ? '<i class="ri-arrow-down-s-line"></i> 收起匹配详情' : '<i class="ri-arrow-right-s-line"></i> 展开匹配详情';
        
        return `
            <div class="resolved-models ${collapsedClass}">
                <div class="resolved-toggle" onclick="ModelMap.toggleResolved(this, '${escapedUnifiedName}')">
                    <span>${toggleText}</span>
                </div>
                <div class="resolved-content" style="display: ${contentDisplay};">
                    ${unifiedName ? `
                    <div class="protocol-config-hint">
                        <span>左击可检测健康状态，右击可配置协议</span>
                        <button class="btn btn-sm btn-secondary" onclick="ModelMap.showBatchProtocolModal('${escapedUnifiedName}')">
                            批量配置协议
                        </button>
                    </div>
                    ` : ''}
                    ${entries.map(([providerId, models]) => {
                        // 将 provider_id 转换为显示名称
                        const providerName = this.providerIdNameMap[providerId] || providerId;
                        const providerProtocol = this.providerDefaultProtocols[providerId];
                        const weight = this.providerWeights[providerId] !== undefined ? this.providerWeights[providerId] : 0;
                        
                        // 检查渠道是否被禁用
                        const isProviderDisabled = this.providerEnabledStatus[providerId] === false;
                        const providerDisabledClass = isProviderDisabled ? 'provider-disabled' : '';
                        return `
                            <div class="provider-models ${providerDisabledClass}">
                                <span class="provider-name">
                                    ${providerName}
                                    <span class="provider-weight" title="权重">(w:${weight})</span>:
                                </span>
                                <div class="model-tags" oncontextmenu="return ModelMap.showModelContextMenu(event, '${escapedUnifiedName}', '${providerId}')">
                                    ${models.map(model => this.renderModelTag(providerId, model, unifiedName)).join('')}
                                </div>
                            </div>
                        `;
                    }).join('')}
                </div>
            </div>
        `;
    },

    /**
     * 获取模型的协议配置状态
     * @returns {object} { protocol: string|null, source: 'model'|'provider'|'none', isConfigured: boolean }
     */
    getModelProtocolStatus(unifiedName, providerId, model) {
        const mapping = this.mappings[unifiedName];
        if (!mapping) return { protocol: null, source: 'none', isConfigured: false };
        
        const modelSettings = mapping.model_settings || {};
        const key = `${providerId}:${model}`;
        
        // 检查模型级配置
        if (modelSettings[key] && modelSettings[key].protocol) {
            return { protocol: modelSettings[key].protocol, source: 'model', isConfigured: true };
        }
        
        // 检查 Provider 默认协议
        const providerProtocol = this.providerDefaultProtocols[providerId];
        if (providerProtocol) {
            return { protocol: providerProtocol, source: 'provider', isConfigured: true };
        }
        
        // 未配置
        return { protocol: null, source: 'none', isConfigured: false };
    },

    renderModelTag(providerId, model, unifiedName = null) {
        // key 使用 provider_id:model 格式
        const key = `${providerId}:${model}`;
        const runtimeState = this.runtimeStates[key];
        const healthResult = this.healthResults[key];
        
        // 检查渠道是否被禁用
        const isProviderDisabled = this.providerEnabledStatus[providerId] === false;
        
        let healthClass = 'health-unknown';
        let tooltipContent = '点击检测';
        let clickAction = `ModelMap.testSingleModelSilent(this, '${providerId}', '${model}')`;
        
        // 如果渠道被禁用，添加禁用样式
        if (isProviderDisabled) {
            healthClass = 'provider-disabled-model';
            tooltipContent = '';
            clickAction = '';  // 禁用点击
        }
        
        // 优先检查运行时熔断状态（COOLING 和 PERMANENTLY_DISABLED）- 仅当渠道未禁用时
        if (!isProviderDisabled && runtimeState) {
            if (runtimeState.status === 'cooling') {
                healthClass = 'health-cooling';
                const remainingSec = Math.max(0, Math.ceil(runtimeState.cooldown_remaining || 0));
                const reasonText = runtimeState.cooldown_reason === 'rate_limited' ? '触发限流' :
                                   runtimeState.cooldown_reason === 'server_error' ? '服务器错误' :
                                   runtimeState.cooldown_reason === 'health_check_failed' ? '健康检测失败' : '熔断';
                tooltipContent = `${reasonText}，冷却中 (${remainingSec}s)`;
                if (runtimeState.last_error) {
                    tooltipContent += ` | ${runtimeState.last_error}`;
                }
                // 熔断中的模型仍可点击重新检测
                clickAction = `ModelMap.testSingleModelSilent(this, '${providerId}', '${model}')`;
            } else if (runtimeState.status === 'permanently_disabled') {
                healthClass = 'health-disabled';
                tooltipContent = '永久禁用';
                if (runtimeState.last_error) {
                    tooltipContent += ` | 原因: ${runtimeState.last_error}`;
                }
                // 永久禁用的模型禁用点击
                clickAction = '';
            }
        }
        
        // 如果不是熔断/禁用状态，检查健康状态 - 仅当渠道未禁用时
        if (!isProviderDisabled && healthClass === 'health-unknown') {
            // 判断是否健康：运行时状态 healthy 且有活动记录，或者健康检测成功
            const isRuntimeHealthy = runtimeState && runtimeState.status === 'healthy' && runtimeState.last_activity_time;
            const isHealthCheckSuccess = healthResult && healthResult.success;
            
            if (isRuntimeHealthy || isHealthCheckSuccess) {
                healthClass = 'health-success';
                clickAction = '';  // 已健康的模型无需点击检测
                
                // Tooltip 显示延迟（如有，来自健康检测），没有延迟则不显示
                if (healthResult && healthResult.success && healthResult.latency_ms) {
                    tooltipContent = `延迟: ${Math.round(healthResult.latency_ms)}ms`;
                } else {
                    tooltipContent = '';
                }
            } else if (healthResult && !healthResult.success) {
                // 健康检测失败
                healthClass = 'health-error';
                // healthResult.error 已包含完整错误信息（如 "HTTP 403: {...}"），无需重复添加 response_body
                if (healthResult.error) {
                    tooltipContent = `${healthResult.error}`;
                } else if (healthResult.response_body) {
                    // 仅当没有 error 字段时才显示 response_body
                    try {
                        tooltipContent = JSON.stringify(healthResult.response_body);
                    } catch (e) {
                        tooltipContent = '检测失败';
                    }
                } else {
                    tooltipContent = '检测失败';
                }
                // 失败的模型点击可以重新检测
                clickAction = `ModelMap.testSingleModelSilent(this, '${providerId}', '${model}')`;
            }
        }
        
        // 获取协议配置状态
        let protocolBadge = '';
        if (unifiedName) {
            const protocolStatus = this.getModelProtocolStatus(unifiedName, providerId, model);
            if (protocolStatus.isConfigured) {
                const badgeClass = protocolStatus.source === 'model' ? 'protocol-model' : 'protocol-provider';
                protocolBadge = `<span class="protocol-badge ${badgeClass}" title="${protocolStatus.source === 'model' ? '模型级配置' : 'Provider 默认'}">${protocolStatus.protocol}</span>`;
            } else {
                protocolBadge = `<span class="protocol-badge protocol-none" title="未配置协议，将被跳过"><i class="ri-alert-line"></i></span>`;
                // 未配置协议的模型禁用左键点击健康检测
                clickAction = '';
                tooltipContent = '未配置协议，请右键配置后再检测';
            }
        }
        
        return `
            <span class="model-tag ${healthClass}"
                data-provider-id="${providerId}"
                data-model="${model}"
                ${clickAction ? `onclick="${clickAction}"` : ''}
                ${tooltipContent ? `data-tooltip="${Utils.escapeHtml(tooltipContent)}"` : ''}>
                ${model}${protocolBadge}
            </span>
        `;
    },

    // 静默检测单个模型（点击灰色/红色模型标签时触发）
    async testSingleModelSilent(el, providerId, model) {
        // 禁用模型标签，防止重复点击
        if (el) {
            el.classList.add('is-loading');
        }
        
        try {
            const result = await API.testSingleModelHealth(providerId, model);
            
            // key 使用 provider_id:model 格式
            const key = `${providerId}:${model}`;
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
            // 发生错误时恢复模型标签状态
            if (el) {
                el.classList.remove('is-loading');
            }
        }
    },

    toggleResolved(el, unifiedName = null) {
        const container = el.parentElement;
        const content = container.querySelector('.resolved-content');
        const isCollapsed = container.classList.contains('collapsed');
        
        if (isCollapsed) {
            container.classList.remove('collapsed');
            content.style.display = 'block';
            el.querySelector('span').innerHTML = '<i class="ri-arrow-down-s-line"></i> 收起匹配详情';
            // 记录展开状态
            if (unifiedName) {
                this.expandedMappings.add(unifiedName);
            }
        } else {
            container.classList.add('collapsed');
            content.style.display = 'none';
            el.querySelector('span').innerHTML = '<i class="ri-arrow-right-s-line"></i> 展开匹配详情';
            // 移除展开状态
            if (unifiedName) {
                this.expandedMappings.delete(unifiedName);
            }
        }
    },

    // ==================== 同步操作 ====================

    async syncAll() {
        try {
            const result = await API.syncModelMappings();
            Toast.success(`同步完成，共 ${result.synced_count} 个映射`);
            await this.load();
        } catch (error) {
            Toast.error('同步失败: ' + error.message);
        }
    },

    async syncSingle(unifiedName) {
        try {
            await API.syncModelMappings(unifiedName);
            Toast.success(`同步完成`);
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
            // 结果中 provider 字段存储 provider_id
            for (const r of result.results) {
                const key = `${r.provider}:${r.model}`;
                this.healthResults[key] = r;
            }
            
            this.render();
        } catch (error) {
            Toast.error('健康检测失败: ' + error.message);
        }
    },

    async testSingleModel(providerId, model) {
        try {
            const result = await API.testSingleModelHealth(providerId, model);
            
            const key = `${providerId}:${model}`;
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
            // 新格式: { provider_id: { provider_name: "xxx", models: [...] } }
            this.processProviderModelsData(data.provider_models || {});
        } catch (error) {
            console.error('Fetch provider models error:', error);
            this.providerModels = {};
            this.providerIdNameMap = {};
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
            // 新格式: { provider_id: { provider_name: "xxx", models: [...] } }
            this.processProviderModelsData(data.provider_models || {});
        } catch (error) {
            console.error('Fetch provider models error:', error);
            this.providerModels = {};
            this.providerIdNameMap = {};
        }

        const content = this.buildModalContent(unifiedName, mapping);
        Modal.show('编辑模型映射', content, { width: '800px' });
        
        // 初始化预览
        this.refreshPreview();
    },

    /**
     * 处理从 API 返回的 provider_models 数据
     * 新格式: { provider_id: { provider_name: "xxx", models: [...] } }
     */
    processProviderModelsData(rawData) {
        this.providerModels = {};
        this.providerIdNameMap = {};
        
        for (const [providerId, providerData] of Object.entries(rawData)) {
            const providerName = providerData.provider_name || providerId;
            const models = providerData.models || [];
            
            this.providerIdNameMap[providerId] = providerName;
            this.providerModels[providerId] = models;
        }
    },

    buildModalContent(unifiedName, mapping = null) {
        const isEdit = !!mapping;
        const rules = mapping?.rules || [];
        const manualIncludes = mapping?.manual_includes || [];
        const excludedProviders = mapping?.excluded_providers || [];  // 这是 provider_id 数组

        // 使用 provider_id 作为 value，显示 provider_name
        const providerOptions = Object.entries(this.providerModels).map(([providerId, models]) => {
            const providerName = this.providerIdNameMap[providerId] || providerId;
            const modelCount = Array.isArray(models) ? models.length : (models.models?.length || 0);
            return `<option value="${providerId}">${providerName} (${modelCount} 个模型)</option>`;
        }).join('');

        // 生成排除渠道的checkbox列表，使用 provider_id 作为 value
        const excludedProvidersCheckboxes = Object.entries(this.providerModels).map(([providerId, models]) => {
            const providerName = this.providerIdNameMap[providerId] || providerId;
            const modelCount = Array.isArray(models) ? models.length : (models.models?.length || 0);
            const isExcluded = excludedProviders.includes(providerId);
            return `
                <label class="provider-checkbox">
                    <input type="checkbox" name="excluded-provider" value="${providerId}" ${isExcluded ? 'checked' : ''}>
                    <span class="provider-name">${providerName}</span>
                    <span class="model-count">(${modelCount})</span>
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
                                    required
                                    placeholder="例如：gpt-4">
                                <div class="hint">用户调用时使用的模型名称</div>
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
                            <label>手动包含的模型</label>
                            <input type="hidden" id="mapping-manual-includes" value="${manualIncludes.join('\n')}">
                            <div id="manual-includes-tags" class="tag-input-container">
                                <div class="tag-input-tags">
                                    ${this.renderManualIncludeTags(manualIncludes)}
                                </div>
                            </div>
                            <div class="hint">点击右侧可选模型添加，点击标签上的 × 删除</div>
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
                            <label>预览匹配结果 <button type="button" class="btn btn-sm btn-secondary" onclick="ModelMap.refreshPreview()"> 刷新</button></label>
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
        const providerId = document.getElementById('mapping-provider-select').value;
        this.currentProviderId = providerId;
        const providerData = this.providerModels[providerId] || [];
        // 处理模型数据：可能是直接的模型数组，或者是包含 models 字段的对象
        const models = Array.isArray(providerData) ? providerData : (providerData.models || []);
        this.currentProviderModels = models.map(m => typeof m === 'string' ? m : m.id);
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
                onclick="ModelMap.addToManualInclude('${Utils.escapeHtml(model)}')"
                data-tooltip="点击添加到手动包含">
                ${Utils.escapeHtml(model)}
            </span>
        `).join('');
    },

    /**
     * 渲染手动包含的模型标签（复用 tag-input-tag 样式）
     */
    renderManualIncludeTags(manualIncludes) {
        if (!manualIncludes || manualIncludes.length === 0) {
            return '<div class="tag-input-empty">暂无手动包含的模型</div>';
        }
        
        return manualIncludes.map(item => {
            const displayName = this.formatManualIncludeForDisplay(item);
            const escapedItem = item.replace(/"/g, '"');
            // 这里我们只需要确保 removeManualInclude 调用时的参数是转义过的
            // 实际上 escapedItem 已经是简单的转义，但为了统一，我们可以使用 Utils
            // 不过原代码使用了简单的替换，且作为 HTML 属性值和 JS 参数。
            // 为了保持一致性，我们保持 escapedItem 的逻辑，或者用 Utils.escapeHtml
            // 但 Utils.escapeHtml 会转义更多字符，可能影响 JS 字符串参数解析。
            // 让我们先只替换 App.escapeHtml 如果有的话。
            // 检查之前的文件内容，这里并没有 App.escapeHtml 调用。
            // 原代码：onclick="ModelMap.removeManualInclude('${escapedItem}')"
            // 看来这部分没有用到 escapeHtml 函数，而是手动 replace。
            
            return `
                <span class="tag-input-tag" data-value="${escapedItem}">
                    ${displayName}
                    <button type="button" class="tag-remove" onclick="ModelMap.removeManualInclude('${escapedItem}')" title="移除">×</button>
                </span>
            `;
        }).join('');
    },

    /**
     * 将 provider_id:model 格式转换为 provider_name:model 用于显示
     */
    formatManualIncludeForDisplay(item) {
        if (!item.includes(':')) return item;
        
        const firstColonIndex = item.indexOf(':');
        const providerId = item.substring(0, firstColonIndex);
        const model = item.substring(firstColonIndex + 1);
        
        const providerName = this.providerIdNameMap[providerId];
        if (providerName) {
            return `${providerName}:${model}`;
        }
        return item;
    },

        /**
         * 从手动包含列表中移除模型
         */
        removeManualInclude(item) {
            const hiddenInput = document.getElementById('mapping-manual-includes');
            const tagsContainer = document.getElementById('manual-includes-tags');
            const tagsWrapper = tagsContainer.querySelector('.tag-input-tags');
            
            let currentModels = hiddenInput.value.split('\n').map(m => m.trim()).filter(m => m);
            currentModels = currentModels.filter(m => m !== item);
            
            hiddenInput.value = currentModels.join('\n');
            tagsWrapper.innerHTML = this.renderManualIncludeTags(currentModels);
            Toast.success('已移除');
        },
    
        addToManualInclude(model) {
            const hiddenInput = document.getElementById('mapping-manual-includes');
            const tagsContainer = document.getElementById('manual-includes-tags');
            const tagsWrapper = tagsContainer.querySelector('.tag-input-tags');
            const currentModels = hiddenInput.value.split('\n').map(m => m.trim()).filter(m => m);
            
            // 使用 provider_id 构建引用
            const providerId = this.currentProviderId;
            const providerName = this.providerIdNameMap[providerId] || providerId;
            const fullRef = providerId ? `${providerId}:${model}` : model;
            const displayRef = providerId ? `${providerName}:${model}` : model;
            
            if (!currentModels.includes(fullRef) && !currentModels.includes(model)) {
                currentModels.push(fullRef);
                hiddenInput.value = currentModels.join('\n');
                tagsWrapper.innerHTML = this.renderManualIncludeTags(currentModels);Toast.success(`已添加: ${displayRef}`);
            } else {
                Toast.info('该模型已在列表中');
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
        
        // matched_models 的 key 是 provider_id
        for (const [providerId, models] of Object.entries(matched_models)) {
            const providerName = this.providerIdNameMap[providerId] || providerId;
            html += `
                <div class="preview-provider">
                    <div class="provider-header">${providerName} (${models.length})</div>
                    <div class="provider-models">
                        ${models.map(m => `
                            <span class="model-tag">
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
        const rules = this.collectRules();
        const manualIncludes = document.getElementById('mapping-manual-includes').value
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
                rules,
                manual_includes: manualIncludes,
                excluded_providers: excludedProviders
            });
            
            Modal.close();
            
            // 立即同步
            await this.syncSingle(unifiedName);
        } catch (error) {
            Toast.error('创建失败: ' + error.message);
        }
    },

    async update(event, unifiedName) {
        event.preventDefault();
        
        const newUnifiedName = document.getElementById('mapping-unified-name').value.trim();
        const rules = this.collectRules();
        const manualIncludes = document.getElementById('mapping-manual-includes').value
            .split('\n').map(m => m.trim()).filter(m => m);
        const excludedProviders = this.collectExcludedProviders();
        
        if (!newUnifiedName) {
            Toast.warning('请输入统一模型名称');
            return;
        }
        
        if (rules.length === 0 && manualIncludes.length === 0) {
            Toast.warning('请至少添加一个规则或手动包含一个模型');
            return;
        }
        
        try {
            const result = await API.updateModelMapping(unifiedName, {
                new_unified_name: newUnifiedName !== unifiedName ? newUnifiedName : undefined,
                rules,
                manual_includes: manualIncludes,
                excluded_providers: excludedProviders
            });
            
            Modal.close();
            
            // 使用返回的最新名称进行同步
            const finalName = result.unified_name || newUnifiedName;
            await this.syncSingle(finalName);
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
    },

    // ==================== 启用/禁用映射 ====================

    /**
     * 切换模型映射的启用/禁用状态
     */
    async toggleEnabled(unifiedName, enabled) {
        try {
            await API.updateModelMapping(unifiedName, { enabled });
            // 更新本地缓存
            if (this.mappings[unifiedName]) {
                this.mappings[unifiedName].enabled = enabled;
            }
            
            Toast.success(enabled ? '映射已启用' : '映射已禁用');
            this.render();
        } catch (error) {
            Toast.error('更新失败: ' + error.message);
            // 失败时重新加载以恢复正确状态
            await this.load();
        }
    },

    // ==================== 协议配置功能 ====================

    /**
     * 右键直接弹出协议配置模态框
     */
    showModelContextMenu(event, unifiedName, providerId) {
        event.preventDefault();
        
        // 获取点击的模型标签
        const target = event.target.closest('.model-tag');
        if (!target) return false;
        
        const model = target.dataset.model;
        if (!model) return false;
        
        // 直接弹出协议配置模态框
        this.showProtocolModal(unifiedName, providerId, model);
        
        return false;
    },

    /**
     * 显示单个模型协议配置模态框
     */
    showProtocolModal(unifiedName, providerId, model) {
        const providerName = this.providerIdNameMap[providerId] || providerId;
        const protocolStatus = this.getModelProtocolStatus(unifiedName, providerId, model);
        const providerDefaultProtocol = this.providerDefaultProtocols[providerId] || '(未设置)';
        
        const protocolOptions = this.availableProtocols.map(p => {
            const selected = protocolStatus.protocol === p.value && protocolStatus.source === 'model' ? 'selected' : '';
            return `<option value="${p.value}" ${selected}>${p.label}</option>`;
        }).join('');
        
        const content = `
            <form onsubmit="ModelMap.saveModelProtocol(event, '${unifiedName}', '${providerId}', '${model}')">
                <div class="form-group">
                    <label>模型</label>
                    <input type="text" value="${model}" disabled>
                </div>
                <div class="form-group">
                    <label>所属渠道</label>
                    <input type="text" value="${providerName}" disabled>
                    <div class="hint">渠道默认协议: ${providerDefaultProtocol}</div>
                </div>
                <div class="form-group">
                    <label>当前状态</label>
                    <div class="protocol-status">
                        ${protocolStatus.isConfigured
                            ? `<span class="status-badge info">${protocolStatus.protocol} (${protocolStatus.source === 'model' ? '模型级配置' : 'Provider默认'})</span>`
                            : `<span class="status-badge warning">未配置 - 该模型将被跳过</span>`
                        }
                    </div>
                </div>
                <div class="form-group">
                    <label>选择协议</label>
                    <select id="model-protocol-select">
                        <option value="">使用 Provider 默认</option>
                        ${protocolOptions}
                    </select>
                </div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="Modal.close()">取消</button>
                    <button type="submit" class="btn btn-primary">保存</button>
                </div>
            </form>
        `;
        
        Modal.show('配置模型协议', content, { width: '500px' });
    },

    /**
     * 保存单个模型协议配置
     */
    async saveModelProtocol(event, unifiedName, providerId, model) {
        event.preventDefault();
        
        const protocol = document.getElementById('model-protocol-select').value || null;
        
        try {
            await API.updateModelProtocol(unifiedName, {
                provider_id: providerId,
                model_id: model,
                protocol: protocol
            });
            
            // 更新本地缓存
            if (!this.mappings[unifiedName].model_settings) {
                this.mappings[unifiedName].model_settings = {};
            }
            const key = `${providerId}:${model}`;
            if (protocol) {
                this.mappings[unifiedName].model_settings[key] = { protocol };
            } else {
                delete this.mappings[unifiedName].model_settings[key];
            }
            
            Modal.close();
            Toast.success(protocol ? `已设置协议为 ${protocol}` : '已清除模型协议配置');
            this.render();
        } catch (error) {
            Toast.error('保存失败: ' + error.message);
        }
    },

    /**
     * 显示批量协议配置模态框
     */
    showBatchProtocolModal(unifiedName) {
        const mapping = this.mappings[unifiedName];
        if (!mapping) {
            Toast.error('映射不存在');
            return;
        }
        
        const resolvedModels = mapping.resolved_models || {};
        const modelSettings = mapping.model_settings || {};
        
        // 统计各协议配置情况
        let configuredCount = 0;
        let unconfiguredCount = 0;
        
        for (const [providerId, models] of Object.entries(resolvedModels)) {
            for (const model of models) {
                const status = this.getModelProtocolStatus(unifiedName, providerId, model);
                if (status.isConfigured) {
                    configuredCount++;
                } else {
                    unconfiguredCount++;
                }
            }
        }
        
        const protocolOptions = this.availableProtocols.map(p => {
            return `<option value="${p.value}">${p.label}</option>`;
        }).join('');
        
        const content = `
            <form onsubmit="ModelMap.saveBatchProtocol(event, '${unifiedName}')">
                <div class="form-group">
                    <label>映射名称</label>
                    <input type="text" value="${unifiedName}" disabled>
                </div>
                <div class="form-group">
                    <label>当前状态</label>
                    <div class="batch-status">
                        <span class="status-badge info">已配置: ${configuredCount}</span>
                        ${unconfiguredCount > 0 ? `<span class="status-badge warning">未配置: ${unconfiguredCount}</span>` : ''}
                    </div>
                </div>
                <div class="form-group">
                    <label>批量操作范围</label>
                    <select id="batch-scope">
                        <option value="unconfigured">仅未配置的模型</option>
                        <option value="all">所有模型</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>设置协议</label>
                    <select id="batch-protocol">
                        ${protocolOptions}
                    </select>
                </div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="Modal.close()">取消</button>
                    <button type="submit" class="btn btn-primary">批量设置</button>
                </div>
            </form>
        `;
        
        Modal.show('批量配置模型协议', content, { width: '500px' });
    },

    /**
     * 保存批量协议配置
     */
    async saveBatchProtocol(event, unifiedName) {
        event.preventDefault();
        
        const scope = document.getElementById('batch-scope').value;
        const protocol = document.getElementById('batch-protocol').value;
        
        if (!protocol) {
            Toast.warning('请选择协议');
            return;
        }
        
        const mapping = this.mappings[unifiedName];
        const resolvedModels = mapping.resolved_models || {};
        
        let successCount = 0;
        let errorCount = 0;
        
        for (const [providerId, models] of Object.entries(resolvedModels)) {
            for (const model of models) {
                // 如果是只处理未配置的，检查是否已配置
                if (scope === 'unconfigured') {
                    const status = this.getModelProtocolStatus(unifiedName, providerId, model);
                    if (status.isConfigured) continue;
                }
                
                try {
                    await API.updateModelProtocol(unifiedName, {
                        provider_id: providerId,
                        model_id: model,
                        protocol: protocol
                    });
                    successCount++;
                } catch (e) {
                    console.error(`设置 ${providerId}:${model} 协议失败:`, e);
                    errorCount++;
                }
            }
        }
        
        Modal.close();
        
        if (errorCount === 0) {
            Toast.success(`成功配置 ${successCount} 个模型`);
        } else {
            Toast.warning(`配置完成: ${successCount} 成功, ${errorCount} 失败`);
        }
        
        // 重新加载以获取最新数据
        await this.load();
    },

    // ==================== 拖拽排序 ====================

    handleDragStart(event) {
        const card = event.target.closest('.model-map-card');
        if (!card) return;
        
        this.draggedItem = card;
        card.classList.add('dragging');
        event.dataTransfer.effectAllowed = 'move';
        event.dataTransfer.setData('text/plain', card.dataset.unifiedName);
    },

    handleDragEnd(event) {
        const card = event.target.closest('.model-map-card');
        if (card) {
            card.classList.remove('dragging');
        }
        this.draggedItem = null;
        
        // 移除所有 drag-over 样式
        document.querySelectorAll('.model-map-card.drag-over').forEach(el => {
            el.classList.remove('drag-over');
        });
    },

    handleDragOver(event) {
        event.preventDefault();
        event.dataTransfer.dropEffect = 'move';
        
        const card = event.target.closest('.model-map-card');
        if (!card || card === this.draggedItem) return;
        
        // 移除其他元素的 drag-over 样式
        document.querySelectorAll('.model-map-card.drag-over').forEach(el => {
            if (el !== card) el.classList.remove('drag-over');
        });
        
        card.classList.add('drag-over');
    },

    handleDrop(event) {
        event.preventDefault();
        
        const targetCard = event.target.closest('.model-map-card');
        if (!targetCard || !this.draggedItem || targetCard === this.draggedItem) return;
        
        const container = document.getElementById('model-map-list');
        const cards = Array.from(container.querySelectorAll('.model-map-card'));
        const draggedIndex = cards.indexOf(this.draggedItem);
        const targetIndex = cards.indexOf(targetCard);
        
        // 交换位置
        if (draggedIndex < targetIndex) {
            targetCard.parentNode.insertBefore(this.draggedItem, targetCard.nextSibling);
        } else {
            targetCard.parentNode.insertBefore(this.draggedItem, targetCard);
        }
        
        targetCard.classList.remove('drag-over');
        // 保存新顺序
        this.saveOrder();
    },

    async saveOrder() {
        const container = document.getElementById('model-map-list');
        const cards = container.querySelectorAll('.model-map-card');
        const orderedNames = Array.from(cards).map(card => card.dataset.unifiedName);
        
        try {
            await API.reorderModelMappings(orderedNames);
            // 更新本地缓存的order_index
            orderedNames.forEach((name, idx) => {
                if (this.mappings[name]) {
                    this.mappings[name].order_index = idx;
                }
            });
        } catch (error) {
            Toast.error('保存排序失败: ' + error.message);
            // 失败时重新渲染恢复原顺序
            this.render();
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
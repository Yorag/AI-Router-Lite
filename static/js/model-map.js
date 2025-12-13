/**
 * 模型映射管理模块
 */

const ModelMap = {
    modelMap: {},
    providerModels: {},  // 缓存各中转站的模型列表

    async init() {
        await this.load();
    },

    async load() {
        try {
            const data = await API.getModelMap();
            this.modelMap = data.model_map || {};
            this.render();
        } catch (error) {
            console.error('Load model map error:', error);
            Toast.error('加载模型映射失败');
        }
    },

    render() {
        const container = document.getElementById('model-map-list');
        const entries = Object.entries(this.modelMap);
        
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

        container.innerHTML = entries.map(([unifiedName, actualModels]) => `
            <div class="model-map-item">
                <div class="model-map-header">
                    <h4>📌 ${unifiedName}</h4>
                    <div class="actions">
                        <button class="btn btn-sm btn-secondary" onclick="ModelMap.showEditModal('${unifiedName}')">
                            编辑
                        </button>
                        <button class="btn btn-sm btn-danger" onclick="ModelMap.confirmDelete('${unifiedName}')">
                            删除
                        </button>
                    </div>
                </div>
                <div class="model-map-targets">
                    ${actualModels.map(model => `<span class="model-tag">${model}</span>`).join('')}
                </div>
            </div>
        `).join('');
    },

    async showCreateModal() {
        // 先获取所有中转站的模型
        Toast.info('正在获取中转站模型列表...');
        try {
            const data = await API.fetchAllProviderModels();
            this.providerModels = data.provider_models || {};
        } catch (error) {
            console.error('Fetch provider models error:', error);
            this.providerModels = {};
        }

        const providerOptions = Object.keys(this.providerModels).map(name => 
            `<option value="${name}">${name} (${this.providerModels[name].length} 个模型)</option>`
        ).join('');

        const content = `
            <form onsubmit="ModelMap.create(event)">
                <div class="form-group">
                    <label>统一模型名称</label>
                    <input type="text" id="mapping-unified-name" required placeholder="例如：gpt-4">
                    <div class="hint">用户在调用时使用的模型名称</div>
                </div>
                
                <div class="form-group">
                    <label>从中转站选择模型</label>
                    <select id="mapping-provider-select" onchange="ModelMap.onProviderChange()">
                        <option value="">-- 选择中转站 --</option>
                        ${providerOptions}
                    </select>
                </div>
                
                <div class="form-group">
                    <label>关键字筛选</label>
                    <input type="text" id="mapping-keyword" placeholder="输入关键字筛选模型，如 gpt-4" oninput="ModelMap.filterModels()">
                    <div class="hint">输入关键字自动筛选匹配的模型</div>
                </div>
                
                <div class="form-group">
                    <label>可选模型 <span id="model-count">(0)</span></label>
                    <div id="available-models" class="model-selector">
                        <div class="hint">请先选择中转站</div>
                    </div>
                </div>
                
                <div class="form-group">
                    <label>已选模型</label>
                    <textarea id="mapping-actual-models" rows="4" required placeholder="每行一个模型名称，或从上方点击选择"></textarea>
                    <div class="hint">当用户请求统一名称时，系统会从这些模型中选择可用的</div>
                </div>
                
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="Modal.close()">取消</button>
                    <button type="submit" class="btn btn-primary">添加映射</button>
                </div>
            </form>
        `;
        Modal.show('添加模型映射', content);
    },

    onProviderChange() {
        const providerName = document.getElementById('mapping-provider-select').value;
        this.currentProviderModels = this.providerModels[providerName] || [];
        this.filterModels();
    },

    currentProviderModels: [],

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
            <span class="model-tag clickable" onclick="ModelMap.selectModel('${model}')">${model}</span>
        `).join('');
    },

    selectModel(model) {
        const textarea = document.getElementById('mapping-actual-models');
        const currentModels = textarea.value.split('\n').map(m => m.trim()).filter(m => m);
        
        if (!currentModels.includes(model)) {
            currentModels.push(model);
            textarea.value = currentModels.join('\n');
        }
    },

    async create(event) {
        event.preventDefault();
        
        const unifiedName = document.getElementById('mapping-unified-name').value.trim();
        const modelsText = document.getElementById('mapping-actual-models').value.trim();
        
        if (!unifiedName) {
            Toast.warning('请输入统一模型名称');
            return;
        }
        
        const actualModels = modelsText.split('\n').map(m => m.trim()).filter(m => m);
        
        if (actualModels.length === 0) {
            Toast.warning('请至少添加一个实际模型');
            return;
        }
        
        try {
            await API.addModelMapping(unifiedName, actualModels);
            Modal.close();
            Toast.success('模型映射已添加');
            await this.load();
            this.showReloadHint();
        } catch (error) {
            Toast.error('添加失败: ' + error.message);
        }
    },

    async showEditModal(unifiedName) {
        const actualModels = this.modelMap[unifiedName] || [];
        const modelsText = actualModels.join('\n');
        
        // 获取所有中转站的模型
        Toast.info('正在获取中转站模型列表...');
        try {
            const data = await API.fetchAllProviderModels();
            this.providerModels = data.provider_models || {};
        } catch (error) {
            console.error('Fetch provider models error:', error);
            this.providerModels = {};
        }

        const providerOptions = Object.keys(this.providerModels).map(name => 
            `<option value="${name}">${name} (${this.providerModels[name].length} 个模型)</option>`
        ).join('');
        
        const content = `
            <form onsubmit="ModelMap.update(event, '${unifiedName}')">
                <div class="form-group">
                    <label>统一模型名称</label>
                    <input type="text" value="${unifiedName}" disabled>
                    <div class="hint">名称不可修改，如需更改请删除后重新创建</div>
                </div>
                
                <div class="form-group">
                    <label>从中转站选择模型</label>
                    <select id="mapping-provider-select" onchange="ModelMap.onProviderChange()">
                        <option value="">-- 选择中转站 --</option>
                        ${providerOptions}
                    </select>
                </div>
                
                <div class="form-group">
                    <label>关键字筛选</label>
                    <input type="text" id="mapping-keyword" placeholder="输入关键字筛选模型" oninput="ModelMap.filterModels()">
                </div>
                
                <div class="form-group">
                    <label>可选模型 <span id="model-count">(0)</span></label>
                    <div id="available-models" class="model-selector">
                        <div class="hint">请先选择中转站</div>
                    </div>
                </div>
                
                <div class="form-group">
                    <label>已选模型</label>
                    <textarea id="edit-mapping-models" rows="6" required>${modelsText}</textarea>
                    <div class="hint">每行一个模型名称</div>
                </div>
                
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="Modal.close()">取消</button>
                    <button type="submit" class="btn btn-primary">保存</button>
                </div>
            </form>
        `;
        Modal.show('编辑模型映射', content);
    },

    async update(event, unifiedName) {
        event.preventDefault();
        
        const modelsText = document.getElementById('edit-mapping-models').value.trim();
        const actualModels = modelsText.split('\n').map(m => m.trim()).filter(m => m);
        
        if (actualModels.length === 0) {
            Toast.warning('请至少保留一个实际模型');
            return;
        }
        
        try {
            await API.updateModelMapping(unifiedName, actualModels);
            Modal.close();
            Toast.success('模型映射已更新');
            await this.load();
            this.showReloadHint();
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
            this.showReloadHint();
        } catch (error) {
            Toast.error('删除失败: ' + error.message);
        }
    },

    showReloadHint() {
        Modal.confirm(
            '配置已更新',
            '模型映射配置已更新。是否立即重新加载配置使更改生效？',
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
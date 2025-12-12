/**
 * 模型映射管理模块
 */

const ModelMap = {
    modelMap: {},

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

    showCreateModal() {
        const content = `
            <form onsubmit="ModelMap.create(event)">
                <div class="form-group">
                    <label>统一模型名称</label>
                    <input type="text" id="mapping-unified-name" required placeholder="例如：gpt-4">
                    <div class="hint">用户在调用时使用的模型名称</div>
                </div>
                <div class="form-group">
                    <label>实际模型列表</label>
                    <textarea id="mapping-actual-models" rows="4" required placeholder="每行一个模型名称&#10;例如：&#10;gpt-4-0613&#10;gpt-4-turbo&#10;gpt-4-turbo-preview"></textarea>
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

    showEditModal(unifiedName) {
        const actualModels = this.modelMap[unifiedName] || [];
        const modelsText = actualModels.join('\n');
        
        const content = `
            <form onsubmit="ModelMap.update(event, '${unifiedName}')">
                <div class="form-group">
                    <label>统一模型名称</label>
                    <input type="text" value="${unifiedName}" disabled>
                    <div class="hint">名称不可修改，如需更改请删除后重新创建</div>
                </div>
                <div class="form-group">
                    <label>实际模型列表</label>
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
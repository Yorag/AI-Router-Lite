/**
 * API 密钥管理模块
 */

const APIKeys = {
    keys: [],

    async init() {
        await this.load();
    },

    async load() {
        try {
            const data = await API.listAPIKeys();
            this.keys = data.keys || [];
            this.render();
        } catch (error) {
            console.error('Load API keys error:', error);
            Toast.error('加载密钥列表失败');
        }
    },

    render() {
        const tbody = document.getElementById('api-keys-table');
        
        if (this.keys.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="8" class="empty-state">
                        <div class="empty-state-icon">🔑</div>
                        <div class="empty-state-text">暂无 API 密钥</div>
                        <div class="empty-state-hint">点击"创建密钥"按钮添加第一个密钥</div>
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = this.keys.map(key => `
            <tr>
                <td><code>${key.key_id}</code></td>
                <td>${key.name}</td>
                <td>
                    <span class="status-badge ${key.enabled ? 'enabled' : 'disabled'}">
                        ${key.enabled ? '启用' : '禁用'}
                    </span>
                </td>
                <td>${key.rate_limit}/分钟</td>
                <td>${key.total_requests}</td>
                <td>${key.last_used_str || '从未使用'}</td>
                <td>${key.created_at_str}</td>
                <td class="actions">
                    <button class="btn btn-sm btn-secondary" onclick="APIKeys.showEditModal('${key.key_id}')">
                        编辑
                    </button>
                    <button class="btn btn-sm ${key.enabled ? 'btn-secondary' : 'btn-success'}" 
                            onclick="APIKeys.toggleEnabled('${key.key_id}', ${!key.enabled})">
                        ${key.enabled ? '禁用' : '启用'}
                    </button>
                    <button class="btn btn-sm btn-danger" onclick="APIKeys.confirmDelete('${key.key_id}')">
                        删除
                    </button>
                </td>
            </tr>
        `).join('');
    },

    showCreateModal() {
        const content = `
            <form onsubmit="APIKeys.create(event)">
                <div class="form-group">
                    <label>密钥名称</label>
                    <input type="text" id="key-name" required placeholder="例如：生产环境密钥">
                    <div class="hint">用于标识此密钥的用途</div>
                </div>
                <div class="form-group">
                    <label>速率限制</label>
                    <input type="number" id="key-rate-limit" value="60" min="1" max="1000">
                    <div class="hint">每分钟允许的最大请求数</div>
                </div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="Modal.close()">取消</button>
                    <button type="submit" class="btn btn-primary">创建密钥</button>
                </div>
            </form>
        `;
        Modal.show('创建 API 密钥', content);
    },

    async create(event) {
        event.preventDefault();
        
        const name = document.getElementById('key-name').value.trim();
        const rateLimit = parseInt(document.getElementById('key-rate-limit').value) || 60;
        
        if (!name) {
            Toast.warning('请输入密钥名称');
            return;
        }
        
        try {
            const result = await API.createAPIKey(name, rateLimit);
            Modal.close();
            Modal.showKeyCreated(result.key, result.info);
        } catch (error) {
            Toast.error('创建密钥失败: ' + error.message);
        }
    },

    showEditModal(keyId) {
        const key = this.keys.find(k => k.key_id === keyId);
        if (!key) return;
        
        const content = `
            <form onsubmit="APIKeys.update(event, '${keyId}')">
                <div class="form-group">
                    <label>密钥 ID</label>
                    <input type="text" value="${key.key_id}" disabled>
                </div>
                <div class="form-group">
                    <label>密钥名称</label>
                    <input type="text" id="edit-key-name" value="${key.name}" required>
                </div>
                <div class="form-group">
                    <label>速率限制</label>
                    <input type="number" id="edit-key-rate-limit" value="${key.rate_limit}" min="1" max="1000">
                    <div class="hint">每分钟允许的最大请求数</div>
                </div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="Modal.close()">取消</button>
                    <button type="submit" class="btn btn-primary">保存</button>
                </div>
            </form>
        `;
        Modal.show('编辑 API 密钥', content);
    },

    async update(event, keyId) {
        event.preventDefault();
        
        const name = document.getElementById('edit-key-name').value.trim();
        const rateLimit = parseInt(document.getElementById('edit-key-rate-limit').value) || 60;
        
        try {
            await API.updateAPIKey(keyId, { name, rate_limit: rateLimit });
            Modal.close();
            Toast.success('密钥已更新');
            await this.load();
        } catch (error) {
            Toast.error('更新失败: ' + error.message);
        }
    },

    async toggleEnabled(keyId, enabled) {
        try {
            await API.updateAPIKey(keyId, { enabled });
            Toast.success(enabled ? '密钥已启用' : '密钥已禁用');
            await this.load();
        } catch (error) {
            Toast.error('操作失败: ' + error.message);
        }
    },

    confirmDelete(keyId) {
        Modal.confirm(
            '确认删除',
            `确定要删除密钥 "${keyId}" 吗？此操作不可恢复。`,
            () => this.delete(keyId)
        );
    },

    async delete(keyId) {
        try {
            await API.deleteAPIKey(keyId);
            Toast.success('密钥已删除');
            await this.load();
        } catch (error) {
            Toast.error('删除失败: ' + error.message);
        }
    }
};
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
                    <td colspan="7" class="empty-state">
                        <div class="empty-state-icon"><i class="ri-key-2-line"></i></div>
                        <div class="empty-state-text">暂无 API 密钥</div>
                        <div class="empty-state-hint">点击"创建密钥"按钮添加第一个密钥</div>
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = this.keys.map(key => {
            const escapedFullKey = (key.full_key || '').replace(/'/g, "\\'");
            return `
                <tr>
                    <td>${key.name}</td>
                    <td class="key-cell">
                        <code class="key-code">${key.key_masked || ''}</code>
                        <button class="btn-icon" onclick="APIKeys.copyKey('${escapedFullKey}')" title="复制密钥">
                            <i class="ri-file-copy-line"></i>
                        </button>
                    </td>
                    <td>
                        <span class="status-badge ${key.enabled ? 'enabled' : 'disabled'}">
                            ${key.enabled ? '启用' : '禁用'}
                        </span>
                    </td>
                    <td>${key.total_requests.toLocaleString()}</td>
                    <td>${key.last_used_str || '从未使用'}</td>
                    <td>${key.created_at_str}</td>
                    <td class="actions">
                        <button class="btn btn-sm btn-secondary" onclick="APIKeys.showEditModal('${key.key_id}')">
                            编辑
                        </button>
                        <button class="btn btn-sm btn-warning" onclick="APIKeys.confirmReset('${key.key_id}')">
                            重置
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
            `;
        }).join('');
    },

    copyKey(fullKey) {
        Utils.copyToClipboard(fullKey).then(() => {
            Toast.success('密钥已复制到剪贴板');
        }).catch(() => {
            Toast.error('复制失败');
        });
    },

    showCreateModal() {
        const content = `
            <form onsubmit="APIKeys.create(event)">
                <div class="form-group">
                    <label>密钥名称</label>
                    <input type="text" id="key-name" required placeholder="例如：生产环境密钥">
                    <div class="hint">用于标识此密钥的用途</div>
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

        if (!name) {
            Toast.warning('请输入密钥名称');
            return;
        }

        try {
            await API.createAPIKey(name);
            Modal.close();
            Toast.success('密钥创建成功');
            await this.load();
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
                    <label>密钥名称</label>
                    <input type="text" id="edit-key-name" value="${key.name}" required>
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
        
        try {
            await API.updateAPIKey(keyId, { name });
            Modal.close();
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
    },

    confirmReset(keyId) {
        const key = this.keys.find(k => k.key_id === keyId);
        Modal.confirm(
            '确认重置密钥',
            `确定要重置密钥 "${key?.name || keyId}" 吗？重置后旧密钥将立即失效。`,
            () => this.resetKey(keyId)
        );
    },

    async resetKey(keyId) {
        try {
            await API.resetAPIKey(keyId);
            Toast.success('密钥已重置');
            await this.load();
        } catch (error) {
            Toast.error('重置失败: ' + error.message);
        }
    }
};
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

    /**
     * 复制文本到剪贴板（带 fallback）
     */
    copyToClipboard(text) {
        // 优先使用现代 Clipboard API
        if (navigator.clipboard && window.isSecureContext) {
            return navigator.clipboard.writeText(text);
        }
        
        // Fallback: 使用传统方法
        return new Promise((resolve, reject) => {
            const textArea = document.createElement('textarea');
            textArea.value = text;
            textArea.style.position = 'fixed';
            textArea.style.left = '-9999px';
            textArea.style.top = '-9999px';
            document.body.appendChild(textArea);
            textArea.focus();
            textArea.select();
            
            try {
                const successful = document.execCommand('copy');
                document.body.removeChild(textArea);
                if (successful) {
                    resolve();
                } else {
                    reject(new Error('execCommand failed'));
                }
            } catch (err) {
                document.body.removeChild(textArea);
                reject(err);
            }
        });
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
            return `
                <tr>
                    <td>${key.name}</td>
                    <td class="key-cell">
                        <code class="key-code">${key.key_masked || ''}</code>
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
            const result = await API.createAPIKey(name);
            Modal.close();
            // 显示密钥创建成功弹窗
            this.showKeyCreatedModal(result.key);
        } catch (error) {
            Toast.error('创建密钥失败: ' + error.message);
        }
    },

    showKeyCreatedModal(keyPlain) {
        const content = `
            <div class="key-created-notice">
                <p><i class="ri-alert-line"></i> 请立即复制并妥善保存此密钥，关闭后将无法再次查看！</p>
            </div>
            <div class="form-group">
                <label>API 密钥</label>
                <div class="key-display" onclick="APIKeys.copyCreatedKey(event)" style="cursor: pointer;" title="点击复制">
                    <code id="created-key-value" style="pointer-events: none;">${keyPlain}</code>
                </div>
                <div class="hint" style="text-align: right; margin-top: 4px;">点击密钥即可复制</div>
            </div>
            <div class="form-actions">
                <button type="button" class="btn btn-primary" onclick="Modal.close(); APIKeys.load();">
                    我已保存，关闭
                </button>
            </div>
        `;
        Modal.show('<i class="ri-key-2-line"></i> 密钥创建成功', content);
    },

    copyCreatedKey(event) {
        if (event) {
            event.stopPropagation();
        }

        const keyValue = document.getElementById('created-key-value').textContent;
        this.copyToClipboard(keyValue).then(() => {
            Toast.success('密钥已复制到剪贴板');
        }).catch(() => {
            Toast.error('复制失败，请手动复制');
        });
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
    }
};
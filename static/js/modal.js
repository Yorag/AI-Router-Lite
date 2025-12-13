/**
 * 模态框模块
 */

const Modal = {
    overlay: null,
    modalEl: null,
    titleEl: null,
    contentEl: null,

    init() {
        this.overlay = document.getElementById('modal-overlay');
        this.modalEl = this.overlay.querySelector('.modal');
        this.titleEl = document.getElementById('modal-title');
        this.contentEl = document.getElementById('modal-content');
    },

    /**
     * 显示模态框
     * @param {string} title - 标题
     * @param {string|HTMLElement} content - 内容
     * @param {Object} options - 选项
     * @param {string} options.width - 宽度，如 '800px'
     */
    show(title, content, options = {}) {
        this.titleEl.textContent = title;
        
        if (typeof content === 'string') {
            this.contentEl.innerHTML = content;
        } else {
            this.contentEl.innerHTML = '';
            this.contentEl.appendChild(content);
        }
        
        // 设置宽度
        if (options.width) {
            this.modalEl.style.maxWidth = options.width;
            this.modalEl.classList.add('wide');
        } else {
            this.modalEl.style.maxWidth = '';
            this.modalEl.classList.remove('wide');
        }
        
        this.overlay.classList.add('active');
        document.body.style.overflow = 'hidden';
    },

    close() {
        this.overlay.classList.remove('active');
        document.body.style.overflow = '';
        // 重置宽度
        this.modalEl.style.maxWidth = '';
        this.modalEl.classList.remove('wide');
    },

    /**
     * 显示确认对话框
     */
    confirm(title, message, onConfirm) {
        const content = `
            <p style="margin-bottom: 24px; color: var(--text-secondary);">${message}</p>
            <div class="form-actions">
                <button class="btn btn-secondary" onclick="Modal.close()">取消</button>
                <button class="btn btn-danger" id="modal-confirm-btn">确认</button>
            </div>
        `;
        
        this.show(title, content);
        
        document.getElementById('modal-confirm-btn').onclick = () => {
            this.close();
            if (onConfirm) onConfirm();
        };
    },

    /**
     * 显示成功创建密钥的弹窗
     */
    showKeyCreated(key, info) {
        const content = `
            <p style="color: var(--text-secondary);">您的 API 密钥已创建成功：</p>
            <div class="key-display">${key}</div>
            <button class="btn btn-secondary copy-btn" onclick="Modal.copyKey('${key}')">
                📋 复制密钥
            </button>
            <div class="key-warning">
                ⚠️ 请立即保存此密钥，关闭后将无法再次查看完整密钥！
            </div>
            <div class="form-actions">
                <button class="btn btn-primary" onclick="Modal.close(); APIKeys.load();">我已保存</button>
            </div>
        `;
        
        this.show('密钥创建成功', content);
    },

    copyKey(key) {
        navigator.clipboard.writeText(key).then(() => {
            Toast.success('密钥已复制到剪贴板');
        }).catch(() => {
            Toast.error('复制失败，请手动复制');
        });
    }
};

// 页面加载时初始化
document.addEventListener('DOMContentLoaded', () => {
    Modal.init();
});
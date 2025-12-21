/**
 * 通用工具函数模块
 */

const TIME_CONSTANTS = {
    SECONDS_PER_MINUTE: 60,
    SECONDS_PER_HOUR: 3600,
    SECONDS_PER_DAY: 86400
};

const Utils = {
    // 格式化时间戳 (秒 -> 本地时间字符串)
    formatTime(timestamp) {
        if (!timestamp) return '-';
        const date = new Date(timestamp * 1000);
        return date.toLocaleString('zh-CN');
    },

    // 格式化日期时间为 YYYY/MM/DD HH:MM:SS
    // 支持时间戳(ms) 或 Date 对象或日期字符串
    formatDateTime(input) {
        if (!input) return '-';
        const date = new Date(input);

        const pad = (num) => num.toString().padStart(2, '0');

        const year = date.getFullYear();
        const month = pad(date.getMonth() + 1);
        const day = pad(date.getDate());
        const hours = pad(date.getHours());
        const minutes = pad(date.getMinutes());
        const seconds = pad(date.getSeconds());

        return `${year}/${month}/${day} ${hours}:${minutes}:${seconds}`;
    },

    // 格式化相对时间
    formatRelativeTime(timestamp) {
        if (!timestamp) return '-';
        
        // 兼容秒和毫秒时间戳
        const isMilliseconds = timestamp > 1000000000000;
        const tsInSeconds = isMilliseconds ? timestamp / 1000 : timestamp;
        
        const now = Date.now() / 1000;
        const diff = now - tsInSeconds;
        
        if (diff < TIME_CONSTANTS.SECONDS_PER_MINUTE) return '刚刚';
        if (diff < TIME_CONSTANTS.SECONDS_PER_HOUR) return `${Math.floor(diff / TIME_CONSTANTS.SECONDS_PER_MINUTE)} 分钟前`;
        if (diff < TIME_CONSTANTS.SECONDS_PER_DAY) return `${Math.floor(diff / TIME_CONSTANTS.SECONDS_PER_HOUR)} 小时前`;
        return `${Math.floor(diff / TIME_CONSTANTS.SECONDS_PER_DAY)} 天前`;
    },

    // 复制到剪贴板（带 fallback）
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

    // HTML 转义
    escapeHtml(text) {
        if (!text) return '';
        // 处理数字或其他类型
        const str = String(text);
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    },

    // 格式化数字 (k, M, B)
    formatNumber(num) {
        if (!num) return '0';
        if (num >= 1000000000) return (num / 1000000000).toFixed(1) + 'B';
        if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
        if (num >= 1000) return (num / 1000).toFixed(1) + 'k';
        return num.toString();
    },

    /**
     * 生成协议标签的 HTML
     * @param {string} protocol - 协议名称，例如 'openai', 'anthropic'。传入 null 或 undefined 将显示 'Empty'。
     * @param {string} title - 标签的 title 属性
     * @returns {string} - 生成的 HTML 字符串
     */
    renderProtocolTag(protocol, title = '默认协议') {
        const isEmpty = !protocol;
        const cssClass = isEmpty ? 'protocol-tag-mini empty' : 'protocol-tag-mini';
        const text = isEmpty ? 'Empty' : protocol;
        return `<span class="${cssClass}" title="${title}">${text}</span>`;
    }
};
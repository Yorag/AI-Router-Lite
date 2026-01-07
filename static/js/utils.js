/**
 * 通用工具函数模块
 */

const TIME_CONSTANTS = {
    SECONDS_PER_MINUTE: 60,
    SECONDS_PER_HOUR: 3600,
    SECONDS_PER_DAY: 86400,
    SECONDS_PER_MONTH: 2592000
};

/**
 * 协议相关工具函数
 */
const ProtocolUtils = {
    // 默认协议列表（API 加载失败时的 fallback）
    DEFAULT_PROTOCOLS: [
        { value: 'openai', label: 'openai', description: 'OpenAI Chat Completions API' },
        { value: 'openai-response', label: 'openai-response', description: 'OpenAI Responses API' },
        { value: 'anthropic', label: 'anthropic', description: 'Anthropic Messages API' },
        { value: 'gemini', label: 'gemini', description: 'Google Gemini API' }
    ],

    /**
     * 从 API 加载可用协议类型
     * @returns {Promise<Array>} 协议列表
     */
    async loadProtocols() {
        try {
            const result = await API.getAvailableProtocols();
            const protocols = result.protocols;
            return protocols && protocols.length > 0 ? protocols : [...this.DEFAULT_PROTOCOLS];
        } catch (err) {
            console.warn('加载协议类型失败:', err);
            return [...this.DEFAULT_PROTOCOLS];
        }
    },

    /**
     * 生成协议选择下拉框的选项 HTML
     * @param {Array} protocols - 协议列表
     * @param {string} selectedValue - 当前选中的值
     * @returns {string} HTML 字符串
     */
    renderProtocolOptions(protocols, selectedValue = '') {
        const options = protocols.map(p => {
            const selected = p.value === selectedValue ? 'selected' : '';
            return `<option value="${p.value}" ${selected}>${p.label}</option>`;
        }).join('');

        const emptySelected = !selectedValue ? 'selected' : '';
        return `<option value="" ${emptySelected}>Empty (Not Specified)</option>${options}`;
    }
};

/**
 * Provider 模型数据处理工具
 */
const ProviderModelUtils = {
    /**
     * 处理从 API 返回的 provider_models 数据
     * @param {Object} rawData - { provider_id: { provider_name: "xxx", models: [...] } }
     * @returns {Object} { providerModels, providerIdNameMap }
     */
    processProviderModelsData(rawData) {
        const providerModels = {};
        const providerIdNameMap = {};

        for (const [providerId, providerData] of Object.entries(rawData)) {
            const providerName = providerData.provider_name || providerId;
            const models = providerData.models || [];

            providerIdNameMap[providerId] = providerName;
            providerModels[providerId] = models;
        }

        return { providerModels, providerIdNameMap };
    },

    /**
     * 更新模型详情缓存
     * @param {Object} providerModels - 支持两种格式:
     *   - API 原始格式: { provider_id: { models: [...], provider_name: "xxx" } }
     *   - 处理后格式: { provider_id: [...] } (模型数组)
     * @param {Object} targetCache - 目标缓存对象
     */
    updateModelDetailsCache(providerModels, targetCache) {
        for (const [providerId, providerData] of Object.entries(providerModels)) {
            // 兼容两种数据格式
            const models = Array.isArray(providerData) ? providerData : (providerData.models || []);
            if (models.length > 0) {
                targetCache[providerId] = {};
                models.forEach(m => {
                    // 模型可能是字符串或对象
                    const modelObj = typeof m === 'string' ? { id: m } : m;
                    targetCache[providerId][modelObj.id] = {
                        id: modelObj.id,
                        owned_by: modelObj.owned_by || '',
                        supported_endpoint_types: modelObj.supported_endpoint_types || []
                    };
                });
            }
        }
    }
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
    // 支持: 秒时间戳、毫秒时间戳、Date对象、ISO字符串
    formatRelativeTime(input) {
        if (!input) return '-';

        // 统一转换为毫秒时间戳
        let ms;
        if (typeof input === 'number') {
            ms = input > 1e12 ? input : input * 1000;
        } else {
            ms = new Date(input).getTime();
        }
        if (isNaN(ms)) return '-';

        const tsInSeconds = ms / 1000;
        
        const now = Date.now() / 1000;
        const diff = now - tsInSeconds;
        
        if (diff < TIME_CONSTANTS.SECONDS_PER_MINUTE) return '刚刚';
        if (diff < TIME_CONSTANTS.SECONDS_PER_HOUR) return `${Math.floor(diff / TIME_CONSTANTS.SECONDS_PER_MINUTE)}分钟前`;
        if (diff < TIME_CONSTANTS.SECONDS_PER_DAY) return `${Math.floor(diff / TIME_CONSTANTS.SECONDS_PER_HOUR)}小时前`;
        if (diff < TIME_CONSTANTS.SECONDS_PER_MONTH) return `${Math.floor(diff / TIME_CONSTANTS.SECONDS_PER_DAY)}天前`;
        return `${Math.floor(diff / TIME_CONSTANTS.SECONDS_PER_MONTH)}个月前`;
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
/**
 * API 模块 - 处理所有后端 API 调用
 */

// API 相关常量配置
const API_CONSTANTS = {
    DEFAULT_RATE_LIMIT: 60,      // 默认速率限制（每分钟请求数）
    DEFAULT_HOURLY_STATS_DAYS: 7 // 默认小时统计天数
};

const API = {
    baseUrl: '',  // 使用相对路径

    /**
     * 发送请求
     */
    async request(method, endpoint, data = null) {
        const options = {
            method,
            headers: {
                'Content-Type': 'application/json'
            }
        };

        if (data) {
            options.body = JSON.stringify(data);
        }

        try {
            const response = await fetch(`${this.baseUrl}${endpoint}`, options);
            const result = await response.json();
            
            if (!response.ok) {
                throw new Error(result.detail || result.message || '请求失败');
            }
            
            return result;
        } catch (error) {
            console.error(`API Error [${method} ${endpoint}]:`, error);
            throw error;
        }
    },

    // ==================== 系统 ====================

    async getHealth() {
        return this.request('GET', '/health');
    },

    async getSystemStats() {
        return this.request('GET', '/api/admin/system-stats');
    },

    async getStats() {
        return this.request('GET', '/stats');
    },

    async reloadConfig() {
        return this.request('POST', '/api/admin/reload-config');
    },

    // ==================== API 密钥 ====================

    async listAPIKeys() {
        return this.request('GET', '/api/keys');
    },

    async createAPIKey(name, rateLimit = API_CONSTANTS.DEFAULT_RATE_LIMIT) {
        return this.request('POST', '/api/keys', { name, rate_limit: rateLimit });
    },

    async getAPIKey(keyId) {
        return this.request('GET', `/api/keys/${keyId}`);
    },

    async updateAPIKey(keyId, data) {
        return this.request('PUT', `/api/keys/${keyId}`, data);
    },

    async deleteAPIKey(keyId) {
        return this.request('DELETE', `/api/keys/${keyId}`);
    },

    // ==================== 日志 ====================

    async getLogs(options = {}) {
        const params = new URLSearchParams();
        if (options.limit) params.append('limit', options.limit);
        if (options.level) params.append('level', options.level);
        if (options.type) params.append('log_type', options.type);
        if (options.model) params.append('model', options.model);
        if (options.provider) params.append('provider', options.provider);
        
        const query = params.toString();
        return this.request('GET', `/api/logs${query ? '?' + query : ''}`);
    },

    async getLogStats(date = null) {
        const params = date ? `?date=${date}` : '';
        return this.request('GET', `/api/logs/stats${params}`);
    },

    async getHourlyStats(days = API_CONSTANTS.DEFAULT_HOURLY_STATS_DAYS) {
        return this.request('GET', `/api/logs/hourly?days=${days}`);
    },

    // ==================== Provider ====================

    async listProviders() {
        return this.request('GET', '/api/providers');
    },

    async addProvider(data) {
        return this.request('POST', '/api/providers', data);
    },

    async getProvider(name) {
        return this.request('GET', `/api/providers/${encodeURIComponent(name)}`);
    },

    async updateProvider(name, data) {
        return this.request('PUT', `/api/providers/${encodeURIComponent(name)}`, data);
    },

    async deleteProvider(name) {
        return this.request('DELETE', `/api/providers/${encodeURIComponent(name)}`);
    },

    async testProvider(name, model = null) {
        const params = model ? `?model=${encodeURIComponent(model)}` : '';
        return this.request('POST', `/api/providers/${encodeURIComponent(name)}/test${params}`);
    },

    async testAllProviders() {
        return this.request('POST', '/api/providers/test-all');
    },

    async testAllProvidersAuto() {
        // 自动健康检测，跳过近期有活动的模型
        return this.request('POST', '/api/providers/test-all-auto');
    },

    async getTestResults() {
        return this.request('GET', '/api/providers/test-results');
    },

    async fetchProviderModels(name) {
        return this.request('GET', `/api/providers/${encodeURIComponent(name)}/models`);
    },

    async fetchAllProviderModels() {
        return this.request('GET', '/api/providers/all-models');
    },

    async resetProvider(name) {
        return this.request('POST', `/api/admin/reset/${encodeURIComponent(name)}`);
    },

    async resetAllProviders() {
        return this.request('POST', '/api/admin/reset-all');
    },

    // ==================== 模型映射 ====================

    async getModelMap() {
        return this.request('GET', '/api/model-map');
    },

    async updateModelMap(modelMap) {
        return this.request('PUT', '/api/model-map', modelMap);
    },

    async addModelMapping(unifiedName, actualModels) {
        return this.request('POST', '/api/model-map', {
            unified_name: unifiedName,
            actual_models: actualModels
        });
    },

    async updateModelMapping(unifiedName, actualModels) {
        return this.request('PUT', `/api/model-map/${encodeURIComponent(unifiedName)}`, actualModels);
    },

    async deleteModelMapping(unifiedName) {
        return this.request('DELETE', `/api/model-map/${encodeURIComponent(unifiedName)}`);
    }
};
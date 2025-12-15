/**
 * API 模块 - 处理所有后端 API 调用
 */

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

    async createAPIKey(name) {
        return this.request('POST', '/api/keys', { name });
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

    async getDailyStats(days = 7) {
        return this.request('GET', `/api/logs/daily?days=${days}`);
    },

    // ==================== Provider ====================

    async listProviders() {
        return this.request('GET', '/api/providers');
    },

    async addProvider(data) {
        return this.request('POST', '/api/providers', data);
    },

    /**
     * 获取指定 Provider（通过 ID 或 name）
     * @param {string} providerId - Provider ID (UUID) 或 name（兼容）
     */
    async getProvider(providerId) {
        return this.request('GET', `/api/providers/${encodeURIComponent(providerId)}`);
    },

    /**
     * 更新 Provider（通过 ID）
     * @param {string} providerId - Provider ID (UUID) 或 name（兼容）
     * @param {Object} data - 更新数据
     */
    async updateProvider(providerId, data) {
        return this.request('PUT', `/api/providers/${encodeURIComponent(providerId)}`, data);
    },

    /**
     * 删除 Provider（通过 ID）
     * @param {string} providerId - Provider ID (UUID) 或 name（兼容）
     */
    async deleteProvider(providerId) {
        return this.request('DELETE', `/api/providers/${encodeURIComponent(providerId)}`);
    },

    /**
     * 从中转站获取可用模型列表
     * @param {string} providerId - Provider ID (UUID) 或 name（兼容）
     */
    async fetchProviderModels(providerId) {
        return this.request('GET', `/api/providers/${encodeURIComponent(providerId)}/models`);
    },

    async fetchAllProviderModels() {
        return this.request('GET', '/api/providers/all-models');
    },

    /**
     * 并发同步所有中转站的模型列表
     * 后端使用 asyncio.gather 并发请求，比串行调用更高效
     */
    async syncAllProviderModels() {
        return this.request('POST', '/api/providers/sync-all-models');
    },

    /**
     * 重置 Provider 状态
     * @param {string} providerId - Provider ID (UUID) 或 name（兼容）
     */
    async resetProvider(providerId) {
        return this.request('POST', `/api/admin/reset/${encodeURIComponent(providerId)}`);
    },

    async resetAllProviders() {
        return this.request('POST', '/api/admin/reset-all');
    },

    // ==================== 模型映射（增强型） ====================

    /**
     * 获取所有模型映射配置
     * @returns {Promise<{mappings: Object, sync_config: Object}>}
     */
    async getModelMappings() {
        return this.request('GET', '/api/model-mappings');
    },

    /**
     * 创建新映射
     * @param {Object} data - {unified_name, description, rules, manual_includes, manual_excludes}
     */
    async createModelMapping(data) {
        return this.request('POST', '/api/model-mappings', data);
    },

    /**
     * 获取指定映射
     * @param {string} unifiedName
     */
    async getModelMapping(unifiedName) {
        return this.request('GET', `/api/model-mappings/${encodeURIComponent(unifiedName)}`);
    },

    /**
     * 更新映射
     * @param {string} unifiedName
     * @param {Object} data - {description?, rules?, manual_includes?, manual_excludes?}
     */
    async updateModelMapping(unifiedName, data) {
        return this.request('PUT', `/api/model-mappings/${encodeURIComponent(unifiedName)}`, data);
    },

    /**
     * 删除映射
     * @param {string} unifiedName
     */
    async deleteModelMapping(unifiedName) {
        return this.request('DELETE', `/api/model-mappings/${encodeURIComponent(unifiedName)}`);
    },

    /**
     * 手动触发同步
     * @param {string|null} unifiedName - 指定映射名称，null则同步全部
     */
    async syncModelMappings(unifiedName = null) {
        const params = unifiedName ? `?unified_name=${encodeURIComponent(unifiedName)}` : '';
        return this.request('POST', `/api/model-mappings/sync${params}`);
    },

    /**
     * 预览匹配结果
     * @param {Object} data - {rules, manual_includes, manual_excludes}
     */
    async previewModelMapping(data) {
        return this.request('POST', '/api/model-mappings/preview', data);
    },

    /**
     * 获取同步配置
     */
    async getSyncConfig() {
        return this.request('GET', '/api/model-mappings/sync-config');
    },

    /**
     * 更新同步配置
     * @param {Object} data - {auto_sync_enabled?, auto_sync_interval_hours?}
     */
    async updateSyncConfig(data) {
        return this.request('PUT', '/api/model-mappings/sync-config', data);
    },

    // ==================== 模型健康检测 ====================

    /**
     * 获取所有健康检测结果
     * @returns {Promise<{results: Object}>}
     */
    async getAllHealthResults() {
        return this.request('GET', '/api/model-health/results');
    },

    /**
     * 获取指定映射的健康检测结果
     * @param {string} unifiedName - 映射名称
     * @returns {Promise<{unified_name: string, results: Object}>}
     */
    async getMappingHealthResults(unifiedName) {
        return this.request('GET', `/api/model-health/results/${encodeURIComponent(unifiedName)}`);
    },

    /**
     * 检测指定映射下的所有模型
     * @param {string} unifiedName - 映射名称
     * @returns {Promise<{status: string, tested_count: number, success_count: number, results: Array}>}
     */
    async testMappingHealth(unifiedName) {
        return this.request('POST', `/api/model-health/test/${encodeURIComponent(unifiedName)}`);
    },

    /**
     * 检测单个模型
     * @param {string} providerId - Provider ID (UUID)
     * @param {string} model - 模型名称
     * @returns {Promise<Object>} - ModelHealthResult
     */
    async testSingleModelHealth(providerId, model) {
        return this.request('POST', '/api/model-health/test-single', { provider_id: providerId, model });
    }
};
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
            },
            credentials: 'same-origin'  // 确保发送 Cookie
        };

        if (data) {
            options.body = JSON.stringify(data);
        }

        try {
            const response = await fetch(`${this.baseUrl}${endpoint}`, options);
            
            // 处理 401 未认证错误 - 跳转到登录页
            if (response.status === 401) {
                window.location.href = '/admin/login.html';
                throw new Error('未登录或会话已过期');
            }
            
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

    // ==================== 认证 ====================

    async getAuthStatus() {
        return this.request('GET', '/api/auth/status');
    },

    async logout() {
        return this.request('POST', '/api/auth/logout');
    },

    async changePassword(oldPassword, newPassword) {
        return this.request('POST', '/api/auth/change-password', {
            old_password: oldPassword,
            new_password: newPassword
        });
    },

    // ==================== 系统 ====================

    async getHealth() {
        return this.request('GET', '/health');
    },

    async getSystemStats() {
        return this.request('GET', '/api/admin/system-stats');
    },

    async getStats(tag = null) {
        const params = tag ? `?tag=${encodeURIComponent(tag)}` : '';
        return this.request('GET', `/stats${params}`);
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

    async resetAPIKey(keyId) {
        return this.request('POST', `/api/keys/${keyId}/reset`);
    },

    // ==================== 日志 ====================

    async getLogs(options = {}) {
        const params = new URLSearchParams();
        if (options.limit) params.append('limit', options.limit);
        if (options.level) params.append('level', options.level);
        if (options.type) params.append('log_type', options.type);
        if (options.keyword) params.append('keyword', options.keyword);
        if (options.provider) params.append('provider', options.provider);
        
        const query = params.toString();
        return this.request('GET', `/api/logs${query ? '?' + query : ''}`);
    },

    async getLogStats(date = null, tag = null) {
        const params = new URLSearchParams();
        if (date) params.append('date', date);
        if (tag) params.append('tag', tag);
        const query = params.toString();
        return this.request('GET', `/api/logs/stats${query ? '?' + query : ''}`);
    },

    async getDailyStats(days = 7, tag = null) {
        const params = new URLSearchParams();
        params.append('days', days);
        if (tag) params.append('tag', tag);
        const query = params.toString();
        return this.request('GET', `/api/logs/daily?${query}`);
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
        return this.request('POST', `/api/providers/${encodeURIComponent(providerId)}/sync-models`);
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
     * 获取 Provider 和模型的运行时熔断状态（轻量级）
     * 用于前端实时展示模型的熔断/冷却状态
     * @returns {Promise<{providers: Object, models: Object}>}
     */
    async getRuntimeStates() {
        return this.request('GET', '/api/providers/runtime-states');
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
     * @param {Object} data - {unified_name, description, rules, manual_includes, excluded_providers}
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
     * @param {Object} data - {description?, rules?, manual_includes?, excluded_providers?}
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
     * @param {Object} data - {rules, manual_includes, excluded_providers}
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

    /**
     * 重新排序模型映射
     * @param {Array<string>} orderedNames - 按顺序排列的统一模型名称列表
     */
    async reorderModelMappings(orderedNames) {
        return this.request('POST', '/api/model-mappings/reorder', { ordered_names: orderedNames });
    },

    // ==================== 协议配置 ====================

    /**
     * 获取可用的协议类型列表
     * @returns {Promise<{protocols: Array}>}
     */
    async getAvailableProtocols() {
        return this.request('GET', '/api/protocols');
    },

    /**
     * 获取指定映射的模型协议配置
     * @param {string} unifiedName - 映射名称
     * @returns {Promise<{unified_name: string, model_settings: Object}>}
     */
    async getModelSettings(unifiedName) {
        return this.request('GET', `/api/model-mappings/${encodeURIComponent(unifiedName)}/model-settings`);
    },

    /**
     * 更新模型协议配置
     * @param {string} unifiedName - 映射名称
     * @param {Object} data - {provider_id, model_id, protocol}
     * @returns {Promise<{status: string, message: string}>}
     */
    async updateModelProtocol(unifiedName, data) {
        return this.request('PUT', `/api/model-mappings/${encodeURIComponent(unifiedName)}/model-settings`, data);
    },

    /**
     * 删除模型协议配置
     * @param {string} unifiedName - 映射名称
     * @param {string} providerId - Provider ID
     * @param {string} modelId - 模型 ID
     * @returns {Promise<{status: string, message: string}>}
     */
    async deleteModelProtocol(unifiedName, providerId, modelId) {
        return this.request('DELETE', `/api/model-mappings/${encodeURIComponent(unifiedName)}/model-settings/${encodeURIComponent(providerId)}/${encodeURIComponent(modelId)}`);
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
/**
 * ProviderHealth - Provider 健康状态圆点渲染（Dashboard/Providers 共享）
 */
const ProviderHealth = {
    escapeAttr(value) {
        if (value === null || value === undefined) return '';
        var result = '';
        var str = String(value);
        for (var i = 0; i < str.length; i++) {
            var c = str.charCodeAt(i);
            if (c === 38) result += String.fromCharCode(38) + 'amp;';
            else if (c === 60) result += String.fromCharCode(38) + 'lt;';
            else if (c === 62) result += String.fromCharCode(38) + 'gt;';
            else if (c === 34) result += String.fromCharCode(38) + 'quot;';
            else if (c === 39) result += String.fromCharCode(38) + '#39;';
            else result += str[i];
        }
        return result;
    },

    formatCooldownReason(reason) {
        var reasonMap = {
            'rate_limited': '触发限流',
            'server_error': '服务器错误',
            'timeout': '请求超时',
            'auth_failed': '认证失败',
            'network_error': '网络错误',
            'model_not_found': '模型不存在',
            'health_check_failed': '健康检测失败'
        };
        return reasonMap[reason] || reason || '未知原因';
    },

    normalize(input) {
        var enabled = input && input.enabled !== false;
        var runtime = input && input.runtime_status;
        if (runtime) {
            var status = runtime.status || 'healthy';
            var cooldownReason = runtime.cooldown_reason || null;
            var remainingSeconds = Math.ceil(runtime.cooldown_remaining || 0);
            var cooldownRemaining = status === 'cooling' ? remainingSeconds + 's' : null;
            var lastError = runtime.last_error || null;
            return { enabled: enabled, status: status, cooldown_reason: cooldownReason, cooldown_remaining: cooldownRemaining, last_error: lastError };
        }
        return {
            enabled: enabled,
            status: (input && input.status) || 'healthy',
            cooldown_reason: (input && input.cooldown_reason) || null,
            cooldown_remaining: (input && input.cooldown_remaining) || null,
            last_error: (input && input.last_error) || null
        };
    },

    renderDot(input, options) {
        options = options || {};
        var healthyTooltip = options.healthyTooltip || '运行正常';
        var unknownTooltip = options.unknownTooltip || '状态未知';
        var disabledTooltip = options.disabledTooltip || '已禁用';
        var showHealthyTooltip = options.showHealthyTooltip !== false;
        var n = this.normalize(input);

        if (!n.enabled) {
            return `<span class="provider-health-dot disabled" data-tooltip-content="${this.escapeAttr(disabledTooltip)}"></span>`;
        }
        if (n.status === 'permanently_disabled') {
            const reason = this.formatCooldownReason(n.cooldown_reason);
            const error = n.last_error ? `<br>${this.escapeAttr(n.last_error)}` : '';
            return `<span class="provider-health-dot permanently_disabled" data-tooltip-content="已熔断: ${this.escapeAttr(reason)}${error}"></span>`;
        }
        if (n.status === 'cooling') {
            const reason2 = this.formatCooldownReason(n.cooldown_reason);
            const remaining = n.cooldown_remaining || '0s';
            return `<span class="provider-health-dot cooling" data-tooltip-content="冷却中: ${this.escapeAttr(reason2)} (${this.escapeAttr(remaining)})"></span>`;
        }
        if (n.status === 'unknown') {
            // 未知状态使用默认样式（与 healthy 相同的外观，但不同的 tooltip）
            return `<span class="provider-health-dot healthy" data-tooltip-content="${this.escapeAttr(unknownTooltip)}"></span>`;
        }
        if (showHealthyTooltip) {
            return `<span class="provider-health-dot healthy" data-tooltip-content="${this.escapeAttr(healthyTooltip)}"></span>`;
        }
        return '<span class="provider-health-dot healthy"></span>';
    }
};
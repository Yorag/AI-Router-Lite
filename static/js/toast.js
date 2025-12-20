/**
 * Toast 通知模块
 */

// Toast 通知配置（毫秒）
const TOAST_CONSTANTS = {
    DURATION_DEFAULT: 3000,   // 默认/成功/信息通知
    DURATION_WARNING: 4000,   // 警告通知
    DURATION_ERROR: 5000,     // 错误通知
    ANIMATION_DURATION: 300   // 滑出动画时长
};

const Toast = {
    container: null,

    init() {
        this.container = document.getElementById('toast-container');
    },

    show(message, type = 'info', duration = TOAST_CONSTANTS.DURATION_DEFAULT) {
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        
        const icons = {
            success: '<i class="ri-checkbox-circle-line"></i>',
            error: '<i class="ri-close-circle-line"></i>',
            warning: '<i class="ri-alert-line"></i>',
            info: '<i class="ri-information-line"></i>'
        };
        
        toast.innerHTML = `
            <span class="toast-icon">${icons[type] || icons.info}</span>
            <span class="toast-message">${message}</span>
            <button class="toast-close" onclick="this.parentElement.remove()">&times;</button>
        `;
        
        this.container.appendChild(toast);
        
        // 自动移除
        setTimeout(() => {
            if (toast.parentElement) {
                toast.style.animation = `slideOut ${TOAST_CONSTANTS.ANIMATION_DURATION / 1000}s ease forwards`;
                setTimeout(() => toast.remove(), TOAST_CONSTANTS.ANIMATION_DURATION);
            }
        }, duration);
    },

    success(message) {
        this.show(message, 'success', TOAST_CONSTANTS.DURATION_DEFAULT);
    },

    error(message) {
        this.show(message, 'error', TOAST_CONSTANTS.DURATION_ERROR);
    },

    warning(message) {
        this.show(message, 'warning', TOAST_CONSTANTS.DURATION_WARNING);
    },

    info(message) {
        this.show(message, 'info', TOAST_CONSTANTS.DURATION_DEFAULT);
    }
};

// 添加滑出动画
const style = document.createElement('style');
style.textContent = `
    @keyframes slideOut {
        from {
            transform: translateX(0);
            opacity: 1;
        }
        to {
            transform: translateX(100%);
            opacity: 0;
        }
    }
`;
document.head.appendChild(style);

// 页面加载时初始化
document.addEventListener('DOMContentLoaded', () => {
    Toast.init();
});
/**
 * 主应用程序模块
 */

// 时间相关常量（秒）
const TIME_CONSTANTS = {
    SECONDS_PER_MINUTE: 60,
    SECONDS_PER_HOUR: 3600,
    SECONDS_PER_DAY: 86400
};

const App = {
    currentPage: 'dashboard',

    async init() {
        // 初始化导航
        this.initNavigation();
        
        // 初始化所有模块
        await Dashboard.init();
        
        // 检查URL hash
        const hash = window.location.hash.slice(1);
        if (hash) {
            this.navigateTo(hash);
        }
        
        // 监听hash变化
        window.addEventListener('hashchange', () => {
            const hash = window.location.hash.slice(1);
            if (hash) {
                this.navigateTo(hash);
            }
        });
        
        console.log('AI-Router-Lite Admin Panel initialized');
    },

    initNavigation() {
        const navItems = document.querySelectorAll('.nav-item');
        
        navItems.forEach(item => {
            item.addEventListener('click', (e) => {
                e.preventDefault();
                const page = item.dataset.page;
                this.navigateTo(page);
            });
        });
    },

    async navigateTo(page) {
        // 更新当前页面
        this.currentPage = page;
        
        // 更新URL hash
        window.location.hash = page;
        
        // 更新导航高亮
        document.querySelectorAll('.nav-item').forEach(item => {
            item.classList.toggle('active', item.dataset.page === page);
        });
        
        // 更新页面显示
        document.querySelectorAll('.page').forEach(pageEl => {
            pageEl.classList.toggle('active', pageEl.id === `page-${page}`);
        });
        
        // 加载页面数据
        switch (page) {
            case 'dashboard':
                await Dashboard.load();
                break;
            case 'api-keys':
                await APIKeys.init();
                break;
            case 'providers':
                await Providers.init();
                break;
            case 'model-map':
                await ModelMap.init();
                break;
            case 'logs':
                await Logs.init();
                break;
        }
    },

    // 工具函数：格式化时间
    formatTime(timestamp) {
        if (!timestamp) return '-';
        const date = new Date(timestamp * 1000);
        return date.toLocaleString('zh-CN');
    },

    // 工具函数：格式化日期时间为 YYYY/MM/DD HH:MM:SS
    formatDateTime(timestamp) {
        if (!timestamp) return '-';
        const date = new Date(timestamp);

        const pad = (num) => num.toString().padStart(2, '0');

        const year = date.getFullYear();
        const month = pad(date.getMonth() + 1);
        const day = pad(date.getDate());
        const hours = pad(date.getHours());
        const minutes = pad(date.getMinutes());
        const seconds = pad(date.getSeconds());

        return `${year}/${month}/${day} ${hours}:${minutes}:${seconds}`;
    },

    // 工具函数：格式化相对时间
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

    // 工具函数：复制到剪贴板
    async copyToClipboard(text) {
        try {
            await navigator.clipboard.writeText(text);
            Toast.success('已复制到剪贴板');
        } catch (error) {
            Toast.error('复制失败');
        }
    },

    // 工具函数：HTML 转义
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },

    // 工具函数：格式化数字 (k, M, B)
    formatNumber(num) {
        if (!num) return '0';
        if (num >= 1000000000) return (num / 1000000000).toFixed(1) + 'B';
        if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
        if (num >= 1000) return (num / 1000).toFixed(1) + 'k';
        return num.toString();
    }
};

// 页面加载完成后初始化应用
document.addEventListener('DOMContentLoaded', () => {
    App.init();
});
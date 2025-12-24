/**
 * 主应用程序模块
 */

const App = {
    currentPage: 'dashboard',

    async init() {
        // 检查认证状态
        try {
            const authStatus = await API.getAuthStatus();
            if (!authStatus.initialized || !authStatus.authenticated) {
                window.location.href = '/admin/login.html';
                return;
            }
        } catch (error) {
            console.error('认证检查失败:', error);
            window.location.href = '/admin/login.html';
            return;
        }

        // 初始化导航
        this.initNavigation();

        // 初始化 UI 组件
        Tooltip.init();
        
        // 初始化所有模块 (一次性)
        if (typeof Dashboard.init === 'function') await Dashboard.init();
        if (typeof APIKeys.init === 'function') await APIKeys.init();
        if (typeof Providers.init === 'function') await Providers.init();
        if (typeof ModelMap.init === 'function') await ModelMap.init();
        if (typeof Logs.init === 'function') await Logs.init();
        
        // 检查URL hash
        const hash = window.location.hash.slice(1);
        if (hash) {
            this.navigateTo(hash);
        } else {
            this.navigateTo('dashboard');
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
        
        // 加载页面数据 (调用 load 方法而不是 init)
        // 注意：各模块需确保实现了 load 方法，如果之前只有 init，需确认 init 是否可重入或修改为 load
        // 这里的假设是各模块的 init 方法包含了数据加载逻辑，且我们会保持现状，
        // 或者我们假设 Dashboard 有 load，其他模块目前只有 init。
        // 为了安全起见，我们将检查方法是否存在。
        
        switch (page) {
            case 'dashboard':
                if (typeof Dashboard.load === 'function') await Dashboard.load();
                break;
            case 'api-keys':
                if (typeof APIKeys.load === 'function') await APIKeys.load();
                else if (typeof APIKeys.init === 'function') await APIKeys.init();
                break;
            case 'providers':
                if (typeof Providers.load === 'function') await Providers.load();
                else if (typeof Providers.init === 'function') await Providers.init();
                break;
            case 'model-map':
                if (typeof ModelMap.load === 'function') await ModelMap.load();
                else if (typeof ModelMap.init === 'function') await ModelMap.init();
                break;
            case 'logs':
                if (typeof Logs.load === 'function') await Logs.load();
                else if (typeof Logs.init === 'function') await Logs.init();
                break;
        }
    },

    // 工具函数：复制到剪贴板
    async copyToClipboard(text) {
        try {
            await Utils.copyToClipboard(text);
            Toast.success('已复制到剪贴板');
        } catch (error) {
            Toast.error('复制失败');
        }
    },

    // 登出
    async logout() {
        try {
            await API.logout();
            window.location.href = '/admin/login.html';
        } catch (error) {
            Toast.error('登出失败');
        }
    },

    // 显示修改密码弹窗
    showChangePasswordModal() {
        Modal.show('修改密码', `
            <form onsubmit="App.handleChangePassword(event)">
                <div class="form-group">
                    <label>原密码</label>
                    <input type="password" id="old-password" required>
                </div>
                <div class="form-group">
                    <label>新密码</label>
                    <input type="password" id="new-password" required minlength="6">
                </div>
                <div class="form-group">
                    <label>确认新密码</label>
                    <input type="password" id="confirm-password" required minlength="6">
                </div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="Modal.close()">取消</button>
                    <button type="submit" class="btn btn-primary">确认修改</button>
                </div>
            </form>
        `);
    },

    // 处理修改密码
    async handleChangePassword(event) {
        event.preventDefault();
        
        const oldPassword = document.getElementById('old-password').value;
        const newPassword = document.getElementById('new-password').value;
        const confirmPassword = document.getElementById('confirm-password').value;
        
        if (newPassword !== confirmPassword) {
            Toast.error('两次输入的新密码不一致');
            return;
        }
        
        try {
            await API.changePassword(oldPassword, newPassword);
            Toast.success('密码修改成功');
            Modal.close();
        } catch (error) {
            Toast.error(error.message || '密码修改失败');
        }
    }
};

// 页面加载完成后初始化应用
document.addEventListener('DOMContentLoaded', () => {
    App.init();
});
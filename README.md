# 🚀 AI-Router-Lite (轻量级 AI 聚合路由)

> **告别"API 焦虑症"：自动检测、自动切换、统一接口。**  
> 一个专为个人开发者设计的轻量级 AI 模型中转聚合工具 (CLI 版)。

## 📖 背景与痛点

你是否也遇到过以下情况？

* **太乱**：A 站只有 Gemini，B 站有 Claude 但经常崩，C 站号称 GPT-4 却是假的。
* **太累**：在 Chatbox/NextChat 里配了一堆 Key，用的时候还要手动切来切去。
* **不可靠**：关键时刻想用，结果报错 `401` 或 `500`，不仅中断思路，还要去排查哪个 Key 过期了。

**AI-Router-Lite** 就是为了解决这些问题而生的。它充当一个"智能管家"，你只需要在软件里配置这**一个接口**，它会在后台自动帮你寻找可用的渠道，并在出错时自动重试。

## ✨ 核心功能

1. **统一接口标准**：对外完全模拟 OpenAI `/v1/chat/completions` 接口，完美兼容 Chatbox, NextChat, LobeChat 等客户端。
2. **智能模型映射**：将不同中转站五花八门的模型名（如 `gpt-4-0613`, `gpt-4-turbo-preview`）统一映射为你喜欢的名字（如 `gpt-4`）。
3. **流式响应支持**：完整支持 SSE 流式传输，实现真正的打字机效果。
4. **自动健康检测 & 熔断**：
   * 自动记录请求失败的渠道。
   * **401/403 (Key 错误/余额不足)**：永久拉黑该渠道。
   * **429 (超频)**：暂时停用 1 分钟。
   * **5xx (服务器崩)**：暂时停用 5 分钟。
   * **Timeout (超时)**：暂时停用 2 分钟。
5. **无感故障转移 (Failover)**：当首选渠道报错时，自动在后台切换到备用渠道重试，用户端无感知。
6. **加权路由选择**：根据配置的权重值，优先选择高权重的 Provider。
7. **可视化管理面板**：全新的 Web 管理界面，让你轻松管理所有配置。
8. **极简配置**：所有逻辑通过一个 `config.json` 文件管理，无需数据库。

## 🎨 管理面板 (v0.4.0 新增)

![管理面板预览](https://via.placeholder.com/800x400?text=AI-Router-Lite+Admin+Panel)

v0.4.0 新增了功能完善的 Web 管理面板，让你可以：

### 📊 仪表板
- 实时查看服务状态统计
- 今日请求量和成功率
- 请求趋势图（按小时统计）
- 模型使用分布图
- Provider 健康状态一览

### 🔑 密钥管理
- 创建和管理 API 密钥
- 设置每分钟速率限制
- 启用/禁用密钥
- 查看密钥使用统计

### 🌐 服务站管理
- 添加/编辑/删除 Provider
- 一键测试 Provider 可用性
- 自动刷新测试（每60秒）
- 查看模型测试结果和延迟

### 🔄 模型映射
- 可视化配置模型映射规则
- 将统一模型名映射到多个实际模型
- 实时生效的配置更新

### 📜 日志监控
- 实时日志流（SSE 推送）
- 按级别/类型/模型过滤
- 查看请求详情和错误信息

## 📦 项目结构

```
ai-router-lite/
├── main.py                 # FastAPI 主应用入口
├── config.json             # 配置文件（需要自行编辑）
├── config.example.json     # 配置模板
├── requirements.txt        # Python 依赖
├── setup_venv.bat          # Windows 虚拟环境配置脚本
├── .gitignore
├── data/                   # 运行时数据目录
│   └── .gitkeep
├── src/
│   ├── __init__.py
│   ├── config.py           # 配置管理模块
│   ├── models.py           # OpenAI 兼容数据模型
│   ├── provider.py         # Provider 管理和熔断逻辑
│   ├── router.py           # 路由策略模块
│   ├── proxy.py            # 请求代理（流式/非流式）
│   ├── api_keys.py         # API 密钥管理模块
│   ├── logger.py           # 日志记录模块
│   └── admin.py            # 管理功能模块
└── static/                 # 前端静态文件
    ├── index.html          # 管理面板主页
    ├── css/
    │   └── style.css       # 样式文件
    └── js/
        ├── api.js          # API 客户端
        ├── app.js          # 主应用程序
        ├── dashboard.js    # 仪表板模块
        ├── api-keys.js     # 密钥管理模块
        ├── providers.js    # Provider 管理模块
        ├── model-map.js    # 模型映射模块
        ├── logs.js         # 日志监控模块
        ├── modal.js        # 模态框组件
        └── toast.js        # Toast 通知组件
```

## 🛠️ 快速开始

### 1. 环境准备

确保你的电脑安装了 [Python 3.8+](https://www.python.org/)。

### 2. 安装依赖

**手动安装**

```bash
# 创建虚拟环境
python -m venv venv

# 激活虚拟环境
# Windows:
venv\Scripts\activate
# Unix/Mac:
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 3. 配置你的中转站 (`config.json`)

复制 `config.example.json` 为 `config.json`，然后填入你的中转站信息：

```json
{
  "server_port": 8000,
  "server_host": "0.0.0.0",
  "max_retries": 3,
  "request_timeout": 120,
  "model_map": {
    "gpt-4": ["gpt-4", "gpt-4-0613", "gpt-4-turbo"],
    "claude-3": ["claude-3-opus-20240229", "claude-3-sonnet-20240229"]
  },
  "providers": [
    {
      "name": "Site_A_Cheap",
      "base_url": "https://api.site-a.com/v1",
      "api_key": "sk-xxxxxx",
      "weight": 10,
      "timeout": 60,
      "supported_models": ["gpt-3.5-turbo", "gpt-4"]
    },
    {
      "name": "Site_B_Stable",
      "base_url": "https://api.site-b.xyz/v1",
      "api_key": "sk-yyyyyy",
      "weight": 5,
      "timeout": 90,
      "supported_models": ["gpt-4", "claude-3-opus-20240229"]
    }
  ]
}
```

### 4. 启动服务

```bash
python main.py
```

看到如下提示即启动成功：

```
╔══════════════════════════════════════════════════════════╗
║                                                          ║
║   🚀 AI-Router-Lite v0.4.0                              ║
║   轻量级 AI 聚合路由 + 管理面板                          ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝

[CONFIG] 服务地址: http://0.0.0.0:8000
[CONFIG] 管理面板: http://0.0.0.0:8000/admin
[CONFIG] 最大重试次数: 3
[CONFIG] Provider 数量: 2 个
[STARTUP] 服务启动完成，等待请求...
```

### 5. 访问管理面板

打开浏览器访问 `http://127.0.0.1:8000/admin` 即可使用管理面板。

### 6. 连接客户端

打开 Chatbox 或 NextChat：

* **API Host**: `http://127.0.0.1:8000`
* **API Key**: `any` (随意填写，因为验证逻辑在 Router 内部处理)
* **Model**: 输入你在映射里定义的名字，例如 `gpt-4`

## 🔌 API 端点

### OpenAI 兼容接口

| 端点 | 方法 | 说明 |
|------|------|------|
| `/v1/chat/completions` | POST | 聊天补全（OpenAI 兼容） |
| `/v1/models` | GET | 获取可用模型列表 |

### 系统接口

| 端点 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/stats` | GET | 获取详细统计信息 |

### 管理接口

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/keys` | GET/POST | API 密钥管理 |
| `/api/keys/{id}` | GET/PUT/DELETE | 单个密钥操作 |
| `/api/logs` | GET | 获取日志列表 |
| `/api/logs/stream` | GET | 日志实时流 (SSE) |
| `/api/logs/stats` | GET | 日志统计 |
| `/api/providers` | GET/POST | Provider 管理 |
| `/api/providers/{name}` | GET/PUT/DELETE | 单个 Provider 操作 |
| `/api/providers/{name}/test` | POST | 测试 Provider |
| `/api/providers/test-all` | POST | 测试所有 Provider |
| `/api/model-map` | GET/PUT | 模型映射配置 |
| `/api/admin/reset/{name}` | POST | 重置指定 Provider 状态 |
| `/api/admin/reset-all` | POST | 重置所有 Provider 状态 |
| `/api/admin/reload-config` | POST | 重新加载配置 |
| `/api/admin/system-stats` | GET | 系统统计信息 |

## 🧩 核心逻辑说明

### 路由策略

当请求 `gpt-4` 进来时：

1. 程序查找 `model_map`，发现它对应 `["gpt-4", "gpt-4-0613", "gpt-4-turbo"]`。
2. 程序遍历 `providers`，寻找支持上述任意模型的**可用**渠道。
3. 根据 `weight` (权重) 进行加权随机选择最佳渠道。
4. 如果渠道 A 请求失败，程序自动捕获异常，标记 A 为"冷却中"，并立即尝试渠道 B。

### 错误处理机制

| 错误码 | 处理方式 | 冷却时间 |
|:-------|:---------|:---------|
| **401/403** | 鉴权失败/余额不足 | 🚫 **永久停用** (直到重启或手动重置) |
| **429** | 速率限制 | ⏳ **60 秒** |
| **500/502** | 服务端错误 | ⏳ **300 秒** |
| **Timeout** | 连接超时 | ⏳ **120 秒** |

## 📚 依赖库说明

| 库名 | 版本要求 | 作用说明 |
|------|----------|----------|
| **fastapi** | >=0.104.0 | 现代高性能 Web 框架，用于构建 RESTful API 服务，提供自动 API 文档生成、请求验证等功能 |
| **uvicorn** | >=0.24.0 | ASGI 服务器，用于运行 FastAPI 应用，支持异步请求处理和高并发 |
| **httpx** | >=0.25.0 | 异步 HTTP 客户端，用于向上游 Provider 转发请求，支持流式响应和连接池管理 |
| **colorama** | >=0.4.6 | 终端颜色输出库，用于在控制台打印彩色日志，提升可读性 |
| **pydantic** | >=2.5.0 | 数据验证和序列化库，用于定义和验证 OpenAI 兼容的请求/响应数据结构 |
| **pydantic-settings** | >=2.1.0 | Pydantic 配置管理扩展，用于加载和验证 config.json 配置文件 |

## 📅 开发计划 (Roadmap)

- [x] **v0.1 (MVP)**: 基础的 JSON 配置读取，单次请求转发，简单的错误捕获。
- [x] **v0.2 (Stability)**: 引入流式响应 (Streaming) 转发，实现真正的打字机效果。
- [x] **v0.3 (Reliability)**: 完善重试机制 (Retry Loop) 和错误分级冷却系统。
- [x] **v0.4 (Monitor)**: Web 管理面板，可视化管理 Provider、模型映射、API 密钥和日志。
- [ ] **v1.0**: 这是一个完整的稳定版本。

## ⚠️ 免责声明

本项目仅供个人学习和技术研究使用，请勿用于商业用途。请遵守各 AI 模型提供商的服务条款。

---

**Enjoy your hassle-free AI experience! 🎉**
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
2. **增强型模型映射**：
   * 支持多种匹配规则：关键字匹配、正则表达式、前缀匹配、精确匹配
   * 手动包含/排除特定模型，优先级最高
   * 自动同步：定时从各中转站拉取最新模型列表并更新映射
   * 预览功能：在保存前预览规则匹配结果
3. **流式响应支持**：完整支持 SSE 流式传输，实现真正的打字机效果。
4. **双层熔断机制**：
   * **渠道级熔断**：整个 Provider 不可用时熔断
   * **模型级熔断**：单个模型失败时仅熔断该模型，不影响同渠道其他模型
   * **401/403 (Key 错误/余额不足/模型不存在)**：永久拉黑。
   * **429 (超频)**：暂时停用 1 分钟。
   * **5xx (服务器崩)**：暂时停用 5 分钟。
   * **Timeout (超时)**：暂时停用 2 分钟。
5. **模型健康检测**：
   * 单模型检测：返回完整响应体，便于验证模型真伪
   * 批量检测：同渠道内串行，跨渠道异步，高效检测
   * 检测结果持久化存储，支持查询历史记录
6. **无感故障转移 (Failover)**：当首选渠道报错时，自动在后台切换到备用渠道重试，用户端无感知。
7. **加权路由选择**：根据配置的权重值，优先选择高权重的 Provider。
8. **可视化管理面板**：功能完善的 Web 管理界面，让你轻松管理所有配置。
9. **极简配置**：核心配置通过 `config.json` 管理，运行时数据自动持久化，无需数据库。

## 🎨 管理面板

![管理面板预览](https://via.placeholder.com/800x400?text=AI-Router-Lite+Admin+Panel)

功能完善的 Web 管理面板，让你可以：

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
- 一键获取中转站实际支持的模型列表
- 测试 Provider 可用性

### 🔄 增强型模型映射
- 可视化配置模型映射规则（关键字/正则/前缀/精确匹配）
- 手动包含或排除特定模型
- 实时预览规则匹配结果
- 一键同步：从所有中转站拉取最新模型列表并匹配
- 自动同步：可配置定时自动同步间隔

### 🩺 模型健康检测
- 按映射批量检测模型可用性
- 查看检测结果和响应延迟
- 返回完整响应体，便于验证模型真伪（如检测假 GPT-4）
- 检测结果持久化存储

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
├── data/                   # 运行时数据目录（自动生成）
│   ├── .gitkeep
│   ├── api_keys.json       # API 密钥数据
│   ├── model_mappings.json # 增强型模型映射数据
│   ├── model_health.json   # 模型健康检测结果
│   └── logs/               # 日志文件目录
├── src/
│   ├── __init__.py
│   ├── config.py           # 配置管理模块
│   ├── constants.py        # 统一常量定义模块
│   ├── models.py           # OpenAI 兼容数据模型
│   ├── provider.py         # Provider 管理和双层熔断逻辑
│   ├── router.py           # 路由策略模块（支持模型级熔断检查）
│   ├── proxy.py            # 请求代理（流式/非流式）
│   ├── api_keys.py         # API 密钥管理模块
│   ├── logger.py           # 日志记录模块
│   ├── admin.py            # 管理功能模块
│   ├── model_mapping.py    # 增强型模型映射模块
│   └── model_health.py     # 模型健康检测模块
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

### API 密钥管理

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/keys` | GET/POST | API 密钥管理 |
| `/api/keys/{id}` | GET/PUT/DELETE | 单个密钥操作 |

### 日志管理

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/logs` | GET | 获取日志列表 |
| `/api/logs/stream` | GET | 日志实时流 (SSE) |
| `/api/logs/stats` | GET | 日志统计 |
| `/api/logs/hourly` | GET | 小时级统计数据 |

### Provider 管理

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/providers` | GET/POST | Provider 管理 |
| `/api/providers/{name}` | GET/PUT/DELETE | 单个 Provider 操作 |
| `/api/providers/{name}/models` | GET | 获取中转站实际模型列表 |
| `/api/providers/all-models` | GET | 获取所有中转站的模型列表 |

### 增强型模型映射

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/model-mappings` | GET/POST | 模型映射 CRUD |
| `/api/model-mappings/{name}` | GET/PUT/DELETE | 单个映射操作 |
| `/api/model-mappings/sync` | POST | 手动触发同步（可指定映射名） |
| `/api/model-mappings/preview` | POST | 预览规则匹配结果（不保存） |
| `/api/model-mappings/sync-config` | GET/PUT | 自动同步配置 |

### 模型健康检测

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/model-health/results` | GET | 获取所有检测结果 |
| `/api/model-health/results/{name}` | GET | 获取指定映射的检测结果 |
| `/api/model-health/test/{name}` | POST | 批量检测映射下的所有模型 |
| `/api/model-health/test-single` | POST | 检测单个模型 |

### 系统管理

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/admin/reset/{name}` | POST | 重置指定 Provider 状态 |
| `/api/admin/reset-all` | POST | 重置所有 Provider 状态 |
| `/api/admin/reload-config` | POST | 重新加载配置 |
| `/api/admin/system-stats` | GET | 系统统计信息 |

## 🧩 核心逻辑说明

### 增强型模型映射

映射规则支持四种匹配方式（取并集）：

| 规则类型 | 说明 | 示例 |
|:---------|:-----|:-----|
| **keyword** | 关键字包含 | `gpt-4` 匹配所有包含 "gpt-4" 的模型 |
| **prefix** | 前缀匹配 | `claude-3` 匹配所有以 "claude-3" 开头的模型 |
| **regex** | 正则表达式 | `gpt-4(-\d+)?$` 精确匹配 gpt-4 系列 |
| **exact** | 精确匹配 | 仅匹配完全相同的模型名 |

**手动包含/排除**：优先级最高，可覆盖规则匹配结果
- 格式：`model_id` 或 `provider:model_id`
- 排除规则优先于包含规则

### 路由策略（双层熔断检查）

当请求 `gpt-4` 进来时：

1. 程序从增强型模型映射中解析 `gpt-4` 对应的所有实际模型。
2. 程序遍历 `providers`，寻找支持上述模型的**可用**渠道（渠道级检查）。
3. 额外检查该 Provider + Model 组合是否可用（模型级检查）。
4. 根据 `weight` (权重) 进行加权随机选择最佳渠道。
5. 如果请求失败，程序根据错误类型决定熔断级别：
   - **404 模型不存在**：仅熔断该 Provider 的该模型，不影响其他模型。
   - **401/403 鉴权失败**：熔断整个 Provider。
   - 其他错误：根据错误类型设置冷却时间。

### 错误处理机制

| 错误码 | 处理方式 | 冷却时间 | 熔断级别 |
|:-------|:---------|:---------|:---------|
| **401/403** | 鉴权失败/余额不足 | 🚫 **永久停用** | 渠道级 |
| **404** | 模型不存在 | 🚫 **永久停用** | 模型级 |
| **429** | 速率限制 | ⏳ **60 秒** | 渠道级 |
| **500/502** | 服务端错误 | ⏳ **300 秒** | 渠道级 |
| **Timeout** | 连接超时 | ⏳ **120 秒** | 渠道级 |

## 📚 依赖库说明

| 库名 | 版本要求 | 作用说明 |
|------|----------|----------|
| **fastapi** | >=0.104.0 | 现代高性能 Web 框架，用于构建 RESTful API 服务，提供自动 API 文档生成、请求验证等功能 |
| **uvicorn** | >=0.24.0 | ASGI 服务器，用于运行 FastAPI 应用，支持异步请求处理和高并发 |
| **httpx** | >=0.25.0 | 异步 HTTP 客户端，用于向上游 Provider 转发请求，支持流式响应和连接池管理 |
| **colorama** | >=0.4.6 | 终端颜色输出库，用于在控制台打印彩色日志，提升可读性 |
| **pydantic** | >=2.5.0 | 数据验证和序列化库，用于定义和验证 OpenAI 兼容的请求/响应数据结构 |
| **pydantic-settings** | >=2.1.0 | Pydantic 配置管理扩展，用于加载和验证 config.json 配置文件 |
| **filelock** | >=3.13.0 | 文件锁库，用于并发安全的数据持久化操作 |

## 📅 开发计划 (Roadmap)

- [x] **v0.1 (MVP)**: 基础的 JSON 配置读取，单次请求转发，简单的错误捕获。
- [x] **v0.2 (Stability)**: 引入流式响应 (Streaming) 转发，实现真正的打字机效果。
- [x] **v0.3 (Reliability)**: 完善重试机制 (Retry Loop) 和错误分级冷却系统。
- [x] **v0.4 (Monitor)**: Web 管理面板，可视化管理 Provider、模型映射、API 密钥和日志。
- [x] **v0.5 (Intelligence)**: 增强型模型映射（规则匹配、自动同步）、模型健康检测、双层熔断机制。
- [ ] **v1.0**: 完整稳定版本，包含负载均衡优化和更多中转站协议支持。

## ⚠️ 免责声明

本项目仅供个人学习和技术研究使用，请勿用于商业用途。请遵守各 AI 模型提供商的服务条款。

---

**Enjoy your hassle-free AI experience! 🎉**
<div align="center">
  <br />
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://readme-typing-svg.herokuapp.com?font=Fira+Code&size=32&pause=1000&color=00BFFF&center=true&vCenter=true&width=435&lines=AI-Router-Lite">
    <img alt="Typing SVG" src="https://readme-typing-svg.herokuapp.com?font=Fira+Code&size=32&pause=1000&color=00BFFF&center=true&vCenter=true&width=435&lines=AI-Router-Lite" />
  </picture>
  <br />
  <p><strong>一个专为个人开发者设计的轻量级、高性能、一体化 AI 模型聚合路由。</strong></p>
  <p>
    <a href="https://python.org"><img alt="Python" src="https://img.shields.io/badge/Python-3.8+-blue?logo=python&logoColor=white"></a>
    <a href="https://fastapi.tiangolo.com/"><img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-0.104+-05998b?logo=fastapi&logoColor=white"></a>
    <a href="https://github.com/Aflydream/AI-Router-Lite/blob/main/LICENSE"><img alt="License" src="https://img.shields.io/github/license/Aflydream/AI-Router-Lite?color=blue"></a>
    <a href="#"><img alt="Version" src="https://img.shields.io/badge/version-0.7.0-brightgreen"></a>
  </p>
</div>

---

**AI-Router-Lite** 是一个专为个人开发者和小型团队设计的 AI 模型聚合网关。它致力于解决在使用多个（免费或付费）AI 模型中转服务时普遍存在的几大痛点：

- **可用性时好时坏？** → 内置**双层熔断机制**和**自动故障转移**，无感自动绕过失效服务，确保您的请求始终在线。
- **模型列表混乱且随时变动？** → 强大的**增强型模型映射**功能，支持**一键/定时从上游服务拉取最新模型列表**，并通过关键字、正则等规则，将杂乱的模型名统一为您自定义的规范名称（例如，将 `claude-opus-4-5`、`claude-opus-4.5`、`claude-opus-4-5-20251101` 全部统一为 `claude-opus-4-5`）。
- **API 端点不统一？** → 项目会自动将请求**透传**至匹配的协议端点（如 `/v1/chat/completions`, `/v1/messages`），您无需关心底层具体路径。

简而言之，AI-Router-Lite 为您屏蔽了底层渠道的复杂性和不稳定性，提供一个稳定、可靠、且始终保持更新的 AI 模型访问入口。

## 🎨 管理面板预览

一个强大且直观的 Web UI，让你对所有服务状态和配置了如指掌。

<table>
  <tr>
    <td align="center"><b>📊 仪表板</b></td>
    <td align="center"><b>🔑 密钥管理</b></td>
  </tr>
  <tr>
    <td><img src="screenshot/dashboard.jpeg" alt="仪表板" width="400"/></td>
    <td><img src="screenshot/api-keys.jpeg" alt="密钥管理" width="400"/></td>
  </tr>
  <tr>
    <td align="center"><b>🌐 服务站管理</b></td>
    <td align="center"><b>🔄 模型映射</b></td>
  </tr>
  <tr>
    <td><img src="screenshot/providers.jpeg" alt="服务站管理" width="400"/></td>
    <td><img src="screenshot/model-map.jpeg" alt="模型映射" width="400"/></td>
  </tr>
</table>

## ✨ 核心功能

| 功能 | 描述 |
| :--- | :--- |
| 🌐 **多协议路由** | 支持 **OpenAI, Anthropic, Gemini** 等多种 API 协议的**原生透传**，自动将请求路由至正确的上游端点。 |
| 🔄 **增强型模型映射** | 通过关键字、正则、前缀等多种规则灵活地将统一模型名映射到不同渠道的实际模型。 |
| 🔌 **双层熔断机制** | **渠道级 + 模型级**双重保障。对 4xx/5xx/超时等错误进行智能分级冷却，最大化服务可用性。 |
| 🩺 **智能健康检测** | 主动探测、被动记录，自动更新模型健康状态并与熔断系统联动，确保请求总是发往健康的节点。 |
| 🔀 **智能故障转移** | 当首选渠道失败时，无感切换到备用渠道重试，按权重选择最佳路径，保证服务连续性。 |
| 💾 **高性能存储** | 基于 **SQLite (WAL 模式)**，配置与日志分离存储。敏感数据（如 API Key）通过 **Fernet** 加密，安全可靠。 |
| 🖥️ **可视化管理** | 提供功能完善的管理面板，轻松完成密钥、服务站、模型映射、健康检测和日志监控等所有配置。 |

## 🚀 快速开始

### 1. 环境准备
确保你的系统已安装 **Python 3.8+**。

### 2. 安装依赖
```bash
# 创建并激活虚拟环境
python -m venv venv
# Windows
venv\Scripts\activate
# Unix/Mac
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 3. 生成加密密钥
运行脚本生成用于保护数据库敏感信息的密钥。
```bash
python scripts/gen_fernet_key.py
```
> 📋 将输出的密钥复制下来，下一步会用到。

### 4. 创建配置文件
复制配置模板，并填入上一步生成的密钥。
```bash
cp config.example.json config.json
```
```jsonc
// config.json
{
  "server_port": 8000,
  "server_host": "0.0.0.0",
  "max_retries": 3,
  "request_timeout": 120,
  // 将密钥粘贴到此处
  "db_encryption_key": "bXlfc2VjcmV0X2tleV9oZXJlXzMyYnl0ZXM=" 
}
```
> ⚠️ **请务必妥善保管 `db_encryption_key`**，它是解密数据库中 API Key 的唯一凭证。

### 5. 初始化数据库
首次运行前，执行以下命令创建数据库和表结构。
```bash
python scripts/init_db.py
```

### 6. 启动服务
```bash
python main.py
```
服务启动后，即可通过 `http://127.0.0.1:8000/admin` 访问管理面板。

## 🛠️ 使用方法

在支持 OpenAI 协议的客户端（如 NextChat, LobeChat 等）中，将 **API Host** 指向 `http://127.0.0.1:8000`，API Key 填写在管理面板中创建的密钥，即可开始使用。

### API 接口说明

| 端点 | 方法 | 说明 |
| :--- | :--- | :--- |
| `/v1/models` | GET | 获取可用模型列表（返回管理面板中配置的统一模型名） |
| `/v1/chat/completions` | POST | OpenAI Chat Completions 协议 |
| `/v1/responses` | POST | OpenAI Responses 协议 (Beta) |
| `/v1/messages` | POST | Anthropic Messages 协议 |
| `/v1beta/models/{model}:generateContent` | POST | Gemini 协议 |

> 💡 **提示**：对话请求的端点取决于您在管理面板「模型映射」中为统一模型配置的协议类型。系统会根据配置自动将请求透传至对应的上游端点。

## 🔧 技术栈

- **后端**: FastAPI, Uvicorn
- **HTTP 客户端**: HTTPX
- **数据库**: SQLite
- **加密**: Cryptography (Fernet)
- **前端**: Vanilla JS, HTML, CSS

## 🗺️ 路线图

- [x] **v0.1-v0.4**: 实现核心转发、流式响应、熔断及基础 Web UI。
- [x] **v0.5 (Intelligence)**: 增强型模型映射、健康检测、双层熔断。
- [x] **v0.6 (Refactor)**: 引入 Provider ID 体系，支持并发同步。
- [x] **v0.7 (Protocol & Storage)**:
  - 多协议**路由**支持（OpenAI, Anthropic, Gemini 等）
  - 双层协议配置机制
  - **SQLite 持久化存储**（替代 JSON 文件）
  - **Fernet 加密**保护敏感数据
  - 关键字排除规则
  - 被动健康记录
- [ ] **v0.8 (Protocol Conversion)**: 引入协议转换层，实现将多种 API 格式（如 Anthropic, Gemini）统一为 OpenAI Chat Completions 格式输出。
- [ ] **v1.0**: 完整稳定版本，包含负载均衡优化、完善的文档和测试覆盖。

## 📄 许可

本项目采用 [MIT License](https://github.com/Aflydream/AI-Router-Lite/blob/main/LICENSE) 授权。
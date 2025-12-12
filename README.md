# 🚀 AI-Router-Lite (轻量级 AI 聚合路由)

> **告别“API 焦虑症”：自动检测、自动切换、统一接口。** \> 一个专为个人开发者设计的轻量级 AI 模型中转聚合工具 (CLI 版)。

 

## 📖 背景与痛点

你是否也遇到过以下情况？

  * **太乱**：A 站只有 Gemini，B 站有 Claude 但经常崩，C 站号称 GPT-4 却是假的。
  * **太累**：在 Chatbox/NextChat 里配了一堆 Key，用的时候还要手动切来切去。
  * **不可靠**：关键时刻想用，结果报错 `401` 或 `500`，不仅中断思路，还要去排查哪个 Key 过期了。

**AI-Router-Lite** 就是为了解决这些问题而生的。它充当一个“智能管家”，你只需要在软件里配置这**一个接口**，它会在后台自动帮你寻找可用的渠道，并在出错时自动重试。

## ✨ 核心功能

1.  **统一接口标准**：对外完全模拟 OpenAI `/v1/chat/completions` 接口，完美兼容 Chatbox, NextChat, LobeChat 等客户端。
2.  **智能模型映射**：将不同中转站五花八门的模型名（如 `gpt-4-0613`, `gpt-4-turbo-preview`）统一映射为你喜欢的名字（如 `gpt-4`）。
3.  **自动健康检测 & 熔断**：
      * 自动记录请求失败的渠道。
      * **401 (Key 错误)**：永久拉黑该渠道。
      * **429 (超频)**：暂时停用 1 分钟。
      * **5xx (服务器崩)**：暂时停用 5 分钟。
4.  **无感故障转移 (Failover)**：当首选渠道报错时，自动在后台切换到备用渠道重试，用户端无感知。
5.  **极简配置**：所有逻辑通过一个 `config.json` 文件管理，无需数据库。

## 🛠️ 快速开始

### 1\. 环境准备

确保你的电脑安装了 [Python 3.8+](https://www.python.org/)。

### 2\. 安装依赖

克隆项目或下载代码后，在终端运行：

```bash
pip install fastapi uvicorn httpx colorama
```

### 3\. 配置你的中转站 (`config.json`)

在项目根目录创建 `config.json` 文件，填入你的中转站信息：

```json
{
  "server_port": 8000,
  "model_map": {
    "my-gpt-4": ["gpt-4", "gpt-4-0613", "gpt-4-turbo"],
    "my-claude": ["claude-3-opus-20240229", "claude-3-opus"]
  },
  "providers": [
    {
      "name": "Site_A_Cheap",
      "base_url": "https://api.site-a.com/v1",
      "api_key": "sk-xxxxxx",
      "weight": 10,
      "supported_models": ["gpt-3.5-turbo", "gpt-4"]
    },
    {
      "name": "Site_B_Stable",
      "base_url": "https://api.site-b.xyz/v1",
      "api_key": "sk-yyyyyy",
      "weight": 5,
      "supported_models": ["gpt-4", "claude-3-opus"]
    }
  ]
}
```

### 4\. 启动服务

```bash
python main.py
```

看到如下提示即启动成功：

```
INFO:     Started server process [1234]
INFO:     Waiting for application startup.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

### 5\. 连接客户端

打开 Chatbox 或 NextChat：

  * **API Host**: `http://127.0.0.1:8000`
  * **API Key**: `any` (随意填写，因为验证逻辑在 Router 内部处理)
  * **Model**: 输入你在映射里定义的名字，例如 `my-gpt-4`

-----

## 🧩 核心逻辑说明

### 路由策略

当请求 `my-gpt-4` 进来时：

1.  程序查找 `model_map`，发现它对应 `["gpt-4", "gpt-4-0613"]`。
2.  程序遍历 `providers`，寻找支持上述任意模型的**可用**渠道。
3.  根据 `weight` (权重) 或响应速度选择最佳渠道。
4.  如果渠道 A 请求失败，程序自动捕获异常，标记 A 为“冷却中”，并立即尝试渠道 B。

### 错误处理机制

| 错误码 | 处理方式 | 冷却时间 |
| :--- | :--- | :--- |
| **401/403** | 鉴权失败/余额不足 | 🚫 **永久停用** (直到重启或手动重置) |
| **429** | 速率限制 | ⏳ **60 秒** |
| **500/502** | 服务端错误 | ⏳ **300 秒** |
| **Timeout** | 连接超时 | ⏳ **120 秒** |

-----

## 📅 开发计划 (Roadmap)

  - [x] **v0.1 (MVP)**: 基础的 JSON 配置读取，单次请求转发，简单的错误捕获。
  - [ ] **v0.2 (Stability)**: 引入流式响应 (Streaming) 转发，实现真正的打字机效果。
  - [ ] **v0.3 (Reliability)**: 完善重试机制 (Retry Loop) 和错误分级冷却系统。
  - [ ] **v0.4 (Monitor)**: 简单的 CLI 统计面板，显示哪个渠道挂了，今日调用次数。
  - [ ] **v1.0**: 这是一个完整的稳定版本。

## ⚠️ 免责声明

本项目仅供个人学习和技术研究使用，请勿用于商业用途。请遵守各 AI 模型提供商的服务条款。

-----

**Enjoy your hassle-free AI experience\! 🎉**
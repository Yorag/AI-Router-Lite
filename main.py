"""
AI-Router-Lite: 轻量级 AI 聚合路由

主应用入口
"""

import sys
import time
from contextlib import asynccontextmanager

import uvicorn
from colorama import init as colorama_init, Fore, Style
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from src.config import config_manager, get_config
from src.models import (
    ChatCompletionRequest,
    ErrorResponse,
    ErrorDetail,
    ModelListResponse,
    ModelInfo,
)
from src.provider import provider_manager
from src.router import ModelRouter
from src.proxy import RequestProxy, ProxyError


# 初始化 colorama
colorama_init()


# 全局组件
router: ModelRouter = None  # type: ignore
proxy: RequestProxy = None  # type: ignore


def print_banner():
    """打印启动横幅"""
    banner = f"""
{Fore.CYAN}╔══════════════════════════════════════════════════════════╗
║                                                          ║
║   {Fore.WHITE}🚀 AI-Router-Lite v0.3.0{Fore.CYAN}                              ║
║   {Fore.WHITE}轻量级 AI 聚合路由{Fore.CYAN}                                    ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝{Style.RESET_ALL}
"""
    print(banner)


def print_config_summary():
    """打印配置摘要"""
    config = get_config()
    print(f"{Fore.GREEN}[CONFIG]{Style.RESET_ALL} 服务地址: http://{config.server_host}:{config.server_port}")
    print(f"{Fore.GREEN}[CONFIG]{Style.RESET_ALL} 最大重试次数: {config.max_retries}")
    print(f"{Fore.GREEN}[CONFIG]{Style.RESET_ALL} 请求超时: {config.request_timeout}s")
    print(f"{Fore.GREEN}[CONFIG]{Style.RESET_ALL} 模型映射: {len(config.model_map)} 个")
    print(f"{Fore.GREEN}[CONFIG]{Style.RESET_ALL} Provider 数量: {len(config.providers)} 个")
    
    for p in config.providers:
        print(f"  {Fore.CYAN}├─{Style.RESET_ALL} {p.name} (权重: {p.weight}, 模型: {len(p.supported_models)} 个)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global router, proxy
    
    # 启动时
    print_banner()
    
    try:
        config = config_manager.load("config.json")
        print(f"{Fore.GREEN}[STARTUP]{Style.RESET_ALL} 配置文件加载成功")
    except FileNotFoundError:
        print(f"{Fore.RED}[ERROR]{Style.RESET_ALL} 配置文件 config.json 不存在！")
        print(f"{Fore.YELLOW}[HINT]{Style.RESET_ALL} 请复制 config.example.json 并重命名为 config.json")
        sys.exit(1)
    except Exception as e:
        print(f"{Fore.RED}[ERROR]{Style.RESET_ALL} 配置文件加载失败: {e}")
        sys.exit(1)
    
    # 注册 Provider
    provider_manager.register_all(config.providers)
    
    # 初始化路由器和代理
    router = ModelRouter(config, provider_manager)
    proxy = RequestProxy(config, provider_manager, router)
    
    print_config_summary()
    print(f"{Fore.GREEN}[STARTUP]{Style.RESET_ALL} 服务启动完成，等待请求...")
    print("-" * 60)
    
    yield
    
    # 关闭时
    await proxy.close()
    print(f"{Fore.YELLOW}[SHUTDOWN]{Style.RESET_ALL} 服务已关闭")


# 创建 FastAPI 应用
app = FastAPI(
    title="AI-Router-Lite",
    description="轻量级 AI 聚合路由",
    version="0.3.0",
    lifespan=lifespan
)

# 添加 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== API 端点 ====================


@app.get("/")
async def root():
    """根路径"""
    return {
        "service": "AI-Router-Lite",
        "version": "0.3.0",
        "status": "running"
    }


@app.get("/v1/models")
async def list_models():
    """
    列出可用模型 (OpenAI 兼容)
    """
    models = router.get_available_models()
    return ModelListResponse(
        data=[
            ModelInfo(
                id=model,
                created=int(time.time())
            )
            for model in models
        ]
    )


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest, raw_request: Request):
    """
    聊天补全端点 (OpenAI 兼容)
    
    支持流式和非流式响应
    """
    original_model = request.model
    is_stream = request.stream or False
    
    # 记录请求日志
    print(
        f"{Fore.MAGENTA}[REQUEST]{Style.RESET_ALL} "
        f"模型: {original_model}, 流式: {is_stream}, "
        f"消息数: {len(request.messages)}"
    )
    
    try:
        if is_stream:
            # 流式响应
            return StreamingResponse(
                proxy.forward_stream(request, original_model),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no"  # 禁用 nginx 缓冲
                }
            )
        else:
            # 非流式响应
            response = await proxy.forward_request(request, original_model)
            return JSONResponse(content=response)
            
    except ProxyError as e:
        print(f"{Fore.RED}[ERROR]{Style.RESET_ALL} 代理错误: {e.message}")
        status_code = e.status_code or 500
        return JSONResponse(
            status_code=status_code,
            content=ErrorResponse(
                error=ErrorDetail(
                    message=e.message,
                    type="proxy_error",
                    code=str(status_code)
                )
            ).model_dump()
        )
    except Exception as e:
        print(f"{Fore.RED}[ERROR]{Style.RESET_ALL} 未知错误: {str(e)}")
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error=ErrorDetail(
                    message=f"内部错误: {str(e)}",
                    type="internal_error",
                    code="500"
                )
            ).model_dump()
        )


@app.get("/health")
async def health_check():
    """健康检查端点"""
    stats = provider_manager.get_stats()
    return {
        "status": "healthy",
        "available_providers": stats["available_providers"],
        "total_providers": stats["total_providers"]
    }


@app.get("/stats")
async def get_stats():
    """获取详细统计信息"""
    return provider_manager.get_stats()


@app.post("/admin/reset/{provider_name}")
async def reset_provider(provider_name: str):
    """重置指定 Provider 的状态"""
    if provider_manager.reset(provider_name):
        return {"status": "success", "message": f"Provider '{provider_name}' 已重置"}
    else:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_name}' 不存在")


@app.post("/admin/reset-all")
async def reset_all_providers():
    """重置所有 Provider 的状态"""
    provider_manager.reset_all()
    return {"status": "success", "message": "所有 Provider 已重置"}


# ==================== 主入口 ====================


if __name__ == "__main__":
    # 先尝试加载配置以获取端口
    try:
        config = config_manager.load("config.json")
        host = config.server_host
        port = config.server_port
    except:
        host = "0.0.0.0"
        port = 8000
    
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=False,
        log_level="info"
    )
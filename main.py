"""
AI-Router-Lite: 轻量级 AI 聚合路由

主应用入口
"""

import sys
import time
import asyncio
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from colorama import init as colorama_init, Fore, Style
from fastapi import FastAPI, HTTPException, Request, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.config import config_manager, get_config
from src.constants import (
    APP_NAME,
    APP_VERSION,
    APP_DESCRIPTION,
    DEFAULT_SERVER_HOST,
    DEFAULT_SERVER_PORT,
    API_KEY_DEFAULT_RATE_LIMIT,
)
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
from src.api_keys import api_key_manager
from src.logger import log_manager, LogLevel
from src.admin import admin_manager


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
║   {Fore.WHITE}🚀 {APP_NAME} v{APP_VERSION}{Fore.CYAN}                              ║
║   {Fore.WHITE}{APP_DESCRIPTION}{Fore.CYAN}                          ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝{Style.RESET_ALL}
"""
    print(banner)


def print_config_summary():
    """打印配置摘要"""
    config = get_config()
    print(f"{Fore.GREEN}[CONFIG]{Style.RESET_ALL} 服务地址: http://{config.server_host}:{config.server_port}")
    print(f"{Fore.GREEN}[CONFIG]{Style.RESET_ALL} 管理面板: http://{config.server_host}:{config.server_port}/admin")
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
    
    # 将 provider_manager 注入到 admin_manager，用于统一健康状态管理
    admin_manager.set_provider_manager(provider_manager)
    
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
    title=APP_NAME,
    description=APP_DESCRIPTION,
    version=APP_VERSION,
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


# ==================== 请求模型 ====================

class CreateAPIKeyRequest(BaseModel):
    name: str
    rate_limit: int = API_KEY_DEFAULT_RATE_LIMIT

class UpdateAPIKeyRequest(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    rate_limit: Optional[int] = None

class ProviderRequest(BaseModel):
    name: str
    base_url: str
    api_key: str
    weight: int = 1
    supported_models: list[str] = []
    timeout: Optional[float] = None

class UpdateProviderRequest(BaseModel):
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    weight: Optional[int] = None
    supported_models: Optional[list[str]] = None
    timeout: Optional[float] = None

class ModelMappingRequest(BaseModel):
    unified_name: str
    actual_models: list[str]


# ==================== API 端点 ====================


@app.get("/")
async def root():
    """根路径"""
    return {
        "service": APP_NAME,
        "version": APP_VERSION,
        "status": "running",
        "admin_panel": "/admin"
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
    start_time = time.time()
    
    # 获取客户端IP
    client_ip = raw_request.client.host if raw_request.client else None
    
    # 记录请求日志
    print(
        f"{Fore.MAGENTA}[REQUEST]{Style.RESET_ALL} "
        f"模型: {original_model}, 流式: {is_stream}, "
        f"消息数: {len(request.messages)}"
    )
    
    # 记录到日志系统
    log_manager.log(
        level=LogLevel.INFO,
        log_type="request",
        method="POST",
        path="/v1/chat/completions",
        model=original_model,
        client_ip=client_ip,
        message=f"请求模型: {original_model}, 流式: {is_stream}"
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
            
            duration_ms = (time.time() - start_time) * 1000
            
            # 记录响应日志
            log_manager.log(
                level=LogLevel.INFO,
                log_type="response",
                method="POST",
                path="/v1/chat/completions",
                model=original_model,
                status_code=200,
                duration_ms=duration_ms,
                client_ip=client_ip
            )
            
            return JSONResponse(content=response)
            
    except ProxyError as e:
        duration_ms = (time.time() - start_time) * 1000
        print(f"{Fore.RED}[ERROR]{Style.RESET_ALL} 代理错误: {e.message}")
        
        # 记录错误日志
        log_manager.log(
            level=LogLevel.ERROR,
            log_type="error",
            method="POST",
            path="/v1/chat/completions",
            model=original_model,
            provider=e.provider_name,
            status_code=e.status_code or 500,
            duration_ms=duration_ms,
            error=e.message,
            client_ip=client_ip
        )
        
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
        duration_ms = (time.time() - start_time) * 1000
        print(f"{Fore.RED}[ERROR]{Style.RESET_ALL} 未知错误: {str(e)}")
        
        # 记录错误日志
        log_manager.log(
            level=LogLevel.ERROR,
            log_type="error",
            method="POST",
            path="/v1/chat/completions",
            model=original_model,
            status_code=500,
            duration_ms=duration_ms,
            error=str(e),
            client_ip=client_ip
        )
        
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


# ==================== API 密钥管理 ====================


@app.get("/api/keys")
async def list_api_keys():
    """列出所有 API 密钥"""
    return {
        "keys": api_key_manager.list_keys(),
        "stats": api_key_manager.get_stats()
    }


@app.post("/api/keys")
async def create_api_key(request: CreateAPIKeyRequest):
    """创建新的 API 密钥"""
    full_key, key_info = api_key_manager.create_key(
        name=request.name,
        rate_limit=request.rate_limit
    )
    return {
        "key": full_key,  # 仅在创建时返回完整密钥
        "info": key_info,
        "warning": "请保存此密钥，它不会再次显示"
    }


@app.get("/api/keys/{key_id}")
async def get_api_key(key_id: str):
    """获取指定密钥信息"""
    key_info = api_key_manager.get_key(key_id)
    if not key_info:
        raise HTTPException(status_code=404, detail="密钥不存在")
    return key_info


@app.put("/api/keys/{key_id}")
async def update_api_key(key_id: str, request: UpdateAPIKeyRequest):
    """更新密钥信息"""
    success = api_key_manager.update_key(
        key_id=key_id,
        name=request.name,
        enabled=request.enabled,
        rate_limit=request.rate_limit
    )
    if not success:
        raise HTTPException(status_code=404, detail="密钥不存在")
    return {"status": "success", "message": "更新成功"}


@app.delete("/api/keys/{key_id}")
async def delete_api_key(key_id: str):
    """删除密钥"""
    success = api_key_manager.delete_key(key_id)
    if not success:
        raise HTTPException(status_code=404, detail="密钥不存在")
    return {"status": "success", "message": "删除成功"}


# ==================== 日志管理 ====================


@app.get("/api/logs")
async def get_logs(
    limit: int = Query(100, ge=1, le=1000),
    level: Optional[str] = None,
    log_type: Optional[str] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None
):
    """获取日志"""
    return {
        "logs": log_manager.get_recent_logs(
            limit=limit,
            level=level,
            log_type=log_type,
            model=model,
            provider=provider
        )
    }


@app.get("/api/logs/stream")
async def stream_logs():
    """日志流（SSE）"""
    async def generate():
        import json
        async for log_entry in log_manager.subscribe():
            yield f"data: {json.dumps(log_entry.to_dict(), ensure_ascii=False)}\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive"
        }
    )


@app.get("/api/logs/stats")
async def get_log_stats(date: Optional[str] = None):
    """获取日志统计"""
    return log_manager.get_stats(date)


@app.get("/api/logs/hourly")
async def get_hourly_stats(days: int = Query(7, ge=1, le=30)):
    """获取小时级统计数据"""
    return log_manager.get_hourly_stats(days)


# ==================== Provider 管理 ====================


@app.get("/api/providers")
async def list_providers():
    """列出所有 Provider"""
    return {"providers": admin_manager.list_providers()}


@app.get("/api/providers/test-results")
async def get_test_results():
    """获取测试结果"""
    return {"results": admin_manager.get_test_results()}


@app.get("/api/providers/all-models")
async def fetch_all_provider_models():
    """获取所有中转站的模型列表"""
    result = await admin_manager.fetch_all_provider_models()
    return {"provider_models": result}


@app.post("/api/providers/test-all")
async def test_all_providers():
    """测试所有 Provider（手动触发，不跳过任何模型）"""
    results = await admin_manager.test_all_providers(skip_recent=False)
    return {"results": [r.to_dict() for r in results]}


@app.post("/api/providers/test-all-auto")
async def test_all_providers_auto():
    """
    自动健康检测（跳过近期有活动的模型）
    
    用于自动定时健康检测，会跳过近6小时内有调用记录的模型，
    以减少不必要的测试请求和 token 消耗。
    """
    results = await admin_manager.test_all_providers(skip_recent=True)
    return {
        "results": [r.to_dict() for r in results],
        "message": "已跳过近期有活动的模型"
    }


@app.post("/api/providers")
async def add_provider(request: ProviderRequest):
    """添加 Provider"""
    success, message = admin_manager.add_provider(request.model_dump())
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"status": "success", "message": message}


@app.get("/api/providers/{name}")
async def get_provider(name: str):
    """获取指定 Provider"""
    provider = admin_manager.get_provider(name)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider 不存在")
    return provider


@app.put("/api/providers/{name}")
async def update_provider(name: str, request: UpdateProviderRequest):
    """更新 Provider"""
    provider = admin_manager.get_provider(name)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider 不存在")
    
    # 合并更新
    update_data = request.model_dump(exclude_none=True)
    provider.update(update_data)
    
    success, message = admin_manager.update_provider(name, provider)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"status": "success", "message": message}


@app.delete("/api/providers/{name}")
async def delete_provider(name: str):
    """删除 Provider"""
    success, message = admin_manager.delete_provider(name)
    if not success:
        raise HTTPException(status_code=404, detail=message)
    return {"status": "success", "message": message}


@app.post("/api/providers/{name}/test")
async def test_provider(name: str, model: Optional[str] = None):
    """测试 Provider 可用性"""
    results = await admin_manager.test_provider(name, model)
    return {"results": [r.to_dict() for r in results]}


@app.get("/api/providers/{name}/models")
async def fetch_provider_models(name: str):
    """从中转站获取可用模型列表"""
    success, models, error = await admin_manager.fetch_provider_models(name)
    if not success:
        raise HTTPException(status_code=400, detail=error or "获取模型列表失败")
    return {"models": models}


# ==================== 模型映射管理 ====================


@app.get("/api/model-map")
async def get_model_map():
    """获取模型映射"""
    return {"model_map": admin_manager.get_model_map()}


@app.put("/api/model-map")
async def update_model_map(model_map: dict):
    """更新整个模型映射"""
    success, message = admin_manager.update_model_map(model_map)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"status": "success", "message": message}


@app.post("/api/model-map")
async def add_model_mapping(request: ModelMappingRequest):
    """添加模型映射"""
    success, message = admin_manager.add_model_mapping(
        request.unified_name,
        request.actual_models
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"status": "success", "message": message}


@app.put("/api/model-map/{unified_name}")
async def update_single_model_mapping(unified_name: str, actual_models: list[str]):
    """更新单个模型映射"""
    success, message = admin_manager.update_model_mapping(unified_name, actual_models)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"status": "success", "message": message}


@app.delete("/api/model-map/{unified_name}")
async def delete_model_mapping(unified_name: str):
    """删除模型映射"""
    success, message = admin_manager.delete_model_mapping(unified_name)
    if not success:
        raise HTTPException(status_code=404, detail=message)
    return {"status": "success", "message": message}


# ==================== 系统管理 ====================


@app.post("/api/admin/reset/{provider_name}")
async def reset_provider(provider_name: str):
    """重置指定 Provider 的状态"""
    if provider_manager.reset(provider_name):
        return {"status": "success", "message": f"Provider '{provider_name}' 已重置"}
    else:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_name}' 不存在")


@app.post("/api/admin/reset-all")
async def reset_all_providers():
    """重置所有 Provider 的状态"""
    provider_manager.reset_all()
    return {"status": "success", "message": "所有 Provider 已重置"}


@app.post("/api/admin/reload-config")
async def reload_config():
    """重新加载配置"""
    global router, proxy
    
    try:
        config = config_manager.reload("config.json")
        
        # 重新注册 Provider
        provider_manager._providers.clear()
        provider_manager._model_states.clear()
        provider_manager.register_all(config.providers)
        
        # 重新初始化路由器
        router = ModelRouter(config, provider_manager)
        proxy = RequestProxy(config, provider_manager, router)
        
        return {"status": "success", "message": "配置已重新加载"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"重新加载配置失败: {str(e)}")


@app.get("/api/admin/system-stats")
async def get_system_stats():
    """获取系统统计信息"""
    return {
        "providers": provider_manager.get_stats(),
        "api_keys": api_key_manager.get_stats(),
        "logs": log_manager.get_stats(),
        "model_map": len(admin_manager.get_model_map())
    }


# ==================== 静态文件服务 ====================

# 在所有API路由之后挂载静态文件
from pathlib import Path
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/admin", StaticFiles(directory=str(static_dir), html=True), name="admin")


# ==================== 主入口 ====================


if __name__ == "__main__":
    # 先尝试加载配置以获取端口
    try:
        config = config_manager.load("config.json")
        host = config.server_host
        port = config.server_port
    except:
        host = DEFAULT_SERVER_HOST
        port = DEFAULT_SERVER_PORT
    
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=False,
        log_level="info"
    )
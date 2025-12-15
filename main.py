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
from src.proxy import RequestProxy, ProxyError, ProxyResult, StreamContext
from src.api_keys import api_key_manager
from src.logger import log_manager, LogLevel
from src.admin import admin_manager
from src.model_mapping import model_mapping_manager
from src.model_health import model_health_manager
from src.provider_models import provider_models_manager


# 初始化 colorama
colorama_init()


# 全局组件
router: ModelRouter = None  # type: ignore
proxy: RequestProxy = None  # type: ignore
_auto_sync_task: Optional[asyncio.Task] = None  # 自动同步任务


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
    
    # 加载增强型模型映射
    model_mapping_manager.load()
    mappings_count = len(model_mapping_manager.get_all_mappings())
    
    print(f"{Fore.GREEN}[CONFIG]{Style.RESET_ALL} 服务地址: http://{config.server_host}:{config.server_port}")
    print(f"{Fore.GREEN}[CONFIG]{Style.RESET_ALL} 管理面板: http://{config.server_host}:{config.server_port}/admin")
    print(f"{Fore.GREEN}[CONFIG]{Style.RESET_ALL} 最大重试次数: {config.max_retries}")
    print(f"{Fore.GREEN}[CONFIG]{Style.RESET_ALL} 请求超时: {config.request_timeout}s")
    print(f"{Fore.GREEN}[CONFIG]{Style.RESET_ALL} 模型映射: {mappings_count} 个")
    print(f"{Fore.GREEN}[CONFIG]{Style.RESET_ALL} Provider 数量: {len(config.providers)} 个")
    
    # 从 provider_models_manager 获取每个 provider 的模型数量
    provider_models_map = provider_models_manager.get_all_provider_models_map()
    for p in config.providers:
        model_count = len(provider_models_map.get(p.name, []))
        print(f"  {Fore.CYAN}├─{Style.RESET_ALL} {p.name} (权重: {p.weight}, 模型: {model_count} 个)")


async def auto_sync_model_mappings_task():
    """
    后台自动同步模型映射任务
    
    根据配置的间隔时间定期执行同步
    """
    while True:
        try:
            # 加载最新配置
            model_mapping_manager.load()
            sync_config = model_mapping_manager.get_sync_config()
            
            if not sync_config.auto_sync_enabled:
                # 如果未启用自动同步，每分钟检查一次配置
                await asyncio.sleep(60)
                continue
            
            # 等待同步间隔
            interval_seconds = sync_config.auto_sync_interval_hours * 3600
            print(f"{Fore.CYAN}[AUTO-SYNC]{Style.RESET_ALL} 模型映射自动同步已启用，间隔: {sync_config.auto_sync_interval_hours} 小时")
            
            await asyncio.sleep(interval_seconds)
            
            # 执行同步
            print(f"{Fore.CYAN}[AUTO-SYNC]{Style.RESET_ALL} 开始自动同步模型映射...")
            
            # 获取所有Provider的模型列表
            all_provider_models = await admin_manager.fetch_all_provider_models()
            
            # 转换格式
            provider_models_flat: dict[str, list[str]] = {}
            for provider, models in all_provider_models.items():
                provider_models_flat[provider] = [
                    m["id"] if isinstance(m, dict) else m for m in models
                ]
            
            # 执行同步
            results = model_mapping_manager.sync_all_mappings(provider_models_flat)
            
            total_matched = sum(r.get("matched_count", 0) for r in results)
            print(f"{Fore.GREEN}[AUTO-SYNC]{Style.RESET_ALL} 同步完成: {len(results)} 个映射, {total_matched} 个模型")
            
        except asyncio.CancelledError:
            print(f"{Fore.YELLOW}[AUTO-SYNC]{Style.RESET_ALL} 自动同步任务已取消")
            break
        except Exception as e:
            print(f"{Fore.RED}[AUTO-SYNC]{Style.RESET_ALL} 同步出错: {e}")
            # 出错后等待1分钟再重试
            await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global router, proxy, _auto_sync_task
    
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
    
    # 初始化模型健康检测管理器
    model_health_manager.set_admin_manager(admin_manager)
    
    # 加载 provider_models 数据
    provider_models_manager.load()
    
    # 初始化路由器和代理
    router = ModelRouter(config, provider_manager)
    proxy = RequestProxy(config, provider_manager, router)
    
    # 启动模型映射自动同步任务
    _auto_sync_task = asyncio.create_task(auto_sync_model_mappings_task())
    
    print_config_summary()
    print(f"{Fore.GREEN}[STARTUP]{Style.RESET_ALL} 服务启动完成，等待请求...")
    print("-" * 60)
    
    # 记录系统启动日志
    model_mapping_manager.load()
    mappings_count = len(model_mapping_manager.get_all_mappings())
    log_manager.log(
        level=LogLevel.INFO,
        log_type="system",
        method="STARTUP",
        path="/",
        message=f"服务启动完成 - {len(config.providers)} 个 Provider, {mappings_count} 个模型映射"
    )
    
    yield
    
    # 关闭时
    # 取消自动同步任务
    if _auto_sync_task:
        _auto_sync_task.cancel()
        try:
            await _auto_sync_task
        except asyncio.CancelledError:
            pass
    
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

class UpdateAPIKeyRequest(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None

class ProviderRequest(BaseModel):
    """添加 Provider 请求（模型列表通过 /api/providers/{name}/models 同步）"""
    name: str
    base_url: str
    api_key: str
    weight: int = 1
    timeout: Optional[float] = None

class UpdateProviderRequest(BaseModel):
    """更新 Provider 请求（模型列表通过 /api/providers/{name}/models 同步）"""
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    weight: Optional[int] = None
    timeout: Optional[float] = None
    enabled: Optional[bool] = None

class CreateModelMappingRequest(BaseModel):
    """创建模型映射请求"""
    unified_name: str
    description: str = ""
    rules: list[dict] = []
    manual_includes: list[str] = []
    manual_excludes: list[str] = []
    excluded_providers: list[str] = []


class UpdateModelMappingRequest(BaseModel):
    """更新模型映射请求"""
    description: Optional[str] = None
    rules: Optional[list[dict]] = None
    manual_includes: Optional[list[str]] = None
    manual_excludes: Optional[list[str]] = None
    excluded_providers: Optional[list[str]] = None


class PreviewResolveRequest(BaseModel):
    """预览匹配结果请求"""
    rules: list[dict]
    manual_includes: list[str] = []
    manual_excludes: list[str] = []
    excluded_providers: list[str] = []


class SyncConfigRequest(BaseModel):
    """同步配置请求"""
    auto_sync_enabled: Optional[bool] = None
    auto_sync_interval_hours: Optional[int] = None


class TestSingleModelRequest(BaseModel):
    """测试单个模型请求"""
    provider: str
    model: str


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


# ==================== API 密钥认证 ====================

def get_api_key_from_header(raw_request: Request) -> Optional[str]:
    """从请求头提取 API 密钥"""
    auth_header = raw_request.headers.get("Authorization")
    if not auth_header:
        return None
    
    # 支持 Bearer token 格式
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    
    return auth_header


async def verify_api_key(raw_request: Request) -> None:
    """
    验证 API 密钥的依赖函数
    
    Raises:
        HTTPException: 密钥无效或缺失时抛出 401 错误
    """
    api_key = get_api_key_from_header(raw_request)
    
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="缺少 API 密钥，请在 Authorization 头中提供 Bearer token"
        )
    
    # 验证密钥
    key_obj = api_key_manager.validate_key(api_key)
    
    if not key_obj:
        raise HTTPException(
            status_code=401,
            detail="无效的 API 密钥或密钥已被禁用"
        )
    
    # validate_key 已经更新了 last_used 和 total_requests


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
async def chat_completions(
    request: ChatCompletionRequest,
    raw_request: Request,
    _: None = Depends(verify_api_key)
):
    """
    聊天补全端点 (OpenAI 兼容)
    
    需要有效的 API 密钥认证。
    支持流式和非流式响应。
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
            # 流式响应 - 使用 StreamContext 收集元数据
            stream_context = StreamContext(provider_name="", actual_model="")
            
            async def stream_with_logging():
                """包装流式响应，在完成后记录日志"""
                try:
                    async for chunk in proxy.forward_stream(request, original_model, stream_context):
                        yield chunk
                    
                    # 流式请求完成后记录日志
                    duration_ms = (time.time() - start_time) * 1000
                    print(
                        f"{Fore.GREEN}[RESPONSE]{Style.RESET_ALL} "
                        f"模型: {original_model}, 实际: {stream_context.provider_name}:{stream_context.actual_model}, "
                        f"耗时: {duration_ms:.0f}ms, "
                        f"Tokens: {stream_context.total_tokens or 'N/A'}"
                    )
                    log_manager.log(
                        level=LogLevel.INFO,
                        log_type="response",
                        method="POST",
                        path="/v1/chat/completions",
                        model=original_model,
                        provider=stream_context.provider_name,
                        actual_model=stream_context.actual_model,
                        status_code=200,
                        duration_ms=duration_ms,
                        client_ip=client_ip,
                        request_tokens=stream_context.request_tokens,
                        response_tokens=stream_context.response_tokens,
                        total_tokens=stream_context.total_tokens,
                        message=f"实际模型: {stream_context.provider_name}:{stream_context.actual_model}"
                    )
                except ProxyError as e:
                    # 流式请求中的错误
                    duration_ms = (time.time() - start_time) * 1000
                    log_manager.log(
                        level=LogLevel.ERROR,
                        log_type="error",
                        method="POST",
                        path="/v1/chat/completions",
                        model=original_model,
                        provider=e.provider_name,
                        actual_model=e.actual_model,
                        status_code=e.status_code or 500,
                        duration_ms=duration_ms,
                        error=e.message,
                        client_ip=client_ip
                    )
                    raise
            
            return StreamingResponse(
                stream_with_logging(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no"  # 禁用 nginx 缓冲
                }
            )
        else:
            # 非流式响应
            result: ProxyResult = await proxy.forward_request(request, original_model)
            
            duration_ms = (time.time() - start_time) * 1000
            
            # 打印详细日志
            print(
                f"{Fore.GREEN}[RESPONSE]{Style.RESET_ALL} "
                f"模型: {original_model}, 实际: {result.provider_name}:{result.actual_model}, "
                f"耗时: {duration_ms:.0f}ms, "
                f"Tokens: {result.total_tokens or 'N/A'} "
                f"(请求: {result.request_tokens or 'N/A'}, 响应: {result.response_tokens or 'N/A'})"
            )
            
            # 记录响应日志
            log_manager.log(
                level=LogLevel.INFO,
                log_type="response",
                method="POST",
                path="/v1/chat/completions",
                model=original_model,
                provider=result.provider_name,
                actual_model=result.actual_model,
                status_code=200,
                duration_ms=duration_ms,
                client_ip=client_ip,
                request_tokens=result.request_tokens,
                response_tokens=result.response_tokens,
                total_tokens=result.total_tokens,
                message=f"实际模型: {result.provider_name}:{result.actual_model}"
            )
            
            return JSONResponse(content=result.response)
            
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
            actual_model=e.actual_model,
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
        name=request.name
    )
    return {
        "key": full_key,
        "info": key_info
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
        enabled=request.enabled
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


@app.get("/api/providers/all-models")
async def fetch_all_provider_models():
    """
    获取所有中转站的模型列表（从 provider_models.json 读取）
    
    返回格式包含 owned_by 和 supported_endpoint_types 元信息
    """
    provider_models_map = provider_models_manager.get_all_provider_models_map()
    
    # 转换为带元信息的格式
    result = {}
    for provider_name, model_ids in provider_models_map.items():
        provider_data = provider_models_manager.get_provider(provider_name)
        if provider_data:
            result[provider_name] = [
                {
                    "id": mid,
                    "owned_by": provider_data.models.get(mid).owned_by if mid in provider_data.models else "",
                    "supported_endpoint_types": provider_data.models.get(mid).supported_endpoint_types if mid in provider_data.models else []
                }
                for mid in model_ids
            ]
        else:
            result[provider_name] = [{"id": mid, "owned_by": "", "supported_endpoint_types": []} for mid in model_ids]
    
    return {"provider_models": result}


@app.post("/api/providers")
async def add_provider(request: ProviderRequest):
    """添加 Provider"""
    success, message = admin_manager.add_provider(request.model_dump())
    if not success:
        raise HTTPException(status_code=400, detail=message)
    log_manager.log(
        level=LogLevel.INFO, log_type="admin", method="POST",
        path="/api/providers", message=f"添加 Provider: {request.name}"
    )
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
    log_manager.log(
        level=LogLevel.INFO, log_type="admin", method="PUT",
        path=f"/api/providers/{name}", message=f"更新 Provider: {name}"
    )
    return {"status": "success", "message": message}


@app.delete("/api/providers/{name}")
async def delete_provider(name: str):
    """删除 Provider"""
    success, message = admin_manager.delete_provider(name)
    if not success:
        raise HTTPException(status_code=404, detail=message)
    log_manager.log(
        level=LogLevel.WARNING, log_type="admin", method="DELETE",
        path=f"/api/providers/{name}", message=f"删除 Provider: {name}"
    )
    return {"status": "success", "message": message}


@app.get("/api/providers/{name}/models")
async def fetch_provider_models(name: str):
    """从中转站获取可用模型列表（并保存到 provider_models.json）"""
    success, models, error, sync_stats = await admin_manager.fetch_provider_models(name)
    if not success:
        raise HTTPException(status_code=400, detail=error or "获取模型列表失败")
    return {
        "models": models,
        "sync_stats": sync_stats
    }


# ==================== 模型映射管理（增强型） ====================


@app.get("/api/model-mappings")
async def get_model_mappings():
    """获取所有模型映射配置"""
    model_mapping_manager.load()
    mappings = model_mapping_manager.get_all_mappings()
    sync_config = model_mapping_manager.get_sync_config()
    
    return {
        "mappings": {name: m.to_dict() for name, m in mappings.items()},
        "sync_config": sync_config.to_dict()
    }


@app.post("/api/model-mappings")
async def create_model_mapping(request: CreateModelMappingRequest):
    """创建新映射"""
    success, message = model_mapping_manager.create_mapping(
        unified_name=request.unified_name,
        description=request.description,
        rules=request.rules,
        manual_includes=request.manual_includes,
        manual_excludes=request.manual_excludes,
        excluded_providers=request.excluded_providers
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)
    log_manager.log(
        level=LogLevel.INFO, log_type="admin", method="POST",
        path="/api/model-mappings", message=f"创建模型映射: {request.unified_name}"
    )
    return {"status": "success", "message": message}


@app.get("/api/model-mappings/{unified_name}")
async def get_model_mapping(unified_name: str):
    """获取指定映射"""
    mapping = model_mapping_manager.get_mapping(unified_name)
    if not mapping:
        raise HTTPException(status_code=404, detail=f"映射 '{unified_name}' 不存在")
    return {"mapping": mapping.to_dict()}


@app.put("/api/model-mappings/{unified_name}")
async def update_model_mapping(unified_name: str, request: UpdateModelMappingRequest):
    """更新映射"""
    success, message = model_mapping_manager.update_mapping(
        unified_name=unified_name,
        description=request.description,
        rules=request.rules,
        manual_includes=request.manual_includes,
        manual_excludes=request.manual_excludes,
        excluded_providers=request.excluded_providers
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)
    log_manager.log(
        level=LogLevel.INFO, log_type="admin", method="PUT",
        path=f"/api/model-mappings/{unified_name}", message=f"更新模型映射: {unified_name}"
    )
    return {"status": "success", "message": message}


@app.delete("/api/model-mappings/{unified_name}")
async def delete_model_mapping(unified_name: str):
    """删除映射"""
    success, message = model_mapping_manager.delete_mapping(unified_name)
    if not success:
        raise HTTPException(status_code=404, detail=message)
    log_manager.log(
        level=LogLevel.WARNING, log_type="admin", method="DELETE",
        path=f"/api/model-mappings/{unified_name}", message=f"删除模型映射: {unified_name}"
    )
    return {"status": "success", "message": message}


@app.post("/api/model-mappings/sync")
async def sync_model_mappings(unified_name: Optional[str] = None):
    """
    手动触发同步
    
    Args:
        unified_name: 指定要同步的映射名称，不传则同步全部
    
    注意：使用 provider_models.json 中的模型列表，如果该文件为空，
    请先在服务站管理中同步模型列表。
    """
    # 从 provider_models_manager 获取模型列表
    provider_models_flat = provider_models_manager.get_all_provider_models_map()
    
    if unified_name:
        # 同步单个映射
        success, message, resolved = model_mapping_manager.sync_mapping(
            unified_name, provider_models_flat
        )
        if not success:
            raise HTTPException(status_code=400, detail=message)
        
        total_models = sum(len(models) for models in resolved.values())
        return {
            "status": "success",
            "message": message,
            "synced_count": 1,
            "results": [{
                "unified_name": unified_name,
                "success": True,
                "matched_count": total_models,
                "providers": list(resolved.keys())
            }]
        }
    else:
        # 同步全部映射
        results = model_mapping_manager.sync_all_mappings(provider_models_flat)
        return {
            "status": "success",
            "synced_count": len(results),
            "results": results
        }


@app.post("/api/model-mappings/preview")
async def preview_model_mapping(request: PreviewResolveRequest):
    """
    预览匹配结果（不保存）
    
    用于在创建/编辑映射时实时预览规则匹配的效果
    
    注意：使用 provider_models.json 中的模型列表，而非实时网络请求，
    以提供快速的预览响应。如需获取最新模型列表，请先在服务站管理中同步模型。
    """
    # 从 provider_models_manager 获取模型列表
    provider_models_flat = provider_models_manager.get_all_provider_models_map()
    
    # 预览解析结果
    resolved = model_mapping_manager.preview_resolve(
        rules=request.rules,
        manual_includes=request.manual_includes,
        manual_excludes=request.manual_excludes,
        all_provider_models=provider_models_flat,
        excluded_providers=request.excluded_providers
    )
    
    total_models = sum(len(models) for models in resolved.values())
    return {
        "matched_models": resolved,
        "total_count": total_models,
        "provider_count": len(resolved)
    }


@app.get("/api/model-mappings/sync-config")
async def get_sync_config():
    """获取同步配置"""
    model_mapping_manager.load()
    sync_config = model_mapping_manager.get_sync_config()
    return {"sync_config": sync_config.to_dict()}


@app.put("/api/model-mappings/sync-config")
async def update_sync_config(request: SyncConfigRequest):
    """更新同步配置"""
    success, message = model_mapping_manager.update_sync_config(
        auto_sync_enabled=request.auto_sync_enabled,
        auto_sync_interval_hours=request.auto_sync_interval_hours
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"status": "success", "message": message}


# ==================== 模型健康检测 ====================


@app.get("/api/model-health/results")
async def get_all_health_results():
    """获取所有模型健康检测结果"""
    model_health_manager.load()
    results = model_health_manager.get_all_results()
    return {
        "results": {key: r.to_dict() for key, r in results.items()}
    }


@app.get("/api/model-health/results/{unified_name}")
async def get_mapping_health_results(unified_name: str):
    """获取指定映射的健康检测结果"""
    # 获取映射的 resolved_models
    mapping = model_mapping_manager.get_mapping(unified_name)
    if not mapping:
        raise HTTPException(status_code=404, detail=f"映射 '{unified_name}' 不存在")
    
    model_health_manager.load()
    results = model_health_manager.get_results_for_models(mapping.resolved_models)
    
    return {
        "unified_name": unified_name,
        "results": {key: r.to_dict() for key, r in results.items()}
    }


@app.post("/api/model-health/test/{unified_name}")
async def test_mapping_health(unified_name: str):
    """
    检测指定映射下的所有模型健康状态
    
    策略：同渠道内串行检测，不同渠道间异步检测
    """
    # 获取映射的 resolved_models
    mapping = model_mapping_manager.get_mapping(unified_name)
    if not mapping:
        raise HTTPException(status_code=404, detail=f"映射 '{unified_name}' 不存在")
    
    if not mapping.resolved_models:
        return {
            "status": "warning",
            "message": "该映射没有解析到任何模型，请先同步映射",
            "tested_count": 0,
            "success_count": 0,
            "results": []
        }
    
    # 执行批量检测
    results = await model_health_manager.test_mapping_models(mapping.resolved_models)
    
    success_count = sum(1 for r in results if r.success)
    
    return {
        "status": "success",
        "unified_name": unified_name,
        "tested_count": len(results),
        "success_count": success_count,
        "results": [r.to_dict() for r in results]
    }


@app.post("/api/model-health/test-single")
async def test_single_model_health(request: TestSingleModelRequest):
    """检测单个模型的健康状态"""
    result = await model_health_manager.test_single_model(
        provider_name=request.provider,
        model=request.model
    )
    return result.to_dict()


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
        
        log_manager.log(
            level=LogLevel.INFO, log_type="system", method="POST",
            path="/api/admin/reload-config", message="配置已重新加载"
        )
        return {"status": "success", "message": "配置已重新加载"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"重新加载配置失败: {str(e)}")


@app.get("/api/admin/system-stats")
async def get_system_stats():
    """获取系统统计信息"""
    model_mapping_manager.load()
    return {
        "providers": provider_manager.get_stats(),
        "api_keys": api_key_manager.get_stats(),
        "logs": log_manager.get_stats(),
        "model_mappings": len(model_mapping_manager.get_all_mappings())
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
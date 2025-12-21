"""
AI-Router-Lite: 轻量级 AI 聚合路由

主应用入口
"""

import sys
import time
import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional, Dict

import uvicorn
import httpx
from fastapi import FastAPI, HTTPException, Request, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from src.config import config_manager, get_config
from src.constants import (
    APP_NAME,
    APP_VERSION,
    APP_DESCRIPTION,
    DEFAULT_SERVER_HOST,
    DEFAULT_SERVER_PORT,
    AUTO_SYNC_CHECK_INTERVAL_SECONDS,
    HEALTH_TEST_FAILURE_COOLDOWN_SECONDS
)
from src.provider import ModelStatus, CooldownReason
from src.schemas import (
    ErrorResponse,
    ErrorDetail,
    ModelListResponse,
    ModelInfo,
    CreateAPIKeyRequest,
    UpdateAPIKeyRequest,
    ProviderRequest,
    UpdateProviderRequest,
    CreateModelMappingRequest,
    UpdateModelMappingRequest,
    PreviewResolveRequest,
    SyncConfigRequest,
    ReorderModelMappingsRequest,
    TestSingleModelRequest,
    UpdateModelProtocolRequest
)
from src.provider import provider_manager
from src.router import ModelRouter
from src.proxy import RequestProxy, ProxyError, RoutingError, ProxyResult, StreamContext
from src.api_keys import api_key_manager, APIKey
from src.logger import log_manager, LogLevel, get_today_str
from src.admin import admin_manager
from src.model_mapping import model_mapping_manager
from src.model_health import model_health_manager
from src.provider_models import provider_models_manager
from src.protocols import get_protocol, is_supported_protocol


router: ModelRouter = None  # type: ignore
proxy: RequestProxy = None  # type: ignore
_auto_sync_task: Optional[asyncio.Task] = None


def print_banner():
    banner = f"""
╔══════════════════════════════════════════════════════════╗
║                                                          ║
║    {APP_NAME} v{APP_VERSION}                              ║
║   {APP_DESCRIPTION}                          ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
"""
    print(banner)


def print_config_summary():
    config = get_config()
    providers = admin_manager.list_providers()

    model_mapping_manager.load()
    mappings_count = len(model_mapping_manager.get_all_mappings())

    print(f"[CONFIG] 服务地址: http://{config.server_host}:{config.server_port}")
    print(f"[CONFIG] 管理面板: http://{config.server_host}:{config.server_port}/admin")
    print(f"[CONFIG] 最大重试次数: {config.max_retries}")
    print(f"[CONFIG] 请求超时: {config.request_timeout}s")
    print(f"[CONFIG] 模型映射: {mappings_count} 个")
    print(f"[CONFIG] Provider 数量: {len(providers)} 个")

    provider_models_map = provider_models_manager.get_all_provider_models_map()
    for p in providers:
        model_count = len(provider_models_map.get(p["id"], []))
        print(f"  ├─ {p['name']} (ID: {p['id'][:8]}..., 权重: {p['weight']}, 模型: {model_count} 个)")


async def fetch_remote_models(base_url: str, api_key: str, provider_id: str, provider_name: str) -> Optional[list[dict]]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {api_key}"}
            )
            if response.status_code == 200:
                data = response.json()
                if "data" in data and isinstance(data["data"], list):
                    return [
                        {
                            "id": m.get("id"),
                            "owned_by": m.get("owned_by", ""),
                            "supported_endpoint_types": m.get("supported_endpoint_types", [])
                        }
                        for m in data["data"] if m.get("id")
                    ]
                
                log_manager.log(
                    level=LogLevel.WARNING,
                    log_type="sync",
                    method="SYNC",
                    path="/providers/sync",
                    provider=provider_name,
                    provider_id=provider_id,
                    message="同步失败: 响应格式不正确",
                    error=response.text[:500]
                )
                return None
            else:
                log_manager.log(
                    level=LogLevel.WARNING,
                    log_type="sync",
                    method="SYNC",
                    path="/providers/sync",
                    provider=provider_name,
                    provider_id=provider_id,
                    message=f"同步失败: HTTP {response.status_code}",
                    error=response.text[:500]
                )
                return None
    except Exception as e:
        log_manager.log(
            level=LogLevel.WARNING,
            log_type="sync",
            method="SYNC",
            path="/providers/sync",
            provider=provider_name,
            provider_id=provider_id,
            message="同步失败: 网络错误",
            error=str(e)
        )
        return None

async def sync_all_provider_models_logic() -> dict:
    """Shared logic for syncing all providers (used by task and API)"""
    providers = admin_manager.list_providers()
    
    from src.sqlite_repos import ProviderRepo
    provider_repo = ProviderRepo()

    async def process_provider(p):
        pid = p["id"]
        pname = p["name"]
        api_key = p.get("api_key")
        base_url = p.get("base_url")

        if not p.get("allow_model_update", True):
            return False
        
        if not api_key or not base_url:
            return False

        remote_models = await fetch_remote_models(base_url, api_key, pid, pname)
        
        if remote_models is not None:
            provider_models_manager.update_models_from_remote(pid, remote_models, pname)
            provider_repo.update_models_updated_at(pid)
            return True
        return False

    results = await asyncio.gather(*[process_provider(p) for p in providers])
    
    synced_count = sum(1 for res in results if res)

    provider_models_flat = provider_models_manager.get_all_provider_models_map()
    total_models = sum(len(models) for models in provider_models_flat.values())

    # Sync mappings
    provider_id_name_map = admin_manager.get_provider_id_name_map()
    provider_protocols = admin_manager.get_provider_protocols()

    mapping_results = model_mapping_manager.sync_all_mappings(
        provider_models_flat, provider_id_name_map, provider_protocols
    )
    
    return {
        "synced_count": synced_count,
        "total_models": total_models,
        "mapping_results": mapping_results
    }

async def auto_sync_model_mappings_task():
    """
    轮询检查机制：定期检查是否需要同步
    基于目标时间（上次同步时间 + 配置间隔）来判断
    """
    while True:
        try:
            await asyncio.sleep(AUTO_SYNC_CHECK_INTERVAL_SECONDS)
            
            model_mapping_manager.load()
            sync_config = model_mapping_manager.get_sync_config()

            if not sync_config.auto_sync_enabled:
                continue

            # 计算目标同步时间
            interval_seconds = sync_config.auto_sync_interval_hours * 3600
            
            # 如果从未同步过，立即同步
            if not sync_config.last_full_sync:
                print(f"[AUTO-SYNC] 首次同步，立即执行...")
                result = await sync_all_provider_models_logic()
                print(f"[AUTO-SYNC] 完成: 同步了 {result['synced_count']} 个 Provider")
                continue
            
            # 解析上次同步时间
            try:
                last_sync_dt = datetime.fromisoformat(sync_config.last_full_sync.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                # 无法解析时间，执行同步
                print(f"[AUTO-SYNC] 无法解析上次同步时间，立即执行同步...")
                result = await sync_all_provider_models_logic()
                print(f"[AUTO-SYNC] 完成: 同步了 {result['synced_count']} 个 Provider")
                continue
            
            # 计算目标时间和当前时间
            target_sync_time = last_sync_dt.timestamp() + interval_seconds
            current_time = datetime.now(timezone.utc).timestamp()
            
            # 判断是否需要同步
            if current_time >= target_sync_time:
                print(f"[AUTO-SYNC] 已到达同步时间，开始自动同步...")
                result = await sync_all_provider_models_logic()
                print(f"[AUTO-SYNC] 完成: 同步了 {result['synced_count']} 个 Provider")

        except asyncio.CancelledError:
            print(f"[AUTO-SYNC] 任务已取消")
            break
        except Exception as e:
            print(f"[AUTO-SYNC] 出错: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global router, proxy, _auto_sync_task

    print_banner()

    try:
        config = config_manager.load()
        print(f"[STARTUP] SQLite 配置加载成功")
    except Exception as e:
        print(f"[ERROR] SQLite 配置加载失败: {e}")
        sys.exit(1)

    # 从数据库加载 providers 并注册
    from src.sqlite_repos import ProviderRepo
    from src.config import ProviderConfig
    provider_repo = ProviderRepo()
    providers_data = provider_repo.list()
    providers = [ProviderConfig(**p) for p in providers_data]
    provider_manager.register_all(providers)

    model_health_manager.set_admin_manager(admin_manager)

    provider_models_manager.load()

    router = ModelRouter(config, provider_manager)
    proxy = RequestProxy(config, provider_manager, router)

    _auto_sync_task = asyncio.create_task(auto_sync_model_mappings_task())

    print_config_summary()
    print(f"[STARTUP] 服务启动完成，等待请求...")
    print("-" * 60)

    model_mapping_manager.load()
    mappings_count = len(model_mapping_manager.get_all_mappings())
    log_manager.log(
        level=LogLevel.INFO,
        log_type="system",
        method="STARTUP",
        path="/",
        message=f"服务启动完成 - {len(providers)} 个 Provider, {mappings_count} 个模型映射",
    )

    yield

    if _auto_sync_task:
        _auto_sync_task.cancel()
        try:
            await _auto_sync_task
        except asyncio.CancelledError:
            pass

    await proxy.close()
    print(f"[SHUTDOWN] 服务已关闭")


app = FastAPI(
    title=APP_NAME,
    description=APP_DESCRIPTION,
    version=APP_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {
        "service": APP_NAME,
        "version": APP_VERSION,
        "status": "running",
        "admin_panel": "/admin",
    }


def get_api_key_from_header(raw_request: Request) -> Optional[str]:
    auth_header = raw_request.headers.get("Authorization")
    if auth_header:
        if auth_header.startswith("Bearer "):
            return auth_header[7:]
        return auth_header

    api_key = raw_request.headers.get("x-api-key")
    if api_key:
        return api_key

    api_key = raw_request.query_params.get("key")
    if api_key:
        return api_key

    return None


async def verify_api_key(raw_request: Request) -> APIKey:
    api_key = get_api_key_from_header(raw_request)

    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="缺少 API 密钥，请在 Authorization 头(Bearer)、x-api-key 头或 key 查询参数中提供",
        )

    key_obj = api_key_manager.validate_key(api_key)

    if not key_obj:
        raise HTTPException(status_code=401, detail="无效的 API 密钥或密钥已被禁用")

    return key_obj


@app.get("/v1/models")
async def list_models():
    models = router.get_available_models()
    return ModelListResponse(
        data=[ModelInfo(id=model, created=int(time.time())) for model in models]
    )


async def process_request(
    request: Request,
    protocol_type: str,
    api_key: APIKey,
    path_params: Optional[Dict[str, str]] = None,
):
    protocol_handler = get_protocol(protocol_type)
    if not protocol_handler:
        raise HTTPException(status_code=500, detail=f"不支持的协议类型: {protocol_type}")

    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="无效的 JSON 请求体")

    if path_params:
        body.update(path_params)

    original_model, is_stream = protocol_handler.parse_request(body)
    if not original_model:
        raise HTTPException(status_code=400, detail="无法从请求中提取模型名称")

    start_time = time.time()
    client_ip = request.client.host if request.client else None
    api_key_id = api_key.key_id
    api_key_name = api_key.name

    try:
        if is_stream:
            stream_context = StreamContext(provider_name="", actual_model="")

            async def stream_with_logging():
                try:
                    async for chunk in proxy.forward_stream(
                        body,
                        protocol_handler,
                        original_model,
                        stream_context,
                        api_key_name=api_key_name,
                        api_key_id=api_key_id,
                    ):
                        yield chunk

                    duration_ms = (time.time() - start_time) * 1000
                    log_manager.log(
                        level=LogLevel.INFO,
                        log_type="proxy",
                        method=request.method,
                        path=request.url.path,
                        model=original_model,
                        provider=stream_context.provider_name,
                        provider_id=stream_context.provider_id,
                        actual_model=stream_context.actual_model,
                        status_code=200,
                        duration_ms=duration_ms,
                        client_ip=client_ip,
                        api_key_id=api_key_id,
                        api_key_name=api_key_name,
                        protocol=protocol_type,
                        request_tokens=stream_context.request_tokens,
                        response_tokens=stream_context.response_tokens,
                        total_tokens=stream_context.total_tokens,
                        message="",
                    )
                except ProxyError as e:
                    error_response = {
                        "error": {
                            "message": e.message,
                            "type": "proxy_error",
                            "code": str(e.status_code or 500),
                            "provider": e.provider_name,
                            "model": e.actual_model,
                        }
                    }
                    yield f"data: {json.dumps(error_response)}\n\n"
                    yield "data: [DONE]\n\n"
                except Exception as e:
                    duration_ms = (time.time() - start_time) * 1000
                    log_manager.log(
                        level=LogLevel.ERROR,
                        log_type="system",
                        method=request.method,
                        path=request.url.path,
                        model=original_model,
                        status_code=500,
                        duration_ms=duration_ms,
                        error=str(e),
                        client_ip=client_ip,
                        api_key_id=api_key_id,
                        api_key_name=api_key_name,
                    )
                    error_response = {
                        "error": {
                            "message": f"内部错误: {str(e)}",
                            "type": "internal_error",
                            "code": "500",
                        }
                    }
                    yield f"data: {json.dumps(error_response)}\n\n"
                    yield "data: [DONE]\n\n"

            return StreamingResponse(
                stream_with_logging(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        result: ProxyResult = await proxy.forward_request(
            body, protocol_handler, original_model, api_key_name=api_key_name, api_key_id=api_key_id
        )

        duration_ms = (time.time() - start_time) * 1000
        log_manager.log(
            level=LogLevel.INFO,
            log_type="proxy",
            method=request.method,
            path=request.url.path,
            model=original_model,
            provider=result.provider_name,
            provider_id=result.provider_id,
            actual_model=result.actual_model,
            status_code=200,
            duration_ms=duration_ms,
            client_ip=client_ip,
            api_key_id=api_key_id,
            api_key_name=api_key_name,
            protocol=protocol_type,
            request_tokens=result.request_tokens,
            response_tokens=result.response_tokens,
            total_tokens=result.total_tokens,
            message="",
        )
        return JSONResponse(content=result.response)

    except ProxyError as e:
        status_code = e.status_code or 500
        return JSONResponse(
            status_code=status_code,
            content=ErrorResponse(
                error=ErrorDetail(message=e.message, type="proxy_error", code=str(status_code))
            ).model_dump(),
        )
    except RoutingError as e:
        duration_ms = (time.time() - start_time) * 1000
        log_manager.log(
            level=LogLevel.ERROR,
            log_type="system",
            method=request.method,
            path=request.url.path,
            model=original_model,
            status_code=404,
            duration_ms=duration_ms,
            error=str(e),
            client_ip=client_ip,
            api_key_id=api_key_id,
            api_key_name=api_key_name,
        )
        return JSONResponse(
            status_code=404,
            content=ErrorResponse(
                error=ErrorDetail(message=str(e), type="system_error", code="404")
            ).model_dump(),
        )
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        log_manager.log(
            level=LogLevel.ERROR,
            log_type="system",
            method=request.method,
            path=request.url.path,
            model=original_model,
            status_code=500,
            duration_ms=duration_ms,
            error=str(e),
            client_ip=client_ip,
            api_key_id=api_key_id,
            api_key_name=api_key_name,
        )
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error=ErrorDetail(message=f"内部错误: {str(e)}", type="internal_error", code="500")
            ).model_dump(),
        )


@app.post("/v1/chat/completions")
async def chat_completions(request: Request, api_key: APIKey = Depends(verify_api_key)):
    return await process_request(request, "openai", api_key)


@app.post("/v1/responses")
async def openai_responses(request: Request, api_key: APIKey = Depends(verify_api_key)):
    return await process_request(request, "openai-response", api_key)


@app.post("/v1/messages")
async def anthropic_messages(request: Request, api_key: APIKey = Depends(verify_api_key)):
    return await process_request(request, "anthropic", api_key)


@app.post("/v1beta/models/{model}:generateContent")
async def gemini_generate_content(model: str, request: Request, api_key: APIKey = Depends(verify_api_key)):
    return await process_request(request, "gemini", api_key, {"model": model, "stream": False})


@app.post("/v1beta/models/{model}:streamGenerateContent")
async def gemini_stream_generate_content(model: str, request: Request, api_key: APIKey = Depends(verify_api_key)):
    return await process_request(request, "gemini", api_key, {"model": model, "stream": True})


@app.get("/health")
async def health_check():
    stats = provider_manager.get_stats()
    return {
        "status": "healthy",
        "available_providers": stats["available_providers"],
        "total_providers": stats["total_providers"],
    }


@app.get("/stats")
async def get_stats(tag: Optional[str] = None):
    return provider_manager.get_stats(tag=tag)


@app.get("/api/keys")
async def list_api_keys():
    return {"keys": api_key_manager.list_keys(), "stats": api_key_manager.get_stats()}


@app.post("/api/keys")
async def create_api_key(request: CreateAPIKeyRequest):
    full_key, key_info = api_key_manager.create_key(name=request.name)
    return {"key": full_key, "info": key_info}


@app.get("/api/keys/{key_id}")
async def get_api_key(key_id: str):
    key_info = api_key_manager.get_key(key_id)
    if not key_info:
        raise HTTPException(status_code=404, detail="密钥不存在")
    return key_info


@app.put("/api/keys/{key_id}")
async def update_api_key(key_id: str, request: UpdateAPIKeyRequest):
    success = api_key_manager.update_key(key_id=key_id, name=request.name, enabled=request.enabled)
    if not success:
        raise HTTPException(status_code=404, detail="密钥不存在")
    return {"status": "success", "message": "更新成功"}


@app.delete("/api/keys/{key_id}")
async def delete_api_key(key_id: str):
    success = api_key_manager.delete_key(key_id)
    if not success:
        raise HTTPException(status_code=404, detail="密钥不存在")
    return {"status": "success", "message": "删除成功"}


@app.get("/api/logs")
async def get_logs(
    limit: int = Query(100, ge=1, le=1000),
    level: Optional[str] = None,
    log_type: Optional[str] = None,
    keyword: Optional[str] = None,
    provider: Optional[str] = None,
):
    return {
        "logs": log_manager.get_recent_logs(
            limit=limit, level=level, log_type=log_type, keyword=keyword, provider=provider
        )
    }


@app.get("/api/logs/stream")
async def stream_logs():
    async def generate():
        async for log_entry in log_manager.subscribe():
            yield f"data: {json.dumps(log_entry.to_dict(), ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.get("/api/logs/stats")
async def get_log_stats(date: Optional[str] = None, tag: Optional[str] = None):
    return log_manager.get_stats(date, tag=tag)


@app.get("/api/logs/daily")
async def get_daily_stats(days: int = Query(7, ge=1, le=30), tag: Optional[str] = None):
    return log_manager.get_daily_stats(days, tag=tag)


@app.get("/api/providers")
async def list_providers():
    providers = admin_manager.list_providers()
    runtime_states = provider_manager.get_runtime_states()
    for p in providers:
        provider_id = p.get("id")
        if provider_id and provider_id in runtime_states.get("providers", {}):
            p["runtime_status"] = runtime_states["providers"][provider_id]
    return {"providers": providers}


@app.post("/api/providers")
async def add_provider(request: ProviderRequest):
    provider_data = request.model_dump()
    if "id" not in provider_data or not provider_data.get("id"):
        # SQLite admin requires id; keep existing behavior by generating server-side UUID if missing
        import uuid

        provider_data["id"] = str(uuid.uuid4())

    success, message, provider_id = admin_manager.add_provider(provider_data)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    
    log_manager.log(
        level=LogLevel.INFO,
        log_type="admin",
        method="POST",
        path="/api/providers",
        message=f"添加 Provider: {request.name} (ID: {provider_id})",
    )
    return {"status": "success", "message": message, "provider_id": provider_id}


@app.get("/api/providers/all-models")
async def get_all_provider_models():
    """获取所有 Provider 的模型列表 (DB SSOT)"""
    all_providers = admin_manager.list_providers()
    all_models_map = provider_models_manager.get_all_provider_models_map()
    
    response_data = {}
    for p in all_providers:
        pid = p["id"]
        response_data[pid] = {
            "provider_name": p["name"],
            "models": all_models_map.get(pid, [])
        }
        
    return {"provider_models": response_data}


@app.post("/api/providers/sync-all-models")
async def sync_all_models():
    """手动触发全量同步"""
    result = await sync_all_provider_models_logic()
    return result


@app.post("/api/providers/{provider_id}/sync-models")
async def sync_single_provider_models(provider_id: str):
    provider = admin_manager.get_provider_by_id(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    if not provider.get("allow_model_update", True):
        raise HTTPException(status_code=400, detail="该渠道已禁用模型更新")

    pname = provider["name"]
    api_key = provider.get("api_key")
    base_url = provider.get("base_url")

    if not api_key or not base_url:
        raise HTTPException(status_code=400, detail="Provider is not configured with API key or base URL")

    remote_models = await fetch_remote_models(base_url, api_key, provider_id, pname)

    if remote_models is not None:
        added, updated, removed, _, _ = provider_models_manager.update_models_from_remote(
            provider_id, remote_models, pname
        )
        
        # Update the timestamp
        from src.sqlite_repos import ProviderRepo
        ProviderRepo().update_models_updated_at(provider_id)
        
        updated_provider_models_info = provider_models_manager.get_provider(provider_id)
        models_list = []
        if updated_provider_models_info:
            for m_info in updated_provider_models_info.models.values():
                model_dict = m_info.to_dict()
                model_dict['id'] = m_info.model_id
                models_list.append(model_dict)

        return {
            "models": models_list,
            "sync_stats": {
                "added": added,
                "updated": updated,
                "removed": removed,
            }
        }
    else:
        raise HTTPException(status_code=500, detail="从远程服务站获取模型列表失败")


@app.get("/api/providers/runtime-states")
async def get_runtime_states():
    """获取 Provider 和模型的运行时状态"""
    return provider_manager.get_runtime_states()


@app.get("/api/model-health/results")
async def get_all_health_results():
    """获取所有健康检测结果"""
    return {"results": {k: v.to_dict() for k, v in model_health_manager.get_all_results().items()}}


@app.get("/api/model-health/results/{unified_name}")
async def get_mapping_health_results(unified_name: str):
    """获取指定映射的健康检测结果"""
    mapping = model_mapping_manager.get_mapping(unified_name)
    if not mapping:
        raise HTTPException(status_code=404, detail="映射不存在")
    
    results = model_health_manager.get_results_for_models(mapping.resolved_models)
    return {"unified_name": unified_name, "results": {k: v.to_dict() for k, v in results.items()}}


@app.post("/api/model-health/test/{unified_name}")
async def test_mapping_health(unified_name: str):
    """检测指定映射下的所有模型"""
    mapping = model_mapping_manager.get_mapping(unified_name)
    if not mapping:
        raise HTTPException(status_code=404, detail="映射不存在")
    
    results = await model_health_manager.test_mapping_models(mapping.resolved_models)
    
    # 更新 Provider 状态
    for res in results:
        provider_manager.update_model_health_from_test(res.provider, res.model, res.success, res.error)

    success_count = sum(1 for r in results if r.success)
    
    return {
        "status": "success",
        "tested_count": len(results),
        "success_count": success_count,
        "results": [r.to_dict() for r in results]
    }


@app.post("/api/model-health/test-single")
async def test_single_model_health(request: TestSingleModelRequest):
    """检测单个模型"""
    result = await model_health_manager.test_single_model(request.provider_id, request.model)
    
    # 更新 Provider 状态
    provider_manager.update_model_health_from_test(result.provider, result.model, result.success, result.error)
    
    return result.to_dict()


@app.get("/api/protocols")
async def get_protocols():
    from src.protocols import _protocols
    return {"protocols": [{"value": k, "label": k} for k in _protocols.keys()]}


@app.get("/api/model-mappings")
async def list_model_mappings():
    mappings = model_mapping_manager.get_all_mappings()
    sync_config = model_mapping_manager.get_sync_config()
    return {
        "mappings": {k: v.to_dict() for k, v in mappings.items()},
        "sync_config": sync_config.to_dict()
    }


@app.post("/api/model-mappings")
async def create_model_mapping(request: CreateModelMappingRequest):
    success, message = model_mapping_manager.create_mapping(
        unified_name=request.unified_name,
        description=request.description,
        rules=request.rules,
        manual_includes=request.manual_includes,
        excluded_providers=request.excluded_providers,
        enabled=request.enabled
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"status": "success", "message": message}


# 具体路径路由必须在通用路径参数路由之前定义
@app.post("/api/model-mappings/preview")
async def preview_model_mapping(request: PreviewResolveRequest):
    provider_models_map = provider_models_manager.get_all_provider_models_map()
    matched = model_mapping_manager.preview_resolve(
        request.rules,
        request.manual_includes,
        provider_models_map,
        request.excluded_providers
    )
    total = sum(len(ms) for ms in matched.values())
    return {
        "matched_models": matched,
        "total_count": total,
        "provider_count": len(matched)
    }


@app.post("/api/model-mappings/sync")
async def sync_model_mappings(unified_name: Optional[str] = Query(None)):
    provider_models_map = provider_models_manager.get_all_provider_models_map()
    provider_id_name_map = admin_manager.get_provider_id_name_map()
    provider_protocols = admin_manager.get_provider_protocols()

    if unified_name:
        success, message, resolved = model_mapping_manager.sync_mapping(
            unified_name,
            provider_models_map,
            provider_id_name_map,
            provider_protocols
        )
        if not success:
            raise HTTPException(status_code=400, detail=message)
        return {"status": "success", "message": message, "synced_count": 1}
    else:
        results = model_mapping_manager.sync_all_mappings(
            provider_models_map,
            provider_id_name_map,
            provider_protocols
        )
        return {"status": "success", "synced_count": len(results), "results": results}


@app.post("/api/model-mappings/reorder")
async def reorder_model_mappings(request: ReorderModelMappingsRequest):
    success, message = model_mapping_manager.reorder_mappings(request.ordered_names)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"status": "success", "message": message}


@app.get("/api/model-mappings/sync-config")
async def get_sync_config():
    return model_mapping_manager.get_sync_config().to_dict()


@app.put("/api/model-mappings/sync-config")
async def update_sync_config(request: SyncConfigRequest):
    success, message = model_mapping_manager.update_sync_config(
        auto_sync_enabled=request.auto_sync_enabled,
        auto_sync_interval_hours=request.auto_sync_interval_hours
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"status": "success", "message": message}


# 通用路径参数路由必须在具体路径路由之后定义
@app.get("/api/model-mappings/{unified_name}")
async def get_model_mapping(unified_name: str):
    mapping = model_mapping_manager.get_mapping(unified_name)
    if not mapping:
        raise HTTPException(status_code=404, detail="映射不存在")
    return mapping.to_dict()


@app.put("/api/model-mappings/{unified_name}")
async def update_model_mapping(unified_name: str, request: UpdateModelMappingRequest):
    if request.new_unified_name and request.new_unified_name != unified_name:
        success, message = model_mapping_manager.rename_mapping(unified_name, request.new_unified_name)
        if not success:
            raise HTTPException(status_code=400, detail=message)
        unified_name = request.new_unified_name

    success, message = model_mapping_manager.update_mapping(
        unified_name=unified_name,
        description=request.description,
        rules=request.rules,
        manual_includes=request.manual_includes,
        excluded_providers=request.excluded_providers,
        enabled=request.enabled
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"status": "success", "message": message, "unified_name": unified_name}


@app.delete("/api/model-mappings/{unified_name}")
async def delete_model_mapping(unified_name: str):
    success, message = model_mapping_manager.delete_mapping(unified_name)
    if not success:
        raise HTTPException(status_code=404, detail=message)
    return {"status": "success", "message": message}


@app.get("/api/model-mappings/{unified_name}/model-settings")
async def get_model_settings(unified_name: str):
    mapping = model_mapping_manager.get_mapping(unified_name)
    if not mapping:
        raise HTTPException(status_code=404, detail="映射不存在")
    return {"unified_name": unified_name, "model_settings": mapping.model_settings}


@app.put("/api/model-mappings/{unified_name}/model-settings")
async def update_model_protocol(unified_name: str, request: UpdateModelProtocolRequest):
    if request.protocol and not is_supported_protocol(request.protocol):
        raise HTTPException(status_code=400, detail=f"不支持的协议: {request.protocol}")
        
    success, message = model_mapping_manager.set_model_protocol(
        unified_name,
        request.provider_id,
        request.model_id,
        request.protocol
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"status": "success", "message": message}


@app.delete("/api/model-mappings/{unified_name}/model-settings/{provider_id}/{model_id}")
async def delete_model_protocol(unified_name: str, provider_id: str, model_id: str):
    success, message = model_mapping_manager.set_model_protocol(
        unified_name,
        provider_id,
        model_id,
        None
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"status": "success", "message": message}


@app.get("/api/providers/{provider_id}")
async def get_provider(provider_id: str):
    provider = admin_manager.get_provider_by_id(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider 不存在")
    return provider


@app.put("/api/providers/{provider_id}")
async def update_provider(provider_id: str, request: UpdateProviderRequest):
    provider = admin_manager.get_provider_by_id(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider 不存在")

    update_data = request.model_dump(exclude_unset=True)
    provider.update(update_data)

    success, message = admin_manager.update_provider(provider_id, provider)
    if not success:
        raise HTTPException(status_code=400, detail=message)

    return {"status": "success", "message": message}


@app.delete("/api/providers/{provider_id}")
async def delete_provider(provider_id: str):
    provider = admin_manager.get_provider_by_id(provider_id)

    success, message = admin_manager.delete_provider(provider_id)
    if not success:
        raise HTTPException(status_code=404, detail=message)

    provider_name = provider.get("name", provider_id) if provider else provider_id
    log_manager.log(
        level=LogLevel.WARNING,
        log_type="admin",
        method="DELETE",
        path=f"/api/providers/{provider_id}",
        message=f"删除 Provider: {provider_name}",
    )
    return {"status": "success", "message": message}


@app.post("/api/admin/reset/{provider_id}")
async def reset_provider(provider_id: str):
    provider = admin_manager.get_provider_by_id(provider_id)

    if provider_manager.reset(provider_id):
        provider_name = provider.get("name", provider_id) if provider else provider_id
        return {"status": "success", "message": f"Provider '{provider_name}' 已重置"}
    raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' 不存在")


@app.post("/api/admin/reset-all")
async def reset_all_providers():
    provider_manager.reset_all()
    return {"status": "success", "message": "所有 Provider 已重置"}


@app.get("/api/admin/system-stats")
async def get_system_stats():
    model_mapping_manager.load()
    return {
        "providers": provider_manager.get_stats(),
        "api_keys": api_key_manager.get_stats(),
        "logs": log_manager.get_stats(),
        "model_mappings": len(model_mapping_manager.get_all_mappings()),
        "today": get_today_str(),
    }


from pathlib import Path

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/admin", StaticFiles(directory=str(static_dir), html=True), name="admin")


if __name__ == "__main__":
    try:
        config = config_manager.load()
        host = config.server_host
        port = config.server_port
    except Exception:
        host = DEFAULT_SERVER_HOST
        port = DEFAULT_SERVER_PORT

    uvicorn.run("main:app", host=host, port=port, reload=False, log_level="info")

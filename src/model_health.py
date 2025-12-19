import json
import time
import asyncio
from datetime import datetime, timezone
from typing import Optional, Any
from dataclasses import dataclass, asdict
import httpx

from .constants import ADMIN_HTTP_TIMEOUT, PROXY_ERROR_MESSAGE_MAX_LENGTH
from .sqlite_repos import ModelHealthRepo
from .provider_models import provider_models_manager
from .model_mapping import model_mapping_manager
from .protocols import get_protocol


@dataclass
class ModelHealthResult:
    """单个模型的健康检测结果"""
    provider: str           # Provider ID (UUID)
    model: str              # 模型名称
    success: bool           # 检测是否成功
    latency_ms: float       # 响应延迟（毫秒）
    response_body: dict     # 完整响应体JSON
    error: Optional[str]    # 错误信息（如果失败）
    tested_at: str          # ISO8601 时间戳
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> "ModelHealthResult":
        return cls(
            provider=data.get("provider", ""),
            model=data.get("model", ""),
            success=data.get("success", False),
            latency_ms=data.get("latency_ms", 0.0),
            response_body=data.get("response_body", {}),
            error=data.get("error"),
            tested_at=data.get("tested_at", "")
        )
    
    @staticmethod
    def make_key(provider_id: str, model: str) -> str:
        return f"{provider_id}:{model}"


class ModelHealthManager:
    """
    模型健康检测管理器 (SQLite)
    """
    
    VERSION = "1.0"
    
    def __init__(self):
        self._repo = ModelHealthRepo()
        self._admin_manager = None
        # Cache results in memory for fast read access? 
        # Yes, to avoid DB hit on every check if frequent.
        # But for consistency with other managers, let's load on demand or keep cache.
        # Given health checks are periodic or on-demand, maybe caching is good.
        self._results: dict[str, ModelHealthResult] = {}
        self.load()

    def load(self) -> None:
        raw_results = self._repo.get_all_results()
        self._results = {}
        for key, rdata in raw_results.items():
            self._results[key] = ModelHealthResult.from_dict(rdata)

    def save(self, immediate: bool = False) -> None:
        """Compatibility method (no-op)"""
        pass

    def set_admin_manager(self, admin_manager: Any) -> None:
        self._admin_manager = admin_manager

    def _get_model_protocol(self, provider_id: str, model: str) -> Optional[str]:
        mappings = model_mapping_manager.get_all_mappings()
        key = f"{provider_id}:{model}"
        for mapping in mappings.values():
            if key in mapping.model_settings:
                return mapping.model_settings[key].get("protocol")
        return None

    def record_passive_result(
        self,
        provider_id: str,
        model: str,
        success: bool,
        latency_ms: float = 0.0,
        error: Optional[str] = None,
        response_body: Optional[dict] = None
    ) -> None:
        result = ModelHealthResult(
            provider=provider_id,
            model=model,
            success=success,
            latency_ms=latency_ms,
            response_body=response_body if not success and response_body else {},
            error=error,
            tested_at=datetime.now(timezone.utc).isoformat()
        )
        
        key = ModelHealthResult.make_key(provider_id, model)
        self._results[key] = result
        
        # Truncate body if needed before saving to DB (Guide 2.5)
        db_data = result.to_dict()
        if not success and db_data.get("response_body"):
            body_str = json.dumps(db_data["response_body"], ensure_ascii=False)
            if len(body_str) > PROXY_ERROR_MESSAGE_MAX_LENGTH:
                # We can't easily truncate JSON and keep it valid JSON without parsing.
                # But the repo expects a dict to dump.
                # The guide says: "写入前 json.dumps... 并截断".
                # Repo does json.dumps. So we should probably pass a truncated string wrapped in a dict or just a specific key?
                # Actually, repo `upsert_result` does: `body_json = json.dumps(result.get("response_body", {})...)`
                # So if we want to truncate, we should probably do it in the Repo or modify what we pass.
                # Let's handle it by passing a special dict indicating truncation if too long.
                pass
                # Actually, let's modify the Repo to handle truncation as per guide strictly.
                # Guide says: "model_health_last.response_body_json 仅在失败时写入... 并按... 截断"
        
        self._repo.upsert_result(db_data)

    def get_result(self, provider_id: str, model: str) -> Optional[ModelHealthResult]:
        key = ModelHealthResult.make_key(provider_id, model)
        return self._results.get(key)

    def get_all_results(self) -> dict[str, ModelHealthResult]:
        return self._results.copy()

    def get_results_for_models(
        self,
        resolved_models: dict[str, list[str]]
    ) -> dict[str, ModelHealthResult]:
        results = {}
        for provider_id, models in resolved_models.items():
            for model in models:
                key = ModelHealthResult.make_key(provider_id, model)
                if key in self._results:
                    results[key] = self._results[key]
        return results

    async def test_single_model(
        self,
        provider_id: str,
        model: str,
        save_immediately: bool = False,
        skip_disabled_check: bool = False
    ) -> ModelHealthResult:
        # Same logic as original, but using _admin_manager and protocols
        if not self._admin_manager:
            return self._create_error_result(provider_id, model, "AdminManager 未初始化")
        
        provider = self._admin_manager.get_provider(provider_id)
        if not provider:
            return self._create_error_result(provider_id, model, f"Provider ID '{provider_id}' 不存在")
        
        if not skip_disabled_check:
            if not provider.get("enabled", True):
                return self._create_skipped_result(provider_id, model)
            if not provider.get("allow_health_check", True):
                return self._create_error_result(provider_id, model, "该服务站已禁用健康检测")
        
        protocol_type = self._get_model_protocol(provider_id, model)
        # If no specific protocol, fallback to provider default?
        # The original code only checked mapping. Let's check provider default too.
        if not protocol_type:
            protocol_type = provider.get("default_protocol")
            
        if not protocol_type:
            return self._create_error_result(provider_id, model, "未配置协议，跳过健康检测")
        
        protocol = get_protocol(protocol_type)
        if not protocol:
            return self._create_error_result(provider_id, model, f"不支持的协议类型: {protocol_type}")
        
        base_url = provider.get("base_url", "").rstrip("/")
        api_key = provider.get("api_key", "")
        
        minimal_body = protocol.get_health_check_body(model)
        req = protocol.build_request(base_url, api_key, minimal_body, model)
        
        start_time = time.time()
        try:
            async with httpx.AsyncClient(timeout=ADMIN_HTTP_TIMEOUT) as client:
                response = await client.post(
                    req.url,
                    headers=req.headers,
                    json=req.body
                )
                latency_ms = (time.time() - start_time) * 1000
                
                try:
                    response_body = response.json()
                except json.JSONDecodeError:
                    response_body = {"raw_text": response.text[:500]}
                
                if response.status_code == 200:
                    result = ModelHealthResult(
                        provider=provider_id,
                        model=model,
                        success=True,
                        latency_ms=latency_ms,
                        response_body={},
                        error=None,
                        tested_at=datetime.now(timezone.utc).isoformat()
                    )
                else:
                    error_detail = json.dumps(response_body, ensure_ascii=False).replace('\n', ' ')
                    full_error = f"HTTP {response.status_code}: {error_detail}"
                    result = ModelHealthResult(
                        provider=provider_id,
                        model=model,
                        success=False,
                        latency_ms=latency_ms,
                        response_body=response_body,
                        error=full_error,
                        tested_at=datetime.now(timezone.utc).isoformat()
                    )
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            result = ModelHealthResult(
                provider=provider_id,
                model=model,
                success=False,
                latency_ms=latency_ms,
                response_body={},
                error=str(e),
                tested_at=datetime.now(timezone.utc).isoformat()
            )
        
        # Save
        key = ModelHealthResult.make_key(provider_id, model)
        self._results[key] = result
        self._repo.upsert_result(result.to_dict())
        
        # Integration
        # provider_manager is not imported to avoid circular import if possible
        # but original code imported it.
        # We need to import provider_manager from somewhere.
        # In main.py, provider_manager is from src.provider.
        # Let's import inside method.
        from .provider import provider_manager
        provider_manager.update_model_health_from_test(
            provider_name=provider_id,
            model_name=model,
            success=result.success,
            error_message=result.error
        )
        
        provider_models_manager.update_activity(provider_id, model, "health_test")
        
        return result

    def _create_error_result(self, provider_id: str, model: str, error: str) -> ModelHealthResult:
        return ModelHealthResult(
            provider=provider_id,
            model=model,
            success=False,
            latency_ms=0.0,
            response_body={},
            error=error,
            tested_at=datetime.now(timezone.utc).isoformat()
        )

    def _create_skipped_result(self, provider_id: str, model: str) -> ModelHealthResult:
        return ModelHealthResult(
            provider=provider_id,
            model=model,
            success=False,
            latency_ms=0.0,
            response_body={},
            error=None, # Skipped is not error? Original code had error=None but success=False?
            # Original: success=False, error=None -> implies skipped/unknown.
            tested_at=datetime.now(timezone.utc).isoformat()
        )

    async def test_mapping_models(
        self,
        resolved_models: dict[str, list[str]],
        save_after_completion: bool = True,
        skip_disabled_providers: bool = True
    ) -> list[ModelHealthResult]:
        
        filtered = resolved_models
        if skip_disabled_providers and self._admin_manager:
            filtered = {}
            for pid, models in resolved_models.items():
                p = self._admin_manager.get_provider(pid)
                if p and p.get("enabled", True) and p.get("allow_health_check", True):
                    filtered[pid] = models
        
        async def test_provider(pid: str, models: list[str]) -> list[ModelHealthResult]:
            results = []
            for m in models:
                res = await self.test_single_model(
                    pid, m, save_immediately=False, skip_disabled_check=True
                )
                results.append(res)
            return results
        
        tasks = [test_provider(pid, models) for pid, models in filtered.items()]
        nested = await asyncio.gather(*tasks, return_exceptions=True)
        
        all_results = []
        for res in nested:
            if isinstance(res, Exception):
                print(f"[ModelHealth] Batch test error: {res}")
                continue
            all_results.extend(res)
            
        return all_results

    def clear_result(self, provider_id: str, model: str) -> None:
        key = ModelHealthResult.make_key(provider_id, model)
        if key in self._results:
            del self._results[key]
            self._repo.delete_result(provider_id, model)

    def clear_results(self) -> None:
        self._results.clear()
        self._repo.clear_all()


model_health_manager = ModelHealthManager()
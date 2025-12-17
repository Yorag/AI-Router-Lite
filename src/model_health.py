"""
模型健康检测模块

负责管理模型健康状态的检测和持久化存储
支持：
- 单模型检测（返回完整响应体）
- 批量检测（同渠道串行，跨渠道异步）
- 结果持久化存储

存储策略：
- 健康检测结果：缓冲落盘（批量检测完成后统一保存或定时保存）

注意：使用 provider_id (UUID) 作为内部标识，而非 provider name
存储格式为 "provider_id:model_name"
"""

import json
import time
import asyncio
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Any
from dataclasses import dataclass, asdict
import httpx

from .constants import (
    MODEL_HEALTH_STORAGE_PATH,
    ADMIN_HTTP_TIMEOUT,
    HEALTH_TEST_MAX_TOKENS,
    HEALTH_TEST_MESSAGE,
    STORAGE_BUFFER_INTERVAL_SECONDS,
)
from .storage import BaseStorageManager, persistence_manager
from .provider import provider_manager
from .provider_models import provider_models_manager


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
        """生成存储键（provider_id:model）"""
        return f"{provider_id}:{model}"


class ModelHealthManager(BaseStorageManager):
    """
    模型健康检测管理器
    
    继承 BaseStorageManager，实现缓冲保存策略：
    - 单次检测后标记脏数据，由定时任务保存
    - 批量检测完成后可调用 save(immediate=True) 立即保存
    """
    
    VERSION = "1.0"
    
    def __init__(self, data_path: str = MODEL_HEALTH_STORAGE_PATH):
        super().__init__(
            data_path=data_path,
            save_interval=STORAGE_BUFFER_INTERVAL_SECONDS,
            use_file_lock=True
        )
        self._results: dict[str, ModelHealthResult] = {}
        self._admin_manager = None  # 延迟注入
        
        # 注册到全局持久化管理器
        persistence_manager.register(self)
    
    def _get_default_data(self) -> dict:
        """返回默认数据结构"""
        return {
            "version": self.VERSION,
            "results": {}
        }
    
    def _do_load(self) -> None:
        """加载所有健康检测结果"""
        data = self._read_from_file()
        
        self._results.clear()
        for key, result_data in data.get("results", {}).items():
            self._results[key] = ModelHealthResult.from_dict(result_data)
    
    def _do_save(self) -> None:
        """保存所有健康检测结果"""
        data = {
            "version": self.VERSION,
            "results": {key: r.to_dict() for key, r in self._results.items()}
        }
        self._write_to_file(data)
    
    def set_admin_manager(self, admin_manager: Any) -> None:
        """
        设置 AdminManager 引用，用于获取 Provider 配置
        
        Args:
            admin_manager: AdminManager 实例
        """
        self._admin_manager = admin_manager
    
    # ==================== 被动请求结果记录 ====================
    
    def record_passive_result(
        self,
        provider_id: str,
        model: str,
        success: bool,
        latency_ms: float = 0.0,
        error: Optional[str] = None,
        response_body: Optional[dict] = None
    ) -> None:
        """
        记录被动请求的健康状态（最后一次请求结果）
        
        仅标记脏数据，由定时任务批量保存，不立即写盘。
        
        Args:
            provider_id: Provider 的唯一 ID (UUID)
            model: 模型名称
            success: 请求是否成功
            latency_ms: 响应延迟（毫秒）
            error: 错误信息（如果失败）
            response_body: 响应体（仅失败时保存，成功时忽略）
        """
        self._ensure_loaded()
        
        result = ModelHealthResult(
            provider=provider_id,
            model=model,
            success=success,
            latency_ms=latency_ms,
            response_body=response_body if not success and response_body else {},  # 仅失败时保存响应体
            error=error,
            tested_at=datetime.now(timezone.utc).isoformat()
        )
        
        with self._lock:
            key = ModelHealthResult.make_key(provider_id, model)
            self._results[key] = result
            self.mark_dirty()  # 仅标记脏数据，由定时任务保存
    
    # ==================== 结果查询 ====================
    
    def get_result(self, provider_id: str, model: str) -> Optional[ModelHealthResult]:
        """获取单个模型的检测结果"""
        self._ensure_loaded()
        with self._lock:
            key = ModelHealthResult.make_key(provider_id, model)
            return self._results.get(key)
    
    def get_all_results(self) -> dict[str, ModelHealthResult]:
        """获取所有检测结果"""
        self._ensure_loaded()
        with self._lock:
            return self._results.copy()
    
    def get_results_for_models(
        self,
        resolved_models: dict[str, list[str]]
    ) -> dict[str, ModelHealthResult]:
        """
        获取指定模型集合的检测结果
        
        Args:
            resolved_models: {provider_id: [model_ids]}
            
        Returns:
            {provider_id:model: ModelHealthResult}
        """
        self._ensure_loaded()
        with self._lock:
            results = {}
            
            for provider_id, models in resolved_models.items():
                for model in models:
                    key = ModelHealthResult.make_key(provider_id, model)
                    if key in self._results:
                        results[key] = self._results[key]
            
            return results
    
    # ==================== 健康检测 ====================
    
    async def test_single_model(
        self,
        provider_id: str,
        model: str,
        save_immediately: bool = False,
        skip_disabled_check: bool = False
    ) -> ModelHealthResult:
        """
        检测单个模型，返回完整响应体
        
        Args:
            provider_id: Provider 的唯一 ID (UUID)
            model: 模型名称
            save_immediately: 是否立即保存（默认 False，由定时任务保存）
            skip_disabled_check: 是否跳过禁用检查（默认 False，用于内部强制检测场景）
            
        Returns:
            ModelHealthResult 包含完整响应体
            
        Note:
            - 默认使用缓冲保存策略，仅标记脏数据
            - 如果渠道被手动禁用（enabled=False），会跳过检测并返回错误
        """
        if not self._admin_manager:
            return ModelHealthResult(
                provider=provider_id,
                model=model,
                success=False,
                latency_ms=0.0,
                response_body={},
                error="AdminManager 未初始化",
                tested_at=datetime.now(timezone.utc).isoformat()
            )
        
        # 获取 Provider 配置（通过 ID 查找）
        provider = self._admin_manager.get_provider(provider_id)
        if not provider:
            return ModelHealthResult(
                provider=provider_id,
                model=model,
                success=False,
                latency_ms=0.0,
                response_body={},
                error=f"Provider ID '{provider_id}' 不存在",
                tested_at=datetime.now(timezone.utc).isoformat()
            )
        
        # 检查渠道是否被手动禁用
        if not skip_disabled_check and not provider.get("enabled", True):
            provider_name = provider.get("name", provider_id)
            return ModelHealthResult(
                provider=provider_id,
                model=model,
                success=False,
                latency_ms=0.0,
                response_body={},
                tested_at=datetime.now(timezone.utc).isoformat()
            )
        
        base_url = provider.get("base_url", "").rstrip("/")
        api_key = provider.get("api_key", "")
        
        start_time = time.time()
        
        try:
            async with httpx.AsyncClient(timeout=ADMIN_HTTP_TIMEOUT) as client:
                response = await client.post(
                    f"{base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": HEALTH_TEST_MESSAGE}],
                        "max_tokens": HEALTH_TEST_MAX_TOKENS
                    }
                )
                
                latency_ms = (time.time() - start_time) * 1000
                
                # 尝试解析响应体
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
                        response_body={},  # 成功时不保存响应体，仅记录延迟
                        error=None,
                        tested_at=datetime.now(timezone.utc).isoformat()
                    )
                else:
                    # 将响应体转为单行字符串作为错误详情
                    error_detail = json.dumps(response_body, ensure_ascii=False).replace('\n', ' ').replace('\r', ' ')
                    result = ModelHealthResult(
                        provider=provider_id,
                        model=model,
                        success=False,
                        latency_ms=latency_ms,
                        response_body=response_body,
                        error=f"HTTP {response.status_code}: {error_detail}",
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
        
        # 保存结果到内存（使用 provider_id 作为 key）
        with self._lock:
            key = ModelHealthResult.make_key(provider_id, model)
            self._results[key] = result
            
            if save_immediately:
                # 立即保存
                self.save(immediate=True)
            else:
                # 标记脏数据，由定时任务保存
                self.mark_dirty()
        
        # 与熔断系统集成：根据健康检测结果更新模型状态
        provider_manager.update_model_health_from_test(
            provider_name=provider_id,  # 注意：provider_manager 可能还需要适配
            model_name=model,
            success=result.success,
            error_message=result.error
        )
        
        # 更新模型最后活动时间
        provider_models_manager.update_activity(
            provider_id, model, "health_test"
        )
        
        return result
    
    async def test_mapping_models(
        self,
        resolved_models: dict[str, list[str]],
        save_after_completion: bool = True,
        skip_disabled_providers: bool = True
    ) -> list[ModelHealthResult]:
        """
        批量检测映射下的所有模型
        
        策略：同渠道内串行检测，不同渠道间异步检测
        
        Args:
            resolved_models: {provider_id: [model_ids]}
            save_after_completion: 检测完成后是否立即保存（默认 True）
            skip_disabled_providers: 是否跳过禁用的渠道（默认 True）
            
        Returns:
            所有检测结果列表（不包含被跳过的禁用渠道模型）
        """
        self._ensure_loaded()
        
        # 过滤掉禁用的渠道
        filtered_resolved_models = resolved_models
        skipped_count = 0
        if skip_disabled_providers and self._admin_manager:
            filtered_resolved_models = {}
            for provider_id, models in resolved_models.items():
                provider = self._admin_manager.get_provider(provider_id)
                if provider and provider.get("enabled", True):
                    filtered_resolved_models[provider_id] = models
                else:
                    skipped_count += len(models)
                    provider_name = provider.get("name", provider_id) if provider else provider_id
                    print(f"[ModelHealth] 跳过禁用渠道 '{provider_name}' 的 {len(models)} 个模型")
        
        async def test_provider_models(provider_id: str, models: list[str]) -> list[ModelHealthResult]:
            """串行检测单个渠道内的所有模型"""
            results = []
            for model in models:
                # 单个检测不立即保存，批量完成后统一保存
                result = await self.test_single_model(provider_id, model, save_immediately=False)
                results.append(result)
            return results
        
        # 为每个渠道创建异步任务（已过滤禁用渠道）
        tasks = [
            test_provider_models(provider_id, models)
            for provider_id, models in filtered_resolved_models.items()
        ]
        
        # 并发执行所有渠道的检测
        all_results_nested = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 展平结果列表
        all_results: list[ModelHealthResult] = []
        for result in all_results_nested:
            if isinstance(result, Exception):
                # 记录异常但继续处理其他结果
                print(f"[ModelHealth] 检测出错: {result}")
                continue
            all_results.extend(result)
        
        # 批量检测完成后统一保存
        if save_after_completion and all_results:
            self.save(immediate=True)
        
        return all_results
    
    def clear_results(self) -> None:
        """清除所有检测结果"""
        with self._lock:
            self._results.clear()
            self.save(immediate=True)


# 全局实例
model_health_manager = ModelHealthManager()
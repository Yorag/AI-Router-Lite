"""
模型健康检测模块

负责管理模型健康状态的检测和持久化存储
支持：
- 单模型检测（返回完整响应体）
- 批量检测（同渠道串行，跨渠道异步）
- 结果持久化存储
"""

import json
import time
import asyncio
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Any
from dataclasses import dataclass, asdict
import filelock
import httpx

from .constants import (
    MODEL_HEALTH_STORAGE_PATH,
    ADMIN_HTTP_TIMEOUT,
    HEALTH_TEST_MAX_TOKENS,
    HEALTH_TEST_MESSAGE,
)


@dataclass
class ModelHealthResult:
    """单个模型的健康检测结果"""
    provider: str           # 渠道名称
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
    def make_key(provider: str, model: str) -> str:
        """生成存储键"""
        return f"{provider}:{model}"


class ModelHealthManager:
    """模型健康检测管理器"""
    
    VERSION = "1.0"
    
    def __init__(self, data_path: str = MODEL_HEALTH_STORAGE_PATH):
        self.data_path = Path(data_path)
        self.lock_path = self.data_path.with_suffix(".json.lock")
        self._results: dict[str, ModelHealthResult] = {}
        self._loaded = False
        self._admin_manager = None  # 延迟注入
    
    def set_admin_manager(self, admin_manager: Any) -> None:
        """
        设置 AdminManager 引用，用于获取 Provider 配置
        
        Args:
            admin_manager: AdminManager 实例
        """
        self._admin_manager = admin_manager
    
    def _ensure_file_exists(self) -> None:
        """确保数据文件存在"""
        if not self.data_path.exists():
            self.data_path.parent.mkdir(parents=True, exist_ok=True)
            self._save_data({
                "version": self.VERSION,
                "results": {}
            })
    
    def _load_data(self) -> dict:
        """加载数据文件"""
        self._ensure_file_exists()
        try:
            with open(self.data_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {"version": self.VERSION, "results": {}}
    
    def _save_data(self, data: dict) -> None:
        """保存数据文件（带文件锁）"""
        self.data_path.parent.mkdir(parents=True, exist_ok=True)
        lock = filelock.FileLock(self.lock_path, timeout=10)
        with lock:
            with open(self.data_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
    
    def load(self) -> None:
        """加载所有健康检测结果"""
        data = self._load_data()
        
        self._results = {}
        for key, result_data in data.get("results", {}).items():
            self._results[key] = ModelHealthResult.from_dict(result_data)
        
        self._loaded = True
    
    def save(self) -> None:
        """保存所有健康检测结果"""
        data = {
            "version": self.VERSION,
            "results": {key: r.to_dict() for key, r in self._results.items()}
        }
        self._save_data(data)
    
    def _ensure_loaded(self) -> None:
        """确保数据已加载"""
        if not self._loaded:
            self.load()
    
    # ==================== 结果查询 ====================
    
    def get_result(self, provider: str, model: str) -> Optional[ModelHealthResult]:
        """获取单个模型的检测结果"""
        self._ensure_loaded()
        key = ModelHealthResult.make_key(provider, model)
        return self._results.get(key)
    
    def get_all_results(self) -> dict[str, ModelHealthResult]:
        """获取所有检测结果"""
        self._ensure_loaded()
        return self._results.copy()
    
    def get_results_for_models(
        self, 
        resolved_models: dict[str, list[str]]
    ) -> dict[str, ModelHealthResult]:
        """
        获取指定模型集合的检测结果
        
        Args:
            resolved_models: {provider: [model_ids]}
            
        Returns:
            {provider:model: ModelHealthResult}
        """
        self._ensure_loaded()
        results = {}
        
        for provider, models in resolved_models.items():
            for model in models:
                key = ModelHealthResult.make_key(provider, model)
                if key in self._results:
                    results[key] = self._results[key]
        
        return results
    
    # ==================== 健康检测 ====================
    
    async def test_single_model(
        self, 
        provider_name: str, 
        model: str
    ) -> ModelHealthResult:
        """
        检测单个模型，返回完整响应体
        
        Args:
            provider_name: Provider 名称
            model: 模型名称
            
        Returns:
            ModelHealthResult 包含完整响应体
        """
        if not self._admin_manager:
            return ModelHealthResult(
                provider=provider_name,
                model=model,
                success=False,
                latency_ms=0.0,
                response_body={},
                error="AdminManager 未初始化",
                tested_at=datetime.now(timezone.utc).isoformat()
            )
        
        # 获取 Provider 配置
        provider = self._admin_manager.get_provider(provider_name)
        if not provider:
            return ModelHealthResult(
                provider=provider_name,
                model=model,
                success=False,
                latency_ms=0.0,
                response_body={},
                error=f"Provider '{provider_name}' 不存在",
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
                        provider=provider_name,
                        model=model,
                        success=True,
                        latency_ms=latency_ms,
                        response_body=response_body,
                        error=None,
                        tested_at=datetime.now(timezone.utc).isoformat()
                    )
                else:
                    result = ModelHealthResult(
                        provider=provider_name,
                        model=model,
                        success=False,
                        latency_ms=latency_ms,
                        response_body=response_body,
                        error=f"HTTP {response.status_code}",
                        tested_at=datetime.now(timezone.utc).isoformat()
                    )
                    
        except httpx.TimeoutException:
            latency_ms = (time.time() - start_time) * 1000
            result = ModelHealthResult(
                provider=provider_name,
                model=model,
                success=False,
                latency_ms=latency_ms,
                response_body={},
                error="请求超时",
                tested_at=datetime.now(timezone.utc).isoformat()
            )
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            result = ModelHealthResult(
                provider=provider_name,
                model=model,
                success=False,
                latency_ms=latency_ms,
                response_body={},
                error=str(e),
                tested_at=datetime.now(timezone.utc).isoformat()
            )
        
        # 保存结果
        key = ModelHealthResult.make_key(provider_name, model)
        self._results[key] = result
        self.save()
        
        return result
    
    async def test_mapping_models(
        self, 
        resolved_models: dict[str, list[str]]
    ) -> list[ModelHealthResult]:
        """
        批量检测映射下的所有模型
        
        策略：同渠道内串行检测，不同渠道间异步检测
        
        Args:
            resolved_models: {provider: [model_ids]}
            
        Returns:
            所有检测结果列表
        """
        self._ensure_loaded()
        
        async def test_provider_models(provider: str, models: list[str]) -> list[ModelHealthResult]:
            """串行检测单个渠道内的所有模型"""
            results = []
            for model in models:
                result = await self.test_single_model(provider, model)
                results.append(result)
            return results
        
        # 为每个渠道创建异步任务
        tasks = [
            test_provider_models(provider, models)
            for provider, models in resolved_models.items()
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
        
        return all_results
    
    def clear_results(self) -> None:
        """清除所有检测结果"""
        self._results.clear()
        self.save()


# 全局实例
model_health_manager = ModelHealthManager()
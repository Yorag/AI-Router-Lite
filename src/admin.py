"""
管理模块

负责 Provider 管理、模型映射管理、可用性测试等管理功能
"""

import json
import time
import asyncio
from pathlib import Path
from typing import Optional, TYPE_CHECKING
from dataclasses import dataclass, asdict

import httpx

from .config import ProviderConfig, AppConfig, config_manager
from .constants import (
    HEALTH_CHECK_SKIP_THRESHOLD_HOURS,
    ADMIN_HTTP_TIMEOUT,
    HEALTH_TEST_MAX_TOKENS,
    HEALTH_TEST_MESSAGE,
)

if TYPE_CHECKING:
    from .provider import ProviderManager


@dataclass
class ProviderTestResult:
    """Provider 测试结果"""
    provider_name: str
    model: str
    success: bool
    latency_ms: Optional[float] = None
    error: Optional[str] = None
    tested_at: float = 0.0
    
    def to_dict(self) -> dict:
        return asdict(self)


class AdminManager:
    """管理功能管理器"""
    
    def __init__(self, config_path: str = "config.json"):
        self.config_path = Path(config_path)
        self._test_results: dict[str, ProviderTestResult] = {}  # provider:model -> result
        self._test_lock = asyncio.Lock()
        self._provider_manager: Optional["ProviderManager"] = None
    
    def set_provider_manager(self, provider_manager: "ProviderManager") -> None:
        """
        设置 ProviderManager 引用，用于统一健康状态管理
        
        Args:
            provider_manager: ProviderManager 实例
        """
        self._provider_manager = provider_manager
    
    def get_config(self) -> dict:
        """获取当前配置"""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            return {"error": str(e)}
    
    def save_config(self, config: dict) -> bool:
        """保存配置"""
        try:
            # 备份当前配置
            backup_path = self.config_path.with_suffix(".json.bak")
            if self.config_path.exists():
                with open(self.config_path, "r", encoding="utf-8") as f:
                    backup_data = f.read()
                with open(backup_path, "w", encoding="utf-8") as f:
                    f.write(backup_data)
            
            # 保存新配置
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            
            return True
        except Exception as e:
            print(f"[AdminManager] 保存配置失败: {e}")
            return False
    
    # ==================== Provider 管理 ====================
    
    def list_providers(self) -> list[dict]:
        """列出所有 Provider"""
        config = self.get_config()
        providers = config.get("providers", [])
        
        # 添加测试结果
        for provider in providers:
            name = provider.get("name", "")
            test_results = []
            for model in provider.get("supported_models", []):
                key = f"{name}:{model}"
                if key in self._test_results:
                    test_results.append(self._test_results[key].to_dict())
            provider["test_results"] = test_results
        
        return providers
    
    def get_provider(self, name: str) -> Optional[dict]:
        """获取指定 Provider"""
        config = self.get_config()
        for provider in config.get("providers", []):
            if provider.get("name") == name:
                return provider
        return None
    
    def add_provider(self, provider_data: dict) -> tuple[bool, str]:
        """添加 Provider"""
        config = self.get_config()
        providers = config.get("providers", [])
        
        # 检查名称是否已存在
        name = provider_data.get("name", "")
        if any(p.get("name") == name for p in providers):
            return False, f"Provider '{name}' 已存在"
        
        # 验证必填字段
        required_fields = ["name", "base_url", "api_key"]
        for field in required_fields:
            if not provider_data.get(field):
                return False, f"缺少必填字段: {field}"
        
        # 设置默认值
        if "weight" not in provider_data:
            provider_data["weight"] = 1
        if "supported_models" not in provider_data:
            provider_data["supported_models"] = []
        
        providers.append(provider_data)
        config["providers"] = providers
        
        if self.save_config(config):
            return True, "添加成功"
        return False, "保存配置失败"
    
    def update_provider(self, name: str, provider_data: dict) -> tuple[bool, str]:
        """更新 Provider"""
        config = self.get_config()
        providers = config.get("providers", [])
        
        for i, provider in enumerate(providers):
            if provider.get("name") == name:
                # 保留原有的统计数据等
                provider_data["name"] = name  # 名称不可更改
                providers[i] = provider_data
                config["providers"] = providers
                
                if self.save_config(config):
                    return True, "更新成功"
                return False, "保存配置失败"
        
        return False, f"Provider '{name}' 不存在"
    
    def delete_provider(self, name: str) -> tuple[bool, str]:
        """删除 Provider"""
        config = self.get_config()
        providers = config.get("providers", [])
        
        new_providers = [p for p in providers if p.get("name") != name]
        
        if len(new_providers) == len(providers):
            return False, f"Provider '{name}' 不存在"
        
        config["providers"] = new_providers
        
        if self.save_config(config):
            return True, "删除成功"
        return False, "保存配置失败"
    
    # ==================== 模型映射管理 ====================
    
    def get_model_map(self) -> dict:
        """获取模型映射配置"""
        config = self.get_config()
        return config.get("model_map", {})
    
    def update_model_map(self, model_map: dict) -> tuple[bool, str]:
        """更新整个模型映射"""
        config = self.get_config()
        config["model_map"] = model_map
        
        if self.save_config(config):
            return True, "更新成功"
        return False, "保存配置失败"
    
    def add_model_mapping(self, unified_name: str, actual_models: list[str]) -> tuple[bool, str]:
        """添加单个模型映射"""
        config = self.get_config()
        model_map = config.get("model_map", {})
        
        if unified_name in model_map:
            return False, f"映射 '{unified_name}' 已存在"
        
        model_map[unified_name] = actual_models
        config["model_map"] = model_map
        
        if self.save_config(config):
            return True, "添加成功"
        return False, "保存配置失败"
    
    def update_model_mapping(self, unified_name: str, actual_models: list[str]) -> tuple[bool, str]:
        """更新单个模型映射"""
        config = self.get_config()
        model_map = config.get("model_map", {})
        
        model_map[unified_name] = actual_models
        config["model_map"] = model_map
        
        if self.save_config(config):
            return True, "更新成功"
        return False, "保存配置失败"
    
    def delete_model_mapping(self, unified_name: str) -> tuple[bool, str]:
        """删除模型映射"""
        config = self.get_config()
        model_map = config.get("model_map", {})
        
        if unified_name not in model_map:
            return False, f"映射 '{unified_name}' 不存在"
        
        del model_map[unified_name]
        config["model_map"] = model_map
        
        if self.save_config(config):
            return True, "删除成功"
        return False, "保存配置失败"
    
    # ==================== 获取远程模型列表 ====================
    
    async def fetch_provider_models(self, provider_name: str) -> tuple[bool, list[dict], str]:
        """
        从中转站获取可用模型列表
        
        仅提取 id 和 owned_by 字段。
        """
        provider = self.get_provider(provider_name)
        if not provider:
            return False, [], "Provider 不存在"
        
        base_url = provider.get("base_url", "").rstrip("/")
        api_key = provider.get("api_key", "")
        
        try:
            async with httpx.AsyncClient(timeout=ADMIN_HTTP_TIMEOUT) as client:
                response = await client.get(
                    f"{base_url}/models",
                    headers={"Authorization": f"Bearer {api_key}"}
                )
                
                if response.status_code == 200:
                    data = response.json()
                    models = []
                    # OpenAI 格式: {"data": [{"id": "model-name"}, ...]}
                    if "data" in data:
                        for m in data["data"]:
                            if m.get("id"):
                                models.append({
                                    "id": m.get("id"),
                                    "owned_by": m.get("owned_by", "")
                                })
                    # 按 id 排序
                    models.sort(key=lambda x: x["id"])
                    return True, models, ""
                else:
                    return False, [], f"HTTP {response.status_code}"
        except Exception as e:
            return False, [], str(e)
    
    async def fetch_all_provider_models(self) -> dict[str, list[dict]]:
        """获取所有中转站的模型列表"""
        result = {}
        providers = self.list_providers()
        
        for provider in providers:
            name = provider.get("name", "")
            success, models, _ = await self.fetch_provider_models(name)
            if success:
                result[name] = models
        
        return result
    
    def filter_models_by_keyword(self, models: list[str], keyword: str) -> list[str]:
        """根据关键字筛选模型"""
        if not keyword:
            return models
        keyword = keyword.lower()
        return [m for m in models if keyword in m.lower()]
    
    # ==================== 可用性测试 ====================
    
    async def test_provider(self, provider_name: str, model: Optional[str] = None,
                            skip_recent: bool = False) -> list[ProviderTestResult]:
        """
        测试 Provider 可用性
        
        Args:
            provider_name: Provider 名称
            model: 指定测试的模型（可选，不指定则测试所有模型）
            skip_recent: 是否跳过近期有活动的模型
            
        Returns:
            测试结果列表
        """
        provider = self.get_provider(provider_name)
        if not provider:
            return [ProviderTestResult(
                provider_name=provider_name,
                model="",
                success=False,
                error="Provider 不存在",
                tested_at=time.time()
            )]
        
        models_to_test = [model] if model else provider.get("supported_models", [])
        results = []
        
        async with httpx.AsyncClient(timeout=ADMIN_HTTP_TIMEOUT) as client:
            for test_model in models_to_test:
                # 检查是否跳过近期活跃的模型
                if skip_recent and self._provider_manager:
                    if self._provider_manager.is_model_recently_active(
                        provider_name, test_model, HEALTH_CHECK_SKIP_THRESHOLD_HOURS
                    ):
                        # 跳过近期有活动的模型，使用缓存的测试结果
                        key = f"{provider_name}:{test_model}"
                        if key in self._test_results:
                            results.append(self._test_results[key])
                        continue
                
                result = await self._test_single_model(client, provider, test_model)
                results.append(result)
                
                # 保存测试结果
                key = f"{provider_name}:{test_model}"
                self._test_results[key] = result
                
                # 统一更新 ProviderManager 的健康状态
                if self._provider_manager:
                    self._provider_manager.update_model_health_from_test(
                        provider_name, test_model, result.success, result.error
                    )
        
        return results
    
    async def test_all_providers(self, skip_recent: bool = False) -> list[ProviderTestResult]:
        """
        测试所有 Provider
        
        Args:
            skip_recent: 是否跳过近期有活动的模型（用于自动健康检测）
            
        Returns:
            测试结果列表
        """
        async with self._test_lock:
            providers = self.list_providers()
            all_results = []
            
            for provider in providers:
                results = await self.test_provider(
                    provider.get("name", ""),
                    skip_recent=skip_recent
                )
                all_results.extend(results)
            
            return all_results
    
    async def _test_single_model(self, client: httpx.AsyncClient, 
                                  provider: dict, model: str) -> ProviderTestResult:
        """测试单个模型"""
        provider_name = provider.get("name", "")
        base_url = provider.get("base_url", "").rstrip("/")
        api_key = provider.get("api_key", "")
        
        start_time = time.time()
        
        try:
            # 发送简单的测试请求
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
            
            if response.status_code == 200:
                return ProviderTestResult(
                    provider_name=provider_name,
                    model=model,
                    success=True,
                    latency_ms=latency_ms,
                    tested_at=time.time()
                )
            else:
                error_body = response.text[:200]
                return ProviderTestResult(
                    provider_name=provider_name,
                    model=model,
                    success=False,
                    latency_ms=latency_ms,
                    error=f"HTTP {response.status_code}: {error_body}",
                    tested_at=time.time()
                )
                
        except httpx.TimeoutException:
            latency_ms = (time.time() - start_time) * 1000
            return ProviderTestResult(
                provider_name=provider_name,
                model=model,
                success=False,
                latency_ms=latency_ms,
                error="请求超时",
                tested_at=time.time()
            )
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            return ProviderTestResult(
                provider_name=provider_name,
                model=model,
                success=False,
                latency_ms=latency_ms,
                error=str(e),
                tested_at=time.time()
            )
    
    def get_test_results(self) -> dict[str, dict]:
        """获取所有测试结果"""
        return {k: v.to_dict() for k, v in self._test_results.items()}
    
    def clear_test_results(self) -> None:
        """清除测试结果"""
        self._test_results.clear()


# 全局实例
admin_manager = AdminManager()
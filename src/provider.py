"""
Provider 管理和熔断逻辑模块

负责管理 Provider 状态、实现双层熔断器模式（渠道级 + 模型级）

注意：内部使用 provider_id (UUID) 作为标识，而非 provider name
"""

import time
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING
from .config import ProviderConfig

if TYPE_CHECKING:
    from .logger import LogManager
from .constants import (
    HEALTH_CHECK_SKIP_THRESHOLD_HOURS,
    HEALTH_TEST_FAILURE_COOLDOWN_SECONDS,
    COOLDOWN_RATE_LIMITED,
    COOLDOWN_SERVER_ERROR,
    COOLDOWN_TIMEOUT,
    COOLDOWN_NETWORK_ERROR,
    COOLDOWN_PERMANENT,
)


class ProviderStatus(Enum):
    """Provider 状态枚举"""
    HEALTHY = "healthy"           # 健康可用
    COOLING = "cooling"           # 冷却中（临时不可用）
    PERMANENTLY_DISABLED = "permanently_disabled"  # 永久禁用


class ModelStatus(Enum):
    """模型状态枚举"""
    HEALTHY = "healthy"           # 健康可用
    COOLING = "cooling"           # 冷却中（临时不可用）
    PERMANENTLY_DISABLED = "permanently_disabled"  # 永久禁用


class CooldownReason(Enum):
    """冷却原因"""
    RATE_LIMITED = "rate_limited"       # 429 超频 -> 模型级
    SERVER_ERROR = "server_error"       # 5xx 服务器错误 -> 模型级
    TIMEOUT = "timeout"                 # 超时 -> 渠道级
    AUTH_FAILED = "auth_failed"         # 401/403 鉴权失败（永久）-> 渠道级
    NETWORK_ERROR = "network_error"     # 网络错误 -> 渠道级
    MODEL_NOT_FOUND = "model_not_found" # 404 模型不存在 -> 模型级
    HEALTH_CHECK_FAILED = "health_check_failed"  # 健康检测失败 -> 模型级


# 冷却时间配置（秒）- 使用统一常量
COOLDOWN_TIMES = {
    CooldownReason.RATE_LIMITED: COOLDOWN_RATE_LIMITED,           # 429: 超频
    CooldownReason.SERVER_ERROR: COOLDOWN_SERVER_ERROR,           # 5xx: 服务器错误
    CooldownReason.TIMEOUT: COOLDOWN_TIMEOUT,                     # 超时
    CooldownReason.AUTH_FAILED: COOLDOWN_PERMANENT,               # 永久禁用
    CooldownReason.NETWORK_ERROR: COOLDOWN_NETWORK_ERROR,         # 网络错误
    CooldownReason.MODEL_NOT_FOUND: COOLDOWN_PERMANENT,           # 模型不存在: 永久禁用（该模型）
    CooldownReason.HEALTH_CHECK_FAILED: HEALTH_TEST_FAILURE_COOLDOWN_SECONDS,  # 健康检测失败
}


# 渠道级错误（影响整个 Provider）
PROVIDER_LEVEL_ERRORS = {
    CooldownReason.AUTH_FAILED,
    CooldownReason.TIMEOUT,
    CooldownReason.NETWORK_ERROR,
}

# 模型级错误（仅影响特定模型）
MODEL_LEVEL_ERRORS = {
    CooldownReason.RATE_LIMITED,
    CooldownReason.SERVER_ERROR,
    CooldownReason.MODEL_NOT_FOUND,
    CooldownReason.HEALTH_CHECK_FAILED,
}


@dataclass
class ModelState:
    """模型运行时状态（针对特定 Provider + Model 组合）"""
    provider_id: str  # Provider 的唯一 ID (UUID)
    model_name: str
    status: ModelStatus = ModelStatus.HEALTHY
    cooldown_until: float = 0.0
    cooldown_reason: Optional[CooldownReason] = None
    
    # 统计数据
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_tokens: int = 0
    last_error: Optional[str] = None
    last_error_time: Optional[float] = None
    
    # 最后活动时间（用于健康检测跳过判断）
    last_activity_time: Optional[float] = None
    
    @property
    def is_available(self) -> bool:
        """检查模型是否可用"""
        if self.status == ModelStatus.PERMANENTLY_DISABLED:
            return False
        if self.status == ModelStatus.COOLING:
            if time.time() >= self.cooldown_until:
                # 冷却时间已过，恢复健康状态
                self.status = ModelStatus.HEALTHY
                self.cooldown_reason = None
                return True
            return False
        return True
    
    @property
    def success_rate(self) -> float:
        """计算成功率"""
        if self.total_requests == 0:
            return 1.0
        return self.successful_requests / self.total_requests


@dataclass
class ProviderState:
    """Provider 运行时状态"""
    config: ProviderConfig
    status: ProviderStatus = ProviderStatus.HEALTHY
    cooldown_until: float = 0.0
    cooldown_reason: Optional[CooldownReason] = None
    
    # 错误信息（用于展示最后一次错误）
    last_error: Optional[str] = None
    last_error_time: Optional[float] = None
    
    @property
    def is_available(self) -> bool:
        """检查 Provider 是否可用（渠道级）"""
        # 检查是否被手动禁用
        if not self.config.enabled:
            return False
        if self.status == ProviderStatus.PERMANENTLY_DISABLED:
            return False
        if self.status == ProviderStatus.COOLING:
            if time.time() >= self.cooldown_until:
                # 冷却时间已过，恢复健康状态
                self.status = ProviderStatus.HEALTHY
                self.cooldown_reason = None
                return True
            return False
        return True


class ProviderManager:
    """
    Provider 管理器
    
    支持双层熔断机制：
    - 渠道级熔断：影响整个 Provider（如鉴权失败、网络错误）
    - 模型级熔断：仅影响特定 Provider + Model 组合（如超频、服务错误）
    
    注意：内部使用 provider_id (UUID) 作为标识
    """
    
    def __init__(self):
        # key = provider_id
        self._providers: dict[str, ProviderState] = {}
        # 模型状态：key = "provider_id:model_name"
        self._model_states: dict[str, ModelState] = {}
        # 日志管理器引用（延迟获取，避免循环导入）
        self._log_manager: Optional["LogManager"] = None
    
    def _get_log_manager(self) -> "LogManager":
        """延迟获取日志管理器（避免循环导入）"""
        if self._log_manager is None:
            from .logger import log_manager
            self._log_manager = log_manager
        return self._log_manager
    
    def _get_model_key(self, provider_id: str, model_name: str) -> str:
        """生成模型状态的唯一键（provider_id:model_name）"""
        return f"{provider_id}:{model_name}"
    
    def register(self, config: ProviderConfig) -> None:
        """注册一个 Provider（使用 id 作为 key）"""
        self._providers[config.id] = ProviderState(config=config)
        # self._log_info(f"已注册 Provider: {config.name} (ID: {config.id})")
    
    def register_all(self, configs: list[ProviderConfig]) -> None:
        """批量注册 Provider"""
        for config in configs:
            self.register(config)
    
    def get(self, provider_id: str) -> Optional[ProviderState]:
        """通过 ID 获取指定 Provider 的状态"""
        return self._providers.get(provider_id)
    
    def get_by_name(self, name: str) -> Optional[ProviderState]:
        """通过名称获取 Provider 状态（兼容性方法）"""
        for provider in self._providers.values():
            if provider.config.name == name:
                return provider
        return None
    
    def get_model_state(self, provider_id: str, model_name: str) -> ModelState:
        """
        获取指定 Provider + Model 组合的状态
        如果不存在则创建新的健康状态
        """
        key = self._get_model_key(provider_id, model_name)
        if key not in self._model_states:
            self._model_states[key] = ModelState(
                provider_id=provider_id,
                model_name=model_name
            )
        return self._model_states[key]
    
    def get_all(self) -> list[ProviderState]:
        """获取所有 Provider 状态"""
        return list(self._providers.values())
    
    def get_available(self) -> list[ProviderState]:
        """获取所有渠道级可用的 Provider"""
        return [p for p in self._providers.values() if p.is_available]
    
    def is_model_available(self, provider_id: str, model_name: str) -> bool:
        """
        检查特定 Provider + Model 组合是否可用
        
        需要满足两个条件：
        1. Provider 渠道级可用
        2. 该 Provider 下的该模型可用
        """
        provider = self._providers.get(provider_id)
        if not provider or not provider.is_available:
            return False
        
        model_state = self.get_model_state(provider_id, model_name)
        return model_state.is_available
    
    def get_model_last_activity_time(self, provider_id: str, model_name: str) -> Optional[float]:
        """
        获取模型的最后活动时间
        
        Args:
            provider_id: Provider 的唯一 ID
            model_name: 模型名称
            
        Returns:
            最后活动时间戳，如果从未有活动则返回 None
        """
        key = self._get_model_key(provider_id, model_name)
        if key in self._model_states:
            return self._model_states[key].last_activity_time
        return None
    
    def is_model_recently_active(self, provider_id: str, model_name: str,
                                  threshold_hours: float = HEALTH_CHECK_SKIP_THRESHOLD_HOURS) -> bool:
        """
        检查模型是否在近期有活动
        
        Args:
            provider_id: Provider 的唯一 ID
            model_name: 模型名称
            threshold_hours: 活动阈值（小时），默认使用 HEALTH_CHECK_SKIP_THRESHOLD_HOURS
            
        Returns:
            如果在阈值时间内有活动返回 True，否则返回 False
        """
        last_activity = self.get_model_last_activity_time(provider_id, model_name)
        if last_activity is None:
            return False
        
        threshold_seconds = threshold_hours * 3600
        return (time.time() - last_activity) < threshold_seconds
    
    def update_model_health_from_test(self, provider_name: str, model_name: str,
                                       success: bool, error_message: Optional[str] = None) -> None:
        """
        根据健康测试结果更新模型状态（统一健康标记）
        
        Args:
            provider_name: Provider 的 ID（参数名保留兼容但含义为 ID）
            model_name: 模型名称
            success: 测试是否成功
            error_message: 错误消息（如果失败）
        """
        provider_id = provider_name  # 实际上是 provider_id
        model_state = self.get_model_state(provider_id, model_name)
        model_state.last_activity_time = time.time()
        
        if success:
            # 测试成功，如果当前是冷却状态，恢复为健康
            if model_state.status == ModelStatus.COOLING:
                model_state.status = ModelStatus.HEALTHY
                model_state.cooldown_until = 0.0
                model_state.cooldown_reason = None
                self._log_info(f"模型 [{provider_id}:{model_name}] 健康检测通过，已恢复为健康状态")
        else:
            # 测试失败，记录错误并触发模型级熔断
            model_state.last_error = error_message
            model_state.last_error_time = time.time()
            # 触发模型级熔断
            self._apply_model_cooldown(model_state, CooldownReason.HEALTH_CHECK_FAILED)
    
    def mark_success(self, provider_id: str, model_name: Optional[str] = None, tokens: int = 0) -> None:
        """
        标记请求成功
        
        Args:
            provider_id: Provider 的唯一 ID
            model_name: 模型名称（可选，用于更新模型级统计）
            tokens: 本次请求消耗的 token 数
        
        注意：Provider 级别的统计数据现在从日志系统持久化获取，
        此方法仅更新模型级统计。
        """
        # 更新模型级统计
        if model_name:
            model_state = self.get_model_state(provider_id, model_name)
            model_state.total_requests += 1
            model_state.successful_requests += 1
            model_state.total_tokens += tokens
            model_state.last_activity_time = time.time()  # 记录最后活动时间
    
    def mark_failure(
        self,
        provider_id: str,
        model_name: Optional[str] = None,
        status_code: Optional[int] = None,
        error_message: Optional[str] = None
    ) -> None:
        """
        标记请求失败并根据错误类型设置冷却（双层熔断）
        
        Args:
            provider_id: Provider 的唯一 ID
            model_name: 模型名称（用于模型级熔断）
            status_code: HTTP 状态码
            error_message: 错误消息
        
        注意：Provider 级别的统计数据现在从日志系统持久化获取，
        此方法仅更新错误信息和模型级统计。
        """
        provider = self._providers.get(provider_id)
        if not provider:
            return
        
        # 更新 Provider 级错误信息（用于展示）
        provider.last_error = error_message
        provider.last_error_time = time.time()
        
        # 更新模型级统计
        model_state = None
        if model_name:
            model_state = self.get_model_state(provider_id, model_name)
            model_state.total_requests += 1
            model_state.failed_requests += 1
            model_state.last_error = error_message
            model_state.last_error_time = time.time()
            model_state.last_activity_time = time.time()  # 记录最后活动时间（失败也算活动）
        
        # 根据状态码决定冷却策略和级别
        reason = self._determine_cooldown_reason(status_code, error_message)
        
        if reason in PROVIDER_LEVEL_ERRORS:
            # 渠道级熔断
            self._apply_provider_cooldown(provider, reason)
        elif reason in MODEL_LEVEL_ERRORS and model_state:
            # 模型级熔断
            self._apply_model_cooldown(model_state, reason)
        elif model_state:
            # 未知错误类型，默认使用模型级熔断
            self._apply_model_cooldown(model_state, CooldownReason.SERVER_ERROR)
        else:
            # 没有模型信息时，fallback 到渠道级
            self._apply_provider_cooldown(provider, reason)
    
    def _determine_cooldown_reason(
        self,
        status_code: Optional[int],
        error_message: Optional[str]
    ) -> CooldownReason:
        """根据状态码和错误消息确定冷却原因"""
        if status_code in (401, 403):
            return CooldownReason.AUTH_FAILED
        elif status_code == 404:
            return CooldownReason.MODEL_NOT_FOUND
        elif status_code == 429:
            return CooldownReason.RATE_LIMITED
        elif status_code and 500 <= status_code < 600:
            return CooldownReason.SERVER_ERROR
        elif error_message:
            lower_msg = error_message.lower()
            if "timeout" in lower_msg:
                return CooldownReason.TIMEOUT
            elif "network" in lower_msg or "connection" in lower_msg:
                return CooldownReason.NETWORK_ERROR
        return CooldownReason.SERVER_ERROR
    
    def _apply_provider_cooldown(self, provider: ProviderState, reason: CooldownReason) -> None:
        """应用渠道级冷却"""
        from .logger import LogLevel  # 避免循环导入
        
        cooldown_seconds = COOLDOWN_TIMES[reason]
        
        if cooldown_seconds < 0:
            # 永久禁用
            provider.status = ProviderStatus.PERMANENTLY_DISABLED
            provider.cooldown_reason = reason
            message = f"Provider [{provider.config.name}] 已被永久禁用，原因: {reason.value}"
            self._log_error(message)
            # 记录熔断状态变更日志（不包含详细错误，错误已在 proxy.py 中记录）
            log_manager = self._get_log_manager()
            log_manager.log(
                level=LogLevel.WARNING,
                log_type="circuit_breaker",
                method="BREAKER",
                path="/provider",
                provider=provider.config.name,
                message=message
            )
        else:
            provider.status = ProviderStatus.COOLING
            provider.cooldown_until = time.time() + cooldown_seconds
            provider.cooldown_reason = reason
            message = f"[{provider.config.name}] 进入冷却状态（渠道级），冷却 {cooldown_seconds} 秒，原因: {reason.value}"
            self._log_warning(message)
            # 记录熔断状态变更日志（不包含详细错误，错误已在 proxy.py 中记录）
            log_manager = self._get_log_manager()
            log_manager.log(
                level=LogLevel.WARNING,
                log_type="circuit_breaker",
                method="BREAKER",
                path="/provider",
                provider=provider.config.name,
                message=message
            )
    
    def _apply_model_cooldown(self, model_state: ModelState, reason: CooldownReason) -> None:
        """应用模型级冷却"""
        from .logger import LogLevel  # 避免循环导入
        
        cooldown_seconds = COOLDOWN_TIMES[reason]
        
        # 获取 Provider 名称
        provider = self._providers.get(model_state.provider_id)
        provider_name = provider.config.name if provider else model_state.provider_id
        
        if cooldown_seconds < 0:
            # 永久禁用该模型
            model_state.status = ModelStatus.PERMANENTLY_DISABLED
            model_state.cooldown_reason = reason
            message = f"模型 [{provider_name}:{model_state.model_name}] 已被永久禁用，原因: {reason.value}"
            self._log_error(message)
            # 记录熔断状态变更日志（不包含详细错误，错误已在 proxy.py 中记录）
            log_manager = self._get_log_manager()
            log_manager.log(
                level=LogLevel.WARNING,
                log_type="circuit_breaker",
                method="BREAKER",
                path="/model",
                provider=provider_name,
                actual_model=model_state.model_name,
                message=message
            )
        else:
            model_state.status = ModelStatus.COOLING
            model_state.cooldown_until = time.time() + cooldown_seconds
            model_state.cooldown_reason = reason
            message = f"[{provider_name}:{model_state.model_name}] 进入冷却状态（模型级），冷却 {cooldown_seconds} 秒，原因: {reason.value}"
            self._log_warning(message)
            # 记录熔断状态变更日志（不包含详细错误，错误已在 proxy.py 中记录）
            log_manager = self._get_log_manager()
            log_manager.log(
                level=LogLevel.WARNING,
                log_type="circuit_breaker",
                method="BREAKER",
                path="/model",
                provider=provider_name,
                actual_model=model_state.model_name,
                message=message
            )
    
    def reset(self, provider_id: str) -> bool:
        """重置指定 Provider 的状态（包括其下所有模型）"""
        provider = self._providers.get(provider_id)
        if provider:
            # 重置渠道级状态
            provider.status = ProviderStatus.HEALTHY
            provider.cooldown_until = 0.0
            provider.cooldown_reason = None
            
            # 重置该 Provider 下所有模型状态
            for key, model_state in self._model_states.items():
                if model_state.provider_id == provider_id:
                    model_state.status = ModelStatus.HEALTHY
                    model_state.cooldown_until = 0.0
                    model_state.cooldown_reason = None
            
            self._log_info(f"Provider [{provider_id}] 已重置为健康状态（包括所有模型）")
            return True
        return False
    
    def reset_model(self, provider_id: str, model_name: str) -> bool:
        """重置指定模型的状态"""
        key = self._get_model_key(provider_id, model_name)
        if key in self._model_states:
            model_state = self._model_states[key]
            model_state.status = ModelStatus.HEALTHY
            model_state.cooldown_until = 0.0
            model_state.cooldown_reason = None
            self._log_info(f"模型 [{provider_id}:{model_name}] 已重置为健康状态")
            return True
        return False
    
    def reset_all(self) -> None:
        """重置所有 Provider 和模型的状态"""
        for name in self._providers:
            self.reset(name)
    
    def get_stats(self, tag: Optional[str] = None) -> dict:
        """获取统计信息（包括渠道级和模型级）
        
        Args:
            tag: 标签过滤（API Key Name）
        """
        log_manager = self._get_log_manager()
        log_stats = log_manager.get_stats(tag=tag)
        
        persisted_provider_stats = log_stats.get("provider_stats", {})
        # 兼容旧格式
        if not persisted_provider_stats and "provider_usage" in log_stats:
             persisted_provider_stats = {
                p: {"total": c, "successful": c, "failed": 0}
                for p, c in log_stats["provider_usage"].items()
            }
            
        persisted_model_stats = log_stats.get("provider_model_stats", {})
        
        stats = {
            "total_providers": len(self._providers),
            "available_providers": len(self.get_available()),
            "providers": {},
            "models": {}
        }
        
        # 处理 Provider 统计
        for provider_id, provider in self._providers.items():
            provider_name = provider.config.name
            p_stats = persisted_provider_stats.get(provider_name, {})
            
            total = p_stats.get("total", 0)
            successful = p_stats.get("successful", 0)
            failed = p_stats.get("failed", 0)
            success_rate = 1.0 if total == 0 else successful / total
            
            stats["providers"][provider_id] = {
                "name": provider_name,
                "status": provider.status.value,
                "enabled": provider.config.enabled,
                "total_requests": total,
                "successful_requests": successful,
                "failed_requests": failed,
                "success_rate": f"{success_rate:.1%}",
                "last_error": provider.last_error,
                "cooldown_reason": provider.cooldown_reason.value if provider.cooldown_reason else None,
            }
            
            if provider.status == ProviderStatus.COOLING:
                remaining = max(0, provider.cooldown_until - time.time())
                stats["providers"][provider_id]["cooldown_remaining"] = f"{remaining:.0f}s"
        
        # 处理模型级统计
        all_model_keys = set(self._model_states.keys())
        for provider_name, models in persisted_model_stats.items():
             provider = self.get_by_name(provider_name)
             if provider:
                 for model_name in models:
                     all_model_keys.add(self._get_model_key(provider.config.id, model_name))

        for key in all_model_keys:
            parts = key.split(":", 1)
            if len(parts) != 2: continue
            provider_id, model_name = parts
            
            provider = self._providers.get(provider_id)
            if not provider: continue
            
            model_state = self._model_states.get(key)
            pm_stats = persisted_model_stats.get(provider.config.name, {}).get(model_name, {})
            
            total = pm_stats.get("total", 0)
            successful = pm_stats.get("successful", 0)
            failed = pm_stats.get("failed", 0)
            tokens = pm_stats.get("tokens", 0)
            
            # 如果没有 tag 过滤，且内存数据更新，则使用内存数据
            if not tag and model_state and model_state.total_requests > total:
                total = model_state.total_requests
                successful = model_state.successful_requests
                failed = model_state.failed_requests
                tokens = model_state.total_tokens

            # 仅显示有数据或状态异常的模型（tag 模式下仅显示有数据的）
            if total > 0 or (model_state and model_state.status != ModelStatus.HEALTHY) or not tag:
                success_rate = 1.0 if total == 0 else successful / total
                
                model_data = {
                    "status": ModelStatus.HEALTHY.value,
                    "total_requests": total,
                    "successful_requests": successful,
                    "failed_requests": failed,
                    "total_tokens": tokens,
                    "success_rate": f"{success_rate:.1%}",
                    "last_error": None,
                    "cooldown_reason": None,
                }
                
                if model_state:
                    model_data.update({
                        "status": model_state.status.value,
                        "last_error": model_state.last_error,
                        "cooldown_reason": model_state.cooldown_reason.value if model_state.cooldown_reason else None
                    })
                    if model_state.status == ModelStatus.COOLING:
                        model_data["cooldown_remaining"] = f"{max(0, model_state.cooldown_until - time.time()):.0f}s"
                
                stats["models"][key] = model_data
        
        return stats
    
    def get_runtime_states(self) -> dict:
        """
        获取轻量级运行时状态（仅内存数据，无日志读取）
        
        用于前端展示模型熔断状态，避免读取日志的性能开销。
        
        Returns:
            {
                "providers": {
                    provider_id: {
                        "name": str,
                        "status": str,  # healthy, cooling, permanently_disabled
                        "cooldown_until": float | None,
                        "cooldown_reason": str | None,
                        "cooldown_remaining": float | None,
                        "last_error": str | None,
                        "last_error_time": float | None
                    }
                },
                "models": {
                    "provider_id:model_name": {
                        "status": str,  # healthy, cooling, permanently_disabled
                        "cooldown_until": float | None,
                        "cooldown_reason": str | None,
                        "cooldown_remaining": float | None,
                        "last_error": str | None,
                        "last_error_time": float | None
                    }
                }
            }
        """
        current_time = time.time()
        result = {
            "providers": {},
            "models": {}
        }
        
        # 收集 Provider 级运行时状态
        for provider_id, provider in self._providers.items():
            # 检查并更新冷却状态（触发 is_available 的副作用）
            _ = provider.is_available
            
            provider_state = {
                "name": provider.config.name,
                "status": provider.status.value,
                "cooldown_until": None,
                "cooldown_reason": None,
                "cooldown_remaining": None,
                "last_error": provider.last_error,
                "last_error_time": provider.last_error_time
            }
            
            if provider.status == ProviderStatus.COOLING:
                provider_state["cooldown_until"] = provider.cooldown_until
                provider_state["cooldown_reason"] = provider.cooldown_reason.value if provider.cooldown_reason else None
                provider_state["cooldown_remaining"] = max(0, provider.cooldown_until - current_time)
            elif provider.status == ProviderStatus.PERMANENTLY_DISABLED:
                provider_state["cooldown_reason"] = provider.cooldown_reason.value if provider.cooldown_reason else None
            
            result["providers"][provider_id] = provider_state
        
        # 收集模型级运行时状态
        for key, model_state in self._model_states.items():
            # 检查并更新冷却状态（触发 is_available 的副作用）
            _ = model_state.is_available
            
            model_info = {
                "status": model_state.status.value,
                "cooldown_until": None,
                "cooldown_reason": None,
                "cooldown_remaining": None,
                "last_error": model_state.last_error,
                "last_error_time": model_state.last_error_time,
                "last_activity_time": model_state.last_activity_time,
                "successful_requests": model_state.successful_requests,
                "failed_requests": model_state.failed_requests
            }
            
            if model_state.status == ModelStatus.COOLING:
                model_info["cooldown_until"] = model_state.cooldown_until
                model_info["cooldown_reason"] = model_state.cooldown_reason.value if model_state.cooldown_reason else None
                model_info["cooldown_remaining"] = max(0, model_state.cooldown_until - current_time)
            elif model_state.status == ModelStatus.PERMANENTLY_DISABLED:
                model_info["cooldown_reason"] = model_state.cooldown_reason.value if model_state.cooldown_reason else None
            
            result["models"][key] = model_info
        
        return result
    
    @staticmethod
    def _log_info(message: str) -> None:
        """输出信息日志"""
        print(f"[INFO] {message}")
    
    @staticmethod
    def _log_warning(message: str) -> None:
        """输出警告日志"""
        print(f"[WARN] {message}")
    
    @staticmethod
    def _log_error(message: str) -> None:
        """输出错误日志"""
        print(f"[ERROR] {message}")


# 全局 Provider 管理器实例
provider_manager = ProviderManager()
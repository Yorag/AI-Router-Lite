"""
Provider 管理和熔断逻辑模块

负责管理 Provider 状态、实现双层熔断器模式（渠道级 + 模型级）
"""

import time
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional
from colorama import Fore, Style

from .config import ProviderConfig
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
    provider_name: str
    model_name: str
    status: ModelStatus = ModelStatus.HEALTHY
    cooldown_until: float = 0.0
    cooldown_reason: Optional[CooldownReason] = None
    
    # 统计数据
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
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
    
    # 统计数据
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    last_error: Optional[str] = None
    last_error_time: Optional[float] = None
    
    @property
    def is_available(self) -> bool:
        """检查 Provider 是否可用（渠道级）"""
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
    
    @property
    def success_rate(self) -> float:
        """计算成功率"""
        if self.total_requests == 0:
            return 1.0
        return self.successful_requests / self.total_requests


class ProviderManager:
    """
    Provider 管理器
    
    支持双层熔断机制：
    - 渠道级熔断：影响整个 Provider（如鉴权失败、网络错误）
    - 模型级熔断：仅影响特定 Provider + Model 组合（如超频、服务错误）
    """
    
    def __init__(self):
        self._providers: dict[str, ProviderState] = {}
        # 模型状态：key = "provider_name:model_name"
        self._model_states: dict[str, ModelState] = {}
    
    def _get_model_key(self, provider_name: str, model_name: str) -> str:
        """生成模型状态的唯一键"""
        return f"{provider_name}:{model_name}"
    
    def register(self, config: ProviderConfig) -> None:
        """注册一个 Provider"""
        self._providers[config.name] = ProviderState(config=config)
        self._log_info(f"已注册 Provider: {config.name}")
    
    def register_all(self, configs: list[ProviderConfig]) -> None:
        """批量注册 Provider"""
        for config in configs:
            self.register(config)
    
    def get(self, name: str) -> Optional[ProviderState]:
        """获取指定 Provider 的状态"""
        return self._providers.get(name)
    
    def get_model_state(self, provider_name: str, model_name: str) -> ModelState:
        """
        获取指定 Provider + Model 组合的状态
        如果不存在则创建新的健康状态
        """
        key = self._get_model_key(provider_name, model_name)
        if key not in self._model_states:
            self._model_states[key] = ModelState(
                provider_name=provider_name,
                model_name=model_name
            )
        return self._model_states[key]
    
    def get_all(self) -> list[ProviderState]:
        """获取所有 Provider 状态"""
        return list(self._providers.values())
    
    def get_available(self) -> list[ProviderState]:
        """获取所有渠道级可用的 Provider"""
        return [p for p in self._providers.values() if p.is_available]
    
    def is_model_available(self, provider_name: str, model_name: str) -> bool:
        """
        检查特定 Provider + Model 组合是否可用
        
        需要满足两个条件：
        1. Provider 渠道级可用
        2. 该 Provider 下的该模型可用
        """
        provider = self._providers.get(provider_name)
        if not provider or not provider.is_available:
            return False
        
        model_state = self.get_model_state(provider_name, model_name)
        return model_state.is_available
    
    def get_model_last_activity_time(self, provider_name: str, model_name: str) -> Optional[float]:
        """
        获取模型的最后活动时间
        
        Args:
            provider_name: Provider 名称
            model_name: 模型名称
            
        Returns:
            最后活动时间戳，如果从未有活动则返回 None
        """
        key = self._get_model_key(provider_name, model_name)
        if key in self._model_states:
            return self._model_states[key].last_activity_time
        return None
    
    def is_model_recently_active(self, provider_name: str, model_name: str,
                                  threshold_hours: float = HEALTH_CHECK_SKIP_THRESHOLD_HOURS) -> bool:
        """
        检查模型是否在近期有活动
        
        Args:
            provider_name: Provider 名称
            model_name: 模型名称
            threshold_hours: 活动阈值（小时），默认使用 HEALTH_CHECK_SKIP_THRESHOLD_HOURS
            
        Returns:
            如果在阈值时间内有活动返回 True，否则返回 False
        """
        last_activity = self.get_model_last_activity_time(provider_name, model_name)
        if last_activity is None:
            return False
        
        threshold_seconds = threshold_hours * 3600
        return (time.time() - last_activity) < threshold_seconds
    
    def update_model_health_from_test(self, provider_name: str, model_name: str,
                                       success: bool, error_message: Optional[str] = None) -> None:
        """
        根据健康测试结果更新模型状态（统一健康标记）
        
        Args:
            provider_name: Provider 名称
            model_name: 模型名称
            success: 测试是否成功
            error_message: 错误消息（如果失败）
        """
        model_state = self.get_model_state(provider_name, model_name)
        model_state.last_activity_time = time.time()
        
        if success:
            # 测试成功，如果当前是冷却状态，恢复为健康
            if model_state.status == ModelStatus.COOLING:
                model_state.status = ModelStatus.HEALTHY
                model_state.cooldown_until = 0.0
                model_state.cooldown_reason = None
                self._log_info(f"模型 [{provider_name}:{model_name}] 健康检测通过，已恢复为健康状态")
        else:
            # 测试失败，记录错误并触发模型级熔断
            model_state.last_error = error_message
            model_state.last_error_time = time.time()
            # 触发模型级熔断
            self._apply_model_cooldown(model_state, CooldownReason.HEALTH_CHECK_FAILED)
    
    def mark_success(self, name: str, model_name: Optional[str] = None) -> None:
        """
        标记请求成功
        
        Args:
            name: Provider 名称
            model_name: 模型名称（可选，用于更新模型级统计）
        """
        provider = self._providers.get(name)
        if provider:
            provider.total_requests += 1
            provider.successful_requests += 1
        
        # 同时更新模型级统计
        if model_name:
            model_state = self.get_model_state(name, model_name)
            model_state.total_requests += 1
            model_state.successful_requests += 1
            model_state.last_activity_time = time.time()  # 记录最后活动时间
    
    def mark_failure(
        self,
        name: str,
        model_name: Optional[str] = None,
        status_code: Optional[int] = None,
        error_message: Optional[str] = None
    ) -> None:
        """
        标记请求失败并根据错误类型设置冷却（双层熔断）
        
        Args:
            name: Provider 名称
            model_name: 模型名称（用于模型级熔断）
            status_code: HTTP 状态码
            error_message: 错误消息
        """
        provider = self._providers.get(name)
        if not provider:
            return
        
        # 更新 Provider 级统计
        provider.total_requests += 1
        provider.failed_requests += 1
        provider.last_error = error_message
        provider.last_error_time = time.time()
        
        # 更新模型级统计
        model_state = None
        if model_name:
            model_state = self.get_model_state(name, model_name)
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
        cooldown_seconds = COOLDOWN_TIMES[reason]
        
        if cooldown_seconds < 0:
            # 永久禁用
            provider.status = ProviderStatus.PERMANENTLY_DISABLED
            provider.cooldown_reason = reason
            self._log_error(
                f"Provider [{provider.config.name}] 已被永久禁用，"
                f"原因: {reason.value}"
            )
        else:
            provider.status = ProviderStatus.COOLING
            provider.cooldown_until = time.time() + cooldown_seconds
            provider.cooldown_reason = reason
            self._log_warning(
                f"Provider [{provider.config.name}] 进入冷却状态（渠道级），"
                f"原因: {reason.value}，冷却 {cooldown_seconds} 秒"
            )
    
    def _apply_model_cooldown(self, model_state: ModelState, reason: CooldownReason) -> None:
        """应用模型级冷却"""
        cooldown_seconds = COOLDOWN_TIMES[reason]
        
        if cooldown_seconds < 0:
            # 永久禁用该模型
            model_state.status = ModelStatus.PERMANENTLY_DISABLED
            model_state.cooldown_reason = reason
            self._log_error(
                f"模型 [{model_state.provider_name}:{model_state.model_name}] 已被永久禁用，"
                f"原因: {reason.value}"
            )
        else:
            model_state.status = ModelStatus.COOLING
            model_state.cooldown_until = time.time() + cooldown_seconds
            model_state.cooldown_reason = reason
            self._log_warning(
                f"模型 [{model_state.provider_name}:{model_state.model_name}] 进入冷却状态（模型级），"
                f"原因: {reason.value}，冷却 {cooldown_seconds} 秒"
            )
    
    def reset(self, name: str) -> bool:
        """重置指定 Provider 的状态（包括其下所有模型）"""
        provider = self._providers.get(name)
        if provider:
            # 重置渠道级状态
            provider.status = ProviderStatus.HEALTHY
            provider.cooldown_until = 0.0
            provider.cooldown_reason = None
            
            # 重置该 Provider 下所有模型状态
            for key, model_state in self._model_states.items():
                if model_state.provider_name == name:
                    model_state.status = ModelStatus.HEALTHY
                    model_state.cooldown_until = 0.0
                    model_state.cooldown_reason = None
            
            self._log_info(f"Provider [{name}] 已重置为健康状态（包括所有模型）")
            return True
        return False
    
    def reset_model(self, provider_name: str, model_name: str) -> bool:
        """重置指定模型的状态"""
        key = self._get_model_key(provider_name, model_name)
        if key in self._model_states:
            model_state = self._model_states[key]
            model_state.status = ModelStatus.HEALTHY
            model_state.cooldown_until = 0.0
            model_state.cooldown_reason = None
            self._log_info(f"模型 [{provider_name}:{model_name}] 已重置为健康状态")
            return True
        return False
    
    def reset_all(self) -> None:
        """重置所有 Provider 和模型的状态"""
        for name in self._providers:
            self.reset(name)
    
    def get_stats(self) -> dict:
        """获取统计信息（包括渠道级和模型级）"""
        stats = {
            "total_providers": len(self._providers),
            "available_providers": len(self.get_available()),
            "providers": {},
            "models": {}
        }
        
        for name, provider in self._providers.items():
            stats["providers"][name] = {
                "status": provider.status.value,
                "total_requests": provider.total_requests,
                "successful_requests": provider.successful_requests,
                "failed_requests": provider.failed_requests,
                "success_rate": f"{provider.success_rate:.1%}",
                "last_error": provider.last_error,
                "cooldown_reason": provider.cooldown_reason.value if provider.cooldown_reason else None,
            }
            
            if provider.status == ProviderStatus.COOLING:
                remaining = max(0, provider.cooldown_until - time.time())
                stats["providers"][name]["cooldown_remaining"] = f"{remaining:.0f}s"
        
        # 模型级统计
        for key, model_state in self._model_states.items():
            if model_state.total_requests > 0 or model_state.status != ModelStatus.HEALTHY:
                stats["models"][key] = {
                    "status": model_state.status.value,
                    "total_requests": model_state.total_requests,
                    "successful_requests": model_state.successful_requests,
                    "failed_requests": model_state.failed_requests,
                    "success_rate": f"{model_state.success_rate:.1%}",
                    "last_error": model_state.last_error,
                    "cooldown_reason": model_state.cooldown_reason.value if model_state.cooldown_reason else None,
                }
                
                if model_state.status == ModelStatus.COOLING:
                    remaining = max(0, model_state.cooldown_until - time.time())
                    stats["models"][key]["cooldown_remaining"] = f"{remaining:.0f}s"
        
        return stats
    
    @staticmethod
    def _log_info(message: str) -> None:
        """输出信息日志"""
        print(f"{Fore.GREEN}[INFO]{Style.RESET_ALL} {message}")
    
    @staticmethod
    def _log_warning(message: str) -> None:
        """输出警告日志"""
        print(f"{Fore.YELLOW}[WARN]{Style.RESET_ALL} {message}")
    
    @staticmethod
    def _log_error(message: str) -> None:
        """输出错误日志"""
        print(f"{Fore.RED}[ERROR]{Style.RESET_ALL} {message}")


# 全局 Provider 管理器实例
provider_manager = ProviderManager()
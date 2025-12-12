"""
Provider 管理和熔断逻辑模块

负责管理 Provider 状态、实现熔断器模式
"""

import time
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional
from colorama import Fore, Style

from .config import ProviderConfig


class ProviderStatus(Enum):
    """Provider 状态枚举"""
    HEALTHY = "healthy"           # 健康可用
    COOLING = "cooling"           # 冷却中（临时不可用）
    PERMANENTLY_DISABLED = "permanently_disabled"  # 永久禁用


class CooldownReason(Enum):
    """冷却原因"""
    RATE_LIMITED = "rate_limited"       # 429 超频
    SERVER_ERROR = "server_error"       # 5xx 服务器错误
    TIMEOUT = "timeout"                 # 超时
    AUTH_FAILED = "auth_failed"         # 401/403 鉴权失败（永久）


# 冷却时间配置（秒）
COOLDOWN_TIMES = {
    CooldownReason.RATE_LIMITED: 60,    # 429: 60秒
    CooldownReason.SERVER_ERROR: 300,   # 5xx: 300秒
    CooldownReason.TIMEOUT: 120,        # 超时: 120秒
    CooldownReason.AUTH_FAILED: -1,     # 永久禁用
}


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
        """检查 Provider 是否可用"""
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
    """Provider 管理器"""
    
    def __init__(self):
        self._providers: dict[str, ProviderState] = {}
    
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
    
    def get_all(self) -> list[ProviderState]:
        """获取所有 Provider 状态"""
        return list(self._providers.values())
    
    def get_available(self) -> list[ProviderState]:
        """获取所有可用的 Provider"""
        return [p for p in self._providers.values() if p.is_available]
    
    def mark_success(self, name: str) -> None:
        """标记请求成功"""
        provider = self._providers.get(name)
        if provider:
            provider.total_requests += 1
            provider.successful_requests += 1
    
    def mark_failure(
        self,
        name: str,
        status_code: Optional[int] = None,
        error_message: Optional[str] = None
    ) -> None:
        """
        标记请求失败并根据错误类型设置冷却
        
        Args:
            name: Provider 名称
            status_code: HTTP 状态码
            error_message: 错误消息
        """
        provider = self._providers.get(name)
        if not provider:
            return
        
        provider.total_requests += 1
        provider.failed_requests += 1
        provider.last_error = error_message
        provider.last_error_time = time.time()
        
        # 根据状态码决定冷却策略
        if status_code in (401, 403):
            # 鉴权失败：永久禁用
            self._disable_permanently(provider, CooldownReason.AUTH_FAILED)
        elif status_code == 429:
            # 超频：短暂冷却
            self._set_cooldown(provider, CooldownReason.RATE_LIMITED)
        elif status_code and 500 <= status_code < 600:
            # 服务器错误：较长冷却
            self._set_cooldown(provider, CooldownReason.SERVER_ERROR)
        elif error_message and "timeout" in error_message.lower():
            # 超时：中等冷却
            self._set_cooldown(provider, CooldownReason.TIMEOUT)
        else:
            # 其他错误：使用服务器错误的冷却时间
            self._set_cooldown(provider, CooldownReason.SERVER_ERROR)
    
    def _set_cooldown(self, provider: ProviderState, reason: CooldownReason) -> None:
        """设置冷却时间"""
        cooldown_seconds = COOLDOWN_TIMES[reason]
        provider.status = ProviderStatus.COOLING
        provider.cooldown_until = time.time() + cooldown_seconds
        provider.cooldown_reason = reason
        self._log_warning(
            f"Provider [{provider.config.name}] 进入冷却状态，"
            f"原因: {reason.value}，冷却 {cooldown_seconds} 秒"
        )
    
    def _disable_permanently(self, provider: ProviderState, reason: CooldownReason) -> None:
        """永久禁用 Provider"""
        provider.status = ProviderStatus.PERMANENTLY_DISABLED
        provider.cooldown_reason = reason
        self._log_error(
            f"Provider [{provider.config.name}] 已被永久禁用，"
            f"原因: {reason.value}"
        )
    
    def reset(self, name: str) -> bool:
        """重置指定 Provider 的状态"""
        provider = self._providers.get(name)
        if provider:
            provider.status = ProviderStatus.HEALTHY
            provider.cooldown_until = 0.0
            provider.cooldown_reason = None
            self._log_info(f"Provider [{name}] 已重置为健康状态")
            return True
        return False
    
    def reset_all(self) -> None:
        """重置所有 Provider 的状态"""
        for name in self._providers:
            self.reset(name)
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        stats = {
            "total_providers": len(self._providers),
            "available_providers": len(self.get_available()),
            "providers": {}
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
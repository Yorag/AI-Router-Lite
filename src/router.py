"""
路由策略模块

负责根据请求的模型名称选择合适的 Provider
"""

import random
from typing import Optional
from colorama import Fore, Style

from .config import AppConfig
from .provider import ProviderManager, ProviderState
from .model_mapping import model_mapping_manager


class ModelRouter:
    """模型路由器"""
    
    def __init__(self, config: AppConfig, provider_manager: ProviderManager):
        self.config = config
        self.provider_manager = provider_manager
    
    def resolve_model(self, requested_model: str) -> list[str]:
        """
        解析用户请求的模型名，返回实际模型名列表
        
        使用增强型模型映射，如果没有匹配则直接返回原始模型名。
        
        Args:
            requested_model: 用户请求的模型名（可能是映射名）
            
        Returns:
            实际模型名列表
        """
        # 从增强型模型映射获取
        resolved = model_mapping_manager.get_resolved_models_for_unified(requested_model)
        if resolved:
            return resolved
        
        # 否则直接返回原始模型名
        return [requested_model]
    
    def find_providers(
        self,
        requested_model: str,
        exclude: Optional[set[str]] = None
    ) -> list[tuple[ProviderState, str]]:
        """
        查找支持指定模型的可用 Provider 列表（双层熔断检查）
        
        Args:
            requested_model: 用户请求的模型名
            exclude: 要排除的 Provider 名称集合
            
        Returns:
            列表：[(Provider 状态, 实际模型名), ...]
            按权重排序（高权重优先）
            
        Note:
            此方法会同时检查：
            1. Provider 渠道级是否可用
            2. Provider + Model 组合是否可用（模型级熔断）
        """
        exclude = exclude or set()
        actual_models = self.resolve_model(requested_model)
        candidates: list[tuple[ProviderState, str, int]] = []
        
        # 遍历所有渠道级可用的 Provider
        for provider in self.provider_manager.get_available():
            # 跳过被排除的 Provider
            if provider.config.name in exclude:
                continue
            
            # 检查 Provider 支持的模型
            for actual_model in actual_models:
                if actual_model in provider.config.supported_models:
                    # 双层检查：还需检查该 Provider + Model 组合是否可用
                    if self.provider_manager.is_model_available(provider.config.name, actual_model):
                        candidates.append((provider, actual_model, provider.config.weight))
                        break  # 每个 Provider 只加入一次
        
        # 按权重降序排序
        candidates.sort(key=lambda x: x[2], reverse=True)
        
        return [(p, m) for p, m, _ in candidates]
    
    def select_provider(
        self,
        requested_model: str,
        exclude: Optional[set[str]] = None,
        strategy: str = "weighted"
    ) -> Optional[tuple[ProviderState, str]]:
        """
        选择一个合适的 Provider
        
        Args:
            requested_model: 用户请求的模型名
            exclude: 要排除的 Provider 名称集合
            strategy: 选择策略 ("weighted", "random", "first")
            
        Returns:
            (Provider 状态, 实际模型名) 或 None
        """
        candidates = self.find_providers(requested_model, exclude)
        
        if not candidates:
            return None
        
        if strategy == "first":
            # 直接选择第一个（权重最高的）
            return candidates[0]
        
        elif strategy == "random":
            # 随机选择
            return random.choice(candidates)
        
        else:  # weighted
            # 加权随机选择
            return self._weighted_random_select(candidates)
    
    def _weighted_random_select(
        self,
        candidates: list[tuple[ProviderState, str]]
    ) -> tuple[ProviderState, str]:
        """
        加权随机选择
        
        权重越高的 Provider 被选中的概率越大
        """
        if len(candidates) == 1:
            return candidates[0]
        
        # 计算总权重
        weights = [p.config.weight for p, _ in candidates]
        total_weight = sum(weights)
        
        # 随机选择
        r = random.uniform(0, total_weight)
        cumulative = 0
        
        for (provider, model), weight in zip(candidates, weights):
            cumulative += weight
            if r <= cumulative:
                return (provider, model)
        
        # 兜底返回最后一个
        return candidates[-1]
    
    def get_available_models(self) -> list[str]:
        """
        获取所有可用的模型列表
        
        Returns:
            模型名列表（包括映射名和原始模型名）
        """
        models = set()
        
        # 添加增强型模型映射的统一名称
        model_mapping_manager.load()
        mappings = model_mapping_manager.get_all_mappings()
        models.update(mappings.keys())
        
        # 添加所有 Provider 支持的原始模型名
        for provider in self.provider_manager.get_available():
            models.update(provider.config.supported_models)
        
        return sorted(models)
    
    @staticmethod
    def _log_info(message: str) -> None:
        """输出信息日志"""
        print(f"{Fore.CYAN}[ROUTER]{Style.RESET_ALL} {message}")
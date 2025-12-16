"""
路由策略模块

负责根据请求的模型名称选择合适的 Provider

注意：内部使用 provider_id (UUID) 作为标识
exclude 参数接收的是 provider_id 集合
"""

import random
from typing import Optional
from .config import AppConfig
from .provider import ProviderManager, ProviderState
from .model_mapping import model_mapping_manager
from .provider_models import provider_models_manager


class ModelRouter:
    """模型路由器"""
    
    def __init__(self, config: AppConfig, provider_manager: ProviderManager):
        self.config = config
        self.provider_manager = provider_manager
    
    def resolve_model(self, requested_model: str) -> dict[str, list[str]]:
        """
        解析用户请求的模型名，返回 Provider 和模型的映射关系
        
        使用增强型模型映射，保留 provider_id 关联信息，确保请求只被路由到
        明确配置的 Provider + Model 组合。
        
        如果没有匹配的映射，则返回空字典（表示该模型不可用）。
        
        Args:
            requested_model: 用户请求的模型名（统一模型名）
            
        Returns:
            {provider_id: [model_ids]} 格式的映射，空字典表示该模型未配置映射（不可用）
        """
        mapping = model_mapping_manager.get_mapping(requested_model)
        if mapping and mapping.resolved_models:
            return mapping.resolved_models.copy()
        
        # 没有映射配置，返回空字典
        return {}
    
    def find_providers(
        self,
        requested_model: str,
        exclude: Optional[set[str]] = None,
        required_protocol: Optional[str] = None
    ) -> list[tuple[ProviderState, str]]:
        """
        查找支持指定模型的可用 Provider 列表（双层熔断检查 + 协议过滤）
        
        Args:
            requested_model: 用户请求的模型名
            exclude: 要排除的 Provider ID 集合
            required_protocol: 要求的协议类型（如 "openai", "anthropic" 等），
                              如果指定，则只返回协议匹配的 Provider
            
        Returns:
            列表：[(Provider 状态, 实际模型名), ...]
            按权重排序（高权重优先）
            
        Note:
            此方法会同时检查：
            1. Provider 渠道级是否可用
            2. Provider + Model 组合是否可用（模型级熔断）
            3. Provider 是否在统一模型映射的 resolved_models 中（防止路由到不在映射范围内的 Provider）
            4. 如果指定了 required_protocol，检查模型协议是否匹配
        """
        exclude = exclude or set()
        candidates: list[tuple[ProviderState, str, int]] = []
        
        # 解析模型映射（返回 {provider_id: [model_ids]} 格式）
        resolved_models = self.resolve_model(requested_model)
        
        # 获取映射配置（用于协议检查）
        mapping = model_mapping_manager.get_mapping(requested_model)
        
        if resolved_models:
            # 有映射配置：只匹配 resolved_models 中明确指定的 provider_id 和 model_id 组合
            for provider_id, model_ids in resolved_models.items():
                # 跳过被排除的 Provider
                if provider_id in exclude:
                    continue
                
                # 获取 Provider 状态
                provider = self.provider_manager.get(provider_id)
                if not provider or not provider.is_available:
                    continue
                
                # 获取该 Provider 实际支持的模型列表（用于二次验证）
                supported_models = self._get_supported_models(provider_id)
                
                # 遍历映射中指定的模型
                for model_id in model_ids:
                    # 验证 Provider 确实支持该模型
                    if model_id not in supported_models:
                        continue
                    
                    # 协议过滤：检查模型协议是否匹配
                    if required_protocol and mapping:
                        model_protocol = mapping.get_model_protocol(provider_id, model_id)
                        if model_protocol != required_protocol:
                            # 协议不匹配，跳过此模型
                            continue
                    
                    # 双层检查：检查该 Provider + Model 组合是否可用（模型级熔断）
                    if self.provider_manager.is_model_available(provider_id, model_id):
                        candidates.append((provider, model_id, provider.config.weight))
                        break  # 每个 Provider 只加入一次
        
        # 没有映射配置时，candidates 为空，表示该模型不可用
        # 系统设计原则：可用的模型仅在模型映射列表中体现
        
        # 按权重降序排序
        candidates.sort(key=lambda x: x[2], reverse=True)
        
        return [(p, m) for p, m, _ in candidates]
    
    def select_provider(
        self,
        requested_model: str,
        exclude: Optional[set[str]] = None,
        strategy: str = "weighted",
        required_protocol: Optional[str] = None
    ) -> Optional[tuple[ProviderState, str]]:
        """
        选择一个合适的 Provider
        
        Args:
            requested_model: 用户请求的模型名
            exclude: 要排除的 Provider ID 集合
            strategy: 选择策略 ("weighted", "random", "first")
            required_protocol: 要求的协议类型（如 "openai", "anthropic" 等）
            
        Returns:
            (Provider 状态, 实际模型名) 或 None
        """
        candidates = self.find_providers(requested_model, exclude, required_protocol)
        
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
    
    def _get_supported_models(self, provider_id: str) -> set[str]:
        """
        获取指定 Provider 支持的模型集合
        
        从 provider_models_manager 获取（包含 owned_by, supported_endpoint_types 等元信息）
        
        Args:
            provider_id: Provider 的唯一 ID (UUID)
            
        Returns:
            支持的模型 ID 集合
        """
        model_ids = provider_models_manager.get_provider_model_ids(provider_id)
        return set(model_ids) if model_ids else set()
    
    def get_available_models(self) -> list[str]:
        """
        获取所有可用的模型列表
        
        仅返回模型映射的统一名称。
        实际请求时会在内部将统一名称映射到健康的真实模型。
        
        Returns:
            模型映射的统一名称列表
        """
        # 加载并返回模型映射的统一名称
        model_mapping_manager.load()
        mappings = model_mapping_manager.get_all_mappings()
        return sorted(mappings.keys())
    
    @staticmethod
    def _log_info(message: str) -> None:
        """输出信息日志"""
        print(f"[ROUTER] {message}")
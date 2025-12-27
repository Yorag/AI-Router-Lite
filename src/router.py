"""
路由策略模块

负责根据请求的模型名称选择合适的 Provider

注意：内部使用 provider_id (UUID) 作为标识
exclude 参数接收的是 provider_id 集合
"""

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
        
        如果没有匹配的映射或映射已禁用，则返回空字典（表示该模型不可用）。
        
        Args:
            requested_model: 用户请求的模型名（统一模型名）
            
        Returns:
            {provider_id: [model_ids]} 格式的映射，空字典表示该模型未配置映射或已禁用（不可用）
        """
        mapping = model_mapping_manager.get_mapping(requested_model)
        if mapping and mapping.enabled and mapping.resolved_models:
            return mapping.resolved_models.copy()
        
        # 没有映射配置或已禁用，返回空字典
        return {}
    
    def find_candidate_providers(
        self,
        requested_model: str,
        exclude_providers: Optional[set[str]] = None,
        required_protocol: Optional[str] = None
    ) -> tuple[list[tuple[ProviderState, list[str]]], bool]:
        """
        查找支持指定模型的所有可用渠道及其可用模型列表（两阶段选择支持）

        Args:
            requested_model: 用户请求的模型名
            exclude_providers: 要排除的 provider_id 集合
            required_protocol: 要求的协议类型（如 "openai", "anthropic" 等），
                              如果指定，则只返回协议匹配的模型

        Returns:
            (candidates, is_fallback): 候选列表和是否为保底标记
            - candidates: [(Provider 状态, [可用模型列表]), ...] 按权重降序排序
            - is_fallback: True 表示所有候选都被熔断，返回的是保底候选

        Note:
            此方法会同时检查：
            1. Provider 渠道级是否可用
            2. Provider + Model 组合是否可用（模型级熔断）
            3. Provider 是否在统一模型映射的 resolved_models 中
            4. 如果指定了 required_protocol，检查模型协议是否匹配

            保底机制：当所有候选都被熔断时，选择权重最高渠道的第一个模型
        """
        exclude_providers = exclude_providers or set()
        # {provider_id: (ProviderState, [model_ids], weight)}
        provider_candidates: dict[str, tuple[ProviderState, list[str], int]] = {}

        # 解析模型映射（返回 {provider_id: [model_ids]} 格式）
        resolved_models = self.resolve_model(requested_model)

        # 获取映射配置（用于协议检查）
        mapping = model_mapping_manager.get_mapping(requested_model)

        if resolved_models:
            # 有映射配置：匹配 resolved_models 中所有可用的 provider_id 和 model_id 组合
            for provider_id, model_ids in resolved_models.items():
                # 跳过被排除的渠道
                if provider_id in exclude_providers:
                    continue

                # 获取 Provider 状态
                provider = self.provider_manager.get(provider_id)
                if not provider or not provider.is_available:
                    continue

                # 获取该 Provider 实际支持的模型列表（用于二次验证）
                supported_models = self._get_supported_models(provider_id)

                available_models: list[str] = []

                # 遍历映射中指定的所有模型
                for model_id in model_ids:
                    # 验证 Provider 确实支持该模型
                    if model_id not in supported_models:
                        continue

                    # 协议过滤：检查模型协议是否匹配
                    if required_protocol and mapping:
                        model_protocol = mapping.get_model_protocol(provider_id, model_id)
                        if model_protocol != required_protocol:
                            continue

                    # 双层检查：检查该 Provider + Model 组合是否可用（模型级熔断）
                    if self.provider_manager.is_model_available(provider_id, model_id):
                        available_models.append(model_id)

                # 只有当渠道有可用模型时才加入候选
                if available_models:
                    provider_candidates[provider_id] = (provider, available_models, provider.config.weight)

        # 按权重降序排序
        sorted_candidates = sorted(provider_candidates.values(), key=lambda x: x[2], reverse=True)

        # 保底机制：如果所有候选都被熔断，选择权重最高渠道的第一个模型
        if not sorted_candidates and resolved_models:
            fallback_candidates: list[tuple[ProviderState, list[str], int]] = []
            for provider_id, model_ids in resolved_models.items():
                if provider_id in exclude_providers:
                    continue
                provider = self.provider_manager.get(provider_id)
                # 仅检查 enabled 状态，不检查熔断
                if not provider or not provider.config.enabled:
                    continue
                supported = self._get_supported_models(provider_id)
                valid_models = []
                for m in model_ids:
                    if m not in supported:
                        continue
                    # 协议过滤
                    if required_protocol and mapping:
                        if mapping.get_model_protocol(provider_id, m) != required_protocol:
                            continue
                    valid_models.append(m)
                if valid_models:
                    fallback_candidates.append((provider, valid_models, provider.config.weight))

            if fallback_candidates:
                fallback_candidates.sort(key=lambda x: x[2], reverse=True)
                best = fallback_candidates[0]
                # 返回权重最高渠道的第一个模型作为保底
                return ([(best[0], [best[1][0]])], True)

        return ([(p, models) for p, models, _ in sorted_candidates], False)

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
        
        仅返回已启用的模型映射的统一名称。
        实际请求时会在内部将统一名称映射到健康的真实模型。
        
        Returns:
            已启用的模型映射的统一名称列表
        """
        # 加载并返回已启用的模型映射的统一名称
        model_mapping_manager.load()
        mappings = model_mapping_manager.get_all_mappings()
        return sorted(name for name, mapping in mappings.items() if mapping.enabled)
    
    @staticmethod
    def _log_info(message: str) -> None:
        """输出信息日志"""
        print(f"[ROUTER] {message}")
"""
请求代理模块

负责将请求转发到上游 Provider，支持流式和非流式响应
支持多协议（OpenAI, Anthropic, Gemini等），由 protocols 模块处理协议细节
"""

from typing import AsyncIterator, Optional, Dict, Any
from dataclasses import dataclass
import ssl
import random

import httpx

from .config import AppConfig
from .provider import ProviderManager, ProviderState
from .router import ModelRouter
from .provider_models import provider_models_manager
from .protocols import BaseProtocol
from .logger import log_manager, LogLevel
from .model_health import model_health_manager


@dataclass
class ProxyResult:
    """代理请求结果"""
    response: Any  # 响应内容
    provider_id: str  # 实际使用的 Provider ID (UUID)
    provider_name: str  # Provider 显示名称（用于日志）
    actual_model: str  # 实际使用的模型名
    request_tokens: Optional[int] = None  # 请求 token 数
    response_tokens: Optional[int] = None  # 响应 token 数
    total_tokens: Optional[int] = None  # 总 token 数


@dataclass
class StreamContext:
    """流式请求上下文（用于跟踪流式请求的元数据）"""
    provider_id: str = ""  # Provider ID (UUID)
    provider_name: str = ""  # Provider 显示名称
    actual_model: str = ""
    request_tokens: Optional[int] = None
    response_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


class ProxyError(Exception):
    """代理错误"""
    
    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        provider_name: Optional[str] = None,
        actual_model: Optional[str] = None
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.provider_name = provider_name
        self.actual_model = actual_model


class RequestProxy:
    """
    请求代理
    
    支持多协议的请求转发。
    """
    
    def __init__(
        self,
        config: AppConfig,
        provider_manager: ProviderManager,
        router: ModelRouter
    ):
        self.config = config
        self.provider_manager = provider_manager
        self.router = router
        self._client: Optional[httpx.AsyncClient] = None
    
    async def get_client(self) -> httpx.AsyncClient:
        """获取 HTTP 客户端"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.request_timeout),
                follow_redirects=True
            )
        return self._client
    
    async def close(self) -> None:
        """关闭 HTTP 客户端"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
    
    def _weighted_random_select_index(
        self,
        candidates: list[tuple["ProviderState", str]]
    ) -> int:
        """
        加权随机选择候选索引
        
        Args:
            candidates: 候选列表 [(Provider, model_id), ...]
            
        Returns:
            选中的索引
        """
        if len(candidates) == 1:
            return 0
        
        weights = [p.config.weight for p, _ in candidates]
        total_weight = sum(weights)
        
        r = random.uniform(0, total_weight)
        cumulative = 0
        
        for i, weight in enumerate(weights):
            cumulative += weight
            if r <= cumulative:
                return i
        
        return len(candidates) - 1
    
    def _reorder_candidates_with_weighted_first(
        self,
        candidates: list[tuple["ProviderState", str]]
    ) -> list[tuple["ProviderState", str]]:
        """
        重排候选列表：首个元素通过加权随机选择，其余按原顺序
        
        Args:
            candidates: 按权重排序的候选列表
            
        Returns:
            重排后的列表
        """
        if len(candidates) <= 1:
            return candidates
        
        # 加权随机选择首个
        first_idx = self._weighted_random_select_index(candidates)
        
        # 构建新列表：选中的在前，其余按原顺序
        result = [candidates[first_idx]]
        result.extend(candidates[:first_idx])
        result.extend(candidates[first_idx + 1:])
        
        return result
    
    async def forward_request(
        self,
        request_body: Dict[str, Any],
        protocol_handler: BaseProtocol,
        original_model: str,
        required_protocol: Optional[str] = None
    ) -> ProxyResult:
        """
        转发非流式请求（带模型级重试机制）
        
        首次请求通过加权随机选择，失败后按权重顺序依次重试。
        
        Args:
            request_body: 原始请求体 (dict)
            protocol_handler: 协议处理器实例
            original_model: 用户请求的原始模型名
            required_protocol: 要求的协议类型
            
        Returns:
            ProxyResult 对象
        """
        last_error: Optional[ProxyError] = None
        
        # 如果未指定 required_protocol，使用 handler 的类型
        req_protocol = required_protocol or protocol_handler.protocol_type
        
        # 一次性获取所有候选 (Provider, Model) 组合（已按权重排序）
        all_candidates = self.router.find_candidate_models(original_model, required_protocol=req_protocol)
        
        if not all_candidates:
            raise ProxyError(
                f"没有找到支持模型 '{original_model}' (协议: {req_protocol}) 的可用 Provider",
                status_code=404
            )
        
        # 重排列表：首个加权随机，其余按原顺序
        ordered_candidates = self._reorder_candidates_with_weighted_first(all_candidates)
        max_attempts = len(ordered_candidates)
        
        # 遍历所有候选组合进行模型级重试
        for attempt, (provider, actual_model) in enumerate(ordered_candidates, 1):
            self._log_info(
                f"[尝试 {attempt}/{max_attempts}] "
                f"Provider: {provider.config.name}, 模型: {actual_model}, 协议: {req_protocol}"
            )
            
            try:
                response, protocol_resp = await self._do_request(
                    provider, request_body, protocol_handler, actual_model, original_model
                )
                
                # 记录成功
                self.provider_manager.mark_success(
                    provider.config.id,
                    model_name=actual_model,
                    tokens=protocol_resp.total_tokens or 0
                )
                
                # 记录被动健康状态（缓冲落盘）
                model_health_manager.record_passive_result(
                    provider.config.id, actual_model, success=True
                )
                
                provider_models_manager.update_activity(
                    provider.config.id, actual_model, "call"
                )
                
                return ProxyResult(
                    response=protocol_resp.response,
                    provider_id=provider.config.id,
                    provider_name=provider.config.name,
                    actual_model=actual_model,
                    request_tokens=protocol_resp.request_tokens,
                    response_tokens=protocol_resp.response_tokens,
                    total_tokens=protocol_resp.total_tokens
                )
                
            except ProxyError as e:
                last_error = e
                last_error.actual_model = actual_model
                self.provider_manager.mark_failure(
                    provider.config.id,
                    model_name=actual_model,
                    status_code=e.status_code,
                    error_message=e.message
                )
                
                # 记录被动健康状态（缓冲落盘）
                model_health_manager.record_passive_result(
                    provider.config.id, actual_model, success=False, error=e.message
                )
                continue
        
        # 所有候选都失败
        raise ProxyError(
            f"所有支持模型 '{original_model}' (协议: {req_protocol}) 的 Provider 都已尝试失败",
            status_code=503
        ) if last_error else ProxyError("请求失败", status_code=500)
    
    async def forward_stream(
        self,
        request_body: Dict[str, Any],
        protocol_handler: BaseProtocol,
        original_model: str,
        stream_context: Optional[StreamContext] = None,
        required_protocol: Optional[str] = None
    ) -> AsyncIterator[str]:
        """
        转发流式请求（带模型级重试机制）
        
        首次请求通过加权随机选择，失败后按权重顺序依次重试。
        """
        last_error: Optional[ProxyError] = None
        
        req_protocol = required_protocol or protocol_handler.protocol_type
        
        # 一次性获取所有候选 (Provider, Model) 组合（已按权重排序）
        all_candidates = self.router.find_candidate_models(original_model, required_protocol=req_protocol)
        
        if not all_candidates:
            raise ProxyError(
                f"没有找到支持模型 '{original_model}' (协议: {req_protocol}) 的可用 Provider",
                status_code=404
            )
        
        # 重排列表：首个加权随机，其余按原顺序
        ordered_candidates = self._reorder_candidates_with_weighted_first(all_candidates)
        max_attempts = len(ordered_candidates)
        
        # 遍历所有候选组合进行模型级重试
        for attempt, (provider, actual_model) in enumerate(ordered_candidates, 1):
            if stream_context is not None:
                stream_context.provider_id = provider.config.id
                stream_context.provider_name = provider.config.name
                stream_context.actual_model = actual_model
            
            self._log_info(
                f"[流式尝试 {attempt}/{max_attempts}] "
                f"Provider: {provider.config.name} (ID: {provider.config.id}), 模型: {actual_model}, 协议: {req_protocol}"
            )
            
            try:
                async for chunk in self._do_stream_request(
                    provider, request_body, protocol_handler, actual_model, original_model, stream_context
                ):
                    yield chunk
                
                # 成功完成
                total_tokens = 0
                if stream_context:
                    if stream_context.total_tokens:
                        total_tokens = stream_context.total_tokens
                    elif stream_context.request_tokens or stream_context.response_tokens:
                        total_tokens = (stream_context.request_tokens or 0) + (stream_context.response_tokens or 0)
                
                self.provider_manager.mark_success(
                    provider.config.id,
                    model_name=actual_model,
                    tokens=total_tokens
                )
                
                # 记录被动健康状态（缓冲落盘）
                model_health_manager.record_passive_result(
                    provider.config.id, actual_model, success=True
                )
                
                provider_models_manager.update_activity(
                    provider.config.id, actual_model, "call"
                )
                
                return
                
            except ProxyError as e:
                last_error = e
                last_error.actual_model = actual_model
                self.provider_manager.mark_failure(
                    provider.config.id,
                    model_name=actual_model,
                    status_code=e.status_code,
                    error_message=e.message
                )
                
                # 记录被动健康状态（缓冲落盘）
                model_health_manager.record_passive_result(
                    provider.config.id, actual_model, success=False, error=e.message
                )
                continue
        
        # 所有候选都失败
        raise ProxyError(
            f"所有支持模型 '{original_model}' (协议: {req_protocol}) 的 Provider 都已尝试失败",
            status_code=503
        ) if last_error else ProxyError("流式请求失败", status_code=500)
    
    def _get_timeout(self, provider: ProviderState) -> float:
        return provider.config.timeout if provider.config.timeout is not None else self.config.request_timeout
    
    async def _do_request(
        self,
        provider: ProviderState,
        request_body: Dict[str, Any],
        protocol_handler: BaseProtocol,
        actual_model: str,
        original_model: str
    ) -> Any:
        """执行单次非流式请求"""
        client = await self.get_client()
        base_url = provider.config.base_url
        
        # 使用协议处理器构建请求
        protocol_request = protocol_handler.build_request(
            base_url,
            provider.config.api_key,
            request_body,
            actual_model
        )
        
        try:
            response = await client.post(
                protocol_request.url,
                json=protocol_request.body,
                headers=protocol_request.headers,
                timeout=self._get_timeout(provider)
            )
            
            if response.status_code != 200:
                error_body = response.text
                # 保留原始响应体，压缩换行符到一行
                error_body_oneline = error_body.replace('\r\n', ' ').replace('\n', ' ').replace('\r', ' ').strip()
                raise ProxyError(
                    f"HTTP {response.status_code}: {error_body_oneline}",
                    status_code=response.status_code,
                    provider_name=provider.config.name
                )
            
            raw_response = response.json()
            
            # 使用协议处理器转换响应
            protocol_response = protocol_handler.transform_response(raw_response, original_model)
            
            return raw_response, protocol_response
            
        except httpx.TimeoutException as e:
            raise ProxyError(
                str(e) if str(e) else "TimeoutException",
                status_code=408,
                provider_name=provider.config.name
            )
        except (ssl.SSLError, ConnectionResetError, BrokenPipeError) as e:
            raise ProxyError(
                str(e),
                status_code=502,
                provider_name=provider.config.name
            )
        except httpx.RequestError as e:
            raise ProxyError(
                str(e),
                status_code=502,
                provider_name=provider.config.name
            )
    
    async def _do_stream_request(
        self,
        provider: ProviderState,
        request_body: Dict[str, Any],
        protocol_handler: BaseProtocol,
        actual_model: str,
        original_model: str,
        stream_context: Optional[StreamContext] = None
    ) -> AsyncIterator[str]:
        """执行单次流式请求"""
        client = await self.get_client()
        base_url = provider.config.base_url
        
        protocol_request = protocol_handler.build_request(
            base_url,
            provider.config.api_key,
            request_body,
            actual_model
        )
        
        try:
            async with client.stream(
                "POST",
                protocol_request.url,
                json=protocol_request.body,
                headers=protocol_request.headers,
                timeout=self._get_timeout(provider)
            ) as response:
                if response.status_code != 200:
                    error_body = await response.aread()
                    # 保留原始响应体，压缩换行符到一行
                    error_body_text = error_body.decode()
                    error_body_oneline = error_body_text.replace('\r\n', ' ').replace('\n', ' ').replace('\r', ' ').strip()
                    raise ProxyError(
                        f"HTTP {response.status_code}: {error_body_oneline}",
                        status_code=response.status_code,
                        provider_name=provider.config.name,
                        actual_model=actual_model
                    )
                
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    
                    # 使用协议处理器转换流式块
                    transformed, usage = protocol_handler.transform_stream_chunk(line, original_model)
                    
                    if transformed:
                        if stream_context and usage:
                            # 累加或更新 usage
                            if "prompt_tokens" in usage:
                                stream_context.request_tokens = usage["prompt_tokens"]
                            if "completion_tokens" in usage:
                                stream_context.response_tokens = usage["completion_tokens"]
                            
                            if "total_tokens" in usage:
                                stream_context.total_tokens = usage["total_tokens"]
                            elif stream_context.request_tokens is not None or stream_context.response_tokens is not None:
                                stream_context.total_tokens = (stream_context.request_tokens or 0) + (stream_context.response_tokens or 0)
                        
                        yield transformed
                        
        except httpx.TimeoutException as e:
            raise ProxyError(
                str(e) if str(e) else "TimeoutException",
                status_code=408,
                provider_name=provider.config.name,
                actual_model=actual_model
            )
        except (ssl.SSLError, ConnectionResetError, BrokenPipeError) as e:
            raise ProxyError(
                str(e),
                status_code=502,
                provider_name=provider.config.name,
                actual_model=actual_model
            )
        except httpx.RequestError as e:
            raise ProxyError(
                str(e),
                status_code=502,
                provider_name=provider.config.name,
                actual_model=actual_model
            )
    
    @staticmethod
    def _log_info(message: str) -> None:
        """输出信息日志"""
        print(f"[PROXY] {message}")
    
    @staticmethod
    def _log_warning(message: str) -> None:
        """输出警告日志"""
        print(f"[PROXY] {message}")
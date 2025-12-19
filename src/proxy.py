"""
请求代理模块

负责将请求转发到上游 Provider，支持流式和非流式响应
支持多协议（OpenAI, Anthropic, Gemini等），由 protocols 模块处理协议细节
"""

from typing import AsyncIterator, Optional, Dict, Any
from dataclasses import dataclass
import ssl
import random
import json

import httpx

from .config import AppConfig
from .provider import ProviderManager, ProviderState
from .router import ModelRouter
from .provider_models import provider_models_manager
from .protocols import BaseProtocol
from .logger import log_manager, LogLevel
from .model_health import model_health_manager
from .constants import PROXY_ERROR_MESSAGE_MAX_LENGTH


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
        actual_model: Optional[str] = None,
        response_body: Optional[Dict[str, Any]] = None,
        skip_retry: bool = False,
        provider_id: Optional[str] = None,
        log_type: str = "proxy"
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.provider_name = provider_name
        self.actual_model = actual_model
        self.response_body = response_body
        self.skip_retry = skip_retry
        self.provider_id = provider_id
        self.log_type = log_type


class RoutingError(Exception):
    """路由错误（无可用 Provider）"""
    pass


def _create_network_error(
    e: Exception,
    provider_name: str,
    actual_model: Optional[str] = None,
    provider_id: Optional[str] = None
) -> ProxyError:
    """根据网络异常类型创建对应的 ProxyError"""
    error_msg = str(e) or type(e).__name__
    # SSL EOF 错误：系统级错误（503），不重试、不冷却
    # 其他网络错误：上游服务器问题（502），可重试
    lower_msg = error_msg.lower()
    is_ssl_eof = "ssl" in lower_msg and "eof" in lower_msg
    
    # 所有网络层错误（超时、连接重置、SSL错误等）都归类为 system 错误
    return ProxyError(
        error_msg,
        status_code=503 if is_ssl_eof else 502,
        provider_name=provider_name,
        actual_model=actual_model,
        skip_retry=is_ssl_eof,
        provider_id=provider_id,
        log_type="system"
    )


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
    
    def _log_proxy_error(
        self,
        provider_name: str,
        original_model: str,
        actual_model: str,
        status_code: Optional[int],
        error_message: str,
        is_stream: bool = False,
        api_key_name: Optional[str] = None,
        api_key_id: Optional[str] = None,
        provider_id: Optional[str] = None,
        log_type: str = "proxy",
        protocol: Optional[str] = None
    ) -> None:
        """记录代理请求错误日志（用于统计）"""
        path = "/proxy/stream" if is_stream else "/proxy"
        prefix = "流式请求失败" if is_stream else "请求失败"
        log_manager.log(
            level=LogLevel.ERROR,
            log_type=log_type,
            method="POST",
            path=path,
            model=original_model,
            provider=provider_name,
            provider_id=provider_id,
            actual_model=actual_model,
            status_code=status_code,
            error=error_message,
            message=f"{prefix} [{provider_name}:{actual_model}]",
            api_key_name=api_key_name,
            api_key_id=api_key_id,
            protocol=protocol
        )
    
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
        required_protocol: Optional[str] = None,
        api_key_name: Optional[str] = None,
        api_key_id: Optional[str] = None
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
            raise RoutingError(f"没有找到支持模型 '{original_model}' (协议: {req_protocol}) 的可用 Provider")
        
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
                
                # SSL EOF 等系统错误：不重试、不冷却，直接抛出
                if e.skip_retry:
                    raise e
                
                self.provider_manager.mark_failure(
                    provider.config.id,
                    model_name=actual_model,
                    status_code=e.status_code,
                    error_message=e.message
                )
                
                # 记录错误日志（用于统计）
                self._log_proxy_error(
                    provider.config.name, original_model, actual_model,
                    e.status_code, e.message, is_stream=False,
                    api_key_name=api_key_name,
                    api_key_id=api_key_id,
                    provider_id=provider.config.id,
                    log_type=e.log_type,
                    protocol=req_protocol
                )
                
                # 记录被动健康状态（缓冲落盘）
                model_health_manager.record_passive_result(
                    provider.config.id, actual_model, success=False, error=e.message,
                    response_body=e.response_body
                )
                continue
        
        # 所有候选都失败，直接抛出最后一个错误
        if last_error:
            raise last_error
        
        raise ProxyError(f"为模型 '{original_model}' 尝试所有候选后请求失败", status_code=500)
    
    async def forward_stream(
        self,
        request_body: Dict[str, Any],
        protocol_handler: BaseProtocol,
        original_model: str,
        stream_context: Optional[StreamContext] = None,
        required_protocol: Optional[str] = None,
        api_key_name: Optional[str] = None,
        api_key_id: Optional[str] = None
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
            raise RoutingError(f"没有找到支持模型 '{original_model}' (协议: {req_protocol}) 的可用 Provider")
        
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
                f"Provider: {provider.config.name}, 模型: {actual_model}, 协议: {req_protocol}"
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
                
                # SSL EOF 等系统错误：不重试、不冷却，直接抛出
                if e.skip_retry:
                    raise e
                
                self.provider_manager.mark_failure(
                    provider.config.id,
                    model_name=actual_model,
                    status_code=e.status_code,
                    error_message=e.message
                )
                
                # 记录错误日志（用于统计）
                self._log_proxy_error(
                    provider.config.name, original_model, actual_model,
                    e.status_code, e.message, is_stream=True,
                    api_key_name=api_key_name,
                    api_key_id=api_key_id,
                    provider_id=provider.config.id,
                    log_type=e.log_type,
                    protocol=req_protocol
                )
                
                # 记录被动健康状态（缓冲落盘）
                model_health_manager.record_passive_result(
                    provider.config.id, actual_model, success=False, error=e.message,
                    response_body=e.response_body
                )
                continue
        
        # 所有候选都失败，直接抛出最后一个错误
        if last_error:
            raise last_error
        
        raise ProxyError(f"为模型 '{original_model}' 尝试所有候选后流式请求失败", status_code=500)
    
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
                # 截断过长的错误消息
                if len(error_body_oneline) > PROXY_ERROR_MESSAGE_MAX_LENGTH:
                    error_body_oneline = error_body_oneline[:PROXY_ERROR_MESSAGE_MAX_LENGTH] + "..."
                # 尝试解析 JSON 响应体用于健康检测记录
                try:
                    error_response_body = response.json()
                except Exception:
                    error_response_body = {"raw_text": error_body[:500]}
                raise ProxyError(
                    f"HTTP {response.status_code}: {error_body_oneline}",
                    status_code=response.status_code,
                    provider_name=provider.config.name,
                    response_body=error_response_body,
                    provider_id=provider.config.id
                )
            
            try:
                raw_response = response.json()
            except Exception:
                # 捕获 JSON 解析错误 (如返回 HTML 或空字符串)
                error_body = response.text
                error_msg = error_body.replace('\r\n', ' ').replace('\n', ' ').replace('\r', ' ').strip()
                if len(error_msg) > PROXY_ERROR_MESSAGE_MAX_LENGTH:
                    error_msg = error_msg[:PROXY_ERROR_MESSAGE_MAX_LENGTH] + "..."
                    
                raise ProxyError(
                    f"无效的响应格式: {error_msg or '空响应'}",
                    status_code=502,
                    provider_name=provider.config.name,
                    actual_model=actual_model,
                    response_body={"raw": error_body[:1000]},
                    provider_id=provider.config.id
                )
            
            # 使用协议处理器转换响应
            protocol_response = protocol_handler.transform_response(raw_response, original_model)
            
            return raw_response, protocol_response
            
        except (httpx.TimeoutException, ssl.SSLError, ConnectionResetError, BrokenPipeError, httpx.RequestError) as e:
            raise _create_network_error(e, provider.config.name, provider_id=provider.config.id)
    
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
                    # 截断过长的错误消息
                    if len(error_body_oneline) > PROXY_ERROR_MESSAGE_MAX_LENGTH:
                        error_body_oneline = error_body_oneline[:PROXY_ERROR_MESSAGE_MAX_LENGTH] + "..."
                    # 尝试解析 JSON 响应体用于健康检测记录
                    try:
                        error_response_body = json.loads(error_body_text)
                    except Exception:
                        error_response_body = {"raw_text": error_body_text[:500]}
                    raise ProxyError(
                        f"HTTP {response.status_code}: {error_body_oneline}",
                        status_code=response.status_code,
                        provider_name=provider.config.name,
                        actual_model=actual_model,
                        response_body=error_response_body,
                        provider_id=provider.config.id
                    )
                
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    
                    # 使用协议处理器转换流式块
                    try:
                        transformed, usage = protocol_handler.transform_stream_chunk(line, original_model)
                    except Exception:
                        # 忽略无法解析的行（可能是心跳包或非标准格式）
                        continue

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
                        
        except (httpx.TimeoutException, ssl.SSLError, ConnectionResetError, BrokenPipeError, httpx.RequestError) as e:
            raise _create_network_error(e, provider.config.name, actual_model, provider_id=provider.config.id)
    
    @staticmethod
    def _log_info(message: str) -> None:
        """输出信息日志"""
        print(f"[PROXY] {message}")
    
    @staticmethod
    def _log_warning(message: str) -> None:
        """输出警告日志"""
        print(f"[PROXY] {message}")
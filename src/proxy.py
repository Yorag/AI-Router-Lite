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
        candidates: list[tuple["ProviderState", list[str]]]
    ) -> int:
        """
        加权随机选择候选渠道索引

        Args:
            candidates: 候选列表 [(Provider, [model_ids]), ...]

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

    def _reorder_providers_with_weighted_first(
        self,
        candidates: list[tuple["ProviderState", list[str]]]
    ) -> list[tuple["ProviderState", list[str]]]:
        """
        重排候选渠道列表：首个元素通过加权随机选择，其余按原顺序

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

    def _select_model_in_provider(
        self,
        api_key_name: str,
        unified_model: str,
        provider_id: str,
        available_models: list[str]
    ) -> str:
        """
        在渠道内选择模型（支持 sticky）

        Args:
            api_key_name: API 密钥名称（用于隔离 sticky 偏好）
            unified_model: 统一模型名
            provider_id: Provider ID
            available_models: 该渠道下可用的模型列表

        Returns:
            选中的模型名
        """
        if not available_models:
            raise ValueError("available_models cannot be empty")

        # 优先使用 sticky 模型（按 api_key_name 隔离）
        sticky = self.provider_manager.get_sticky_model(api_key_name, unified_model, provider_id)
        if sticky and sticky in available_models:
            return sticky

        # 否则随机选择
        return random.choice(available_models)
    
    async def _execute_with_retry(
        self,
        request_body: Dict[str, Any],
        protocol_handler: BaseProtocol,
        original_model: str,
        is_stream: bool,
        required_protocol: Optional[str] = None,
        api_key_name: Optional[str] = None,
        api_key_id: Optional[str] = None,
        stream_context: Optional[StreamContext] = None,
        client_headers: Optional[Dict[str, str]] = None
    ) -> AsyncIterator[Any]:
        """统一的重试执行逻辑 (作为异步生成器) - 两阶段选择"""
        last_error: Optional[ProxyError] = None
        req_protocol = required_protocol or protocol_handler.protocol_type

        # 第一阶段：获取候选渠道列表
        all_providers = self.router.find_candidate_providers(original_model, required_protocol=req_protocol)

        if not all_providers:
            raise RoutingError(f"没有找到支持模型 '{original_model}' (协议: {req_protocol}) 的可用 Provider")

        # 按权重随机重排渠道
        ordered_providers = self._reorder_providers_with_weighted_first(all_providers)
        max_attempts = len(ordered_providers)

        # 用于 sticky 的密钥标识（无密钥时使用默认值）
        sticky_key = api_key_name or "_default_"

        for attempt, (provider, available_models) in enumerate(ordered_providers, 1):
            # 第二阶段：在渠道内选择模型（优先 sticky）
            actual_model = self._select_model_in_provider(
                sticky_key, original_model, provider.config.id, available_models
            )

            if stream_context:
                stream_context.provider_id = provider.config.id
                stream_context.provider_name = provider.config.name
                stream_context.actual_model = actual_model

            self._log_info(
                f"[{'流式' if is_stream else ''}尝试 {attempt}/{max_attempts}] "
                f"Provider: {provider.config.name}, 模型: {actual_model}, 协议: {req_protocol}"
            )

            try:
                if is_stream:
                    async for chunk in self._do_stream_request(provider, request_body, protocol_handler, actual_model, original_model, stream_context, client_headers):
                        yield chunk

                    # 成功完成流式传输
                    total_tokens = 0
                    if stream_context:
                        if stream_context.total_tokens:
                            total_tokens = stream_context.total_tokens
                        elif stream_context.request_tokens or stream_context.response_tokens:
                            total_tokens = (stream_context.request_tokens or 0) + (stream_context.response_tokens or 0)

                    self.provider_manager.mark_success(provider.config.id, model_name=actual_model, tokens=total_tokens)
                    self.provider_manager.set_sticky_model(sticky_key, original_model, provider.config.id, actual_model)
                    model_health_manager.record_passive_result(provider.config.id, actual_model, success=True)
                    provider_models_manager.update_activity(provider.config.id, actual_model, "call")
                    return  # 成功，结束生成器

                else:  # not is_stream
                    _, protocol_resp = await self._do_request(provider, request_body, protocol_handler, actual_model, original_model, client_headers)

                    self.provider_manager.mark_success(provider.config.id, model_name=actual_model, tokens=protocol_resp.total_tokens or 0)
                    self.provider_manager.set_sticky_model(sticky_key, original_model, provider.config.id, actual_model)
                    model_health_manager.record_passive_result(provider.config.id, actual_model, success=True)
                    provider_models_manager.update_activity(provider.config.id, actual_model, "call")

                    yield ProxyResult(
                        response=protocol_resp.response,
                        provider_id=provider.config.id,
                        provider_name=provider.config.name,
                        actual_model=actual_model,
                        request_tokens=protocol_resp.request_tokens,
                        response_tokens=protocol_resp.response_tokens,
                        total_tokens=protocol_resp.total_tokens
                    )
                    return  # 成功，结束生成器

            except ProxyError as e:
                last_error = e
                last_error.actual_model = actual_model

                if e.skip_retry:
                    raise e

                # 清除 sticky 并触发熔断，然后切换到下一个渠道
                self.provider_manager.clear_sticky_model(sticky_key, original_model, provider.config.id)
                self.provider_manager.mark_failure(provider.config.id, model_name=actual_model, status_code=e.status_code, error_message=e.message)

                self._log_proxy_error(
                    provider.config.name, original_model, actual_model,
                    e.status_code, e.message, is_stream=is_stream,
                    api_key_name=api_key_name, api_key_id=api_key_id,
                    provider_id=provider.config.id, log_type=e.log_type, protocol=req_protocol
                )

                model_health_manager.record_passive_result(provider.config.id, actual_model, success=False, error=e.message, response_body=e.response_body)
                continue

        if last_error:
            raise last_error

        raise ProxyError(f"为模型 '{original_model}' 尝试所有候选后{'流式' if is_stream else ''}请求失败", status_code=500)

    async def forward_request(
        self,
        request_body: Dict[str, Any],
        protocol_handler: BaseProtocol,
        original_model: str,
        required_protocol: Optional[str] = None,
        api_key_name: Optional[str] = None,
        api_key_id: Optional[str] = None,
        client_headers: Optional[Dict[str, str]] = None
    ) -> ProxyResult:
        async for result in self._execute_with_retry(
            request_body=request_body,
            protocol_handler=protocol_handler,
            original_model=original_model,
            is_stream=False,
            required_protocol=required_protocol,
            api_key_name=api_key_name,
            api_key_id=api_key_id,
            client_headers=client_headers
        ):
            return result
        # This part should not be reached if logic is correct
        raise ProxyError("Request forwarding failed unexpectedly.")

    async def forward_stream(
        self,
        request_body: Dict[str, Any],
        protocol_handler: BaseProtocol,
        original_model: str,
        stream_context: Optional[StreamContext] = None,
        required_protocol: Optional[str] = None,
        api_key_name: Optional[str] = None,
        api_key_id: Optional[str] = None,
        client_headers: Optional[Dict[str, str]] = None
    ) -> AsyncIterator[str]:
        async for chunk in self._execute_with_retry(
            request_body=request_body,
            protocol_handler=protocol_handler,
            original_model=original_model,
            is_stream=True,
            required_protocol=required_protocol,
            api_key_name=api_key_name,
            api_key_id=api_key_id,
            stream_context=stream_context,
            client_headers=client_headers
        ):
            yield chunk
    
    def _get_timeout(self, provider: ProviderState) -> float:
        return provider.config.timeout if provider.config.timeout is not None else self.config.request_timeout
    
    async def _create_http_error(self, response: httpx.Response, provider: ProviderState, actual_model: str) -> ProxyError:
        """创建 HTTP 错误异常"""
        error_body_bytes = await response.aread()
        error_body_text = error_body_bytes.decode(errors='replace')
        
        error_body_oneline = error_body_text.replace('\r\n', ' ').replace('\n', ' ').replace('\r', ' ').strip()
        if len(error_body_oneline) > PROXY_ERROR_MESSAGE_MAX_LENGTH:
            error_body_oneline = error_body_oneline[:PROXY_ERROR_MESSAGE_MAX_LENGTH] + "..."
            
        try:
            error_response_body = json.loads(error_body_text)
        except Exception:
            error_response_body = {"raw_text": error_body_text[:500]}
            
        return ProxyError(
            f"HTTP {response.status_code}: {error_body_oneline}",
            status_code=response.status_code,
            provider_name=provider.config.name,
            actual_model=actual_model,
            response_body=error_response_body,
            provider_id=provider.config.id
        )

    async def _do_request(
        self,
        provider: ProviderState,
        request_body: Dict[str, Any],
        protocol_handler: BaseProtocol,
        actual_model: str,
        original_model: str,
        client_headers: Optional[Dict[str, str]] = None
    ) -> Any:
        """执行单次非流式请求"""
        client = await self.get_client()
        base_url = provider.config.base_url

        protocol_request = protocol_handler.build_request(
            base_url,
            provider.config.api_key,
            request_body,
            actual_model,
            client_headers
        )
        
        try:
            response = await client.post(
                protocol_request.url,
                json=protocol_request.body,
                headers=protocol_request.headers,
                timeout=self._get_timeout(provider)
            )
            
            if response.status_code != 200:
                raise await self._create_http_error(response, provider, actual_model)
            
            try:
                raw_response = response.json()
            except Exception:
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
        stream_context: Optional[StreamContext] = None,
        client_headers: Optional[Dict[str, str]] = None
    ) -> AsyncIterator[str]:
        """执行单次流式请求"""
        client = await self.get_client()
        base_url = provider.config.base_url

        protocol_request = protocol_handler.build_request(
            base_url,
            provider.config.api_key,
            request_body,
            actual_model,
            client_headers
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
                    raise await self._create_http_error(response, provider, actual_model)
                
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
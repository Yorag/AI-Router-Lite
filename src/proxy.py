"""
请求代理模块

负责将请求转发到上游 Provider，支持流式和非流式响应

注意：内部使用 provider_id (UUID) 作为标识，而非 provider name
"""

import json
import time
import uuid
from typing import AsyncIterator, Optional
from dataclasses import dataclass

import httpx
from colorama import Fore, Style

from .config import AppConfig
from .models import ChatCompletionRequest
from .provider import ProviderManager, ProviderState
from .router import ModelRouter
from .provider_models import provider_models_manager


@dataclass
class ProxyResult:
    """代理请求结果"""
    response: dict  # 原始响应
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
    """请求代理"""
    
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
    
    async def forward_request(
        self,
        request: ChatCompletionRequest,
        original_model: str
    ) -> ProxyResult:
        """
        转发非流式请求（带重试机制）
        
        Args:
            request: 聊天补全请求
            original_model: 用户请求的原始模型名
            
        Returns:
            ProxyResult 对象，包含响应和元数据
            
        Raises:
            ProxyError: 所有 Provider 都失败时抛出
        """
        tried_providers: set[str] = set()  # 存储已尝试的 provider_id
        last_error: Optional[ProxyError] = None
        
        for attempt in range(self.config.max_retries):
            # 选择一个可用的 Provider
            selection = self.router.select_provider(original_model, exclude=tried_providers)
            
            if selection is None:
                if tried_providers:
                    raise ProxyError(
                        f"所有支持模型 '{original_model}' 的 Provider 都已尝试失败",
                        status_code=503
                    )
                else:
                    raise ProxyError(
                        f"没有找到支持模型 '{original_model}' 的可用 Provider",
                        status_code=404
                    )
            
            provider, actual_model = selection
            tried_providers.add(provider.config.id)  # 使用 id 而非 name
            
            self._log_info(
                f"[尝试 {attempt + 1}/{self.config.max_retries}] "
                f"Provider: {provider.config.name} (ID: {provider.config.id}), 模型: {actual_model}"
            )
            
            try:
                response = await self._do_request(provider, request, actual_model)
                self.provider_manager.mark_success(provider.config.id, model_name=actual_model)
                
                # 更新模型最后活动时间（使用 provider_id）
                provider_models_manager.update_activity(
                    provider.config.id, actual_model, "call"
                )
                
                # 提取 token 使用量
                usage = response.get("usage", {})
                request_tokens = usage.get("prompt_tokens")
                response_tokens = usage.get("completion_tokens")
                total_tokens = usage.get("total_tokens")
                
                # 将响应中的模型名替换回用户请求的模型名
                if "model" in response:
                    response["model"] = original_model
                
                return ProxyResult(
                    response=response,
                    provider_id=provider.config.id,
                    provider_name=provider.config.name,
                    actual_model=actual_model,
                    request_tokens=request_tokens,
                    response_tokens=response_tokens,
                    total_tokens=total_tokens
                )
                
            except ProxyError as e:
                last_error = e
                last_error.actual_model = actual_model
                self.provider_manager.mark_failure(
                    provider.config.id,  # 使用 id 而非 name
                    model_name=actual_model,
                    status_code=e.status_code,
                    error_message=e.message
                )
                self._log_warning(
                    f"Provider [{provider.config.name}] 请求失败: {e.message}"
                )
                continue
        
        # 所有重试都失败
        raise last_error or ProxyError("请求失败", status_code=500)
    
    async def forward_stream(
        self,
        request: ChatCompletionRequest,
        original_model: str,
        stream_context: Optional[StreamContext] = None
    ) -> AsyncIterator[str]:
        """
        转发流式请求（带重试机制）
        
        Args:
            request: 聊天补全请求
            original_model: 用户请求的原始模型名
            stream_context: 可选的流上下文对象，用于收集流式请求的元数据
            
        Yields:
            SSE 格式的响应数据块
            
        Raises:
            ProxyError: 所有 Provider 都失败时抛出
        """
        tried_providers: set[str] = set()  # 存储已尝试的 provider_id
        last_error: Optional[ProxyError] = None
        
        for attempt in range(self.config.max_retries):
            # 选择一个可用的 Provider
            selection = self.router.select_provider(original_model, exclude=tried_providers)
            
            if selection is None:
                if tried_providers:
                    raise ProxyError(
                        f"所有支持模型 '{original_model}' 的 Provider 都已尝试失败",
                        status_code=503
                    )
                else:
                    raise ProxyError(
                        f"没有找到支持模型 '{original_model}' 的可用 Provider",
                        status_code=404
                    )
            
            provider, actual_model = selection
            tried_providers.add(provider.config.id)  # 使用 id 而非 name
            
            # 更新流上下文
            if stream_context is not None:
                stream_context.provider_id = provider.config.id
                stream_context.provider_name = provider.config.name
                stream_context.actual_model = actual_model
            
            self._log_info(
                f"[流式尝试 {attempt + 1}/{self.config.max_retries}] "
                f"Provider: {provider.config.name} (ID: {provider.config.id}), 模型: {actual_model}"
            )
            
            try:
                async for chunk in self._do_stream_request(provider, request, actual_model, original_model, stream_context):
                    yield chunk
                
                self.provider_manager.mark_success(provider.config.id, model_name=actual_model)
                
                # 更新模型最后活动时间（使用 provider_id）
                provider_models_manager.update_activity(
                    provider.config.id, actual_model, "call"
                )
                
                return  # 成功完成，退出重试循环
                
            except ProxyError as e:
                last_error = e
                last_error.actual_model = actual_model
                self.provider_manager.mark_failure(
                    provider.config.id,  # 使用 id 而非 name
                    model_name=actual_model,
                    status_code=e.status_code,
                    error_message=e.message
                )
                self._log_warning(
                    f"Provider [{provider.config.name}] 流式请求失败: {e.message}"
                )
                continue
        
        # 所有重试都失败
        raise last_error or ProxyError("流式请求失败", status_code=500)
    
    def _get_timeout(self, provider: ProviderState) -> float:
        """
        获取 Provider 的超时时间
        
        如果 Provider 配置了 timeout 则使用，否则使用全局 request_timeout
        """
        return provider.config.timeout if provider.config.timeout is not None else self.config.request_timeout
    
    async def _do_request(
        self,
        provider: ProviderState,
        request: ChatCompletionRequest,
        actual_model: str
    ) -> dict:
        """
        执行单次非流式请求
        """
        client = await self.get_client()
        url = f"{provider.config.base_url.rstrip('/')}/chat/completions"
        
        # 构建请求体，替换模型名
        body = request.model_dump(exclude_none=True)
        body["model"] = actual_model
        body["stream"] = False
        
        headers = {
            "Authorization": f"Bearer {provider.config.api_key}",
            "Content-Type": "application/json"
        }
        
        try:
            response = await client.post(
                url,
                json=body,
                headers=headers,
                timeout=self._get_timeout(provider)
            )
            
            if response.status_code != 200:
                error_body = response.text
                raise ProxyError(
                    f"HTTP {response.status_code}: {error_body[:200]}",
                    status_code=response.status_code,
                    provider_name=provider.config.name
                )
            
            return response.json()
            
        except httpx.TimeoutException:
            raise ProxyError(
                "请求超时",
                status_code=408,
                provider_name=provider.config.name
            )
        except httpx.RequestError as e:
            raise ProxyError(
                f"网络错误: {str(e)}",
                status_code=502,
                provider_name=provider.config.name
            )
    
    async def _do_stream_request(
        self,
        provider: ProviderState,
        request: ChatCompletionRequest,
        actual_model: str,
        original_model: str,
        stream_context: Optional[StreamContext] = None
    ) -> AsyncIterator[str]:
        """
        执行单次流式请求
        """
        client = await self.get_client()
        url = f"{provider.config.base_url.rstrip('/')}/chat/completions"
        
        # 构建请求体，替换模型名
        body = request.model_dump(exclude_none=True)
        body["model"] = actual_model
        body["stream"] = True
        # 请求包含 usage 信息（如果 Provider 支持）
        body["stream_options"] = {"include_usage": True}
        
        headers = {
            "Authorization": f"Bearer {provider.config.api_key}",
            "Content-Type": "application/json"
        }
        
        try:
            async with client.stream(
                "POST",
                url,
                json=body,
                headers=headers,
                timeout=self._get_timeout(provider)
            ) as response:
                if response.status_code != 200:
                    error_body = await response.aread()
                    raise ProxyError(
                        f"HTTP {response.status_code}: {error_body.decode()[:200]}",
                        status_code=response.status_code,
                        provider_name=provider.config.name,
                        actual_model=actual_model
                    )
                
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    
                    # 处理 SSE 格式
                    if line.startswith("data: "):
                        data = line[6:]  # 移除 "data: " 前缀
                        
                        if data.strip() == "[DONE]":
                            yield "data: [DONE]\n\n"
                            break
                        
                        # 解析并替换模型名
                        try:
                            chunk = json.loads(data)
                            if "model" in chunk:
                                chunk["model"] = original_model
                            
                            # 提取流式响应中的 usage 信息（通常在最后一个 chunk 中）
                            if stream_context is not None and "usage" in chunk:
                                usage = chunk["usage"]
                                stream_context.request_tokens = usage.get("prompt_tokens")
                                stream_context.response_tokens = usage.get("completion_tokens")
                                stream_context.total_tokens = usage.get("total_tokens")
                            
                            yield f"data: {json.dumps(chunk)}\n\n"
                        except json.JSONDecodeError:
                            # 无法解析的直接透传
                            yield f"data: {data}\n\n"
                    else:
                        # 非 data 行直接透传
                        yield f"{line}\n"
                        
        except httpx.TimeoutException:
            raise ProxyError(
                "流式请求超时",
                status_code=408,
                provider_name=provider.config.name,
                actual_model=actual_model
            )
        except httpx.RequestError as e:
            raise ProxyError(
                f"流式网络错误: {str(e)}",
                status_code=502,
                provider_name=provider.config.name,
                actual_model=actual_model
            )
    
    @staticmethod
    def generate_response_id() -> str:
        """生成响应 ID"""
        return f"chatcmpl-{uuid.uuid4().hex[:24]}"
    
    @staticmethod
    def _log_info(message: str) -> None:
        """输出信息日志"""
        print(f"{Fore.BLUE}[PROXY]{Style.RESET_ALL} {message}")
    
    @staticmethod
    def _log_warning(message: str) -> None:
        """输出警告日志"""
        print(f"{Fore.YELLOW}[PROXY]{Style.RESET_ALL} {message}")
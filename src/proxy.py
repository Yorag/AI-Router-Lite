"""
请求代理模块

负责将请求转发到上游 Provider，支持流式和非流式响应
"""

import json
import time
import uuid
from typing import AsyncIterator, Optional

import httpx
from colorama import Fore, Style

from .config import AppConfig
from .models import ChatCompletionRequest
from .provider import ProviderManager, ProviderState
from .router import ModelRouter


class ProxyError(Exception):
    """代理错误"""
    
    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        provider_name: Optional[str] = None
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.provider_name = provider_name


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
    ) -> dict:
        """
        转发非流式请求（带重试机制）
        
        Args:
            request: 聊天补全请求
            original_model: 用户请求的原始模型名
            
        Returns:
            响应字典
            
        Raises:
            ProxyError: 所有 Provider 都失败时抛出
        """
        tried_providers: set[str] = set()
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
            tried_providers.add(provider.config.name)
            
            self._log_info(
                f"[尝试 {attempt + 1}/{self.config.max_retries}] "
                f"Provider: {provider.config.name}, 模型: {actual_model}"
            )
            
            try:
                response = await self._do_request(provider, request, actual_model)
                self.provider_manager.mark_success(provider.config.name)
                
                # 将响应中的模型名替换回用户请求的模型名
                if "model" in response:
                    response["model"] = original_model
                
                return response
                
            except ProxyError as e:
                last_error = e
                self.provider_manager.mark_failure(
                    provider.config.name,
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
        original_model: str
    ) -> AsyncIterator[str]:
        """
        转发流式请求（带重试机制）
        
        Args:
            request: 聊天补全请求
            original_model: 用户请求的原始模型名
            
        Yields:
            SSE 格式的响应数据块
            
        Raises:
            ProxyError: 所有 Provider 都失败时抛出
        """
        tried_providers: set[str] = set()
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
            tried_providers.add(provider.config.name)
            
            self._log_info(
                f"[流式尝试 {attempt + 1}/{self.config.max_retries}] "
                f"Provider: {provider.config.name}, 模型: {actual_model}"
            )
            
            try:
                async for chunk in self._do_stream_request(provider, request, actual_model, original_model):
                    yield chunk
                
                self.provider_manager.mark_success(provider.config.name)
                return  # 成功完成，退出重试循环
                
            except ProxyError as e:
                last_error = e
                self.provider_manager.mark_failure(
                    provider.config.name,
                    status_code=e.status_code,
                    error_message=e.message
                )
                self._log_warning(
                    f"Provider [{provider.config.name}] 流式请求失败: {e.message}"
                )
                continue
        
        # 所有重试都失败
        raise last_error or ProxyError("流式请求失败", status_code=500)
    
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
                timeout=provider.config.timeout
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
        original_model: str
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
                timeout=provider.config.timeout
            ) as response:
                if response.status_code != 200:
                    error_body = await response.aread()
                    raise ProxyError(
                        f"HTTP {response.status_code}: {error_body.decode()[:200]}",
                        status_code=response.status_code,
                        provider_name=provider.config.name
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
                provider_name=provider.config.name
            )
        except httpx.RequestError as e:
            raise ProxyError(
                f"流式网络错误: {str(e)}",
                status_code=502,
                provider_name=provider.config.name
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
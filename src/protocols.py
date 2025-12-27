"""
协议适配器模块

本模块定义多协议支持，负责解析请求、构建上游 URL 和处理响应。
支持的协议类型：
- openai: 标准 OpenAI Chat Completions (/v1/chat/completions)
- openai-response: OpenAI Responses API (/v1/responses)
- anthropic: Anthropic Claude Messages API (/v1/messages)
- gemini: Google Gemini API (/models)
"""

import json
import time
import uuid
import re
from abc import ABC, abstractmethod
from typing import Optional, Any, Tuple, Dict, Union
from dataclasses import dataclass

from .constants import HEALTH_TEST_MAX_TOKENS, HEALTH_TEST_MESSAGE, DEFAULT_USER_AGENT, BLOCKED_HEADERS

@dataclass
class ProtocolRequest:
    """协议请求数据"""
    url: str  # 完整的上游 URL
    headers: Dict[str, str]  # 请求头
    body: Union[Dict, bytes]  # 请求体
    stream: bool = False  # 是否流式请求

@dataclass
class ProtocolResponse:
    """协议响应数据"""
    response: Any  # 响应内容
    request_tokens: Optional[int] = None
    response_tokens: Optional[int] = None
    total_tokens: Optional[int] = None

class BaseProtocol(ABC):
    """协议适配器基类"""

    @property
    @abstractmethod
    def protocol_type(self) -> str:
        """协议类型标识"""
        pass

    @abstractmethod
    def parse_request(self, request_body: Dict[str, Any]) -> Tuple[str, bool]:
        """
        解析请求体，提取模型名称和流式标志
        
        Returns:
            (model_name, is_stream)
        """
        pass

    @abstractmethod
    def build_request(
        self,
        base_url: str,
        api_key: str,
        original_request: Dict[str, Any],
        actual_model: str,
        client_headers: Optional[Dict[str, str]] = None
    ) -> ProtocolRequest:
        """
        构建发送给上游 Provider 的请求

        Args:
            base_url: Provider 的基础 URL
            api_key: Provider 的 API Key
            original_request: 原始请求体 (dict)
            actual_model: 实际使用的模型名称 (可能经过映射)
            client_headers: 客户端请求头（用于穿透）

        Returns:
            ProtocolRequest 对象
        """
        pass

    def _filter_passthrough_headers(self, client_headers: Optional[Dict[str, str]]) -> Dict[str, str]:
        """
        过滤客户端请求头，排除黑名单中的头，其他全部穿透。
        如果客户端未提供 User-Agent，则使用默认值。
        """
        if not client_headers:
            return {"User-Agent": DEFAULT_USER_AGENT}

        result = {
            key: value
            for key, value in client_headers.items()
            if key.lower() not in BLOCKED_HEADERS
        }

        # 如果客户端未提供 User-Agent，使用默认值
        if not any(k.lower() == "user-agent" for k in result):
            result["User-Agent"] = DEFAULT_USER_AGENT

        return result

    @abstractmethod
    def get_health_check_body(self, model: str) -> Dict[str, Any]:
        """返回健康检测用的最小请求体"""
        pass

    def transform_response(self, raw_response: Any, original_model: str) -> ProtocolResponse:
        """
        处理非流式响应（默认透传）
        """
        return ProtocolResponse(response=raw_response)

    def transform_stream_chunk(self, chunk: str, original_model: str) -> Tuple[str, Optional[Dict[str, int]]]:
        """
        处理流式响应块（默认透传）
        
        Returns:
            (processed_chunk, usage_info)
        """
        return chunk, None

    @staticmethod
    def generate_response_id() -> str:
        """生成响应 ID"""
        return f"req-{uuid.uuid4().hex[:24]}"

    @staticmethod
    def get_timestamp() -> int:
        """获取当前时间戳"""
        return int(time.time())


class OpenAIProtocol(BaseProtocol):
    """
    OpenAI Chat Completions 协议适配器
    端点: /v1/chat/completions
    """

    @property
    def protocol_type(self) -> str:
        return "openai"

    def parse_request(self, request_body: Dict[str, Any]) -> Tuple[str, bool]:
        model = request_body.get("model", "")
        stream = request_body.get("stream", False)
        return model, stream

    def build_request(
        self,
        base_url: str,
        api_key: str,
        original_request: Dict[str, Any],
        actual_model: str,
        client_headers: Optional[Dict[str, str]] = None
    ) -> ProtocolRequest:
        url = f"{base_url.rstrip('/')}/chat/completions"

        body = original_request.copy()
        body["model"] = actual_model

        if body.get("stream"):
            if "stream_options" not in body:
                body["stream_options"] = {"include_usage": True}

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        headers.update(self._filter_passthrough_headers(client_headers))

        return ProtocolRequest(
            url=url,
            headers=headers,
            body=body,
            stream=body.get("stream", False)
        )

    def get_health_check_body(self, model: str) -> Dict[str, Any]:
        return {"model": model, "messages": [{"role": "user", "content": HEALTH_TEST_MESSAGE}], "max_tokens": HEALTH_TEST_MAX_TOKENS}

    def transform_response(self, raw_response: dict, original_model: str) -> ProtocolResponse:
        # 替换模型名为用户请求的原始模型名
        if isinstance(raw_response, dict):
            if "model" in raw_response:
                raw_response["model"] = original_model
            
            # 提取 usage
            usage = raw_response.get("usage", {})
            return ProtocolResponse(
                response=raw_response,
                request_tokens=usage.get("prompt_tokens"),
                response_tokens=usage.get("completion_tokens"),
                total_tokens=usage.get("total_tokens")
            )
        return ProtocolResponse(response=raw_response)

    def transform_stream_chunk(self, raw_line: str, original_model: str) -> Tuple[str, Optional[Dict[str, int]]]:
        if not raw_line.startswith("data: "):
            return raw_line + "\n", None
        
        data = raw_line[6:]
        if data.strip() == "[DONE]":
            return raw_line + "\n", None
            
        try:
            chunk = json.loads(data)
            if "model" in chunk:
                chunk["model"] = original_model
                
            usage = None
            if "usage" in chunk and chunk["usage"]:
                usage = chunk["usage"]
                
            return f"data: {json.dumps(chunk)}\n\n", usage
        except json.JSONDecodeError:
            return raw_line + "\n", None


class OpenAIResponseProtocol(BaseProtocol):
    """
    OpenAI Responses API 协议适配器 (Beta)
    端点: /v1/responses
    """

    @property
    def protocol_type(self) -> str:
        return "openai-response"

    def parse_request(self, request_body: Dict[str, Any]) -> Tuple[str, bool]:
        model = request_body.get("model", "")
        stream = request_body.get("stream", False)
        return model, stream

    def build_request(
        self,
        base_url: str,
        api_key: str,
        original_request: Dict[str, Any],
        actual_model: str,
        client_headers: Optional[Dict[str, str]] = None
    ) -> ProtocolRequest:
        url = f"{base_url.rstrip('/')}/responses"

        body = original_request.copy()
        body["model"] = actual_model

        if "max_output_tokens" in body:
            body.setdefault("max_tokens", body.pop("max_output_tokens"))

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        headers.update(self._filter_passthrough_headers(client_headers))

        return ProtocolRequest(
            url=url,
            headers=headers,
            body=body,
            stream=body.get("stream", False)
        )

    def get_health_check_body(self, model: str) -> Dict[str, Any]:
        return {"model": model, "input": HEALTH_TEST_MESSAGE, "max_output_tokens": HEALTH_TEST_MAX_TOKENS}

    def transform_response(self, raw_response: dict, original_model: str) -> ProtocolResponse:
        # Responses API 结构与 Chat API 略有不同，但仍包含 model 字段
        if isinstance(raw_response, dict):
            if "model" in raw_response:
                raw_response["model"] = original_model
            
            # 提取 usage (Responses API 使用 input_tokens/output_tokens 而非 prompt_tokens/completion_tokens)
            usage = raw_response.get("usage", {})
            return ProtocolResponse(
                response=raw_response,
                request_tokens=usage.get("input_tokens"),
                response_tokens=usage.get("output_tokens"),
                total_tokens=usage.get("total_tokens")
            )
        return ProtocolResponse(response=raw_response)

    def transform_stream_chunk(self, raw_line: str, original_model: str) -> Tuple[str, Optional[Dict[str, int]]]:
        # Responses API 流式格式与 Chat API 类似
        if not raw_line.startswith("data: "):
            return raw_line + "\n", None
        
        data = raw_line[6:]
        if data.strip() == "[DONE]":
            return raw_line + "\n", None
            
        try:
            chunk = json.loads(data)
            if "model" in chunk:
                chunk["model"] = original_model
                
            usage = None
            if "usage" in chunk and chunk["usage"]:
                # Responses API 使用 input_tokens/output_tokens，转换为统一格式
                raw_usage = chunk["usage"]
                usage = {
                    "prompt_tokens": raw_usage.get("input_tokens", 0),
                    "completion_tokens": raw_usage.get("output_tokens", 0),
                    "total_tokens": raw_usage.get("total_tokens", 0)
                }
                
            return f"data: {json.dumps(chunk)}\n\n", usage
        except json.JSONDecodeError:
            return raw_line + "\n", None


class AnthropicProtocol(BaseProtocol):
    """
    Anthropic Claude Messages API 协议适配器
    端点: /v1/messages
    """

    @property
    def protocol_type(self) -> str:
        return "anthropic"

    def parse_request(self, request_body: Dict[str, Any]) -> Tuple[str, bool]:
        model = request_body.get("model", "")
        stream = request_body.get("stream", False)
        return model, stream

    def build_request(
        self,
        base_url: str,
        api_key: str,
        original_request: Dict[str, Any],
        actual_model: str,
        client_headers: Optional[Dict[str, str]] = None
    ) -> ProtocolRequest:
        base = base_url.rstrip('/')
        if base.endswith("/v1"):
            url = f"{base}/messages"
        else:
            url = f"{base}/v1/messages"

        body = original_request.copy()
        body["model"] = actual_model

        headers = {
            "x-api-key": api_key,
            # "Authorization": f"Bearer {api_key}",
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json"
        }
        headers.update(self._filter_passthrough_headers(client_headers))

        return ProtocolRequest(
            url=url,
            headers=headers,
            body=body,
            stream=body.get("stream", False)
        )

    def get_health_check_body(self, model: str) -> Dict[str, Any]:
        return {"model": model, "messages": [{"role": "user", "content": HEALTH_TEST_MESSAGE}], "max_tokens": HEALTH_TEST_MAX_TOKENS}

    def transform_response(self, raw_response: dict, original_model: str) -> ProtocolResponse:
        if isinstance(raw_response, dict):
            if "model" in raw_response:
                raw_response["model"] = original_model
                
            usage = raw_response.get("usage", {})
            return ProtocolResponse(
                response=raw_response,
                request_tokens=usage.get("input_tokens"),
                response_tokens=usage.get("output_tokens"),
                total_tokens=(usage.get("input_tokens", 0) + usage.get("output_tokens", 0))
            )
        return ProtocolResponse(response=raw_response)

    def transform_stream_chunk(self, raw_line: str, original_model: str) -> Tuple[str, Optional[Dict[str, int]]]:
        # Anthropic SSE 格式:
        # event: message_start
        # data: {"type": "message_start", "message": {...}}
        # 
        # event: content_block_delta
        # data: {"type": "content_block_delta", "index": 0, "delta": {...}}
        
        if raw_line.startswith("data: "):
            try:
                data_str = raw_line[6:]
                chunk = json.loads(data_str)
                
                # 替换模型名 (仅在 message_start 事件中出现)
                if chunk.get("type") == "message_start" and "message" in chunk:
                    if "model" in chunk["message"]:
                        chunk["message"]["model"] = original_model
                
                # 提取 usage
                usage = None
                if chunk.get("type") == "message_start" and "message" in chunk:
                    msg_usage = chunk["message"].get("usage", {})
                    if msg_usage:
                        usage = {
                            "prompt_tokens": msg_usage.get("input_tokens", 0),
                            "completion_tokens": msg_usage.get("output_tokens", 0),
                            "total_tokens": msg_usage.get("input_tokens", 0) + msg_usage.get("output_tokens", 0)
                        }
                
                elif chunk.get("type") == "message_delta" and "usage" in chunk:
                     msg_usage = chunk.get("usage", {})
                     # message_delta 只包含 output_tokens
                     if msg_usage:
                         usage = {
                             "completion_tokens": msg_usage.get("output_tokens", 0)
                         }

                return f"data: {json.dumps(chunk)}\n\n", usage
            except json.JSONDecodeError:
                pass
                
        return raw_line + "\n", None


class GeminiProtocol(BaseProtocol):
    """
    Google Gemini API 协议适配器
    端点: /v1beta/models/{model}:generateContent
    """

    @property
    def protocol_type(self) -> str:
        return "gemini"

    def parse_request(self, request_body: Dict[str, Any]) -> Tuple[str, bool]:
        model = request_body.get("model", "")
        stream = request_body.get("stream", False)
        return model, stream

    def build_request(
        self,
        base_url: str,
        api_key: str,
        original_request: Dict[str, Any],
        actual_model: str,
        client_headers: Optional[Dict[str, str]] = None
    ) -> ProtocolRequest:
        method = "streamGenerateContent" if original_request.get("stream") else "generateContent"

        base = base_url.rstrip('/')
        url = f"{base}/models/{actual_model}:{method}?key={api_key}"

        body = original_request.copy()
        body.pop("model", None)
        body.pop("stream", None)

        headers = {
            "Content-Type": "application/json"
        }
        headers.update(self._filter_passthrough_headers(client_headers))

        return ProtocolRequest(
            url=url,
            headers=headers,
            body=body,
            stream=original_request.get("stream", False)
        )

    def get_health_check_body(self, model: str) -> Dict[str, Any]:
        return {"model": model, "contents": [{"parts": [{"text": HEALTH_TEST_MESSAGE}]}], "generationConfig": {"maxOutputTokens": HEALTH_TEST_MAX_TOKENS}}

    def transform_response(self, raw_response: Any, original_model: str) -> ProtocolResponse:
        # Gemini 响应处理
        return ProtocolResponse(response=raw_response)


# ==================== 协议工厂 ====================

_protocols = {
    "openai": OpenAIProtocol(),
    "openai-response": OpenAIResponseProtocol(),
    "anthropic": AnthropicProtocol(),
    "gemini": GeminiProtocol()
}

def get_protocol(protocol_type: str) -> Optional[BaseProtocol]:
    """获取协议适配器实例"""
    return _protocols.get(protocol_type)

def is_supported_protocol(protocol_type: str) -> bool:
    """检查协议是否支持"""
    return protocol_type in _protocols
"""
协议适配器模块

负责将系统内部的 OpenAI 格式请求转换为各种上游 API 格式，
并将上游响应转换回 OpenAI 格式。

支持的协议：
- OpenAI: 标准 OpenAI Chat Completions (/v1/chat/completions)
- OpenAI-Response: OpenAI Responses API (/v1/responses)
- Anthropic: Anthropic Claude Messages API (/v1/messages)
- Gemini: Google Gemini API (/models)
"""

import json
import time
import uuid
from abc import ABC, abstractmethod
from typing import Optional, Any, AsyncIterator, Dict, List
from dataclasses import dataclass

from .config import ProtocolType
from .models import ChatCompletionRequest, ChatMessage


@dataclass
class ProtocolRequest:
    """协议请求数据"""
    url: str  # 完整请求 URL
    headers: dict[str, str]  # 请求头
    body: dict  # 请求体


@dataclass
class ProtocolResponse:
    """协议响应数据（转换为 OpenAI 格式）"""
    response: dict  # OpenAI 格式的响应
    request_tokens: Optional[int] = None
    response_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


class BaseProtocol(ABC):
    """
    协议适配器基类
    
    所有协议适配器都需要实现以下方法：
    - get_endpoint: 获取 API 端点路径
    - build_request: 构建协议特定的请求
    - transform_response: 将响应转换为 OpenAI 格式
    - transform_stream_chunk: 将流式响应块转换为 OpenAI 格式
    """
    
    @property
    @abstractmethod
    def protocol_type(self) -> ProtocolType:
        """返回协议类型"""
        pass
    
    @abstractmethod
    def get_endpoint(self, base_url: str, model: str) -> str:
        """
        获取完整的 API 端点 URL
        
        Args:
            base_url: Provider 的基础 URL
            model: 模型名称
            
        Returns:
            完整的 API URL
        """
        pass
    
    @abstractmethod
    def build_request(
        self,
        request: ChatCompletionRequest,
        api_key: str,
        model: str
    ) -> ProtocolRequest:
        """
        构建协议特定的请求
        
        Args:
            request: 原始 OpenAI 格式请求
            api_key: API 密钥
            model: 实际使用的模型名称
            
        Returns:
            ProtocolRequest 对象
        """
        pass
    
    @abstractmethod
    def transform_response(self, raw_response: dict, original_model: str) -> ProtocolResponse:
        """
        将协议响应转换为 OpenAI 格式
        
        Args:
            raw_response: 原始 API 响应
            original_model: 用户请求的原始模型名（用于替换响应中的模型名）
            
        Returns:
            ProtocolResponse 对象
        """
        pass
    
    @abstractmethod
    def transform_stream_chunk(
        self,
        raw_line: str,
        original_model: str
    ) -> tuple[Optional[str], Optional[dict]]:
        """
        转换流式响应块
        
        Args:
            raw_line: 原始响应行
            original_model: 用户请求的原始模型名
            
        Returns:
            (转换后的 SSE 数据, 提取的 usage 信息或 None)
        """
        pass
    
    @staticmethod
    def generate_response_id() -> str:
        """生成响应 ID"""
        return f"chatcmpl-{uuid.uuid4().hex[:24]}"
    
    @staticmethod
    def get_timestamp() -> int:
        """获取当前时间戳"""
        return int(time.time())


class OpenAIProtocol(BaseProtocol):
    """
    OpenAI Chat Completions 协议适配器
    
    端点: /v1/chat/completions
    这是默认协议，基本上是透传模式
    """
    
    @property
    def protocol_type(self) -> ProtocolType:
        return ProtocolType.OPENAI
    
    def get_endpoint(self, base_url: str, model: str) -> str:
        return f"{base_url.rstrip('/')}/chat/completions"
    
    def build_request(
        self,
        request: ChatCompletionRequest,
        api_key: str,
        model: str
    ) -> ProtocolRequest:
        # 构建请求体
        body = request.model_dump(exclude_none=True)
        body["model"] = model
        
        # 如果是流式请求，添加 stream_options
        if body.get("stream"):
            body["stream_options"] = {"include_usage": True}
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        return ProtocolRequest(
            url="",  # URL 由 get_endpoint 提供
            headers=headers,
            body=body
        )
    
    def transform_response(self, raw_response: dict, original_model: str) -> ProtocolResponse:
        # OpenAI 格式直接透传，只替换模型名
        if "model" in raw_response:
            raw_response["model"] = original_model
        
        # 提取 token 使用量
        usage = raw_response.get("usage", {})
        
        return ProtocolResponse(
            response=raw_response,
            request_tokens=usage.get("prompt_tokens"),
            response_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens")
        )
    
    def transform_stream_chunk(
        self,
        raw_line: str,
        original_model: str
    ) -> tuple[Optional[str], Optional[dict]]:
        if not raw_line.startswith("data: "):
            return None, None
        
        data = raw_line[6:]  # 移除 "data: " 前缀
        
        if data.strip() == "[DONE]":
            return "data: [DONE]\n\n", None
        
        try:
            chunk = json.loads(data)
            if "model" in chunk:
                chunk["model"] = original_model
            
            # 提取 usage 信息
            usage = None
            if "usage" in chunk and chunk["usage"] is not None:
                usage = chunk["usage"]
            
            return f"data: {json.dumps(chunk)}\n\n", usage
        except json.JSONDecodeError:
            return f"data: {data}\n\n", None


class OpenAIResponseProtocol(BaseProtocol):
    """
    OpenAI Responses API 协议适配器
    
    端点: /v1/responses
    这是 OpenAI 的新 Responses API 格式
    """
    
    @property
    def protocol_type(self) -> ProtocolType:
        return ProtocolType.OPENAI_RESPONSE
    
    def get_endpoint(self, base_url: str, model: str) -> str:
        return f"{base_url.rstrip('/')}/responses"
    
    def build_request(
        self,
        request: ChatCompletionRequest,
        api_key: str,
        model: str
    ) -> ProtocolRequest:
        # 转换为 Responses API 格式
        # Responses API 使用 input 而不是 messages
        body = {
            "model": model,
            "input": self._convert_messages_to_input(request.messages),
        }
        
        # 添加可选参数
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.max_tokens is not None:
            body["max_output_tokens"] = request.max_tokens
        if request.top_p is not None:
            body["top_p"] = request.top_p
        if request.stream:
            body["stream"] = True
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        return ProtocolRequest(
            url="",
            headers=headers,
            body=body
        )
    
    def _convert_messages_to_input(self, messages: list[ChatMessage]) -> list[dict]:
        """将 messages 格式转换为 Responses API 的 input 格式"""
        result = []
        for msg in messages:
            item = {
                "role": msg.role,
                "content": msg.content or ""
            }
            result.append(item)
        return result
    
    def transform_response(self, raw_response: dict, original_model: str) -> ProtocolResponse:
        # 将 Responses API 响应转换为 Chat Completions 格式
        output = raw_response.get("output", [])
        content = ""
        
        # 提取输出内容
        for item in output:
            if item.get("type") == "message":
                for content_item in item.get("content", []):
                    if content_item.get("type") == "output_text":
                        content += content_item.get("text", "")
        
        # 构建 OpenAI 格式响应
        response = {
            "id": raw_response.get("id", self.generate_response_id()),
            "object": "chat.completion",
            "created": self.get_timestamp(),
            "model": original_model,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content
                },
                "finish_reason": raw_response.get("status", "stop")
            }],
            "usage": raw_response.get("usage", {})
        }
        
        usage = raw_response.get("usage", {})
        return ProtocolResponse(
            response=response,
            request_tokens=usage.get("input_tokens"),
            response_tokens=usage.get("output_tokens"),
            total_tokens=usage.get("total_tokens")
        )
    
    def transform_stream_chunk(
        self,
        raw_line: str,
        original_model: str
    ) -> tuple[Optional[str], Optional[dict]]:
        if not raw_line.startswith("data: "):
            return None, None
        
        data = raw_line[6:]
        
        if data.strip() == "[DONE]":
            return "data: [DONE]\n\n", None
        
        try:
            chunk = json.loads(data)
            
            # 转换为 Chat Completions 流式格式
            output_chunk = {
                "id": chunk.get("id", self.generate_response_id()),
                "object": "chat.completion.chunk",
                "created": self.get_timestamp(),
                "model": original_model,
                "choices": [{
                    "index": 0,
                    "delta": {},
                    "finish_reason": None
                }]
            }
            
            # 提取文本内容
            if chunk.get("type") == "response.output_text.delta":
                output_chunk["choices"][0]["delta"]["content"] = chunk.get("delta", "")
            elif chunk.get("type") == "response.completed":
                output_chunk["choices"][0]["finish_reason"] = "stop"
                # 提取 usage
                if "usage" in chunk:
                    output_chunk["usage"] = chunk["usage"]
                    return f"data: {json.dumps(output_chunk)}\n\n", chunk["usage"]
            
            return f"data: {json.dumps(output_chunk)}\n\n", None
        except json.JSONDecodeError:
            return None, None


class AnthropicProtocol(BaseProtocol):
    """
    Anthropic Claude Messages API 协议适配器
    
    端点: /v1/messages
    """
    
    ANTHROPIC_VERSION = "2023-06-01"
    
    @property
    def protocol_type(self) -> ProtocolType:
        return ProtocolType.ANTHROPIC
    
    def get_endpoint(self, base_url: str, model: str) -> str:
        return f"{base_url.rstrip('/')}/messages"
    
    def build_request(
        self,
        request: ChatCompletionRequest,
        api_key: str,
        model: str
    ) -> ProtocolRequest:
        # 转换为 Anthropic Messages API 格式
        system_content, messages = self._convert_messages(request.messages)
        
        body = {
            "model": model,
            "messages": messages,
            "max_tokens": request.max_tokens or 4096,  # Anthropic 要求必须指定
        }
        
        # 添加 system prompt
        if system_content:
            body["system"] = system_content
        
        # 添加可选参数
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.top_p is not None:
            body["top_p"] = request.top_p
        if request.stop:
            stop_sequences = request.stop if isinstance(request.stop, list) else [request.stop]
            body["stop_sequences"] = stop_sequences
        if request.stream:
            body["stream"] = True
        
        headers = {
            "x-api-key": api_key,
            "anthropic-version": self.ANTHROPIC_VERSION,
            "Content-Type": "application/json"
        }
        
        return ProtocolRequest(
            url="",
            headers=headers,
            body=body
        )
    
    def _convert_messages(self, messages: list[ChatMessage]) -> tuple[str, list[dict]]:
        """
        将 OpenAI messages 转换为 Anthropic 格式
        
        Returns:
            (system_content, messages_list)
        """
        system_content = ""
        anthropic_messages = []
        
        for msg in messages:
            if msg.role == "system":
                system_content += (msg.content or "") + "\n"
            else:
                role = "user" if msg.role == "user" else "assistant"
                anthropic_messages.append({
                    "role": role,
                    "content": msg.content or ""
                })
        
        return system_content.strip(), anthropic_messages
    
    def transform_response(self, raw_response: dict, original_model: str) -> ProtocolResponse:
        # 将 Anthropic 响应转换为 OpenAI 格式
        content = ""
        for block in raw_response.get("content", []):
            if block.get("type") == "text":
                content += block.get("text", "")
        
        # 映射结束原因
        stop_reason_map = {
            "end_turn": "stop",
            "max_tokens": "length",
            "stop_sequence": "stop"
        }
        finish_reason = stop_reason_map.get(
            raw_response.get("stop_reason", ""), 
            raw_response.get("stop_reason", "stop")
        )
        
        # 构建 OpenAI 格式响应
        response = {
            "id": raw_response.get("id", self.generate_response_id()),
            "object": "chat.completion",
            "created": self.get_timestamp(),
            "model": original_model,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content
                },
                "finish_reason": finish_reason
            }],
            "usage": {
                "prompt_tokens": raw_response.get("usage", {}).get("input_tokens", 0),
                "completion_tokens": raw_response.get("usage", {}).get("output_tokens", 0),
                "total_tokens": (
                    raw_response.get("usage", {}).get("input_tokens", 0) +
                    raw_response.get("usage", {}).get("output_tokens", 0)
                )
            }
        }
        
        usage = raw_response.get("usage", {})
        return ProtocolResponse(
            response=response,
            request_tokens=usage.get("input_tokens"),
            response_tokens=usage.get("output_tokens"),
            total_tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
        )
    
    def transform_stream_chunk(
        self,
        raw_line: str,
        original_model: str
    ) -> tuple[Optional[str], Optional[dict]]:
        if not raw_line.startswith("data: "):
            # Anthropic 也可能发送 event: 行，跳过
            return None, None
        
        data = raw_line[6:]
        
        try:
            chunk = json.loads(data)
            event_type = chunk.get("type", "")
            
            # 构建 OpenAI 格式的流式响应
            output_chunk = {
                "id": chunk.get("message", {}).get("id", self.generate_response_id()),
                "object": "chat.completion.chunk",
                "created": self.get_timestamp(),
                "model": original_model,
                "choices": [{
                    "index": 0,
                    "delta": {},
                    "finish_reason": None
                }]
            }
            
            if event_type == "message_start":
                # 消息开始，返回角色
                output_chunk["choices"][0]["delta"]["role"] = "assistant"
                return f"data: {json.dumps(output_chunk)}\n\n", None
            
            elif event_type == "content_block_delta":
                # 内容增量
                delta = chunk.get("delta", {})
                if delta.get("type") == "text_delta":
                    output_chunk["choices"][0]["delta"]["content"] = delta.get("text", "")
                    return f"data: {json.dumps(output_chunk)}\n\n", None
            
            elif event_type == "message_delta":
                # 消息结束，包含 stop_reason
                stop_reason = chunk.get("delta", {}).get("stop_reason")
                if stop_reason:
                    stop_reason_map = {
                        "end_turn": "stop",
                        "max_tokens": "length",
                        "stop_sequence": "stop"
                    }
                    output_chunk["choices"][0]["finish_reason"] = stop_reason_map.get(stop_reason, stop_reason)
                
                # 提取 usage
                usage = chunk.get("usage", {})
                if usage:
                    output_usage = {
                        "prompt_tokens": usage.get("input_tokens", 0),
                        "completion_tokens": usage.get("output_tokens", 0),
                        "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
                    }
                    output_chunk["usage"] = output_usage
                    return f"data: {json.dumps(output_chunk)}\n\n", output_usage
                
                return f"data: {json.dumps(output_chunk)}\n\n", None
            
            elif event_type == "message_stop":
                # 消息完全结束
                return "data: [DONE]\n\n", None
            
            return None, None
            
        except json.JSONDecodeError:
            return None, None


class GeminiProtocol(BaseProtocol):
    """
    Google Gemini API 协议适配器
    
    端点: /v1beta/models/{model}:generateContent
    """
    
    @property
    def protocol_type(self) -> ProtocolType:
        return ProtocolType.GEMINI
    
    def get_endpoint(self, base_url: str, model: str) -> str:
        # Gemini API 的模型名在 URL 中
        return f"{base_url.rstrip('/')}/models/{model}:generateContent"
    
    def get_stream_endpoint(self, base_url: str, model: str) -> str:
        """获取流式 API 端点"""
        return f"{base_url.rstrip('/')}/models/{model}:streamGenerateContent"
    
    def build_request(
        self,
        request: ChatCompletionRequest,
        api_key: str,
        model: str
    ) -> ProtocolRequest:
        # 转换为 Gemini API 格式
        contents = self._convert_messages(request.messages)
        
        body = {
            "contents": contents,
        }
        
        # 构建 generationConfig
        generation_config = {}
        if request.temperature is not None:
            generation_config["temperature"] = request.temperature
        if request.max_tokens is not None:
            generation_config["maxOutputTokens"] = request.max_tokens
        if request.top_p is not None:
            generation_config["topP"] = request.top_p
        if request.stop:
            stop_sequences = request.stop if isinstance(request.stop, list) else [request.stop]
            generation_config["stopSequences"] = stop_sequences
        
        if generation_config:
            body["generationConfig"] = generation_config
        
        # Gemini 使用 URL 参数传递 API key
        headers = {
            "Content-Type": "application/json"
        }
        
        # 在这里我们用特殊标记表示需要在 URL 中添加 key
        # 实际的 URL 构建在 proxy 中处理
        return ProtocolRequest(
            url=f"?key={api_key}",  # 将作为 URL 参数
            headers=headers,
            body=body
        )
    
    def _convert_messages(self, messages: list[ChatMessage]) -> list[dict]:
        """将 OpenAI messages 转换为 Gemini contents 格式"""
        contents = []
        
        # 合并连续的相同角色消息
        for msg in messages:
            role = "user" if msg.role in ["user", "system"] else "model"
            
            part = {"text": msg.content or ""}
            
            # 如果最后一条消息是相同角色，合并内容
            if contents and contents[-1]["role"] == role:
                contents[-1]["parts"].append(part)
            else:
                contents.append({
                    "role": role,
                    "parts": [part]
                })
        
        return contents
    
    def transform_response(self, raw_response: dict, original_model: str) -> ProtocolResponse:
        # 将 Gemini 响应转换为 OpenAI 格式
        candidates = raw_response.get("candidates", [])
        content = ""
        finish_reason = "stop"
        
        if candidates:
            candidate = candidates[0]
            parts = candidate.get("content", {}).get("parts", [])
            for part in parts:
                if "text" in part:
                    content += part["text"]
            
            # 映射结束原因
            finish_reason_map = {
                "STOP": "stop",
                "MAX_TOKENS": "length",
                "SAFETY": "content_filter",
                "RECITATION": "content_filter"
            }
            finish_reason = finish_reason_map.get(
                candidate.get("finishReason", "STOP"),
                "stop"
            )
        
        # 提取 usage
        usage_metadata = raw_response.get("usageMetadata", {})
        prompt_tokens = usage_metadata.get("promptTokenCount", 0)
        completion_tokens = usage_metadata.get("candidatesTokenCount", 0)
        total_tokens = usage_metadata.get("totalTokenCount", prompt_tokens + completion_tokens)
        
        # 构建 OpenAI 格式响应
        response = {
            "id": self.generate_response_id(),
            "object": "chat.completion",
            "created": self.get_timestamp(),
            "model": original_model,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content
                },
                "finish_reason": finish_reason
            }],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens
            }
        }
        
        return ProtocolResponse(
            response=response,
            request_tokens=prompt_tokens,
            response_tokens=completion_tokens,
            total_tokens=total_tokens
        )
    
    def transform_stream_chunk(
        self,
        raw_line: str,
        original_model: str
    ) -> tuple[Optional[str], Optional[dict]]:
        # Gemini 的流式响应是 JSON 行格式
        if not raw_line.strip():
            return None, None
        
        # 处理可能的 SSE 格式
        if raw_line.startswith("data: "):
            raw_line = raw_line[6:]
        
        try:
            chunk = json.loads(raw_line)
            
            candidates = chunk.get("candidates", [])
            content = ""
            finish_reason = None
            
            if candidates:
                candidate = candidates[0]
                parts = candidate.get("content", {}).get("parts", [])
                for part in parts:
                    if "text" in part:
                        content += part["text"]
                
                if candidate.get("finishReason"):
                    finish_reason_map = {
                        "STOP": "stop",
                        "MAX_TOKENS": "length",
                        "SAFETY": "content_filter"
                    }
                    finish_reason = finish_reason_map.get(
                        candidate.get("finishReason"),
                        "stop"
                    )
            
            # 构建 OpenAI 格式的流式响应
            output_chunk = {
                "id": self.generate_response_id(),
                "object": "chat.completion.chunk",
                "created": self.get_timestamp(),
                "model": original_model,
                "choices": [{
                    "index": 0,
                    "delta": {"content": content} if content else {},
                    "finish_reason": finish_reason
                }]
            }
            
            # 提取 usage (如果有)
            usage = None
            usage_metadata = chunk.get("usageMetadata", {})
            if usage_metadata:
                usage = {
                    "prompt_tokens": usage_metadata.get("promptTokenCount", 0),
                    "completion_tokens": usage_metadata.get("candidatesTokenCount", 0),
                    "total_tokens": usage_metadata.get("totalTokenCount", 0)
                }
                output_chunk["usage"] = usage
            
            if finish_reason:
                return f"data: {json.dumps(output_chunk)}\n\ndata: [DONE]\n\n", usage
            
            return f"data: {json.dumps(output_chunk)}\n\n", usage
            
        except json.JSONDecodeError:
            return None, None


# ==================== 协议工厂 ====================


class ProtocolFactory:
    """协议适配器工厂"""
    
    _protocols: dict[str, BaseProtocol] = {}
    
    @classmethod
    def _init_protocols(cls):
        """初始化协议适配器实例"""
        if not cls._protocols:
            cls._protocols = {
                ProtocolType.OPENAI.value: OpenAIProtocol(),
                ProtocolType.OPENAI_RESPONSE.value: OpenAIResponseProtocol(),
                ProtocolType.ANTHROPIC.value: AnthropicProtocol(),
                ProtocolType.GEMINI.value: GeminiProtocol(),
            }
    
    @classmethod
    def get_protocol(cls, protocol_type: str) -> Optional[BaseProtocol]:
        """
        获取协议适配器实例
        
        Args:
            protocol_type: 协议类型字符串 (openai, openai-response, anthropic, gemini)
            
        Returns:
            协议适配器实例，如果类型无效则返回 None
        """
        cls._init_protocols()
        return cls._protocols.get(protocol_type)
    
    @classmethod
    def get_all_protocol_types(cls) -> list[str]:
        """获取所有支持的协议类型"""
        return [p.value for p in ProtocolType]
    
    @classmethod
    def is_valid_protocol(cls, protocol_type: str) -> bool:
        """检查协议类型是否有效"""
        cls._init_protocols()
        return protocol_type in cls._protocols
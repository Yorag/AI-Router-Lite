"""
协议适配器模块

本模块定义协议类型，用于路由层协议过滤。
系统只支持 OpenAI 协议入口和出口，协议字段仅用于过滤不兼容的渠道。

支持的协议类型（用于过滤）：
- openai: 标准 OpenAI Chat Completions (/v1/chat/completions)
- openai-response: OpenAI Responses API (/v1/responses)  
- anthropic: Anthropic Claude Messages API (/v1/messages)
- gemini: Google Gemini API (/models)

注意：本系统只做协议过滤，不做协议转换。
当请求进入 /v1/chat/completions 端点时，只会路由到 protocol=openai 的渠道。
"""

import json
import time
import uuid
from typing import Optional
from dataclasses import dataclass

from .models import ChatCompletionRequest


@dataclass
class ProtocolRequest:
    """协议请求数据"""
    url: str  # 额外的 URL 参数（通常为空）
    headers: dict[str, str]  # 请求头
    body: dict  # 请求体


@dataclass
class ProtocolResponse:
    """协议响应数据"""
    response: dict  # 响应内容
    request_tokens: Optional[int] = None
    response_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


class OpenAIProtocol:
    """
    OpenAI Chat Completions 协议适配器
    
    端点: /v1/chat/completions
    这是透传模式，请求直接转发，只替换模型名
    """
    
    def get_endpoint(self, base_url: str, model: str) -> str:
        """获取 API 端点 URL"""
        return f"{base_url.rstrip('/')}/chat/completions"
    
    def build_request(
        self,
        request: ChatCompletionRequest,
        api_key: str,
        model: str
    ) -> ProtocolRequest:
        """
        构建请求
        
        Args:
            request: 原始请求
            api_key: API 密钥
            model: 实际使用的模型名称
            
        Returns:
            ProtocolRequest 对象
        """
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
            url="",
            headers=headers,
            body=body
        )
    
    def transform_response(self, raw_response: dict, original_model: str) -> ProtocolResponse:
        """
        处理响应（透传，只替换模型名）
        
        Args:
            raw_response: 原始 API 响应
            original_model: 用户请求的原始模型名
            
        Returns:
            ProtocolResponse 对象
        """
        # 替换模型名为用户请求的统一模型名
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
        """
        处理流式响应块（透传，只替换模型名）
        
        Args:
            raw_line: 原始响应行
            original_model: 用户请求的原始模型名
            
        Returns:
            (处理后的 SSE 数据, 提取的 usage 信息或 None)
        """
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
    
    @staticmethod
    def generate_response_id() -> str:
        """生成响应 ID"""
        return f"chatcmpl-{uuid.uuid4().hex[:24]}"
    
    @staticmethod
    def get_timestamp() -> int:
        """获取当前时间戳"""
        return int(time.time())


# ==================== 协议工厂 ====================


# 单例协议适配器
_openai_protocol = OpenAIProtocol()


def get_protocol(protocol_type: str) -> Optional[OpenAIProtocol]:
    """
    获取协议适配器实例
    
    注意：系统只支持 OpenAI 协议，其他协议类型仅用于路由过滤。
    当 protocol_type 不是 "openai" 时，返回 None 表示不支持。
    
    Args:
        protocol_type: 协议类型字符串
        
    Returns:
        OpenAIProtocol 实例（如果是 openai 协议），否则返回 None
    """
    if protocol_type == "openai":
        return _openai_protocol
    return None


def is_supported_protocol(protocol_type: str) -> bool:
    """
    检查协议是否支持实际请求
    
    只有 openai 协议支持实际请求转发。
    其他协议类型仅用于配置和路由过滤。
    """
    return protocol_type == "openai"
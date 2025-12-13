"""
数据模型模块

定义 OpenAI 兼容的请求和响应数据结构
"""

from typing import Optional, Literal, Any, Union, List, Dict
from pydantic import BaseModel, Field

from .constants import MODEL_OWNED_BY


# ==================== 请求模型 ====================

class ChatMessage(BaseModel):
    """聊天消息"""
    role: Literal["system", "user", "assistant", "function", "tool"] = Field(
        ..., description="消息角色"
    )
    content: Optional[str] = Field(default=None, description="消息内容")
    name: Optional[str] = Field(default=None, description="发送者名称")
    function_call: Optional[dict[str, Any]] = Field(default=None, description="函数调用")
    tool_calls: Optional[list[dict[str, Any]]] = Field(default=None, description="工具调用")


class ChatCompletionRequest(BaseModel):
    """聊天补全请求 (OpenAI 兼容)"""
    model: str = Field(..., description="模型名称")
    messages: list[ChatMessage] = Field(..., description="消息列表")
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0, description="温度")
    top_p: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Top-p 采样")
    n: Optional[int] = Field(default=1, ge=1, description="生成数量")
    stream: Optional[bool] = Field(default=False, description="是否流式输出")
    stop: Optional[Union[str, List[str]]] = Field(default=None, description="停止序列")
    max_tokens: Optional[int] = Field(default=None, ge=1, description="最大 token 数")
    presence_penalty: Optional[float] = Field(default=None, ge=-2.0, le=2.0)
    frequency_penalty: Optional[float] = Field(default=None, ge=-2.0, le=2.0)
    logit_bias: Optional[dict[str, float]] = Field(default=None)
    user: Optional[str] = Field(default=None, description="用户标识")
    
    # 允许额外字段以兼容不同客户端
    model_config = {"extra": "allow"}


# ==================== 响应模型 ====================

class Usage(BaseModel):
    """Token 使用统计"""
    prompt_tokens: int = Field(default=0, description="提示词 token 数")
    completion_tokens: int = Field(default=0, description="补全 token 数")
    total_tokens: int = Field(default=0, description="总 token 数")


class ChoiceMessage(BaseModel):
    """响应中的消息"""
    role: str = Field(default="assistant", description="角色")
    content: Optional[str] = Field(default=None, description="内容")
    function_call: Optional[dict[str, Any]] = Field(default=None)
    tool_calls: Optional[list[dict[str, Any]]] = Field(default=None)


class Choice(BaseModel):
    """响应选项"""
    index: int = Field(default=0, description="选项索引")
    message: ChoiceMessage = Field(..., description="消息内容")
    finish_reason: Optional[str] = Field(default=None, description="结束原因")


class ChatCompletionResponse(BaseModel):
    """聊天补全响应 (OpenAI 兼容)"""
    id: str = Field(..., description="响应 ID")
    object: str = Field(default="chat.completion", description="对象类型")
    created: int = Field(..., description="创建时间戳")
    model: str = Field(..., description="模型名称")
    choices: list[Choice] = Field(..., description="响应选项列表")
    usage: Optional[Usage] = Field(default=None, description="使用统计")


# ==================== 流式响应模型 ====================

class DeltaMessage(BaseModel):
    """流式响应中的增量消息"""
    role: Optional[str] = Field(default=None)
    content: Optional[str] = Field(default=None)
    function_call: Optional[dict[str, Any]] = Field(default=None)
    tool_calls: Optional[list[dict[str, Any]]] = Field(default=None)


class StreamChoice(BaseModel):
    """流式响应选项"""
    index: int = Field(default=0)
    delta: DeltaMessage = Field(...)
    finish_reason: Optional[str] = Field(default=None)


class ChatCompletionChunk(BaseModel):
    """流式响应块 (OpenAI 兼容)"""
    id: str = Field(...)
    object: str = Field(default="chat.completion.chunk")
    created: int = Field(...)
    model: str = Field(...)
    choices: list[StreamChoice] = Field(...)


# ==================== 错误模型 ====================

class ErrorDetail(BaseModel):
    """错误详情"""
    message: str = Field(..., description="错误消息")
    type: str = Field(default="invalid_request_error", description="错误类型")
    param: Optional[str] = Field(default=None, description="相关参数")
    code: Optional[str] = Field(default=None, description="错误代码")


class ErrorResponse(BaseModel):
    """错误响应 (OpenAI 兼容)"""
    error: ErrorDetail = Field(..., description="错误详情")


# ==================== 模型列表响应 ====================

class ModelInfo(BaseModel):
    """模型信息"""
    id: str = Field(..., description="模型 ID")
    object: str = Field(default="model", description="对象类型")
    created: int = Field(default=0, description="创建时间")
    owned_by: str = Field(default=MODEL_OWNED_BY, description="所有者")


class ModelListResponse(BaseModel):
    """模型列表响应 (OpenAI 兼容)"""
    object: str = Field(default="list", description="对象类型")
    data: list[ModelInfo] = Field(..., description="模型列表")
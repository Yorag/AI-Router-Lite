"""
数据模型模块

定义 API 响应数据结构
"""

from typing import Optional
from pydantic import BaseModel, Field

from .constants import MODEL_OWNED_BY


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
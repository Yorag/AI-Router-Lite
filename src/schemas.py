"""
API 数据模型定义
"""

from typing import Optional, List, Dict
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
    data: List[ModelInfo] = Field(..., description="模型列表")


# ==================== 请求模型 ====================

class CreateAPIKeyRequest(BaseModel):
    name: str


class UpdateAPIKeyRequest(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None


class ProviderRequest(BaseModel):
    name: str
    base_url: str
    api_key: str
    weight: int = 1
    timeout: Optional[float] = None
    default_protocol: Optional[str] = None


class UpdateProviderRequest(BaseModel):
    name: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    weight: Optional[int] = None
    timeout: Optional[float] = None
    enabled: Optional[bool] = None
    default_protocol: Optional[str] = None
    allow_health_check: Optional[bool] = None
    allow_model_update: Optional[bool] = None
    manual_models: Optional[List[str]] = None


class CreateModelMappingRequest(BaseModel):
    unified_name: str
    description: str = ""
    rules: List[dict] = []
    manual_includes: List[str] = []
    excluded_providers: List[str] = []
    enabled: bool = True


class UpdateModelMappingRequest(BaseModel):
    new_unified_name: Optional[str] = None
    description: Optional[str] = None
    rules: Optional[List[dict]] = None
    manual_includes: Optional[List[str]] = None
    excluded_providers: Optional[List[str]] = None
    enabled: Optional[bool] = None


class PreviewResolveRequest(BaseModel):
    rules: List[dict]
    manual_includes: List[str] = []
    excluded_providers: List[str] = []


class SyncConfigRequest(BaseModel):
    auto_sync_enabled: Optional[bool] = None
    auto_sync_interval_hours: Optional[int] = None


class ReorderModelMappingsRequest(BaseModel):
    ordered_names: List[str]


class TestSingleModelRequest(BaseModel):
    provider_id: str
    model: str


class UpdateModelProtocolRequest(BaseModel):
    provider_id: str
    model_id: str
    protocol: Optional[str] = None
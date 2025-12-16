"""
配置管理模块

负责加载和验证 config.json 配置文件
"""

import json
import uuid
from pathlib import Path
from typing import Optional
from enum import Enum

from pydantic import BaseModel, Field

# 从统一常量模块导入服务器默认配置
from .constants import (
    DEFAULT_SERVER_PORT,
    DEFAULT_SERVER_HOST,
    CONFIG_FILE_PATH,
)


def generate_provider_id() -> str:
    """生成新的 Provider ID (UUID4)"""
    return str(uuid.uuid4())


class ProtocolType(str, Enum):
    """
    渠道协议类型（仅用于路由过滤）
    
    系统只支持 OpenAI 协议入口和出口。
    协议字段用于标识渠道的 API 格式，在路由时过滤不兼容的渠道。
    
    当请求进入特定端点时（如 /v1/chat/completions 或 /v1/messages）：
    - 系统会根据端点对应的协议类型（openai 或 anthropic）进行过滤
    - 只有支持该协议的渠道（或未指定协议的混合渠道）会被选中
    
    协议类型说明：
    - OPENAI: 兼容 OpenAI Chat Completions API (/v1/chat/completions)
    - OPENAI_RESPONSE: OpenAI Responses API 格式（不兼容，会被过滤）
    - ANTHROPIC: Anthropic Claude Messages API 格式（不兼容，会被过滤）
    - GEMINI: Google Gemini API 格式（不兼容，会被过滤）
    """
    OPENAI = "openai"
    OPENAI_RESPONSE = "openai-response"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"


class ProviderConfig(BaseModel):
    """
    单个 Provider 的配置
    
    注意：
    - id 是不可变的唯一标识，用于内部关联（数据文件、健康检测结果等）
    - name 是可变的显示名称，用于用户界面展示
    - 模型列表存储在 data/provider_models.json 中，
      通过 /api/providers/{id}/models 接口同步获取
    - default_protocol 为空表示混合类型，需要在模型映射中单独配置每个模型的协议
    """
    id: str = Field(default_factory=generate_provider_id, description="Provider 唯一标识 (UUID)，内部使用")
    name: str = Field(..., description="Provider 显示名称，可修改")
    base_url: str = Field(..., description="API 基础 URL")
    api_key: str = Field(..., description="API Key")
    weight: int = Field(default=1, ge=1, description="权重，数值越高优先级越高")
    timeout: Optional[float] = Field(default=None, ge=1.0, description="请求超时时间（秒），未配置时使用全局 request_timeout")
    enabled: bool = Field(default=True, description="是否启用该服务站")
    default_protocol: Optional[ProtocolType] = Field(
        default=None,
        description="渠道协议类型（用于路由过滤）。指定后，该渠道仅会被用于处理对应协议的请求。"
    )


class AppConfig(BaseModel):
    """应用配置"""
    server_port: int = Field(default=8000, ge=1, le=65535, description="服务端口")
    server_host: str = Field(default="0.0.0.0", description="服务监听地址")
    providers: list[ProviderConfig] = Field(
        default_factory=list,
        description="Provider 列表"
    )
    max_retries: int = Field(default=3, ge=1, description="最大重试次数")
    request_timeout: float = Field(default=120.0, ge=1.0, description="默认请求超时时间")


class ConfigManager:
    """配置管理器"""
    
    _instance: Optional["ConfigManager"] = None
    _config: Optional[AppConfig] = None
    
    def __new__(cls) -> "ConfigManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def load(self, config_path: str = CONFIG_FILE_PATH) -> AppConfig:
        """
        加载配置文件
        
        Args:
            config_path: 配置文件路径
            
        Returns:
            AppConfig: 解析后的配置对象
            
        Raises:
            FileNotFoundError: 配置文件不存在
            json.JSONDecodeError: JSON 格式错误
            pydantic.ValidationError: 配置验证失败
        """
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"配置文件不存在: {config_path}")
        
        with open(path, "r", encoding="utf-8") as f:
            raw_config = json.load(f)
        
        self._config = AppConfig(**raw_config)
        return self._config
    
    @property
    def config(self) -> AppConfig:
        """获取当前配置"""
        if self._config is None:
            raise RuntimeError("配置尚未加载，请先调用 load() 方法")
        return self._config
    
    def reload(self, config_path: str = CONFIG_FILE_PATH) -> AppConfig:
        """重新加载配置"""
        return self.load(config_path)


# 全局配置管理器实例
config_manager = ConfigManager()


def get_config() -> AppConfig:
    """获取全局配置"""
    return config_manager.config
"""
配置管理模块

负责加载和验证 config.json 配置文件
"""

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class ProviderConfig(BaseModel):
    """单个 Provider 的配置"""
    name: str = Field(..., description="Provider 名称，用于日志标识")
    base_url: str = Field(..., description="API 基础 URL")
    api_key: str = Field(..., description="API Key")
    weight: int = Field(default=1, ge=1, description="权重，数值越高优先级越高")
    supported_models: list[str] = Field(default_factory=list, description="支持的模型列表")
    timeout: Optional[float] = Field(default=None, ge=1.0, description="请求超时时间（秒），未配置时使用全局 request_timeout")


class AppConfig(BaseModel):
    """应用配置"""
    server_port: int = Field(default=8000, ge=1, le=65535, description="服务端口")
    server_host: str = Field(default="0.0.0.0", description="服务监听地址")
    model_map: dict[str, list[str]] = Field(
        default_factory=dict,
        description="模型映射：用户请求的模型名 -> 实际模型名列表"
    )
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
    
    def load(self, config_path: str = "config.json") -> AppConfig:
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
    
    def reload(self, config_path: str = "config.json") -> AppConfig:
        """重新加载配置"""
        return self.load(config_path)


# 全局配置管理器实例
config_manager = ConfigManager()


def get_config() -> AppConfig:
    """获取全局配置"""
    return config_manager.config
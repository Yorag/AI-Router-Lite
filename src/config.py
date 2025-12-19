import json
from typing import Optional

from pydantic import BaseModel, Field

from .constants import DEFAULT_SERVER_HOST, DEFAULT_SERVER_PORT


class ProviderConfig(BaseModel):
    """Provider配置模型，用于描述数据库中的 Provider 数据"""
    id: str = Field(..., description="Provider 唯一标识 (UUID)")
    name: str = Field(..., description="Provider 显示名称")
    base_url: str = Field(..., description="API 基础 URL")
    api_key: str = Field(..., description="API Key（运行时解密得到）")
    weight: int = Field(default=1, ge=1)
    timeout: Optional[float] = Field(default=None, ge=1.0)
    enabled: bool = Field(default=True)
    allow_health_check: bool = Field(default=True)
    allow_model_update: bool = Field(default=True)
    default_protocol: Optional[str] = Field(default=None)


class AppConfig(BaseModel):
    """应用配置模型，直接反映 config.json 的结构"""
    server_port: int = Field(default=DEFAULT_SERVER_PORT, ge=1, le=65535)
    server_host: str = Field(default=DEFAULT_SERVER_HOST)
    max_retries: int = Field(default=3, ge=1)
    request_timeout: float = Field(default=120.0, ge=1.0)
    db_encryption_key: str = Field(..., min_length=1, description="用于数据库加密的 Fernet 密钥")

def load_config_file(config_path: str = "config.json") -> dict:
    """
    加载配置文件并返回原始字典。
    这是一个底层函数，供 ConfigManager 和 init_db.py 共同使用。
    
    Args:
        config_path: 配置文件路径
        
    Returns:
        dict: 配置文件内容
        
    Raises:
        RuntimeError: 配置文件不存在或解析失败
    """
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise RuntimeError(
            f"配置文件 '{config_path}' 未找到。"
            f"请从 config.example.json 复制并填写配置。"
        )
    except json.JSONDecodeError as e:
        raise RuntimeError(f"配置文件 '{config_path}' JSON 解析失败: {e}")


class ConfigManager:
    """配置管理器，负责从 config.json 加载配置"""
    
    def __init__(self, config_path: str = "config.json"):
        self.config_path = config_path
        self._config: Optional[AppConfig] = None
        self._fernet_initialized: bool = False

    def load(self) -> AppConfig:
        """
        加载配置文件并初始化 Fernet 加密实例。
        
        Returns:
            AppConfig: 应用配置对象
        """
        config_data = load_config_file(self.config_path)
        self._config = AppConfig(**config_data)
        
        # 初始化 Fernet 加密实例
        if not self._fernet_initialized:
            from .db import init_fernet
            init_fernet(self._config.db_encryption_key)
            self._fernet_initialized = True
        
        return self._config

    def reload(self) -> AppConfig:
        """重新加载配置"""
        return self.load()

    @property
    def config(self) -> AppConfig:
        """获取当前配置，如未加载则自动加载"""
        if self._config is None:
            return self.load()
        return self._config
        return self._config


config_manager = ConfigManager()


def get_config() -> AppConfig:
    """获取应用配置"""
    return config_manager.config
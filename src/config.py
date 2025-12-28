import json
import os
from typing import Optional

from pydantic import BaseModel, Field


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


class CooldownConfig(BaseModel):
    """熔断器冷却时间配置（秒）"""
    rate_limited: int = Field(default=180, ge=0, description="429 超频冷却时间")
    server_error: int = Field(default=600, ge=0, description="5xx 服务器错误冷却时间")
    timeout: int = Field(default=300, ge=0, description="超时冷却时间")
    network_error: int = Field(default=120, ge=0, description="网络错误冷却时间")


class ExponentialBackoffConfig(BaseModel):
    """指数退避配置"""
    base_multiplier: float = Field(default=2.0, ge=1.0, le=10.0, description="退避倍数基数")
    max_multiplier: float = Field(default=16.0, ge=1.0, le=100.0, description="最大退避倍数，设为1.0可禁用指数退避")


class AuthConfig(BaseModel):
    """认证相关配置"""
    token_expire_hours: int = Field(default=6, ge=1, description="JWT 令牌有效期（小时）")
    lockout_duration_seconds: int = Field(default=900, ge=60, description="登录失败锁定时间（秒）")


class AppConfig(BaseModel):
    """应用配置模型，支持环境变量和配置文件"""
    # 服务器配置（支持环境变量）
    server_port: int = Field(default=8000, ge=1, le=65535)
    server_host: str = Field(default="0.0.0.0")

    # 加密密钥（仅从环境变量读取）
    db_encryption_key: str = Field(..., min_length=1, description="用于数据库加密的 Fernet 密钥，必须通过环境变量 AI_ROUTER_ENCRYPTION_KEY 设置")

    # 请求配置
    request_timeout: float = Field(default=120.0, ge=1.0)

    # 时区配置
    timezone_offset: int = Field(default=8, ge=-12, le=14, description="时区偏移量（小时），如 8 表示 UTC+8")

    # 日志配置
    log_retention_days: int = Field(default=15, ge=1, description="日志保留天数")

    # 熔断器配置
    cooldown: CooldownConfig = Field(default_factory=CooldownConfig)

    # 指数退避配置
    exponential_backoff: ExponentialBackoffConfig = Field(default_factory=ExponentialBackoffConfig)

    # 认证配置
    auth: AuthConfig = Field(default_factory=AuthConfig)

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


# 环境变量名称常量
ENV_ENCRYPTION_KEY = "AI_ROUTER_ENCRYPTION_KEY"
ENV_SERVER_PORT = "AI_ROUTER_PORT"
ENV_SERVER_HOST = "AI_ROUTER_HOST"


class ConfigManager:
    """配置管理器，支持环境变量覆盖配置文件"""

    def __init__(self, config_path: str = "config.json"):
        self.config_path = config_path
        self._config: Optional[AppConfig] = None
        self._fernet_initialized: bool = False

    def load(self) -> AppConfig:
        """
        加载配置，优先级：环境变量 > 配置文件 > 默认值

        环境变量：
        - AI_ROUTER_ENCRYPTION_KEY: 数据库加密密钥（必须设置）
        - AI_ROUTER_PORT: 服务端口
        - AI_ROUTER_HOST: 服务主机

        Returns:
            AppConfig: 应用配置对象
        """
        config_data = load_config_file(self.config_path)

        # 加密密钥必须从环境变量读取
        env_encryption_key = os.getenv(ENV_ENCRYPTION_KEY)
        if not env_encryption_key:
            raise RuntimeError(
                f"环境变量 {ENV_ENCRYPTION_KEY} 未设置。\n"
                f"请使用 python scripts/gen_fernet_key.py 生成密钥，然后设置环境变量。"
            )
        config_data["db_encryption_key"] = env_encryption_key

        # 可选环境变量覆盖
        env_port = os.getenv(ENV_SERVER_PORT)
        if env_port:
            config_data["server_port"] = int(env_port)

        env_host = os.getenv(ENV_SERVER_HOST)
        if env_host:
            config_data["server_host"] = env_host

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


config_manager = ConfigManager()


def get_config() -> AppConfig:
    """获取应用配置"""
    return config_manager.config
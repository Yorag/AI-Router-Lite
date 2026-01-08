"""
密钥管理模块

提供加密密钥和 JWT 密钥的自动生成与加载功能。
- 加密密钥：支持环境变量覆盖和文件持久化
- JWT 密钥：仅内存，每次启动重新生成
"""

import os
import stat
import secrets
import logging
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet

# 环境变量名称
ENV_ENCRYPTION_KEY = "AI_ROUTER_ENCRYPTION_KEY"

# 密钥文件路径
DATA_DIR = Path("data")
ENCRYPTION_KEY_FILE = DATA_DIR / ".encryption_key"

# 模块级缓存
_encryption_key: Optional[str] = None
_jwt_secret: Optional[str] = None

logger = logging.getLogger(__name__)


def _ensure_data_dir() -> None:
    """确保 data 目录存在"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _set_secure_permissions(path: Path) -> None:
    """设置文件为仅所有者可读写 (0600)"""
    if os.name == "nt":
        # Windows: 无法直接设置 Unix 权限，跳过
        return
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError as e:
        logger.warning(f"无法设置文件权限 {path}: {e}")


def _check_file_permissions(path: Path) -> None:
    """检查文件权限是否安全"""
    if os.name == "nt":
        # Windows: 跳过权限检查
        return
    try:
        mode = path.stat().st_mode
        if mode & (stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH):
            logger.warning(
                f"密钥文件 {path} 权限过于宽松。"
                f"建议运行: chmod 600 {path}"
            )
    except OSError:
        pass


def _generate_fernet_key() -> str:
    """生成新的 Fernet 密钥"""
    return Fernet.generate_key().decode("utf-8")


def _generate_jwt_secret() -> str:
    """生成新的 JWT 密钥 (32 字节 hex)"""
    return secrets.token_hex(32)


def _read_key_file(path: Path) -> Optional[str]:
    """从文件读取密钥"""
    if not path.exists():
        return None
    try:
        key = path.read_text(encoding="utf-8").strip()
        if key:
            _check_file_permissions(path)
            return key
    except OSError as e:
        logger.warning(f"读取密钥文件失败 {path}: {e}")
    return None


def _write_key_file(path: Path, key: str) -> None:
    """将密钥写入文件"""
    _ensure_data_dir()
    path.write_text(key, encoding="utf-8")
    _set_secure_permissions(path)


def get_encryption_key() -> str:
    """
    获取加密密钥。

    优先级：环境变量 > 文件 > 自动生成

    Returns:
        str: Fernet 加密密钥
    """
    global _encryption_key

    if _encryption_key:
        return _encryption_key

    # 1. 尝试从环境变量读取
    env_key = os.getenv(ENV_ENCRYPTION_KEY)
    if env_key:
        _encryption_key = env_key
        logger.info("使用环境变量中的加密密钥")
        return _encryption_key

    # 2. 尝试从文件读取
    file_key = _read_key_file(ENCRYPTION_KEY_FILE)
    if file_key:
        _encryption_key = file_key
        logger.info(f"使用文件中的加密密钥: {ENCRYPTION_KEY_FILE}")
        return _encryption_key

    # 3. 自动生成并保存
    _encryption_key = _generate_fernet_key()
    _write_key_file(ENCRYPTION_KEY_FILE, _encryption_key)
    logger.info(f"已自动生成加密密钥并保存到: {ENCRYPTION_KEY_FILE}")
    return _encryption_key


def get_jwt_secret() -> str:
    """
    获取 JWT 密钥（仅内存）。

    每次服务启动时自动生成，重启后会话失效。

    Returns:
        str: JWT 签名密钥
    """
    global _jwt_secret

    if _jwt_secret is None:
        _jwt_secret = _generate_jwt_secret()

    return _jwt_secret


def clear_cache() -> None:
    """清除密钥缓存（仅用于测试）"""
    global _encryption_key, _jwt_secret
    _encryption_key = None
    _jwt_secret = None

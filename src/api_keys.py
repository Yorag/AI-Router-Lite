import secrets
from dataclasses import dataclass
from typing import Optional

from .constants import API_KEY_ID_RANDOM_BYTES, API_KEY_PREFIX, API_KEY_SECRET_BYTES
from .sqlite_repos import ApiKeyRepo


@dataclass
class APIKey:
    key_id: str
    name: str
    enabled: bool = True


class APIKeyManager:
    """API Key 管理器（SQLite 版本：加密存储）"""

    def __init__(self):
        self._repo = ApiKeyRepo()

    @staticmethod
    def _generate_key() -> tuple[str, str]:
        key_id = f"{API_KEY_PREFIX}{secrets.token_hex(API_KEY_ID_RANDOM_BYTES)}"
        key_secret = secrets.token_hex(API_KEY_SECRET_BYTES)
        full_key = f"{key_id}-{key_secret}"
        return key_id, full_key

    @staticmethod
    def _generate_secret() -> str:
        """只生成 secret 部分"""
        return secrets.token_hex(API_KEY_SECRET_BYTES)

    def create_key(self, name: str) -> tuple[str, dict]:
        key_id, full_key = self._generate_key()
        self._repo.create(key_id, full_key, name)
        info = self._repo.get_by_id(key_id) or {"key_id": key_id, "name": name}
        return full_key, info

    def reset_key(self, key_id: str) -> Optional[str]:
        """重置密钥的 secret 部分，返回新的完整密钥"""
        existing = self._repo.get_by_id(key_id)
        if not existing:
            return None
        new_secret = self._generate_secret()
        new_full_key = f"{key_id}-{new_secret}"
        success = self._repo.reset_secret(key_id, new_full_key)
        return new_full_key if success else None

    def validate_key(self, key: str) -> Optional[APIKey]:
        touched = self._repo.validate_and_touch(key)
        if not touched:
            return None
        return APIKey(
            key_id=touched["key_id"],
            name=touched["name"],
            enabled=True,
        )

    def get_key(self, key_id: str) -> Optional[dict]:
        return self._repo.get_by_id(key_id)

    def list_keys(self) -> list[dict]:
        return self._repo.list()

    def update_key(self, key_id: str, name: Optional[str] = None, enabled: Optional[bool] = None) -> bool:
        existing = self._repo.get_by_id(key_id)
        if not existing:
            return False

        new_name = name if name is not None else existing["name"]
        new_enabled = enabled if enabled is not None else existing["enabled"]

        return self._repo.update(key_id, new_name, new_enabled)

    def delete_key(self, key_id: str) -> bool:
        return self._repo.delete(key_id)

    def get_stats(self) -> dict:
        return self._repo.get_stats()


api_key_manager = APIKeyManager()
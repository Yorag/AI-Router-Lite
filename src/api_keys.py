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

    def to_dict(self) -> dict:
        return {
            "key_id": self.key_id,
            "name": self.name,
            "enabled": self.enabled,
        }


class APIKeyManager:
    """API Key 管理器（SQLite 版本：不落盘明文）"""

    def __init__(self):
        self._repo = ApiKeyRepo()

    @staticmethod
    def _generate_key() -> tuple[str, str]:
        key_id = f"{API_KEY_PREFIX}{secrets.token_hex(API_KEY_ID_RANDOM_BYTES)}"
        key_secret = secrets.token_hex(API_KEY_SECRET_BYTES)
        full_key = f"{key_id}-{key_secret}"
        return key_id, full_key

    def create_key(self, name: str) -> tuple[str, dict]:
        key_id, full_key = self._generate_key()

        import hashlib
        key_hash = hashlib.sha256(full_key.encode("utf-8")).hexdigest()

        self._repo.create(key_id, key_hash, name)

        # return plaintext only once
        info = self._repo.get_by_id(key_id) or {"key_id": key_id, "name": name}
        return full_key, info

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
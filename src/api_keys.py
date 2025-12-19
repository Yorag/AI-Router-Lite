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
        import time

        key_hash = hashlib.sha256(full_key.encode("utf-8")).hexdigest()
        now_ms = int(time.time() * 1000)

        from .db import connect_sqlite, get_db_paths

        paths = get_db_paths()
        conn = connect_sqlite(paths.app_db_path)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO api_keys (
              key_id, key_hash, name, created_at_ms, enabled, last_used_ms, total_requests
            ) VALUES (?, ?, ?, ?, 1, NULL, 0)
            """,
            (key_id, key_hash, name, now_ms),
        )
        conn.commit()
        cur.close()
        conn.close()

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
        from .db import connect_sqlite, get_db_paths

        paths = get_db_paths()
        conn = connect_sqlite(paths.app_db_path)
        cur = conn.cursor()

        existing = self._repo.get_by_id(key_id)
        if not existing:
            cur.close()
            conn.close()
            return False

        new_name = name if name is not None else existing["name"]
        new_enabled = 1 if (enabled if enabled is not None else existing["enabled"]) else 0

        cur.execute(
            """
            UPDATE api_keys
            SET name = ?, enabled = ?
            WHERE key_id = ?
            """,
            (new_name, new_enabled, key_id),
        )
        conn.commit()
        cur.close()
        conn.close()
        return True

    def delete_key(self, key_id: str) -> bool:
        from .db import connect_sqlite, get_db_paths

        paths = get_db_paths()
        conn = connect_sqlite(paths.app_db_path)
        cur = conn.cursor()
        cur.execute("DELETE FROM api_keys WHERE key_id = ?", (key_id,))
        deleted = cur.rowcount > 0
        conn.commit()
        cur.close()
        conn.close()
        return deleted

    def get_stats(self) -> dict:
        return self._repo.get_stats()


api_key_manager = APIKeyManager()
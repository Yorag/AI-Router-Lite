"""
API 密钥管理模块

负责生成、验证和管理统一接口的 API 密钥
"""

import json
import secrets
import hashlib
import time
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime

from .constants import (
    API_KEYS_STORAGE_PATH,
    API_KEY_PREFIX,
    API_KEY_ID_RANDOM_BYTES,
    API_KEY_SECRET_BYTES,
)


@dataclass
class APIKey:
    """API 密钥"""
    key_id: str
    key_hash: str  # 存储哈希值用于验证
    name: str
    created_at: float
    key_plain: str = ""  # 存储完整密钥明文，用于显示
    last_used: Optional[float] = None
    enabled: bool = True
    total_requests: int = 0
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "key_id": self.key_id,
            "key_plain": self.key_plain,
            "name": self.name,
            "created_at": self.created_at,
            "created_at_str": datetime.fromtimestamp(self.created_at).strftime("%Y-%m-%d %H:%M:%S"),
            "last_used": self.last_used,
            "last_used_str": datetime.fromtimestamp(self.last_used).strftime("%Y-%m-%d %H:%M:%S") if self.last_used else None,
            "enabled": self.enabled,
            "total_requests": self.total_requests
        }


class APIKeyManager:
    """API 密钥管理器"""
    
    def __init__(self, storage_path: str = API_KEYS_STORAGE_PATH):
        self.storage_path = Path(storage_path)
        self._keys: dict[str, APIKey] = {}  # key_id -> APIKey
        self._key_lookup: dict[str, str] = {}  # key_hash -> key_id
        self._load()
    
    def _load(self) -> None:
        """从文件加载密钥"""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for key_data in data.get("keys", []):
                        key = APIKey(**key_data)
                        self._keys[key.key_id] = key
                        self._key_lookup[key.key_hash] = key.key_id
            except Exception as e:
                print(f"[APIKeyManager] 加载密钥失败: {e}")
    
    def _save(self) -> None:
        """保存密钥到文件"""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "keys": [asdict(key) for key in self._keys.values()]
        }
        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    @staticmethod
    def _hash_key(key: str) -> str:
        """对密钥进行哈希"""
        return hashlib.sha256(key.encode()).hexdigest()
    
    @staticmethod
    def _generate_key() -> tuple[str, str]:
        """生成新的 API 密钥，返回 (key_id, full_key)"""
        key_id = f"{API_KEY_PREFIX}{secrets.token_hex(API_KEY_ID_RANDOM_BYTES)}"
        key_secret = secrets.token_hex(API_KEY_SECRET_BYTES)
        full_key = f"{key_id}-{key_secret}"
        return key_id, full_key
    
    def create_key(self, name: str) -> tuple[str, dict]:
        """
        创建新的 API 密钥
        
        Args:
            name: 密钥名称
            
        Returns:
            (完整密钥, 密钥信息字典)
        """
        key_id, full_key = self._generate_key()
        key_hash = self._hash_key(full_key)
        
        api_key = APIKey(
            key_id=key_id,
            key_hash=key_hash,
            name=name,
            created_at=time.time(),
            key_plain=full_key  # 存储明文密钥
        )
        
        self._keys[key_id] = api_key
        self._key_lookup[key_hash] = key_id
        self._save()
        
        return full_key, api_key.to_dict()
    
    def validate_key(self, key: str) -> Optional[APIKey]:
        """
        验证 API 密钥
        
        Args:
            key: 完整的 API 密钥
            
        Returns:
            有效则返回 APIKey 对象，否则返回 None
        """
        key_hash = self._hash_key(key)
        key_id = self._key_lookup.get(key_hash)
        
        if not key_id:
            return None
        
        api_key = self._keys.get(key_id)
        if not api_key or not api_key.enabled:
            return None
        
        # 更新使用统计
        api_key.last_used = time.time()
        api_key.total_requests += 1
        self._save()
        
        return api_key
    
    def get_key(self, key_id: str) -> Optional[dict]:
        """获取密钥信息"""
        api_key = self._keys.get(key_id)
        return api_key.to_dict() if api_key else None
    
    def list_keys(self) -> list[dict]:
        """列出所有密钥"""
        return [key.to_dict() for key in self._keys.values()]
    
    def update_key(self, key_id: str, name: Optional[str] = None,
                   enabled: Optional[bool] = None) -> bool:
        """更新密钥信息"""
        api_key = self._keys.get(key_id)
        if not api_key:
            return False
        
        if name is not None:
            api_key.name = name
        if enabled is not None:
            api_key.enabled = enabled
        
        self._save()
        return True
    
    def delete_key(self, key_id: str) -> bool:
        """删除密钥"""
        api_key = self._keys.get(key_id)
        if not api_key:
            return False
        
        del self._key_lookup[api_key.key_hash]
        del self._keys[key_id]
        self._save()
        return True
    
    def get_stats(self) -> dict:
        """获取密钥统计"""
        total = len(self._keys)
        enabled = sum(1 for k in self._keys.values() if k.enabled)
        total_requests = sum(k.total_requests for k in self._keys.values())
        
        return {
            "total_keys": total,
            "enabled_keys": enabled,
            "disabled_keys": total - enabled,
            "total_requests": total_requests
        }


# 全局实例
api_key_manager = APIKeyManager()
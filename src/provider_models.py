"""
Provider 模型元信息管理模块

负责管理从中转站获取的模型信息，包括：
- 模型 ID
- owned_by（模型所有者）
- supported_endpoint_types（支持的端点类型）
- last_activity（最后使用时间）
- last_activity_type（活动类型：call/health_test）

与 model_health.json 分离存储，保持轻量和高效更新。

注意：
- 使用 provider_id (UUID) 作为内部标识，而非 provider name
- last_activity 仅在模型被实际使用（API 调用或健康检测）时更新，
  同步操作不会更新此字段，因为同步只是更新元数据，不代表模型被使用
"""

import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Literal
from dataclasses import dataclass, field, asdict
import filelock

from .constants import PROVIDER_MODELS_STORAGE_PATH


# 活动类型：只有 call（API调用）和 health_test（健康检测）
# 同步操作不是"活动"，因为它只是更新元数据，不代表模型被使用
ActivityType = Literal["call", "health_test"]


@dataclass
class ModelInfo:
    """单个模型的元信息"""
    model_id: str
    owned_by: str = ""
    supported_endpoint_types: list[str] = field(default_factory=list)  # 支持的端点类型
    last_activity: Optional[str] = None  # ISO8601 时间戳
    last_activity_type: Optional[ActivityType] = None
    created_at: Optional[str] = None  # 首次添加时间
    
    def to_dict(self) -> dict:
        return {
            "owned_by": self.owned_by,
            "supported_endpoint_types": self.supported_endpoint_types,
            "last_activity": self.last_activity,
            "last_activity_type": self.last_activity_type,
            "created_at": self.created_at
        }
    
    @classmethod
    def from_dict(cls, model_id: str, data: dict) -> "ModelInfo":
        return cls(
            model_id=model_id,
            owned_by=data.get("owned_by", ""),
            supported_endpoint_types=data.get("supported_endpoint_types", []),
            last_activity=data.get("last_activity"),
            last_activity_type=data.get("last_activity_type"),
            created_at=data.get("created_at")
        )


@dataclass
class ProviderModels:
    """单个 Provider 的模型集合"""
    provider_id: str  # Provider 的唯一 ID (UUID)
    models: dict[str, ModelInfo] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            "models": {mid: m.to_dict() for mid, m in self.models.items()}
        }
    
    @classmethod
    def from_dict(cls, provider_id: str, data: dict) -> "ProviderModels":
        models = {}
        for model_id, model_data in data.get("models", {}).items():
            models[model_id] = ModelInfo.from_dict(model_id, model_data)
        return cls(provider_id=provider_id, models=models)
    
    def get_model_ids(self) -> list[str]:
        """获取所有模型 ID 列表"""
        return sorted(self.models.keys())


class ProviderModelsManager:
    """Provider 模型元信息管理器"""
    
    VERSION = "1.0"
    
    def __init__(self, data_path: str = PROVIDER_MODELS_STORAGE_PATH):
        self.data_path = Path(data_path)
        self.lock_path = self.data_path.with_suffix(".json.lock")
        self._providers: dict[str, ProviderModels] = {}
        self._loaded = False
    
    def _ensure_file_exists(self) -> None:
        """确保数据文件存在"""
        if not self.data_path.exists():
            self.data_path.parent.mkdir(parents=True, exist_ok=True)
            self._save_data({
                "version": self.VERSION,
                "providers": {}
            })
    
    def _load_data(self) -> dict:
        """加载数据文件"""
        self._ensure_file_exists()
        try:
            with open(self.data_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {"version": self.VERSION, "providers": {}}
    
    def _save_data(self, data: dict) -> None:
        """保存数据文件（带文件锁）"""
        self.data_path.parent.mkdir(parents=True, exist_ok=True)
        lock = filelock.FileLock(self.lock_path, timeout=10)
        with lock:
            with open(self.data_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
    
    def load(self) -> None:
        """加载所有数据"""
        data = self._load_data()
        
        self._providers = {}
        for provider_id, provider_data in data.get("providers", {}).items():
            self._providers[provider_id] = ProviderModels.from_dict(
                provider_id, provider_data
            )
        
        self._loaded = True
    
    def save(self) -> None:
        """保存所有数据"""
        data = {
            "version": self.VERSION,
            "providers": {
                provider_id: p.to_dict() for provider_id, p in self._providers.items()
            }
        }
        self._save_data(data)
    
    def _ensure_loaded(self) -> None:
        """确保数据已加载"""
        if not self._loaded:
            self.load()
    
    # ==================== Provider 操作 ====================
    
    def get_provider(self, provider_id: str) -> Optional[ProviderModels]:
        """获取指定 Provider 的模型集合"""
        self._ensure_loaded()
        return self._providers.get(provider_id)
    
    def get_all_providers(self) -> dict[str, ProviderModels]:
        """获取所有 Provider（key 为 provider_id）"""
        self._ensure_loaded()
        return self._providers.copy()
    
    def get_provider_model_ids(self, provider_id: str) -> list[str]:
        """获取指定 Provider 的模型 ID 列表"""
        provider = self.get_provider(provider_id)
        if provider:
            return provider.get_model_ids()
        return []
    
    def delete_provider(self, provider_id: str) -> bool:
        """删除 Provider（当 Provider 被删除时调用）"""
        self._ensure_loaded()
        if provider_id in self._providers:
            del self._providers[provider_id]
            self.save()
            return True
        return False
    
    # ==================== 模型操作 ====================
    
    def get_model(self, provider_id: str, model_id: str) -> Optional[ModelInfo]:
        """获取指定模型信息"""
        provider = self.get_provider(provider_id)
        if provider:
            return provider.models.get(model_id)
        return None
    
    def update_models_from_remote(
        self,
        provider_id: str,
        remote_models: list[dict]
    ) -> tuple[int, int, int]:
        """
        从中转站获取的模型列表更新本地存储
        
        Args:
            provider_id: Provider 的唯一 ID (UUID)
            remote_models: 远程模型列表 [{"id": "...", "owned_by": "..."}, ...]
            
        Returns:
            (新增数量, 更新数量, 删除数量)
        """
        self._ensure_loaded()
        
        now = datetime.now(timezone.utc).isoformat()
        
        # 确保 Provider 存在
        if provider_id not in self._providers:
            self._providers[provider_id] = ProviderModels(provider_id=provider_id)
        
        provider = self._providers[provider_id]
        
        # 统计
        added = 0
        updated = 0
        removed = 0
        
        # 构建远程模型 ID 集合
        remote_model_ids = {m.get("id") for m in remote_models if m.get("id")}
        local_model_ids = set(provider.models.keys())
        
        # 处理新增和更新
        for remote_model in remote_models:
            model_id = remote_model.get("id")
            if not model_id:
                continue
            
            owned_by = remote_model.get("owned_by", "")
            supported_endpoint_types = remote_model.get("supported_endpoint_types", [])
            
            if model_id in provider.models:
                # 更新现有模型的 owned_by 和 supported_endpoint_types
                existing = provider.models[model_id]
                changed = False
                if existing.owned_by != owned_by:
                    existing.owned_by = owned_by
                    changed = True
                if existing.supported_endpoint_types != supported_endpoint_types:
                    existing.supported_endpoint_types = supported_endpoint_types
                    changed = True
                if changed:
                    updated += 1
            else:
                # 新增模型 - last_activity 初始为 None，表示从未被使用
                provider.models[model_id] = ModelInfo(
                    model_id=model_id,
                    owned_by=owned_by,
                    supported_endpoint_types=supported_endpoint_types,
                    last_activity=None,  # 新模型从未被使用
                    last_activity_type=None,
                    created_at=now
                )
                added += 1
        
        # 处理删除（远程不存在但本地存在的模型）
        to_remove = local_model_ids - remote_model_ids
        for model_id in to_remove:
            del provider.models[model_id]
            removed += 1
        
        self.save()
        return added, updated, removed
    
    def add_model(
        self,
        provider_id: str,
        model_id: str,
        owned_by: str = "",
        supported_endpoint_types: Optional[list[str]] = None
    ) -> bool:
        """
        手动添加单个模型
        
        Args:
            provider_id: Provider 的唯一 ID (UUID)
            model_id: 模型 ID
            owned_by: 模型所有者
            supported_endpoint_types: 支持的端点类型列表
            
        Returns:
            是否成功（如果模型已存在则返回 False）
        """
        self._ensure_loaded()
        
        now = datetime.now(timezone.utc).isoformat()
        
        # 确保 Provider 存在
        if provider_id not in self._providers:
            self._providers[provider_id] = ProviderModels(provider_id=provider_id)
        
        provider = self._providers[provider_id]
        
        if model_id in provider.models:
            return False
        
        provider.models[model_id] = ModelInfo(
            model_id=model_id,
            owned_by=owned_by,
            supported_endpoint_types=supported_endpoint_types or [],
            last_activity=None,  # 新模型从未被使用
            last_activity_type=None,
            created_at=now
        )
        
        self.save()
        return True
    
    def remove_model(self, provider_id: str, model_id: str) -> bool:
        """删除单个模型"""
        self._ensure_loaded()
        
        provider = self.get_provider(provider_id)
        if provider and model_id in provider.models:
            del provider.models[model_id]
            self.save()
            return True
        return False
    
    def update_activity(
        self,
        provider_id: str,
        model_id: str,
        activity_type: ActivityType
    ) -> bool:
        """
        更新模型的最后活动时间
        
        Args:
            provider_id: Provider 的唯一 ID (UUID)
            model_id: 模型 ID
            activity_type: 活动类型
            
        Returns:
            是否成功
        """
        self._ensure_loaded()
        
        model = self.get_model(provider_id, model_id)
        if model:
            model.last_activity = datetime.now(timezone.utc).isoformat()
            model.last_activity_type = activity_type
            self.save()
            return True
        return False
    
    def batch_update_activity(
        self,
        updates: list[tuple[str, str, ActivityType]]
    ) -> int:
        """
        批量更新模型活动时间
        
        Args:
            updates: [(provider_id, model_id, activity_type), ...]
            
        Returns:
            成功更新的数量
        """
        self._ensure_loaded()
        
        now = datetime.now(timezone.utc).isoformat()
        count = 0
        
        for provider_id, model_id, activity_type in updates:
            model = self.get_model(provider_id, model_id)
            if model:
                model.last_activity = now
                model.last_activity_type = activity_type
                count += 1
        
        if count > 0:
            self.save()
        
        return count
    
    # ==================== 查询辅助 ====================
    
    def get_all_provider_models_map(self) -> dict[str, list[str]]:
        """
        获取所有 Provider 的模型 ID 映射
        
        Returns:
            {provider_id: [model_id, ...]}
        """
        self._ensure_loaded()
        
        result = {}
        for provider_id, provider in self._providers.items():
            result[provider_id] = provider.get_model_ids()
        
        return result
    
    def get_models_needing_health_check(
        self,
        threshold_hours: float = 6.0
    ) -> dict[str, list[str]]:
        """
        获取需要健康检测的模型（超过阈值时间未活动）
        
        Args:
            threshold_hours: 活动时间阈值（小时）
            
        Returns:
            {provider_name: [model_id, ...]}
        """
        self._ensure_loaded()
        
        from datetime import timedelta
        
        now = datetime.now(timezone.utc)
        threshold = timedelta(hours=threshold_hours)
        
        result: dict[str, list[str]] = {}
        
        for provider_id, provider in self._providers.items():
            models_needing_check = []
            
            for model_id, model in provider.models.items():
                needs_check = True
                
                if model.last_activity:
                    try:
                        last_activity_time = datetime.fromisoformat(
                            model.last_activity.replace('Z', '+00:00')
                        )
                        if now - last_activity_time < threshold:
                            needs_check = False
                    except (ValueError, TypeError):
                        pass
                
                if needs_check:
                    models_needing_check.append(model_id)
            
            if models_needing_check:
                result[provider_id] = models_needing_check
        
        return result
    
# 全局实例
provider_models_manager = ProviderModelsManager()
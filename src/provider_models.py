from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Literal

from .sqlite_repos import ProviderModelsRepo

# 活动类型：只有 call（API调用）和 health_test（健康检测）
ActivityType = Literal["call", "health_test"]


@dataclass
class ModelInfo:
    """单个模型的元信息"""
    model_id: str
    owned_by: str = ""
    supported_endpoint_types: list[str] = field(default_factory=list)
    last_activity: Optional[str] = None  # ISO8601 string or ms timestamp? Repo returns ms int
    last_activity_type: Optional[ActivityType] = None
    created_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "owned_by": self.owned_by,
            "supported_endpoint_types": self.supported_endpoint_types,
            "last_activity": self.last_activity,
            "last_activity_type": self.last_activity_type,
            "created_at": self.created_at
        }


@dataclass
class ProviderModels:
    """单个 Provider 的模型集合"""
    provider_id: str
    models: dict[str, ModelInfo] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "models": {mid: m.to_dict() for mid, m in self.models.items()}
        }

    def get_model_ids(self) -> list[str]:
        return sorted(self.models.keys())


class ProviderModelsManager:
    """
    Provider 模型元信息管理器 (SQLite)
    """

    def __init__(self):
        self._repo = ProviderModelsRepo()

    def _iso_from_ms(self, ms: Optional[int]) -> Optional[str]:
        if ms is None:
            return None
        return datetime.fromtimestamp(ms / 1000.0, timezone.utc).isoformat()

    def load(self) -> None:
        """Compatibility method (no-op in SQLite)"""
        pass

    def get_provider(self, provider_id: str) -> Optional[ProviderModels]:
        data = self._repo.get_provider_models(provider_id)
        if not data:
            return None
        
        models = {}
        for mid, mdata in data.items():
            models[mid] = ModelInfo(
                model_id=mid,
                owned_by=mdata["owned_by"],
                supported_endpoint_types=mdata["supported_endpoint_types"],
                last_activity=self._iso_from_ms(mdata["last_activity"]),
                last_activity_type=mdata["last_activity_type"],
                created_at=self._iso_from_ms(mdata["created_at"]),
            )
        return ProviderModels(provider_id=provider_id, models=models)

    def get_all_providers(self) -> dict[str, ProviderModels]:
        raw = self._repo.get_all_provider_models()
        result = {}
        for pid, pdata in raw.items():
            models = {}
            for mid, mdata in pdata.items():
                models[mid] = ModelInfo(
                    model_id=mid,
                    owned_by=mdata["owned_by"],
                    supported_endpoint_types=mdata["supported_endpoint_types"],
                    last_activity=self._iso_from_ms(mdata["last_activity"]),
                    last_activity_type=mdata["last_activity_type"],
                    created_at=self._iso_from_ms(mdata["created_at"]),
                )
            result[pid] = ProviderModels(provider_id=pid, models=models)
        return result

    def get_provider_model_ids(self, provider_id: str) -> list[str]:
        # Optimization: fetch only keys?
        # For now rely on repo method which fetches row but it is okay
        data = self._repo.get_provider_models(provider_id)
        return sorted(data.keys())

    def delete_provider(self, provider_id: str) -> bool:
        self._repo.delete_provider(provider_id)
        return True

    def get_model(self, provider_id: str, model_id: str) -> Optional[ModelInfo]:
        # Optimization: SQL query for single model?
        # Reuse get_provider for now
        provider = self.get_provider(provider_id)
        if provider:
            return provider.models.get(model_id)
        return None

    def update_models_from_remote(
        self,
        provider_id: str,
        remote_models: list[dict],
        provider_name: Optional[str] = None
    ) -> tuple[int, int, int, list[str], list[str]]:
        """
        Sync remote models to DB
        """
        # Get existing IDs
        existing_map = self._repo.get_provider_models(provider_id)
        existing_ids = set(existing_map.keys())
        remote_ids = {m.get("id") for m in remote_models if m.get("id")}

        # Prepare upsert list
        to_upsert = []
        added_count = 0
        updated_count = 0
        added_models = []

        for rm in remote_models:
            mid = rm.get("id")
            if not mid:
                continue
            
            # Check if exists to count added/updated
            # (Note: UPSERT logic in repo handles update, we just need stats here)
            if mid in existing_ids:
                # Check for changes if we want accurate updated_count?
                # For simplicity, assume update if exists
                # Or compare owned_by/types
                curr = existing_map[mid]
                if curr["owned_by"] != rm.get("owned_by", "") or \
                   curr["supported_endpoint_types"] != rm.get("supported_endpoint_types", []):
                    updated_count += 1
            else:
                added_count += 1
                added_models.append(mid)
            
            to_upsert.append({
                "model_id": mid,
                "owned_by": rm.get("owned_by", ""),
                "supported_endpoint_types": rm.get("supported_endpoint_types", []),
            })

        self._repo.upsert_models(provider_id, to_upsert)

        # Handle removals
        to_remove = list(existing_ids - remote_ids)
        removed_count = len(to_remove)
        self._repo.delete_models(provider_id, to_remove)

        self._log_sync_changes(provider_id, provider_name, added_models, to_remove)

        return added_count, updated_count, removed_count, added_models, to_remove

    def update_models_from_manual_input(
        self,
        provider_id: str,
        model_ids: list[str],
        provider_name: Optional[str] = None
    ) -> tuple[int, int, int, list[str], list[str]]:
        
        existing_map = self._repo.get_provider_models(provider_id)
        existing_ids = set(existing_map.keys())
        
        new_ids = {mid.strip() for mid in model_ids if mid and mid.strip()}
        
        to_upsert = []
        added_count = 0
        added_models = []
        
        for mid in new_ids:
            if mid not in existing_ids:
                added_count += 1
                added_models.append(mid)
                to_upsert.append({
                    "model_id": mid,
                    "owned_by": "manual",
                    "supported_endpoint_types": []
                })
            # If exists, we do nothing (preserve existing metadata)
            # But repo upsert will overwrite owned_by? 
            # We should probably fetch existing and keep their metadata if we want strict behavior.
            # But "manual input" implies overriding. 
            # Actually, the JSON implementation preserves existing metadata for "manual input" 
            # only if it is in new list.
            # Let's align: only insert new ones. Existing ones are kept as is.
        
        if to_upsert:
            self._repo.upsert_models(provider_id, to_upsert)
            
        to_remove = list(existing_ids - new_ids)
        removed_count = len(to_remove)
        self._repo.delete_models(provider_id, to_remove)
        
        self._log_sync_changes(provider_id, provider_name, added_models, to_remove)
        
        return added_count, 0, removed_count, added_models, to_remove

    def _log_sync_changes(
        self,
        provider_id: str,
        provider_name: Optional[str],
        added_models: list[str],
        removed_models: list[str]
    ) -> None:
        from .logger import log_manager, LogLevel
        
        display_name = provider_name or provider_id[:8]
        if not added_models and not removed_models:
            return
        
        parts = []
        max_models_to_show = 5
        if added_models:
            sorted_added = sorted(added_models)
            models_preview = ", ".join(sorted_added[:max_models_to_show])
            suffix = f" 等" if len(added_models) > max_models_to_show else ""
            parts.append(f"新增 {len(added_models)} 个 ({models_preview}{suffix})")
        
        if removed_models:
            sorted_removed = sorted(removed_models)
            models_preview = ", ".join(sorted_removed[:max_models_to_show])
            suffix = f" 等" if len(removed_models) > max_models_to_show else ""
            parts.append(f"移除 {len(removed_models)} 个 ({models_preview}{suffix})")
        
        log_message = f"{', '.join(parts)}"
        print(f"[PROVIDER-MODELS] [{display_name}] {log_message}")
        log_manager.log(
            level=LogLevel.INFO,
            log_type="sync",
            method="SYNC",
            path="/providers/sync",
            provider=display_name,
            provider_id=provider_id,
            message=log_message
        )

    def add_model(
        self,
        provider_id: str,
        model_id: str,
        owned_by: str = "",
        supported_endpoint_types: Optional[list[str]] = None
    ) -> bool:
        existing = self._repo.get_provider_models(provider_id)
        if model_id in existing:
            return False
        
        self._repo.upsert_models(provider_id, [{
            "model_id": model_id,
            "owned_by": owned_by,
            "supported_endpoint_types": supported_endpoint_types or []
        }])
        return True

    def remove_model(self, provider_id: str, model_id: str) -> bool:
        existing = self._repo.get_provider_models(provider_id)
        if model_id in existing:
            self._repo.delete_models(provider_id, [model_id])
            return True
        return False

    def update_activity(
        self,
        provider_id: str,
        model_id: str,
        activity_type: ActivityType
    ) -> bool:
        # Check existence first?
        # SQL UPDATE returns affected rows, so we can know if it existed.
        # But repo method doesn't return bool yet. 
        # Let's assume fire and forget or check repo.
        # For perf, maybe just fire update.
        self._repo.update_activity(provider_id, model_id, activity_type)
        return True

    def batch_update_activity(
        self,
        updates: list[tuple[str, str, ActivityType]]
    ) -> int:
        return self._repo.batch_update_activity(updates)

    def get_all_provider_models_map(self) -> dict[str, list[str]]:
        raw = self._repo.get_all_provider_models()
        result = {}
        for pid, pdata in raw.items():
            result[pid] = sorted(pdata.keys())
        return result

    def get_models_needing_health_check(
        self,
        threshold_hours: float = 6.0
    ) -> dict[str, list[str]]:
        
        from datetime import timedelta
        
        raw = self._repo.get_all_provider_models()
        now = datetime.now(timezone.utc)
        threshold = timedelta(hours=threshold_hours)
        
        result = {}
        
        for pid, pdata in raw.items():
            models_needing_check = []
            for mid, mdata in pdata.items():
                needs_check = True
                last_ms = mdata.get("last_activity")
                if last_ms:
                    last_time = datetime.fromtimestamp(last_ms / 1000.0, timezone.utc)
                    if now - last_time < threshold:
                        needs_check = False
                
                if needs_check:
                    models_needing_check.append(mid)
            
            if models_needing_check:
                result[pid] = models_needing_check
        
        return result


provider_models_manager = ProviderModelsManager()
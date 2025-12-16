"""
Provider 模型元信息管理模块

负责管理从中转站获取的模型信息，包括：
- 模型 ID
- owned_by（模型所有者）
- supported_endpoint_types（支持的端点类型）
- last_activity（最后使用时间）
- last_activity_type（活动类型：call/health_test）

与 model_health.json 分离存储，保持轻量和高效更新。

存储策略：
- 模型列表变更（同步、添加、删除）：立即落盘
- 活动状态更新（last_activity）：缓冲落盘

注意：
- 使用 provider_id (UUID) 作为内部标识，而非 provider name
- last_activity 仅在模型被实际使用（API 调用或健康检测）时更新，
  同步操作不会更新此字段，因为同步只是更新元数据，不代表模型被使用
"""

import json
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Literal
from dataclasses import dataclass, field, asdict

from .constants import (
    PROVIDER_MODELS_STORAGE_PATH,
    STORAGE_BUFFER_INTERVAL_SECONDS,
)
from .storage import BaseStorageManager, persistence_manager


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


class ProviderModelsManager(BaseStorageManager):
    """
    Provider 模型元信息管理器
    
    继承 BaseStorageManager，实现两种保存策略：
    - 模型列表变更（update_models_from_remote, add_model, remove_model）：立即保存
    - 活动状态更新（update_activity）：仅更新内存，由定时任务保存
    """
    
    VERSION = "1.0"
    
    def __init__(self, data_path: str = PROVIDER_MODELS_STORAGE_PATH):
        super().__init__(
            data_path=data_path,
            save_interval=STORAGE_BUFFER_INTERVAL_SECONDS,
            use_file_lock=True
        )
        self._providers: dict[str, ProviderModels] = {}
        
        # 注册到全局持久化管理器
        persistence_manager.register(self)
    
    def _get_default_data(self) -> dict:
        """返回默认数据结构"""
        return {
            "version": self.VERSION,
            "providers": {}
        }
    
    def _do_load(self) -> None:
        """加载所有数据（包含数据迁移：清理非 UUID 格式的 provider key）"""
        data = self._read_from_file()
        
        self._providers.clear()
        needs_save = False
        skipped_keys = []
        
        for provider_id, provider_data in data.get("providers", {}).items():
            # 数据迁移：跳过非 UUID 格式的 key（旧格式使用 provider name）
            if not self._is_valid_uuid(provider_id):
                skipped_keys.append(provider_id)
                needs_save = True
                continue
            
            self._providers[provider_id] = ProviderModels.from_dict(
                provider_id, provider_data
            )
        
        # 如果有数据需要迁移，保存清理后的数据
        if needs_save:
            print(f"[PROVIDER-MODELS] 数据迁移: 移除 {len(skipped_keys)} 个旧格式 key (非 UUID): {skipped_keys}")
            self._do_save()
    
    def _do_save(self) -> None:
        """保存所有数据"""
        data = {
            "version": self.VERSION,
            "providers": {
                provider_id: p.to_dict() for provider_id, p in self._providers.items()
            }
        }
        self._write_to_file(data)
    
    @staticmethod
    def _is_valid_uuid(value: str) -> bool:
        """检查字符串是否是有效的 UUID 格式"""
        try:
            uuid.UUID(value)
            return True
        except (ValueError, TypeError):
            return False
    
    # ==================== Provider 操作 ====================
    
    def get_provider(self, provider_id: str) -> Optional[ProviderModels]:
        """获取指定 Provider 的模型集合"""
        self._ensure_loaded()
        with self._lock:
            return self._providers.get(provider_id)
    
    def get_all_providers(self) -> dict[str, ProviderModels]:
        """获取所有 Provider（key 为 provider_id）"""
        self._ensure_loaded()
        with self._lock:
            return self._providers.copy()
    
    def get_provider_model_ids(self, provider_id: str) -> list[str]:
        """获取指定 Provider 的模型 ID 列表"""
        provider = self.get_provider(provider_id)
        if provider:
            return provider.get_model_ids()
        return []
    
    def delete_provider(self, provider_id: str) -> bool:
        """
        删除 Provider（当 Provider 被删除时调用）
        
        Note:
            配置变更，立即保存
        """
        self._ensure_loaded()
        with self._lock:
            if provider_id in self._providers:
                del self._providers[provider_id]
                self.save(immediate=True)
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
        remote_models: list[dict],
        provider_name: Optional[str] = None
    ) -> tuple[int, int, int, list[str], list[str]]:
        """
        从中转站获取的模型列表更新本地存储
        
        Args:
            provider_id: Provider 的唯一 ID (UUID)
            remote_models: 远程模型列表 [{"id": "...", "owned_by": "..."}, ...]
            provider_name: Provider 显示名称（用于日志）
            
        Returns:
            (新增数量, 更新数量, 删除数量, 新增模型列表, 删除模型列表)
            
        Note:
            配置变更，立即保存
        """
        self._ensure_loaded()
        
        with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            
            # 确保 Provider 存在
            if provider_id not in self._providers:
                self._providers[provider_id] = ProviderModels(provider_id=provider_id)
            
            provider = self._providers[provider_id]
            
            # 统计
            added_count = 0
            updated_count = 0
            removed_count = 0
            added_models: list[str] = []
            removed_models: list[str] = []
            
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
                        updated_count += 1
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
                    added_count += 1
                    added_models.append(model_id)
            
            # 处理删除（远程不存在但本地存在的模型）
            to_remove = local_model_ids - remote_model_ids
            for model_id in to_remove:
                del provider.models[model_id]
                removed_count += 1
                removed_models.append(model_id)
            
            # 输出日志
            self._log_sync_changes(provider_id, provider_name, added_models, removed_models)
            
            # 配置变更，立即保存
            self.save(immediate=True)
            
            return added_count, updated_count, removed_count, added_models, removed_models
    
    def _log_sync_changes(
        self,
        provider_id: str,
        provider_name: Optional[str],
        added_models: list[str],
        removed_models: list[str]
    ) -> None:
        """
        输出同步变化日志
        
        Args:
            provider_id: Provider ID
            provider_name: Provider 显示名称
            added_models: 新增的模型列表
            removed_models: 删除的模型列表
        """
        # 延迟导入避免循环依赖
        from .logger import log_manager, LogLevel
        
        display_name = provider_name or provider_id[:8]
        
        if not added_models and not removed_models:
            return
        
        # 构建控制台输出（带颜色）
        console_parts = []
        # 构建日志消息（无颜色）
        log_parts = []
        
        if added_models:
            sorted_added = sorted(added_models)
            models_preview = ", ".join(sorted_added[:5])  # 最多显示5个
            suffix = f"等{len(added_models)}个" if len(added_models) > 5 else ""
            console_parts.append(f"新增 {len(added_models)} 个模型（{models_preview}{suffix}）")
            log_parts.append(f"新增 {len(added_models)} 个模型（{models_preview}{suffix}）")
        
        if removed_models:
            sorted_removed = sorted(removed_models)
            models_preview = ", ".join(sorted_removed[:5])  # 最多显示5个
            suffix = f"等{len(removed_models)}个" if len(removed_models) > 5 else ""
            console_parts.append(f"移除 {len(removed_models)} 个模型（{models_preview}{suffix}）")
            log_parts.append(f"移除 {len(removed_models)} 个模型（{models_preview}{suffix}）")
        
        console_message = f"[{display_name}] 同步完成：{', '.join(console_parts)}"
        log_message = f"[{display_name}] 同步完成：{', '.join(log_parts)}"
        
        print(f"[PROVIDER-MODELS] {console_message}")
        log_manager.log(
            level=LogLevel.INFO,
            log_type="sync",
            method="SYNC",
            path="/provider-models",
            provider=display_name,
            message=log_message
        )
    
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
            
        Note:
            配置变更，立即保存
        """
        self._ensure_loaded()
        
        with self._lock:
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
            
            # 配置变更，立即保存
            self.save(immediate=True)
            return True
    
    def remove_model(self, provider_id: str, model_id: str) -> bool:
        """
        删除单个模型
        
        Note:
            配置变更，立即保存
        """
        self._ensure_loaded()
        
        with self._lock:
            provider = self._providers.get(provider_id)
            if provider and model_id in provider.models:
                del provider.models[model_id]
                # 配置变更，立即保存
                self.save(immediate=True)
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
            
        Note:
            统计更新，仅标记脏数据，由定时任务保存
        """
        self._ensure_loaded()
        
        with self._lock:
            model = self.get_model(provider_id, model_id)
            if model:
                model.last_activity = datetime.now(timezone.utc).isoformat()
                model.last_activity_type = activity_type
                # 统计更新，仅标记脏数据
                self.mark_dirty()
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
            
        Note:
            统计更新，仅标记脏数据，由定时任务保存
        """
        self._ensure_loaded()
        
        with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            count = 0
            
            for provider_id, model_id, activity_type in updates:
                model = self.get_model(provider_id, model_id)
                if model:
                    model.last_activity = now
                    model.last_activity_type = activity_type
                    count += 1
            
            if count > 0:
                # 统计更新，仅标记脏数据
                self.mark_dirty()
            
            return count
    
    # ==================== 查询辅助 ====================
    
    def get_all_provider_models_map(self) -> dict[str, list[str]]:
        """
        获取所有 Provider 的模型 ID 映射
        
        Returns:
            {provider_id: [model_id, ...]}
        """
        self._ensure_loaded()
        
        with self._lock:
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
        
        with self._lock:
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
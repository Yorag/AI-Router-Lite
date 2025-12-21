from typing import Optional

from .sqlite_repos import ProviderRepo
from .provider_models import provider_models_manager
from .provider import provider_manager
from .model_mapping import model_mapping_manager
from .config import ProviderConfig


class AdminManager:
    """管理功能管理器（SQLite 版本：providers SSOT）"""

    def __init__(self):
        self._providers = ProviderRepo()

    def list_providers(self) -> list[dict]:
        providers = self._providers.list()
        # Populate supported_models from provider_models table (DB-driven, no HTTP)
        # This is required for frontend compatibility (providers.js)
        provider_models_map = provider_models_manager.get_all_provider_models_map()
        
        # Get all mapped model keys for highlighting
        mapped_keys = model_mapping_manager.get_all_mapped_model_keys()
        
        for p in providers:
            provider_id = p["id"]
            models = provider_models_map.get(provider_id, [])
            p["supported_models"] = models
            
            # Add mapped_models field for highlighting
            # Contains list of model IDs that are used in any enabled mapping
            p["mapped_models"] = [
                m for m in models
                if f"{provider_id}:{m}" in mapped_keys
            ]
        return providers

    def get_provider_by_id(self, provider_id: str) -> Optional[dict]:
        return self._providers.get_by_id(provider_id)

    def get_provider(self, provider_id: str) -> Optional[dict]:
        return self.get_provider_by_id(provider_id)

    def get_provider_id_name_map(self) -> dict[str, str]:
        return self._providers.get_id_name_map()

    def get_provider_name_id_map(self) -> dict[str, str]:
        return self._providers.get_name_id_map()

    def get_provider_protocols(self) -> dict[str, Optional[str]]:
        return self._providers.get_protocols()

    def _handle_manual_models(self, provider_id: str, provider_name: Optional[str], manual_models: Optional[list[str]]) -> None:
        """处理手动输入的模型列表同步"""
        if manual_models is not None:
            provider_models_manager.update_models_from_manual_input(
                provider_id=provider_id,
                model_ids=manual_models,
                provider_name=provider_name
            )

    def add_provider(self, provider_data: dict) -> tuple[bool, str, Optional[str]]:
        try:
            provider_id = provider_data.get("id")
            if not provider_id:
                return False, "Provider 缺少 id（SQLite 版本要求前端生成或显式传入）", None

            # 提取 manual_models，但不立即处理
            manual_models = provider_data.pop("manual_models", None)
            
            # 1. 先创建 Provider (满足外键约束)
            self._providers.upsert(provider_data)
            
            # 2. 再处理模型同步
            self._handle_manual_models(provider_id, provider_data.get("name"), manual_models)

            # 3. 同步更新内存状态
            provider_manager.register(ProviderConfig(**provider_data))

            return True, "添加成功", provider_id
        except Exception as e:
            return False, str(e), None

    def update_provider(self, provider_id: str, provider_data: dict) -> tuple[bool, str]:
        provider_data = dict(provider_data)
        provider_data["id"] = provider_id

        # 从数据中弹出 manual_models
        manual_models = provider_data.pop("manual_models", None)

        try:
            # 1. 更新服务站自身的信息
            self._providers.upsert(provider_data)

            # 2. 处理模型同步
            self._handle_manual_models(provider_id, provider_data.get("name"), manual_models)

            # 3. 同步更新内存状态
            provider_state = provider_manager.get(provider_id)
            if provider_state:
                # 获取完整数据以确保配置完整性
                full_provider_data = self._providers.get_by_id(provider_id)
                if full_provider_data:
                    provider_state.config = ProviderConfig(**full_provider_data)

            return True, "更新成功"
        except Exception as e:
            return False, str(e)

    def delete_provider(self, provider_id: str) -> tuple[bool, str]:
        try:
            ok = self._providers.delete(provider_id)
            if not ok:
                return False, f"Provider ID '{provider_id}' 不存在"
            
            # Note: Provider models cleanup should be handled by foreign key cascade in SQLite
            
            # 同步更新内存状态
            provider_manager.deregister(provider_id)

            return True, "删除成功"
        except Exception as e:
            return False, str(e)


admin_manager = AdminManager()
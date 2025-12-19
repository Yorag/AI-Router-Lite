from typing import Optional

from .sqlite_repos import ProviderRepo
from .provider_models import provider_models_manager


class AdminManager:
    """管理功能管理器（SQLite 版本：providers SSOT）"""

    def __init__(self):
        self._providers = ProviderRepo()

    def list_providers(self) -> list[dict]:
        providers = self._providers.list()
        # Populate supported_models from provider_models table (DB-driven, no HTTP)
        # This is required for frontend compatibility (providers.js)
        provider_models_map = provider_models_manager.get_all_provider_models_map()
        for p in providers:
            p["supported_models"] = provider_models_map.get(p["id"], [])
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

    def add_provider(self, provider_data: dict) -> tuple[bool, str, Optional[str]]:
        try:
            provider_id = provider_data.get("id")
            if not provider_id:
                return False, "Provider 缺少 id（SQLite 版本要求前端生成或显式传入）", None
            self._providers.upsert(provider_data)
            return True, "添加成功", provider_id
        except Exception as e:
            return False, str(e), None

    def update_provider(self, provider_id: str, provider_data: dict) -> tuple[bool, str]:
        provider_data = dict(provider_data)
        provider_data["id"] = provider_id
        try:
            self._providers.upsert(provider_data)
            return True, "更新成功"
        except Exception as e:
            return False, str(e)

    def delete_provider(self, provider_id: str) -> tuple[bool, str]:
        try:
            ok = self._providers.delete(provider_id)
            if not ok:
                return False, f"Provider ID '{provider_id}' 不存在"
            
            # Note: Provider models cleanup should be handled by foreign key cascade in SQLite
            return True, "删除成功"
        except Exception as e:
            return False, str(e)


admin_manager = AdminManager()
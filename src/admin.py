"""
管理模块

负责 Provider 管理、模型映射管理等管理功能
"""

import json
import asyncio
from pathlib import Path
from typing import Optional

import httpx

from .config import config_manager, generate_provider_id
from .constants import ADMIN_HTTP_TIMEOUT
from .provider_models import provider_models_manager


class AdminManager:
    """管理功能管理器"""
    
    def __init__(self, config_path: str = "config.json"):
        self.config_path = Path(config_path)
    
    def get_config(self) -> dict:
        """获取当前配置"""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            return {"error": str(e)}
    
    def save_config(self, config: dict) -> bool:
        """保存配置"""
        try:
            # 备份当前配置
            backup_path = self.config_path.with_suffix(".json.bak")
            if self.config_path.exists():
                with open(self.config_path, "r", encoding="utf-8") as f:
                    backup_data = f.read()
                with open(backup_path, "w", encoding="utf-8") as f:
                    f.write(backup_data)
            
            # 保存新配置
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            
            return True
        except Exception as e:
            print(f"[AdminManager] 保存配置失败: {e}")
            return False
    
    # ==================== Provider 管理 ====================
    
    def list_providers(self) -> list[dict]:
        """
        列出所有 Provider（合并模型列表）
        
        从 config.json 读取 Provider 配置，并从 provider_models.json 获取模型列表，
        合并后返回给前端，保持 API 兼容性。
        """
        config = self.get_config()
        providers = config.get("providers", [])
        
        # 从 provider_models_manager 获取模型列表，合并到返回结果
        for provider in providers:
            provider_id = provider.get("id", "")
            model_ids = provider_models_manager.get_provider_model_ids(provider_id)
            provider["supported_models"] = model_ids
        
        return providers
    
    def get_provider_by_id(self, provider_id: str) -> Optional[dict]:
        """通过 ID 获取指定 Provider"""
        config = self.get_config()
        for provider in config.get("providers", []):
            if provider.get("id") == provider_id:
                return provider
        return None
    
    def get_provider_by_name(self, name: str) -> Optional[dict]:
        """通过名称获取指定 Provider（用于兼容旧代码）"""
        config = self.get_config()
        for provider in config.get("providers", []):
            if provider.get("name") == name:
                return provider
        return None
    
    def get_provider(self, provider_id: str) -> Optional[dict]:
        """
        获取指定 Provider
        
        优先通过 ID 查找，如果找不到则尝试通过 name 查找（兼容性）
        """
        # 优先通过 ID 查找
        provider = self.get_provider_by_id(provider_id)
        if provider:
            return provider
        # 兼容：尝试通过 name 查找
        return self.get_provider_by_name(provider_id)
    
    def get_provider_id_name_map(self) -> dict[str, str]:
        """获取 provider_id -> name 的映射"""
        config = self.get_config()
        return {
            p.get("id", ""): p.get("name", "")
            for p in config.get("providers", [])
            if p.get("id")
        }
    
    def get_provider_name_id_map(self) -> dict[str, str]:
        """获取 name -> provider_id 的映射"""
        config = self.get_config()
        return {
            p.get("name", ""): p.get("id", "")
            for p in config.get("providers", [])
            if p.get("name")
        }
    
    def add_provider(self, provider_data: dict) -> tuple[bool, str, Optional[str]]:
        """
        添加 Provider
        
        注意：
        - 自动生成唯一 ID (UUID)
        - 模型列表不在 config.json 中存储，
          需要通过 /api/providers/{id}/models 接口同步获取
          
        Returns:
            (成功标志, 消息, 新Provider的ID)
        """
        config = self.get_config()
        providers = config.get("providers", [])
        
        # 验证必填字段
        required_fields = ["name", "base_url", "api_key"]
        for field in required_fields:
            if not provider_data.get(field):
                return False, f"缺少必填字段: {field}", None
        
        # 检查名称是否已存在（name 也应保持唯一，便于识别）
        name = provider_data.get("name", "")
        if any(p.get("name") == name for p in providers):
            return False, f"Provider 名称 '{name}' 已存在", None
        
        # 生成唯一 ID（如果前端没有传入）
        if not provider_data.get("id"):
            provider_data["id"] = generate_provider_id()
        else:
            # 检查 ID 是否已存在
            if any(p.get("id") == provider_data["id"] for p in providers):
                return False, f"Provider ID '{provider_data['id']}' 已存在", None
        
        # 设置默认值
        if "weight" not in provider_data:
            provider_data["weight"] = 1
        
        # 移除 supported_models 字段（如果前端意外传入）
        provider_data.pop("supported_models", None)
        
        providers.append(provider_data)
        config["providers"] = providers
        
        if self.save_config(config):
            return True, "添加成功", provider_data["id"]
        return False, "保存配置失败", None
    
    def update_provider(self, provider_id: str, provider_data: dict) -> tuple[bool, str]:
        """
        更新 Provider
        
        Args:
            provider_id: Provider 的唯一 ID
            provider_data: 要更新的数据（可以包含新的 name）
        """
        config = self.get_config()
        providers = config.get("providers", [])
        
        for i, provider in enumerate(providers):
            if provider.get("id") == provider_id:
                # 保留 ID 不可更改
                provider_data["id"] = provider_id
                
                # 如果要修改名称，检查新名称是否与其他 Provider 冲突
                new_name = provider_data.get("name", "")
                old_name = provider.get("name", "")
                if new_name and new_name != old_name:
                    if any(p.get("name") == new_name and p.get("id") != provider_id for p in providers):
                        return False, f"Provider 名称 '{new_name}' 已被其他 Provider 使用"
                
                # 移除 supported_models 字段（如果前端意外传入）
                provider_data.pop("supported_models", None)
                
                providers[i] = provider_data
                config["providers"] = providers
                
                if self.save_config(config):
                    return True, "更新成功"
                return False, "保存配置失败"
        
        return False, f"Provider ID '{provider_id}' 不存在"
    
    def delete_provider(self, provider_id: str) -> tuple[bool, str]:
        """
        删除 Provider
        
        Args:
            provider_id: Provider 的唯一 ID
        """
        config = self.get_config()
        providers = config.get("providers", [])
        
        # 查找要删除的 Provider
        provider_to_delete = None
        for p in providers:
            if p.get("id") == provider_id:
                provider_to_delete = p
                break
        
        if not provider_to_delete:
            return False, f"Provider ID '{provider_id}' 不存在"
        
        # 从配置中移除
        new_providers = [p for p in providers if p.get("id") != provider_id]
        config["providers"] = new_providers
        
        if self.save_config(config):
            # 同时清理 provider_models 中的数据
            provider_models_manager.delete_provider(provider_id)
            return True, "删除成功"
        return False, "保存配置失败"
    
    # ==================== 获取远程模型列表 ====================
    
    async def fetch_provider_models(
        self,
        provider_id: str,
        save_to_storage: bool = True
    ) -> tuple[bool, list[dict], str, dict]:
        """
        从中转站获取可用模型列表
        
        仅提取 id 和 owned_by 字段，并可选保存到 provider_models.json。
        
        Args:
            provider_id: Provider 的唯一 ID
            save_to_storage: 是否保存到持久化存储（默认 True）
            
        Returns:
            (成功标志, 模型列表, 错误信息, 同步统计 {added, updated, removed})
        """
        provider = self.get_provider(provider_id)
        if not provider:
            return False, [], "Provider 不存在", {}
        
        base_url = provider.get("base_url", "").rstrip("/")
        api_key = provider.get("api_key", "")
        
        try:
            async with httpx.AsyncClient(timeout=ADMIN_HTTP_TIMEOUT) as client:
                response = await client.get(
                    f"{base_url}/models",
                    headers={"Authorization": f"Bearer {api_key}"}
                )
                
                if response.status_code == 200:
                    data = response.json()
                    models = []
                    # OpenAI 格式: {"data": [{"id": "model-name"}, ...]}
                    if "data" in data:
                        for m in data["data"]:
                            if m.get("id"):
                                models.append({
                                    "id": m.get("id"),
                                    "owned_by": m.get("owned_by", ""),
                                    "supported_endpoint_types": m.get("supported_endpoint_types", [])
                                })
                    # 按 id 排序
                    models.sort(key=lambda x: x["id"])
                    
                    # 保存到持久化存储（使用 provider_id 作为 key）
                    sync_stats = {}
                    if save_to_storage:
                        added, updated, removed = provider_models_manager.update_models_from_remote(
                            provider_id, models
                        )
                        sync_stats = {
                            "added": added,
                            "updated": updated,
                            "removed": removed
                        }
                    
                    return True, models, "", sync_stats
                else:
                    return False, [], f"HTTP {response.status_code}", {}
        except Exception as e:
            return False, [], str(e), {}
    
    async def fetch_all_provider_models(
        self,
        save_to_storage: bool = True
    ) -> dict[str, list[dict]]:
        """
        获取所有中转站的模型列表（并发请求）
        
        Args:
            save_to_storage: 是否保存到持久化存储（默认 True）
            
        Returns:
            {provider_id: [{"id": ..., "owned_by": ...}, ...]}
        """
        result = {}
        providers = self.list_providers()
        
        if not providers:
            return result
        
        # 并发获取所有 provider 的模型列表
        async def fetch_single(provider: dict) -> tuple[str, bool, list[dict]]:
            provider_id = provider.get("id", "")
            success, models, _, _ = await self.fetch_provider_models(
                provider_id, save_to_storage=save_to_storage
            )
            return provider_id, success, models
        
        tasks = [fetch_single(p) for p in providers]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        for response in responses:
            if isinstance(response, Exception):
                continue
            provider_id, success, models = response
            if success:
                result[provider_id] = models
        
        return result
    
    def filter_models_by_keyword(self, models: list[str], keyword: str) -> list[str]:
        """根据关键字筛选模型"""
        if not keyword:
            return models
        keyword = keyword.lower()
        return [m for m in models if keyword in m.lower()]


# 全局实例
admin_manager = AdminManager()
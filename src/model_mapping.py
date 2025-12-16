"""
模型映射管理模块

负责管理增强型模型映射，支持规则匹配、手动包含/排除、自动同步

注意：所有 provider 相关的存储和引用都使用 provider_id (UUID)，而非 provider name。
- resolved_models: {provider_id: [model_ids]}
- excluded_providers: [provider_id, ...]
- manual_includes/excludes: "model_id" 或 "provider_id:model_id"
"""

import json
import re
import asyncio
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Any
from dataclasses import dataclass, field, asdict
from enum import Enum
import filelock

from .constants import MODEL_MAPPINGS_STORAGE_PATH

class RuleType(str, Enum):
    """匹配规则类型"""
    KEYWORD = "keyword"      # 关键字包含匹配
    REGEX = "regex"          # 正则表达式匹配
    PREFIX = "prefix"        # 前缀匹配
    EXACT = "exact"          # 精确匹配


@dataclass
class MatchRule:
    """匹配规则"""
    type: RuleType
    pattern: str
    case_sensitive: bool = False
    
    def to_dict(self) -> dict:
        return {
            "type": self.type.value,
            "pattern": self.pattern,
            "case_sensitive": self.case_sensitive
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "MatchRule":
        return cls(
            type=RuleType(data.get("type", "keyword")),
            pattern=data.get("pattern", ""),
            case_sensitive=data.get("case_sensitive", False)
        )

@dataclass
class ModelMapping:
    """
    单个模型映射配置
    
    model_settings 字段用于存储特定 provider:model 组合的配置：
    - key: "{provider_id}:{model_id}"
    - value: {"protocol": "openai" | "openai-response" | "anthropic" | "gemini", ...}
    
    协议继承机制：
    1. 优先使用 model_settings 中指定的协议
    2. 如果未指定，则使用 Provider 的 default_protocol
    3. 如果 Provider 也未指定（混合类型），则该模型视为不可用
    """
    unified_name: str
    description: str = ""
    rules: list[MatchRule] = field(default_factory=list)
    manual_includes: list[str] = field(default_factory=list)  # 格式: "model_id" 或 "provider_id:model_id"
    manual_excludes: list[str] = field(default_factory=list)  # 格式: "model_id" 或 "provider_id:model_id"
    excluded_providers: list[str] = field(default_factory=list)  # 排除的 provider_id 列表
    resolved_models: dict[str, list[str]] = field(default_factory=dict)  # {provider_id: [models]}
    model_settings: dict[str, dict] = field(default_factory=dict)  # {provider_id:model_id: {protocol: str, ...}}
    last_sync: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            "description": self.description,
            "rules": [r.to_dict() for r in self.rules],
            "manual_includes": self.manual_includes,
            "manual_excludes": self.manual_excludes,
            "excluded_providers": self.excluded_providers,
            "resolved_models": self.resolved_models,
            "model_settings": self.model_settings,
            "last_sync": self.last_sync
        }
    
    @classmethod
    def from_dict(cls, unified_name: str, data: dict) -> "ModelMapping":
        return cls(
            unified_name=unified_name,
            description=data.get("description", ""),
            rules=[MatchRule.from_dict(r) for r in data.get("rules", [])],
            manual_includes=data.get("manual_includes", []),
            manual_excludes=data.get("manual_excludes", []),
            excluded_providers=data.get("excluded_providers", []),
            resolved_models=data.get("resolved_models", {}),
            model_settings=data.get("model_settings", {}),
            last_sync=data.get("last_sync")
        )
    
    def get_all_models(self) -> list[str]:
        """获取所有解析后的模型列表（去重）"""
        models = set()
        for provider_models in self.resolved_models.values():
            models.update(provider_models)
        return sorted(models)
    
    def get_model_protocol(self, provider_id: str, model_id: str) -> Optional[str]:
        """
        获取指定模型的协议配置
        
        Args:
            provider_id: Provider 的唯一 ID
            model_id: 模型 ID
            
        Returns:
            协议类型字符串，如果未配置则返回 None
        """
        key = f"{provider_id}:{model_id}"
        settings = self.model_settings.get(key, {})
        return settings.get("protocol")
    
    def set_model_protocol(self, provider_id: str, model_id: str, protocol: Optional[str]) -> None:
        """
        设置指定模型的协议配置
        
        Args:
            provider_id: Provider 的唯一 ID
            model_id: 模型 ID
            protocol: 协议类型字符串，为 None 时删除配置
        """
        key = f"{provider_id}:{model_id}"
        if protocol is None:
            # 删除配置
            if key in self.model_settings:
                del self.model_settings[key]
        else:
            # 设置配置
            if key not in self.model_settings:
                self.model_settings[key] = {}
            self.model_settings[key]["protocol"] = protocol


@dataclass
class SyncConfig:
    """同步配置"""
    auto_sync_enabled: bool = False
    auto_sync_interval_hours: int = 6
    last_full_sync: Optional[str] = None
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> "SyncConfig":
        return cls(
            auto_sync_enabled=data.get("auto_sync_enabled", False),
            auto_sync_interval_hours=data.get("auto_sync_interval_hours", 6),
            last_full_sync=data.get("last_full_sync")
        )


class RuleMatcher:
    """规则匹配引擎"""
    
    @staticmethod
    def match(rule: MatchRule, model_id: str) -> bool:
        """
        检查模型ID是否匹配规则
        
        Args:
            rule: 匹配规则
            model_id: 模型ID
            
        Returns:
            是否匹配
        """
        pattern = rule.pattern
        target = model_id
        
        # 处理大小写敏感
        if not rule.case_sensitive:
            pattern = pattern.lower()
            target = target.lower()
        
        if rule.type == RuleType.KEYWORD:
            return pattern in target
        
        elif rule.type == RuleType.PREFIX:
            return target.startswith(pattern)
        
        elif rule.type == RuleType.EXACT:
            return target == pattern
        
        elif rule.type == RuleType.REGEX:
            try:
                flags = 0 if rule.case_sensitive else re.IGNORECASE
                return bool(re.search(rule.pattern, model_id, flags))
            except re.error:
                # 正则表达式无效
                return False
        
        return False
    
    @staticmethod
    def match_any(rules: list[MatchRule], model_id: str) -> bool:
        """
        检查模型ID是否匹配任意规则（取并集）
        
        Args:
            rules: 规则列表
            model_id: 模型ID
            
        Returns:
            是否匹配任意规则
        """
        for rule in rules:
            if RuleMatcher.match(rule, model_id):
                return True
        return False


class ModelMappingManager:
    """模型映射管理器"""
    
    VERSION = "1.0"
    
    def __init__(self, data_path: str = MODEL_MAPPINGS_STORAGE_PATH):
        self.data_path = Path(data_path)
        self.lock_path = self.data_path.with_suffix(".json.lock")
        self._mappings: dict[str, ModelMapping] = {}
        self._sync_config: SyncConfig = SyncConfig()
        self._loaded = False
    
    def _ensure_file_exists(self) -> None:
        """确保数据文件存在"""
        if not self.data_path.exists():
            self.data_path.parent.mkdir(parents=True, exist_ok=True)
            self._save_data({
                "version": self.VERSION,
                "mappings": {},
                "sync_config": SyncConfig().to_dict()
            })
    
    def _load_data(self) -> dict:
        """加载数据文件"""
        self._ensure_file_exists()
        with open(self.data_path, "r", encoding="utf-8") as f:
            return json.load(f)
    
    def _save_data(self, data: dict) -> None:
        """保存数据文件（带文件锁）"""
        self.data_path.parent.mkdir(parents=True, exist_ok=True)
        lock = filelock.FileLock(self.lock_path, timeout=10)
        with lock:
            with open(self.data_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
    
    def load(self) -> None:
        """加载所有映射配置"""
        data = self._load_data()
        
        # 解析映射
        self._mappings = {}
        for name, mapping_data in data.get("mappings", {}).items():
            self._mappings[name] = ModelMapping.from_dict(name, mapping_data)
        
        # 解析同步配置
        self._sync_config = SyncConfig.from_dict(data.get("sync_config", {}))
        self._loaded = True
    
    def save(self) -> None:
        """保存所有映射配置"""
        data = {
            "version": self.VERSION,
            "mappings": {name: m.to_dict() for name, m in self._mappings.items()},
            "sync_config": self._sync_config.to_dict()
        }
        self._save_data(data)
    
    def _ensure_loaded(self) -> None:
        """确保数据已加载"""
        if not self._loaded:
            self.load()
    
    # ==================== 映射 CRUD ====================
    
    def get_all_mappings(self) -> dict[str, ModelMapping]:
        """获取所有映射"""
        self._ensure_loaded()
        return self._mappings.copy()
    
    def get_mapping(self, unified_name: str) -> Optional[ModelMapping]:
        """获取指定映射"""
        self._ensure_loaded()
        return self._mappings.get(unified_name)
    
    def create_mapping(
        self,
        unified_name: str,
        description: str = "",
        rules: Optional[list[dict]] = None,
        manual_includes: Optional[list[str]] = None,
        manual_excludes: Optional[list[str]] = None,
        excluded_providers: Optional[list[str]] = None
    ) -> tuple[bool, str]:
        """
        创建新映射
        
        Args:
            unified_name: 统一模型名称
            description: 描述
            rules: 规则列表
            manual_includes: 手动包含的模型
            manual_excludes: 手动排除的模型
            excluded_providers: 排除的渠道列表
            
        Returns:
            (成功标志, 消息)
        """
        self._ensure_loaded()
        
        if unified_name in self._mappings:
            return False, f"映射 '{unified_name}' 已存在"
        
        if not unified_name or not unified_name.strip():
            return False, "统一模型名称不能为空"
        
        mapping = ModelMapping(
            unified_name=unified_name,
            description=description,
            rules=[MatchRule.from_dict(r) for r in (rules or [])],
            manual_includes=manual_includes or [],
            manual_excludes=manual_excludes or [],
            excluded_providers=excluded_providers or []
        )
        
        self._mappings[unified_name] = mapping
        self.save()
        return True, "创建成功"
    
    def update_mapping(
        self,
        unified_name: str,
        description: Optional[str] = None,
        rules: Optional[list[dict]] = None,
        manual_includes: Optional[list[str]] = None,
        manual_excludes: Optional[list[str]] = None,
        excluded_providers: Optional[list[str]] = None
    ) -> tuple[bool, str]:
        """
        更新映射
        
        Args:
            unified_name: 统一模型名称
            description: 描述（可选）
            rules: 规则列表（可选）
            manual_includes: 手动包含的模型（可选）
            manual_excludes: 手动排除的模型（可选）
            excluded_providers: 排除的渠道列表（可选）
            
        Returns:
            (成功标志, 消息)
        """
        self._ensure_loaded()
        
        if unified_name not in self._mappings:
            return False, f"映射 '{unified_name}' 不存在"
        
        mapping = self._mappings[unified_name]
        
        if description is not None:
            mapping.description = description
        if rules is not None:
            mapping.rules = [MatchRule.from_dict(r) for r in rules]
        if manual_includes is not None:
            mapping.manual_includes = manual_includes
        if manual_excludes is not None:
            mapping.manual_excludes = manual_excludes
        if excluded_providers is not None:
            mapping.excluded_providers = excluded_providers
        
        self.save()
        return True, "更新成功"
    
    def delete_mapping(self, unified_name: str) -> tuple[bool, str]:
        """删除映射"""
        self._ensure_loaded()
        
        if unified_name not in self._mappings:
            return False, f"映射 '{unified_name}' 不存在"
        
        del self._mappings[unified_name]
        self.save()
        return True, "删除成功"
    
    def update_model_settings(
        self,
        unified_name: str,
        model_settings: dict[str, dict]
    ) -> tuple[bool, str]:
        """
        更新映射的模型设置
        
        Args:
            unified_name: 统一模型名称
            model_settings: 模型设置字典 {provider_id:model_id: {protocol: str, ...}}
            
        Returns:
            (成功标志, 消息)
        """
        self._ensure_loaded()
        
        if unified_name not in self._mappings:
            return False, f"映射 '{unified_name}' 不存在"
        
        mapping = self._mappings[unified_name]
        mapping.model_settings = model_settings
        
        self.save()
        return True, "更新成功"
    
    def set_model_protocol(
        self,
        unified_name: str,
        provider_id: str,
        model_id: str,
        protocol: Optional[str]
    ) -> tuple[bool, str]:
        """
        设置单个模型的协议配置
        
        Args:
            unified_name: 统一模型名称
            provider_id: Provider 的唯一 ID
            model_id: 模型 ID
            protocol: 协议类型字符串，为 None 时删除配置
            
        Returns:
            (成功标志, 消息)
        """
        self._ensure_loaded()
        
        if unified_name not in self._mappings:
            return False, f"映射 '{unified_name}' 不存在"
        
        mapping = self._mappings[unified_name]
        mapping.set_model_protocol(provider_id, model_id, protocol)
        
        self.save()
        return True, "更新成功"
    
    # ==================== 同步配置 ====================
    
    def get_sync_config(self) -> SyncConfig:
        """获取同步配置"""
        self._ensure_loaded()
        return self._sync_config
    
    def update_sync_config(
        self,
        auto_sync_enabled: Optional[bool] = None,
        auto_sync_interval_hours: Optional[int] = None
    ) -> tuple[bool, str]:
        """更新同步配置"""
        self._ensure_loaded()
        
        if auto_sync_enabled is not None:
            self._sync_config.auto_sync_enabled = auto_sync_enabled
        if auto_sync_interval_hours is not None:
            if auto_sync_interval_hours < 1:
                return False, "同步间隔不能小于1小时"
            self._sync_config.auto_sync_interval_hours = auto_sync_interval_hours
        
        self.save()
        return True, "更新成功"
    
    # ==================== 规则匹配与同步 ====================
    
    def resolve_models(
        self,
        mapping: ModelMapping,
        all_provider_models: dict[str, list[str]]
    ) -> dict[str, list[str]]:
        """
        解析映射规则，获取匹配的模型
        
        Args:
            mapping: 映射配置
            all_provider_models: 所有Provider的模型列表 {provider_id: [model_ids]}
            
        Returns:
            解析后的模型 {provider_id: [model_ids]}
        """
        # 解析手动包含/排除的引用格式
        def parse_model_ref(ref: str) -> tuple[Optional[str], str]:
            """解析模型引用，返回 (provider_id, model_id)"""
            if ":" in ref:
                parts = ref.split(":", 1)
                return parts[0], parts[1]
            return None, ref
        
        # 获取排除的渠道列表（使用 provider_id）
        excluded_providers = set(mapping.excluded_providers or [])
        
        # 收集所有匹配的模型 (provider_id, model_id)
        matched: set[tuple[str, str]] = set()
        
        # 1. 应用所有规则（取并集），跳过被排除的渠道
        for provider_id, models in all_provider_models.items():
            if provider_id in excluded_providers:
                continue
            for model_id in models:
                if RuleMatcher.match_any(mapping.rules, model_id):
                    matched.add((provider_id, model_id))
        
        # 2. 添加手动包含（手动包含不受排除渠道限制，因为是用户明确指定的）
        for ref in mapping.manual_includes:
            provider_id, model_id = parse_model_ref(ref)
            if provider_id:
                # 指定了 provider_id（即使在排除列表中也允许，因为是用户明确指定）
                if provider_id in all_provider_models and model_id in all_provider_models[provider_id]:
                    matched.add((provider_id, model_id))
            else:
                # 未指定 provider_id，添加到所有包含该模型的 Provider（排除被排除的渠道）
                for prov_id, models in all_provider_models.items():
                    if prov_id in excluded_providers:
                        continue
                    if model_id in models:
                        matched.add((prov_id, model_id))
        
        # 3. 移除手动排除（最高优先级）
        for ref in mapping.manual_excludes:
            provider_id, model_id = parse_model_ref(ref)
            if provider_id:
                # 指定了 provider_id
                matched.discard((provider_id, model_id))
            else:
                # 未指定 provider_id，从所有 Provider 中排除
                to_remove = [(p, m) for p, m in matched if m == model_id]
                for item in to_remove:
                    matched.discard(item)
        
        # 按 provider_id 分组
        result: dict[str, list[str]] = {}
        for provider_id, model_id in matched:
            if provider_id not in result:
                result[provider_id] = []
            result[provider_id].append(model_id)
        
        # 排序
        for provider_id in result:
            result[provider_id].sort()
        
        return result
    
    def preview_resolve(
        self,
        rules: list[dict],
        manual_includes: list[str],
        manual_excludes: list[str],
        all_provider_models: dict[str, list[str]],
        excluded_providers: Optional[list[str]] = None
    ) -> dict[str, list[str]]:
        """
        预览解析结果（不保存）
        
        Args:
            rules: 规则列表
            manual_includes: 手动包含
            manual_excludes: 手动排除
            all_provider_models: 所有Provider的模型列表
            excluded_providers: 排除的渠道列表
            
        Returns:
            预览的解析结果
        """
        temp_mapping = ModelMapping(
            unified_name="_preview",
            rules=[MatchRule.from_dict(r) for r in rules],
            manual_includes=manual_includes,
            manual_excludes=manual_excludes,
            excluded_providers=excluded_providers or []
        )
        return self.resolve_models(temp_mapping, all_provider_models)
    
    def sync_mapping(
        self,
        unified_name: str,
        all_provider_models: dict[str, list[str]],
        provider_id_name_map: Optional[dict[str, str]] = None,
        provider_protocols: Optional[dict[str, Optional[str]]] = None
    ) -> tuple[bool, str, dict[str, list[str]]]:
        """
        同步单个映射
        
        Args:
            unified_name: 统一模型名称
            all_provider_models: 所有Provider的模型列表 {provider_id: [model_ids]}
            provider_id_name_map: provider_id -> provider_name 的映射（用于日志显示）
            provider_protocols: provider_id -> default_protocol 的映射（用于协议继承）
            
        Returns:
            (成功标志, 消息, 解析后的模型 {provider_id: [model_ids]})
        """
        self._ensure_loaded()
        
        if unified_name not in self._mappings:
            return False, f"映射 '{unified_name}' 不存在", {}
        
        mapping = self._mappings[unified_name]
        
        # 保存旧的 resolved_models 用于比较
        old_resolved = mapping.resolved_models.copy()
        
        resolved = self.resolve_models(mapping, all_provider_models)
        
        # 计算模型变化
        added, removed = self._compute_model_changes(old_resolved, resolved)
        
        # 输出日志
        self._log_sync_changes(unified_name, added, removed, provider_id_name_map)
        
        mapping.resolved_models = resolved
        mapping.last_sync = datetime.now(timezone.utc).isoformat()
        
        # 自动继承协议到 model_settings
        if provider_protocols:
            self._inherit_protocols(mapping, resolved, provider_protocols)
        
        self.save()
        return True, "同步成功", resolved
    
    def sync_all_mappings(
        self,
        all_provider_models: dict[str, list[str]],
        provider_id_name_map: Optional[dict[str, str]] = None,
        provider_protocols: Optional[dict[str, Optional[str]]] = None
    ) -> list[dict]:
        """
        同步所有映射
        
        Args:
            all_provider_models: 所有Provider的模型列表 {provider_id: [model_ids]}
            provider_id_name_map: provider_id -> provider_name 的映射（用于日志显示）
            provider_protocols: provider_id -> default_protocol 的映射（用于协议继承）
            
        Returns:
            同步结果列表 [{unified_name, success, matched_count, provider_ids, added, removed}]
        """
        self._ensure_loaded()
        
        results = []
        for unified_name, mapping in self._mappings.items():
            # 保存旧的 resolved_models 用于比较
            old_resolved = mapping.resolved_models.copy()
            
            resolved = self.resolve_models(mapping, all_provider_models)
            
            # 计算模型变化
            added, removed = self._compute_model_changes(old_resolved, resolved)
            
            # 输出日志
            self._log_sync_changes(unified_name, added, removed, provider_id_name_map)
            
            mapping.resolved_models = resolved
            mapping.last_sync = datetime.now(timezone.utc).isoformat()
            
            # 自动继承协议到 model_settings
            if provider_protocols:
                self._inherit_protocols(mapping, resolved, provider_protocols)
            
            total_models = sum(len(models) for models in resolved.values())
            results.append({
                "unified_name": unified_name,
                "success": True,
                "matched_count": total_models,
                "provider_ids": list(resolved.keys()),
                "added": added,
                "removed": removed
            })
        
        # 更新全局同步时间
        self._sync_config.last_full_sync = datetime.now(timezone.utc).isoformat()
        
        self.save()
        return results
    
    def _inherit_protocols(
        self,
        mapping: ModelMapping,
        resolved_models: dict[str, list[str]],
        provider_protocols: dict[str, Optional[str]]
    ) -> None:
        """
        自动继承协议到 model_settings
        
        对于 resolved_models 中的每个 provider:model 组合：
        - 如果 model_settings 中已有协议配置，保留（用户手动设置优先）
        - 如果没有，则从 provider_protocols 中继承
        - 如果 Provider 也没有 default_protocol，则不设置（表示该模型不可用）
        
        同时清理不在 resolved_models 中的旧 model_settings 条目
        
        Args:
            mapping: 映射配置
            resolved_models: 解析后的模型 {provider_id: [model_ids]}
            provider_protocols: provider_id -> default_protocol 的映射
        """
        # 构建当前有效的 provider:model 集合
        valid_keys: set[str] = set()
        for provider_id, model_ids in resolved_models.items():
            for model_id in model_ids:
                valid_keys.add(f"{provider_id}:{model_id}")
        
        # 清理不在 resolved_models 中的旧条目
        keys_to_remove = [key for key in mapping.model_settings if key not in valid_keys]
        for key in keys_to_remove:
            del mapping.model_settings[key]
        
        # 为新模型继承协议
        for provider_id, model_ids in resolved_models.items():
            provider_protocol = provider_protocols.get(provider_id)
            
            for model_id in model_ids:
                key = f"{provider_id}:{model_id}"
                
                # 如果已有配置且包含 protocol，跳过（用户手动设置优先）
                if key in mapping.model_settings and "protocol" in mapping.model_settings[key]:
                    continue
                
                # 从 Provider 继承协议
                if provider_protocol:
                    if key not in mapping.model_settings:
                        mapping.model_settings[key] = {}
                    mapping.model_settings[key]["protocol"] = provider_protocol
    
    def _compute_model_changes(
        self,
        old_resolved: dict[str, list[str]],
        new_resolved: dict[str, list[str]]
    ) -> tuple[list[str], list[str]]:
        """
        计算模型变化
        
        Args:
            old_resolved: 旧的解析结果 {provider_id: [model_ids]}
            new_resolved: 新的解析结果 {provider_id: [model_ids]}
            
        Returns:
            (新增模型列表, 删除模型列表) - 格式为 "provider_id:model_id"
        """
        # 将 {provider_id: [models]} 扁平化为 set of "provider_id:model_id"
        old_set: set[str] = set()
        for provider_id, models in old_resolved.items():
            for model in models:
                old_set.add(f"{provider_id}:{model}")
        
        new_set: set[str] = set()
        for provider_id, models in new_resolved.items():
            for model in models:
                new_set.add(f"{provider_id}:{model}")
        
        added = sorted(new_set - old_set)
        removed = sorted(old_set - new_set)
        
        return added, removed
    
    def _log_sync_changes(
        self,
        unified_name: str,
        added: list[str],
        removed: list[str],
        provider_id_name_map: Optional[dict[str, str]] = None
    ) -> None:
        """
        输出同步变化日志
        
        Args:
            unified_name: 映射名称
            added: 新增的模型列表 (格式: provider_id:model_id)
            removed: 删除的模型列表 (格式: provider_id:model_id)
            provider_id_name_map: provider_id -> provider_name 的映射
        """
        # 延迟导入避免循环依赖
        from .logger import log_manager, LogLevel
        
        # 将 provider_id:model_id 转换为 provider_name:model_id
        def format_model_ref(ref: str) -> str:
            if ":" in ref:
                provider_id, model_id = ref.split(":", 1)
                if provider_id_name_map and provider_id in provider_id_name_map:
                    provider_name = provider_id_name_map[provider_id]
                else:
                    provider_name = provider_id[:8]  # 使用 ID 前8位作为备用
                return f"{provider_name}:{model_id}"
            return ref
        
        if not added and not removed:
            message = f"[{unified_name}] 同步完成，无变化"
            print(f"[MODEL-MAPPING] {message}")
            log_manager.log(
                level=LogLevel.INFO,
                log_type="sync",
                method="SYNC",
                path="/model-mapping",
                message=message
            )
            return
        
        # 构建控制台输出（带颜色）
        console_parts = []
        # 构建日志消息（无颜色）
        log_parts = []
        
        if added:
            added_models = ", ".join(format_model_ref(m) for m in added[:5])  # 最多显示5个
            suffix = f"等{len(added)}个" if len(added) > 5 else ""
            console_parts.append(f"新增 {len(added)} 个模型（{added_models}{suffix}）")
            log_parts.append(f"新增 {len(added)} 个模型（{added_models}{suffix}）")
        
        if removed:
            removed_models = ", ".join(format_model_ref(m) for m in removed[:5])  # 最多显示5个
            suffix = f"等{len(removed)}个" if len(removed) > 5 else ""
            console_parts.append(f"移除 {len(removed)} 个模型（{removed_models}{suffix}）")
            log_parts.append(f"移除 {len(removed)} 个模型（{removed_models}{suffix}）")
        
        console_message = f"[{unified_name}] 同步完成：{', '.join(console_parts)}"
        log_message = f"[{unified_name}] 同步完成：{', '.join(log_parts)}"
        
        print(f"[MODEL-MAPPING] {console_message}")
        log_manager.log(
            level=LogLevel.INFO,
            log_type="sync",
            method="SYNC",
            path="/model-mapping",
            model=unified_name,
            message=log_message
        )
    
    # ==================== 用于 Provider 集成 ====================
    
    def get_resolved_models_for_unified(self, unified_name: str) -> list[str]:
        """
        获取统一模型名称对应的所有实际模型
        
        注意：此方法返回的是去重后的 model_id 列表，丢失了 provider_id 关联信息。
        如需保留 provider_id 关联，请直接使用 get_mapping() 获取映射后访问 resolved_models 属性。
        
        Args:
            unified_name: 统一模型名称
            
        Returns:
            实际模型列表（去重）
        """
        self._ensure_loaded()
        
        mapping = self._mappings.get(unified_name)
        if not mapping:
            return []
        
        return mapping.get_all_models()
    
    def get_all_unified_to_models_map(self) -> dict[str, list[str]]:
        """
        获取所有 统一名称 -> 实际模型列表 的映射（兼容旧格式）
        
        Returns:
            {unified_name: [model_ids]}
        """
        self._ensure_loaded()
        
        result = {}
        for unified_name, mapping in self._mappings.items():
            result[unified_name] = mapping.get_all_models()
        
        return result


# 全局实例
model_mapping_manager = ModelMappingManager()
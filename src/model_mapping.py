import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Any

from .sqlite_repos import ModelMappingRepo, ProviderRepo

class RuleType(str, Enum):
    KEYWORD = "keyword"
    REGEX = "regex"
    PREFIX = "prefix"
    EXACT = "exact"
    KEYWORD_EXCLUDE = "keyword_exclude"


@dataclass
class MatchRule:
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
    unified_name: str
    description: str = ""
    rules: list[MatchRule] = field(default_factory=list)
    manual_includes: list[str] = field(default_factory=list)
    excluded_providers: list[str] = field(default_factory=list)
    resolved_models: dict[str, list[str]] = field(default_factory=dict)
    model_settings: dict[str, dict] = field(default_factory=dict)
    last_sync: Optional[str] = None
    order_index: int = 0
    enabled: bool = True
    
    def to_dict(self) -> dict:
        return {
            "description": self.description,
            "rules": [r.to_dict() for r in self.rules],
            "manual_includes": self.manual_includes,
            "excluded_providers": self.excluded_providers,
            "resolved_models": self.resolved_models,
            "model_settings": self.model_settings,
            "last_sync": self.last_sync,
            "order_index": self.order_index,
            "enabled": self.enabled
        }
    
    @classmethod
    def from_dict(cls, unified_name: str, data: dict) -> "ModelMapping":
        # Convert ms timestamp to ISO string if needed
        last_sync = data.get("last_sync")
        if isinstance(last_sync, int):
            last_sync = datetime.fromtimestamp(last_sync / 1000.0, timezone.utc).isoformat()
            
        return cls(
            unified_name=unified_name,
            description=data.get("description", ""),
            rules=[MatchRule.from_dict(r) for r in data.get("rules", [])],
            manual_includes=data.get("manual_includes", []),
            excluded_providers=data.get("excluded_providers", []),
            resolved_models=data.get("resolved_models", {}),
            model_settings=data.get("model_settings", {}),
            last_sync=last_sync,
            order_index=data.get("order_index", 0),
            enabled=data.get("enabled", True)
        )
    
    def get_all_models(self) -> list[str]:
        models = set()
        for provider_models in self.resolved_models.values():
            models.update(provider_models)
        return sorted(models)
    
    def get_model_protocol(self, provider_id: str, model_id: str) -> Optional[str]:
        key = f"{provider_id}:{model_id}"
        settings = self.model_settings.get(key, {})
        return settings.get("protocol")


@dataclass
class SyncConfig:
    auto_sync_enabled: bool = False
    auto_sync_interval_hours: int = 6
    last_full_sync: Optional[str] = None
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> "SyncConfig":
        last_full_sync = data.get("last_full_sync") or data.get("last_full_sync_ms")
        if isinstance(last_full_sync, int):
            last_full_sync = datetime.fromtimestamp(last_full_sync / 1000.0, timezone.utc).isoformat()
            
        return cls(
            auto_sync_enabled=data.get("auto_sync_enabled", False),
            auto_sync_interval_hours=data.get("auto_sync_interval_hours", 6),
            last_full_sync=last_full_sync
        )


class RuleMatcher:
    @staticmethod
    def match(rule: MatchRule, model_id: str) -> bool:
        pattern = rule.pattern
        target = model_id
        
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
                return False
        elif rule.type == RuleType.KEYWORD_EXCLUDE:
            return pattern in target
        return False
    
    @staticmethod
    def match_any(rules: list[MatchRule], model_id: str) -> bool:
        for rule in rules:
            if rule.type == RuleType.KEYWORD_EXCLUDE:
                continue
            if RuleMatcher.match(rule, model_id):
                return True
        return False
    
    @staticmethod
    def should_exclude(rules: list[MatchRule], model_id: str) -> bool:
        for rule in rules:
            if rule.type != RuleType.KEYWORD_EXCLUDE:
                continue
            if RuleMatcher.match(rule, model_id):
                return True
        return False


class ModelMappingManager:
    """模型映射管理器 (SQLite)"""
    
    def __init__(self):
        self._repo = ModelMappingRepo()
        # Cache for performance (loaded on demand)
        # Note: In SQLite version, we might want to cache less aggressively or invalidate smartly.
        # But for compatibility and read speed, we can cache the full dict structure.
        self._cache: Optional[dict[str, ModelMapping]] = None
        self._sync_config_cache: Optional[SyncConfig] = None

    def load(self) -> None:
        """Load data from SQLite into cache"""
        raw_mappings = self._repo.list_mappings()
        self._cache = {}
        for uname, mdata in raw_mappings.items():
            self._cache[uname] = ModelMapping.from_dict(uname, mdata)
        
        raw_config = self._repo.get_sync_config()
        self._sync_config_cache = SyncConfig.from_dict(raw_config)

    def _ensure_loaded(self) -> None:
        if self._cache is None:
            self.load()

    def save(self) -> None:
        """No-op for compatibility, changes are immediate in SQLite"""
        pass

    def get_all_mappings(self) -> dict[str, ModelMapping]:
        self._ensure_loaded()
        return self._cache.copy()

    def get_mapping(self, unified_name: str) -> Optional[ModelMapping]:
        self._ensure_loaded()
        return self._cache.get(unified_name)

    def create_mapping(
        self,
        unified_name: str,
        description: str = "",
        rules: Optional[list[dict]] = None,
        manual_includes: Optional[list[str]] = None,
        excluded_providers: Optional[list[str]] = None,
        enabled: bool = True
    ) -> tuple[bool, str]:
        self._ensure_loaded()
        
        if unified_name in self._cache:
            return False, f"映射 '{unified_name}' 已存在"
        if not unified_name or not unified_name.strip():
            return False, "统一模型名称不能为空"
        
        try:
            self._repo.create_mapping(unified_name, description, enabled)
            # Create sub-tables
            self._repo.replace_rules(unified_name, rules or [])
            self._repo.replace_manual_includes(unified_name, manual_includes or [])
            self._repo.replace_excluded_providers(unified_name, excluded_providers or [])
            
            # Reload cache for this item (or full reload to be safe)
            # Full reload is safer but slower.
            # Optimization: construct object locally.
            self._cache[unified_name] = ModelMapping(
                unified_name=unified_name,
                description=description,
                rules=[MatchRule.from_dict(r) for r in (rules or [])],
                manual_includes=manual_includes or [],
                excluded_providers=excluded_providers or [],
                enabled=enabled
            )
            return True, "创建成功"
        except Exception as e:
            return False, str(e)

    def update_mapping(
        self,
        unified_name: str,
        description: Optional[str] = None,
        rules: Optional[list[dict]] = None,
        manual_includes: Optional[list[str]] = None,
        excluded_providers: Optional[list[str]] = None,
        enabled: Optional[bool] = None
    ) -> tuple[bool, str]:
        self._ensure_loaded()
        
        if unified_name not in self._cache:
            return False, f"映射 '{unified_name}' 不存在"
        
        mapping = self._cache[unified_name]
        
        try:
            if description is not None:
                self._repo.update_mapping_meta(unified_name, description=description)
                mapping.description = description
            
            if enabled is not None:
                self._repo.update_mapping_meta(unified_name, enabled=enabled)
                mapping.enabled = enabled
            
            if rules is not None:
                self._repo.replace_rules(unified_name, rules)
                mapping.rules = [MatchRule.from_dict(r) for r in rules]
                
            if manual_includes is not None:
                self._repo.replace_manual_includes(unified_name, manual_includes)
                mapping.manual_includes = manual_includes
                
            if excluded_providers is not None:
                self._repo.replace_excluded_providers(unified_name, excluded_providers)
                mapping.excluded_providers = excluded_providers
                
            return True, "更新成功"
        except Exception as e:
            return False, str(e)

    def delete_mapping(self, unified_name: str) -> tuple[bool, str]:
        self._ensure_loaded()
        
        if unified_name not in self._cache:
            return False, f"映射 '{unified_name}' 不存在"
        
        try:
            self._repo.delete_mapping(unified_name)
            del self._cache[unified_name]
            return True, "删除成功"
        except Exception as e:
            return False, str(e)

    def rename_mapping(self, old_name: str, new_name: str) -> tuple[bool, str]:
        self._ensure_loaded()
        
        if old_name not in self._cache:
            return False, f"映射 '{old_name}' 不存在"
        if not new_name or not new_name.strip():
            return False, "新名称不能为空"
        new_name = new_name.strip()
        if new_name == old_name:
            return True, "名称未变更"
        if new_name in self._cache:
            return False, f"映射 '{new_name}' 已存在"
        
        try:
            self._repo.rename_mapping(old_name, new_name)
            # Update cache
            mapping = self._cache.pop(old_name)
            mapping.unified_name = new_name
            self._cache[new_name] = mapping
            return True, f"映射已重命名: '{old_name}' -> '{new_name}'"
        except Exception as e:
            return False, str(e)

    def update_model_settings(
        self,
        unified_name: str,
        model_settings: dict[str, dict]
    ) -> tuple[bool, str]:
        self._ensure_loaded()
        if unified_name not in self._cache:
            return False, f"映射 '{unified_name}' 不存在"
        
        try:
            self._repo.update_model_settings(unified_name, model_settings)
            self._cache[unified_name].model_settings = model_settings
            return True, "更新成功"
        except Exception as e:
            return False, str(e)

    def set_model_protocol(
        self,
        unified_name: str,
        provider_id: str,
        model_id: str,
        protocol: Optional[str]
    ) -> tuple[bool, str]:
        self._ensure_loaded()
        if unified_name not in self._cache:
            return False, f"映射 '{unified_name}' 不存在"
        
        mapping = self._cache[unified_name]
        old_protocol = mapping.get_model_protocol(provider_id, model_id)
        
        if old_protocol != protocol:
            from .model_health import model_health_manager
            model_health_manager.clear_result(provider_id, model_id)
        
        try:
            self._repo.set_model_protocol(unified_name, provider_id, model_id, protocol)
            
            # Update cache
            key = f"{provider_id}:{model_id}"
            if protocol is None:
                if key in mapping.model_settings:
                    del mapping.model_settings[key]
            else:
                if key not in mapping.model_settings:
                    mapping.model_settings[key] = {}
                mapping.model_settings[key]["protocol"] = protocol
                
            return True, "更新成功"
        except Exception as e:
            return False, str(e)

    # ==================== 同步配置 ====================

    def get_sync_config(self) -> SyncConfig:
        self._ensure_loaded()
        return self._sync_config_cache

    def update_sync_config(
        self,
        auto_sync_enabled: Optional[bool] = None,
        auto_sync_interval_hours: Optional[int] = None
    ) -> tuple[bool, str]:
        self._ensure_loaded()
        
        if auto_sync_interval_hours is not None and auto_sync_interval_hours < 1:
            return False, "同步间隔不能小于1小时"
        
        try:
            self._repo.update_sync_config(auto_sync_enabled, auto_sync_interval_hours)
            if auto_sync_enabled is not None:
                self._sync_config_cache.auto_sync_enabled = auto_sync_enabled
            if auto_sync_interval_hours is not None:
                self._sync_config_cache.auto_sync_interval_hours = auto_sync_interval_hours
            return True, "更新成功"
        except Exception as e:
            return False, str(e)

    # ==================== 规则匹配与同步 ====================

    def resolve_models(
        self,
        mapping: ModelMapping,
        all_provider_models: dict[str, list[str]]
    ) -> dict[str, list[str]]:
        """Same logic as original"""
        def parse_model_ref(ref: str) -> tuple[Optional[str], str]:
            if ":" in ref:
                parts = ref.split(":", 1)
                return parts[0], parts[1]
            return None, ref

        excluded_providers = set(mapping.excluded_providers or [])
        matched: set[tuple[str, str]] = set()

        for provider_id, models in all_provider_models.items():
            if provider_id in excluded_providers:
                continue
            for model_id in models:
                if RuleMatcher.match_any(mapping.rules, model_id):
                    matched.add((provider_id, model_id))

        for ref in mapping.manual_includes:
            provider_id, model_id = parse_model_ref(ref)
            if provider_id:
                if provider_id in all_provider_models and model_id in all_provider_models[provider_id]:
                    matched.add((provider_id, model_id))
            else:
                for prov_id, models in all_provider_models.items():
                    if prov_id in excluded_providers:
                        continue
                    if model_id in models:
                        matched.add((prov_id, model_id))

        to_remove = []
        for provider_id, model_id in matched:
            if RuleMatcher.should_exclude(mapping.rules, model_id):
                to_remove.append((provider_id, model_id))
        for item in to_remove:
            matched.discard(item)

        result: dict[str, list[str]] = {}
        for provider_id, model_id in matched:
            if provider_id not in result:
                result[provider_id] = []
            result[provider_id].append(model_id)

        for provider_id in result:
            result[provider_id].sort()

        return result

    def preview_resolve(
        self,
        rules: list[dict],
        manual_includes: list[str],
        all_provider_models: dict[str, list[str]],
        excluded_providers: Optional[list[str]] = None
    ) -> dict[str, list[str]]:
        temp_mapping = ModelMapping(
            unified_name="_preview",
            rules=[MatchRule.from_dict(r) for r in rules],
            manual_includes=manual_includes,
            excluded_providers=excluded_providers or []
        )
        return self.resolve_models(temp_mapping, all_provider_models)

    def _compute_model_changes(self, old: dict, new: dict) -> tuple[list[str], list[str]]:
        old_set = set()
        for pid, models in old.items():
            for mid in models:
                old_set.add(f"{pid}:{mid}")
        
        new_set = set()
        for pid, models in new.items():
            for mid in models:
                new_set.add(f"{pid}:{mid}")
                
        added = sorted(new_set - old_set)
        removed = sorted(old_set - new_set)
        return added, removed

    def _log_sync_changes(self, unified_name: str, added: list, removed: list, id_map: Optional[dict]) -> None:
        from .logger import log_manager, LogLevel
        
        def format_ref(ref):
            if ":" in ref:
                pid, mid = ref.split(":", 1)
                pname = id_map.get(pid, pid[:8]) if id_map else pid[:8]
                return f"{pname}:{mid}"
            return ref

        if not added and not removed:
            return

        parts = []
        if added:
            prev = ", ".join(format_ref(m) for m in added[:5])
            suffix = f"等{len(added)}个" if len(added) > 5 else ""
            parts.append(f"新增 {len(added)} 个模型（{prev}{suffix}）")
        if removed:
            prev = ", ".join(format_ref(m) for m in removed[:5])
            suffix = f"等{len(removed)}个" if len(removed) > 5 else ""
            parts.append(f"移除 {len(removed)} 个模型（{prev}{suffix}）")
            
        msg = ", ".join(parts)
        print(f"[MODEL-MAPPING] [{unified_name}] {msg}")
        log_manager.log(LogLevel.INFO, "sync", "SYNC", "/model-mapping", model=unified_name, message=msg)

    def _inherit_protocols(
        self,
        mapping: ModelMapping,
        resolved_models: dict[str, list[str]],
        provider_protocols: dict[str, Optional[str]]
    ) -> None:
        # Same logic
        valid_keys = set()
        for pid, models in resolved_models.items():
            for mid in models:
                valid_keys.add(f"{pid}:{mid}")
        
        # We need to reflect changes in repo.
        # But update_model_settings will wipe and replace. 
        # So we can update mapping.model_settings in memory then save.
        
        keys_to_remove = [k for k in mapping.model_settings if k not in valid_keys]
        for k in keys_to_remove:
            del mapping.model_settings[k]
            
        for pid, models in resolved_models.items():
            p_proto = provider_protocols.get(pid)
            for mid in models:
                key = f"{pid}:{mid}"
                if key in mapping.model_settings and "protocol" in mapping.model_settings[key]:
                    continue
                if p_proto:
                    if key not in mapping.model_settings:
                        mapping.model_settings[key] = {}
                    mapping.model_settings[key]["protocol"] = p_proto

    def sync_mapping(
        self,
        unified_name: str,
        all_provider_models: dict[str, list[str]],
        provider_id_name_map: Optional[dict[str, str]] = None,
        provider_protocols: Optional[dict[str, Optional[str]]] = None
    ) -> tuple[bool, str, dict[str, list[str]]]:
        self._ensure_loaded()
        if unified_name not in self._cache:
            return False, f"映射 '{unified_name}' 不存在", {}
        
        mapping = self._cache[unified_name]
        old_resolved = mapping.resolved_models.copy()
        
        resolved = self.resolve_models(mapping, all_provider_models)
        added, removed = self._compute_model_changes(old_resolved, resolved)
        
        self._log_sync_changes(unified_name, added, removed, provider_id_name_map)
        
        mapping.resolved_models = resolved
        mapping.last_sync = datetime.now(timezone.utc).isoformat()
        
        if provider_protocols:
            self._inherit_protocols(mapping, resolved, provider_protocols)
            
        # Save to DB
        try:
            self._repo.replace_resolved_models(unified_name, resolved)
            self._repo.update_model_settings(unified_name, mapping.model_settings)
            
            # Convert ISO to ms int
            last_sync_ms = int(datetime.fromisoformat(mapping.last_sync.replace("Z", "+00:00")).timestamp() * 1000)
            self._repo.update_mapping_meta(unified_name, last_sync_ms=last_sync_ms)
            
            return True, "同步成功", resolved
        except Exception as e:
            return False, str(e), {}

    def sync_all_mappings(
        self,
        all_provider_models: dict[str, list[str]],
        provider_id_name_map: Optional[dict[str, str]] = None,
        provider_protocols: Optional[dict[str, Optional[str]]] = None
    ) -> list[dict]:
        self._ensure_loaded()
        
        results = []
        for uname in self._cache:
            success, msg, resolved = self.sync_mapping(
                uname, all_provider_models, provider_id_name_map, provider_protocols
            )
            
            if success:
                mapping = self._cache[uname]
                # Re-compute changes for result (a bit redundant but cleaner)
                # Actually sync_mapping computed them but didn't return.
                # Let's trust sync_mapping did the job.
                # We need added/removed for result.
                # Ideally sync_mapping should return them or we duplicate logic.
                # Let's duplicate logic here for reporting since sync_mapping updates state.
                # Wait, sync_mapping updated state already. 
                # We can't diff against old state easily unless we kept it.
                # Refactor: move sync logic loop here?
                pass

        # To keep it simple and correct, I will implement the loop logic here similar to original
        results = []
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        
        for uname, mapping in self._cache.items():
            old_resolved = mapping.resolved_models.copy()
            resolved = self.resolve_models(mapping, all_provider_models)
            added, removed = self._compute_model_changes(old_resolved, resolved)
            
            self._log_sync_changes(uname, added, removed, provider_id_name_map)
            
            mapping.resolved_models = resolved
            mapping.last_sync = datetime.now(timezone.utc).isoformat()
            
            if provider_protocols:
                self._inherit_protocols(mapping, resolved, provider_protocols)
            
            self._repo.replace_resolved_models(uname, resolved)
            self._repo.update_model_settings(uname, mapping.model_settings)
            
            # Update meta per mapping? Yes
            self._repo.update_mapping_meta(uname, last_sync_ms=now_ms)
            
            total = sum(len(models) for models in resolved.values())
            results.append({
                "unified_name": uname,
                "success": True,
                "matched_count": total,
                "provider_ids": list(resolved.keys()),
                "added": added,
                "removed": removed
            })
            
        self._repo.update_sync_config(None, None, last_sync=now_ms)
        if self._sync_config_cache:
            self._sync_config_cache.last_full_sync = datetime.fromtimestamp(now_ms / 1000.0, timezone.utc).isoformat()
            
        return results

    def get_resolved_models_for_unified(self, unified_name: str) -> list[str]:
        self._ensure_loaded()
        mapping = self._cache.get(unified_name)
        if not mapping:
            return []
        return mapping.get_all_models()

    def get_all_unified_to_models_map(self) -> dict[str, list[str]]:
        self._ensure_loaded()
        result = {}
        for uname, mapping in self._cache.items():
            result[uname] = mapping.get_all_models()
        return result

    def reorder_mappings(self, ordered_names: list[str]) -> tuple[bool, str]:
        """Reorder mappings based on the provided list of unified names."""
        self._ensure_loaded()
        try:
            updated = self._repo.update_orders(ordered_names)
            # Update cache order_index
            for idx, name in enumerate(ordered_names):
                if name in self._cache:
                    self._cache[name].order_index = idx
            return True, f"已更新 {updated} 个映射的顺序"
        except Exception as e:
            return False, str(e)


model_mapping_manager = ModelMappingManager()
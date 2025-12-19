import asyncio
import time
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional, AsyncIterator, Any

from .constants import (
    DEFAULT_TIMEZONE_OFFSET,
    LOG_MAX_MEMORY_ENTRIES,
    LOG_RECENT_LIMIT_DEFAULT,
    LOG_SUBSCRIBE_QUEUE_SIZE,
)
from .sqlite_repos import LogRepo

_TZ = timezone(timedelta(hours=DEFAULT_TIMEZONE_OFFSET))


def get_current_time() -> datetime:
    return datetime.now(_TZ)


def get_today_str() -> str:
    return get_current_time().strftime("%Y-%m-%d")


def timestamp_to_datetime(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, _TZ)


class LogLevel(Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class RequestLog:
    id: str
    timestamp: float
    level: str
    type: str
    method: str
    path: str
    model: Optional[str] = None
    provider: Optional[str] = None
    actual_model: Optional[str] = None
    status_code: Optional[int] = None
    duration_ms: Optional[float] = None
    message: Optional[str] = None
    error: Optional[str] = None
    client_ip: Optional[str] = None
    api_key_id: Optional[str] = None
    api_key_name: Optional[str] = None
    protocol: Optional[str] = None
    request_tokens: Optional[int] = None
    response_tokens: Optional[int] = None
    total_tokens: Optional[int] = None

    provider_id: Optional[str] = None  # new: stable id for storage/join

    def to_dict(self) -> dict:
        data = asdict(self)
        data["timestamp_str"] = timestamp_to_datetime(self.timestamp).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        if self.provider and self.actual_model:
            data["actual_model_full"] = f"{self.provider}:{self.actual_model}"
        return data


class LogManager:
    def __init__(self, max_memory_logs: int = LOG_MAX_MEMORY_ENTRIES):
        self.max_memory_logs = max_memory_logs
        self._logs: deque[RequestLog] = deque(maxlen=max_memory_logs)
        self._subscribers: list[asyncio.Queue] = []
        self._log_counter = 0
        self._repo = LogRepo()

    def _generate_log_id(self) -> str:
        self._log_counter += 1
        return f"log_{int(time.time() * 1000)}_{self._log_counter}"

    def log(
        self,
        level: LogLevel,
        log_type: str,
        method: str,
        path: str,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        provider_id: Optional[str] = None,
        actual_model: Optional[str] = None,
        status_code: Optional[int] = None,
        duration_ms: Optional[float] = None,
        message: Optional[str] = None,
        error: Optional[str] = None,
        client_ip: Optional[str] = None,
        api_key_id: Optional[str] = None,
        api_key_name: Optional[str] = None,
        protocol: Optional[str] = None,
        request_tokens: Optional[int] = None,
        response_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
    ) -> RequestLog:
        ts = time.time()
        log_entry = RequestLog(
            id=self._generate_log_id(),
            timestamp=ts,
            level=level.value,
            type=log_type,
            method=method,
            path=path,
            model=model,
            provider=provider,
            provider_id=provider_id,
            actual_model=actual_model,
            status_code=status_code,
            duration_ms=duration_ms,
            message=message,
            error=error,
            client_ip=client_ip,
            api_key_id=api_key_id,
            api_key_name=api_key_name,
            protocol=protocol,
            request_tokens=request_tokens,
            response_tokens=response_tokens,
            total_tokens=total_tokens,
        )

        # memory
        self._logs.append(log_entry)

        # persist to sqlite (logs.db)
        self._repo.insert(
            {
                "id": log_entry.id,
                "timestamp_ms": int(ts * 1000),
                "level": log_entry.level,
                "type": log_entry.type,
                "method": log_entry.method,
                "path": log_entry.path,
                "protocol": log_entry.protocol,
                "status_code": log_entry.status_code,
                "duration_ms": log_entry.duration_ms,
                "message": log_entry.message,
                "error": log_entry.error,
                "client_ip": log_entry.client_ip,
                "api_key_id": log_entry.api_key_id,
                "provider_id": log_entry.provider_id,
                "unified_model": log_entry.model,
                "actual_model": log_entry.actual_model,
                "prompt_tokens": log_entry.request_tokens,
                "completion_tokens": log_entry.response_tokens,
                "total_tokens": log_entry.total_tokens,
            }
        )

        self._notify_subscribers(log_entry)
        return log_entry

    def _notify_subscribers(self, log_entry: RequestLog) -> None:
        dead = []
        for q in self._subscribers:
            try:
                q.put_nowait(log_entry)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            if q in self._subscribers:
                self._subscribers.remove(q)

    async def subscribe(self) -> AsyncIterator[RequestLog]:
        q: asyncio.Queue = asyncio.Queue(maxsize=LOG_SUBSCRIBE_QUEUE_SIZE)
        self._subscribers.append(q)
        try:
            while True:
                yield await q.get()
        finally:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def get_recent_logs(
        self,
        limit: int = LOG_RECENT_LIMIT_DEFAULT,
        level: Optional[str] = None,
        log_type: Optional[str] = None,
        keyword: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> list[dict]:
        # Use DB for SSOT (and persistence across restarts)
        logs = self._repo.get_recent(
            limit=limit,
            level=level,
            log_type=log_type,
            keyword=keyword,
            provider=provider
        )
        
        # Application-side JOIN: Map IDs to Names
        from .admin import admin_manager
        from .api_keys import api_key_manager
        
        # Get ID->Name maps (cached or fresh)
        # For performance, admin_manager has get_provider_id_name_map which queries DB.
        # api_key_manager doesn't expose a map getter, but we can list keys.
        # Let's optimize: fetch once per request.
        provider_map = admin_manager.get_provider_id_name_map()
        
        # API Keys map: {key_id: name}
        # ApiKeyRepo has list(), but not a direct map getter. We can build it.
        # Or we can accept that api_key_name might be missing if we don't query it.
        # The repo insert() stored api_key_id.
        # Let's fetch all keys to map.
        all_keys = api_key_manager.list_keys()
        api_key_map = {k["key_id"]: k["name"] for k in all_keys}
        
        # Enrich/Format logs
        for l in logs:
            ts = l["timestamp"]
            l["timestamp_str"] = timestamp_to_datetime(ts).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            
            # Map IDs to Names
            pid = l.get("provider_id")
            if pid:
                l["provider"] = provider_map.get(pid, pid) # Fallback to ID if name not found
            
            ak_id = l.get("api_key_id")
            if ak_id:
                l["api_key_name"] = api_key_map.get(ak_id, "Unknown")
            
            # Reconstruct actual_model_full using names
            if l.get("provider") and l.get("actual_model"):
                l["actual_model_full"] = f"{l['provider']}:{l['actual_model']}"
        
        return logs

    def get_stats(self, date: Optional[str] = None, tag: Optional[str] = None) -> dict:
        stats = self._repo.get_stats(date_str=date, tag=tag)
        
        # Map provider IDs to Names for provider_model_stats
        # Frontend expects provider names as keys in provider_model_stats
        if "provider_model_stats" in stats or "model_provider_stats" in stats:
            from .admin import admin_manager
            provider_map = admin_manager.get_provider_id_name_map()
            
            if "provider_model_stats" in stats:
                new_stats = {}
                for pid, model_stats in stats["provider_model_stats"].items():
                    pname = provider_map.get(pid, pid)
                    new_stats[pname] = model_stats
                stats["provider_model_stats"] = new_stats
                
            if "model_provider_stats" in stats:
                new_model_stats = {}
                for model, providers in stats["model_provider_stats"].items():
                    new_providers = {}
                    for pid, p_stats in providers.items():
                        pname = provider_map.get(pid, pid)
                        new_providers[pname] = p_stats
                    new_model_stats[model] = new_providers
                stats["model_provider_stats"] = new_model_stats
            
        return stats

    def get_daily_stats(self, days: int = 7, tag: Optional[str] = None) -> list[dict]:
        return self._repo.get_daily_stats(days=days, tag=tag)


log_manager = LogManager()
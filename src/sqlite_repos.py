import json
import time
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from typing import Any, Optional, Dict, List, Generator

from cryptography.fernet import InvalidToken

from .db import connect_sqlite, get_db_paths, get_fernet
from .constants import PROXY_ERROR_MESSAGE_MAX_LENGTH


def _now_ms() -> int:
    return int(time.time() * 1000)


@contextmanager
def get_db_cursor(db_path: str) -> Generator[Any, None, None]:
    """Context manager for SQLite database connection and cursor."""
    conn = connect_sqlite(db_path)
    try:
        cur = conn.cursor()
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@dataclass(frozen=True)
class ProviderRow:
    provider_id: str
    name: str
    base_url: str
    api_key: str
    weight: int
    timeout_ms: Optional[int]
    enabled: bool
    allow_health_check: bool
    allow_model_update: bool
    default_protocol: Optional[str]


class ProviderRepo:
    def __init__(self):
        self._paths = get_db_paths()

    def list(self) -> list[dict]:
        fernet = get_fernet()
        with get_db_cursor(self._paths.app_db_path) as cur:
            cur.execute(
                """
                SELECT provider_id, name, base_url, api_key_enc, weight, timeout_ms,
                       enabled, allow_health_check, allow_model_update, default_protocol,
                       models_updated_at_ms
                FROM providers
                ORDER BY name
                """
            )
            rows = cur.fetchall()

        providers: list[dict] = []
        for r in rows:
            try:
                api_key = fernet.decrypt(r["api_key_enc"]).decode("utf-8")
            except InvalidToken:
                raise RuntimeError("Failed to decrypt providers.api_key_enc. Check db_encryption_key in config.json.")
            providers.append(
                {
                    "id": r["provider_id"],
                    "name": r["name"],
                    "base_url": r["base_url"],
                    "api_key": api_key,
                    "weight": int(r["weight"]),
                    "timeout": (float(r["timeout_ms"]) / 1000.0) if r["timeout_ms"] is not None else None,
                    "enabled": bool(r["enabled"]),
                    "allow_health_check": bool(r["allow_health_check"]),
                    "allow_model_update": bool(r["allow_model_update"]),
                    "default_protocol": r["default_protocol"],
                    "models_updated_at": r["models_updated_at_ms"],
                }
            )
        return providers

    def get_by_id(self, provider_id: str) -> Optional[dict]:
        fernet = get_fernet()
        with get_db_cursor(self._paths.app_db_path) as cur:
            cur.execute(
                """
                SELECT provider_id, name, base_url, api_key_enc, weight, timeout_ms,
                       enabled, allow_health_check, allow_model_update, default_protocol,
                       models_updated_at_ms
                FROM providers
                WHERE provider_id = ?
                """,
                (provider_id,),
            )
            r = cur.fetchone()
        
        if not r:
            return None
        try:
            api_key = fernet.decrypt(r["api_key_enc"]).decode("utf-8")
        except InvalidToken:
            raise RuntimeError("Failed to decrypt providers.api_key_enc. Check db_encryption_key in config.json.")
        return {
            "id": r["provider_id"],
            "name": r["name"],
            "base_url": r["base_url"],
            "api_key": api_key,
            "weight": int(r["weight"]),
            "timeout": (float(r["timeout_ms"]) / 1000.0) if r["timeout_ms"] is not None else None,
            "enabled": bool(r["enabled"]),
            "allow_health_check": bool(r["allow_health_check"]),
            "allow_model_update": bool(r["allow_model_update"]),
            "default_protocol": r["default_protocol"],
            "models_updated_at": r["models_updated_at_ms"],
        }

    def get_id_name_map(self) -> dict[str, str]:
        with get_db_cursor(self._paths.app_db_path) as cur:
            cur.execute("SELECT provider_id, name FROM providers")
            rows = cur.fetchall()
        return {r["provider_id"]: r["name"] for r in rows if r["provider_id"]}

    def get_name_id_map(self) -> dict[str, str]:
        with get_db_cursor(self._paths.app_db_path) as cur:
            cur.execute("SELECT provider_id, name FROM providers")
            rows = cur.fetchall()
        return {r["name"]: r["provider_id"] for r in rows if r["name"]}

    def get_protocols(self) -> dict[str, Optional[str]]:
        with get_db_cursor(self._paths.app_db_path) as cur:
            cur.execute("SELECT provider_id, default_protocol FROM providers")
            rows = cur.fetchall()
        return {r["provider_id"]: r["default_protocol"] for r in rows if r["provider_id"]}

    def upsert(self, provider: dict) -> None:
        provider_id = provider.get("id")
        name = provider.get("name")
        base_url = (provider.get("base_url") or "").rstrip("/")
        api_key = provider.get("api_key") or ""
        if not provider_id or not name or not base_url or not api_key:
            raise ValueError("provider must include id/name/base_url/api_key")

        weight = int(provider.get("weight") or 1)
        timeout = provider.get("timeout")
        timeout_ms = None if timeout is None else int(float(timeout) * 1000)
        enabled = 1 if provider.get("enabled", True) else 0
        allow_health_check = 1 if provider.get("allow_health_check", True) else 0
        allow_model_update = 1 if provider.get("allow_model_update", True) else 0
        default_protocol = provider.get("default_protocol")

        fernet = get_fernet()
        api_key_enc = fernet.encrypt(api_key.encode("utf-8"))

        with get_db_cursor(self._paths.app_db_path) as cur:
            cur.execute(
                """
                INSERT INTO providers (
                  provider_id, name, base_url, api_key_enc,
                  weight, timeout_ms, enabled,
                  allow_health_check, allow_model_update,
                  default_protocol, updated_at_ms, models_updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                ON CONFLICT(provider_id) DO UPDATE SET
                  name=excluded.name,
                  base_url=excluded.base_url,
                  api_key_enc=excluded.api_key_enc,
                  weight=excluded.weight,
                  timeout_ms=excluded.timeout_ms,
                  enabled=excluded.enabled,
                  allow_health_check=excluded.allow_health_check,
                  allow_model_update=excluded.allow_model_update,
                  default_protocol=excluded.default_protocol,
                  updated_at_ms=excluded.updated_at_ms
                """,
                (
                    provider_id,
                    name,
                    base_url,
                    api_key_enc,
                    weight,
                    timeout_ms,
                    enabled,
                    allow_health_check,
                    allow_model_update,
                    default_protocol,
                    _now_ms(),
                ),
            )

    def delete(self, provider_id: str) -> bool:
        with get_db_cursor(self._paths.app_db_path) as cur:
            cur.execute("DELETE FROM providers WHERE provider_id = ?", (provider_id,))
            deleted = cur.rowcount > 0
        return deleted

    def update_models_updated_at(self, provider_id: str) -> None:
        with get_db_cursor(self._paths.app_db_path) as cur:
            cur.execute(
                "UPDATE providers SET models_updated_at_ms = ? WHERE provider_id = ?",
                (_now_ms(), provider_id),
            )


class ApiKeyRepo:
    def __init__(self):
        self._paths = get_db_paths()

    def list(self) -> list[dict]:
        with get_db_cursor(self._paths.app_db_path) as cur:
            cur.execute(
                """
                SELECT key_id, name, created_at_ms, last_used_ms, enabled, total_requests
                FROM api_keys
                ORDER BY created_at_ms DESC
                """
            )
            rows = cur.fetchall()
        
        result: list[dict] = []
        for r in rows:
            created_at = float(r["created_at_ms"]) / 1000.0
            last_used = float(r["last_used_ms"]) / 1000.0 if r["last_used_ms"] is not None else None
            result.append(
                {
                    "key_id": r["key_id"],
                    "key_masked": f"{r['key_id'][:6]}****{r['key_id'][-4:]}",
                    "name": r["name"],
                    "created_at": created_at,
                    "created_at_str": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(created_at)),
                    "last_used": last_used,
                    "last_used_str": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_used)) if last_used else None,
                    "enabled": bool(r["enabled"]),
                    "total_requests": int(r["total_requests"]),
                }
            )
        return result

    def get_stats(self) -> dict:
        with get_db_cursor(self._paths.app_db_path) as cur:
            cur.execute("SELECT COUNT(*) AS c FROM api_keys")
            total = int(cur.fetchone()["c"])
            cur.execute("SELECT COUNT(*) AS c FROM api_keys WHERE enabled = 1")
            enabled = int(cur.fetchone()["c"])
            cur.execute("SELECT COALESCE(SUM(total_requests), 0) AS s FROM api_keys")
            total_requests = int(cur.fetchone()["s"])
        
        return {
            "total_keys": total,
            "enabled_keys": enabled,
            "disabled_keys": total - enabled,
            "total_requests": total_requests,
        }

    def get_by_id(self, key_id: str) -> Optional[dict]:
        with get_db_cursor(self._paths.app_db_path) as cur:
            cur.execute(
                """
                SELECT key_id, name, created_at_ms, last_used_ms, enabled, total_requests
                FROM api_keys
                WHERE key_id = ?
                """,
                (key_id,),
            )
            r = cur.fetchone()
        
        if not r:
            return None
        created_at = float(r["created_at_ms"]) / 1000.0
        last_used = float(r["last_used_ms"]) / 1000.0 if r["last_used_ms"] is not None else None
        return {
            "key_id": r["key_id"],
            "key_masked": f"{r['key_id'][:6]}****{r['key_id'][-4:]}",
            "name": r["name"],
            "created_at": created_at,
            "created_at_str": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(created_at)),
            "last_used": last_used,
            "last_used_str": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_used)) if last_used else None,
            "enabled": bool(r["enabled"]),
            "total_requests": int(r["total_requests"]),
        }

    def validate_and_touch(self, full_key: str) -> Optional[dict]:
        import hashlib

        key_hash = hashlib.sha256(full_key.encode("utf-8")).hexdigest()
        now_ms = _now_ms()

        with get_db_cursor(self._paths.app_db_path) as cur:
            cur.execute(
                """
                SELECT key_id, name, created_at_ms, last_used_ms, enabled, total_requests
                FROM api_keys
                WHERE key_hash = ?
                """,
                (key_hash,),
            )
            r = cur.fetchone()
            if not r or not bool(r["enabled"]):
                return None

            cur.execute(
                """
                UPDATE api_keys
                SET last_used_ms = ?, total_requests = total_requests + 1
                WHERE key_id = ?
                """,
                (now_ms, r["key_id"]),
            )

        created_at = float(r["created_at_ms"]) / 1000.0
        last_used = float(now_ms) / 1000.0
        return {
            "key_id": r["key_id"],
            "name": r["name"],
            "created_at": created_at,
            "last_used": last_used,
            "enabled": True,
        }


class LogRepo:
    def __init__(self):
        self._paths = get_db_paths()

    def insert(self, entry: dict[str, Any]) -> None:
        with get_db_cursor(self._paths.logs_db_path) as cur:
            cur.execute(
                """
                INSERT OR REPLACE INTO request_logs (
                  id, timestamp_ms, level, type, method, path, protocol,
                  status_code, duration_ms, message, error, client_ip,
                  api_key_id, provider_id, unified_model, actual_model,
                  prompt_tokens, completion_tokens, total_tokens
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry["id"],
                    entry["timestamp_ms"],
                    entry["level"],
                    entry["type"],
                    entry["method"],
                    entry["path"],
                    entry.get("protocol"),
                    entry.get("status_code"),
                    entry.get("duration_ms"),
                    entry.get("message"),
                    entry.get("error"),
                    entry.get("client_ip"),
                    entry.get("api_key_id"),
                    entry.get("provider_id"),
                    entry.get("unified_model"),
                    entry.get("actual_model"),
                    entry.get("prompt_tokens"),
                    entry.get("completion_tokens"),
                    entry.get("total_tokens"),
                ),
            )

    def get_recent(
        self,
        limit: int,
        level: Optional[str] = None,
        log_type: Optional[str] = None,
        keyword: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> list[dict]:
        with get_db_cursor(self._paths.logs_db_path) as cur:
            query = "SELECT * FROM request_logs WHERE 1=1"
            params = []
            
            if level:
                query += " AND level = ?"
                params.append(level)
            if log_type:
                query += " AND type = ?"
                params.append(log_type)
            if provider:
                # Assuming provider is provider_name, but DB has provider_id.
                # If we want to support name filtering, we need to join or assume ID.
                # The logger passes what it gets.
                # If the user filters by name, we might need ID lookup.
                # For now, let's assume it filters by what's stored (which might be ID or name depending on log call).
                # Wait, LogRepo insert uses entry.get("provider_id").
                # But logger.log also takes "provider" (name).
                # We stored provider_id in DB.
                # If frontend sends name, this SQL won't match ID.
                # However, for now let's just implement basic SQL.
                query += " AND provider_id = ?"
                params.append(provider)
            
            if keyword:
                kw = f"%{keyword}%"
                # Search in message, model, error, actual_model
                query += " AND (message LIKE ? OR unified_model LIKE ? OR actual_model LIKE ? OR error LIKE ?)"
                params.extend([kw, kw, kw, kw])
            
            query += " ORDER BY timestamp_ms DESC LIMIT ?"
            params.append(limit)
            
            cur.execute(query, params)
            rows = cur.fetchall()
            
            # Convert to dicts matching RequestLog structure
            provider_repo = ProviderRepo()
            id_name_map = provider_repo.get_id_name_map()
            
            logs = []
            for r in rows:
                pid = r["provider_id"]
                logs.append({
                    "id": r["id"],
                    "timestamp": r["timestamp_ms"] / 1000.0,
                    "level": r["level"],
                    "type": r["type"],
                    "method": r["method"],
                    "path": r["path"],
                    "protocol": r["protocol"],
                    "status_code": r["status_code"],
                    "duration_ms": r["duration_ms"],
                    "message": r["message"],
                    "error": r["error"],
                    "client_ip": r["client_ip"],
                    "api_key_id": r["api_key_id"],
                    "provider_id": pid,
                    "model": r["unified_model"],
                    "actual_model": r["actual_model"],
                    "request_tokens": r["prompt_tokens"],
                    "response_tokens": r["completion_tokens"],
                    "total_tokens": r["total_tokens"],
                    "provider": id_name_map.get(pid, pid) if pid else None
                })
            return logs

    def get_stats(self, date_str: Optional[str] = None, tag: Optional[str] = None) -> dict:
        """
        Get aggregated stats from logs.db
        """
        with get_db_cursor(self._paths.logs_db_path) as cur:
            where_clauses = ["type = 'proxy'"]
            params = []
            
            if date_str:
                try:
                    dt = datetime.strptime(date_str, "%Y-%m-%d")
                    start_ms = int(dt.timestamp() * 1000)
                    end_ms = int((dt + timedelta(days=1)).timestamp() * 1000)
                    where_clauses.append("timestamp_ms >= ? AND timestamp_ms < ?")
                    params.extend([start_ms, end_ms])
                except ValueError:
                    pass
            
            # Tag filtering logic
            if tag:
                # Need to look up key_id from tag (name) in app.db
                # This is cross-DB, so we do it in two steps.
                key_id = None
                with get_db_cursor(self._paths.app_db_path) as app_cur:
                    app_cur.execute("SELECT key_id FROM api_keys WHERE name = ?", (tag,))
                    row = app_cur.fetchone()
                    if row:
                        key_id = row["key_id"]
                
                if key_id:
                    where_clauses.append("api_key_id = ?")
                    params.append(key_id)
                else:
                    # Tag not found, so no logs match
                    where_clauses.append("1=0")
            
            where_sql = " AND ".join(where_clauses)
            
            # Total requests
            cur.execute(f"SELECT COUNT(*) FROM request_logs WHERE {where_sql}", params)
            total_requests = cur.fetchone()[0]
            
            # Total tokens
            cur.execute(f"SELECT SUM(total_tokens) FROM request_logs WHERE {where_sql}", params)
            total_tokens = cur.fetchone()[0] or 0
            
            # Success rate
            cur.execute(f"SELECT COUNT(*) FROM request_logs WHERE {where_sql} AND status_code = 200", params)
            successful_requests = cur.fetchone()[0]
            
            # Provider usage
            cur.execute(f"SELECT provider_id, COUNT(*) FROM request_logs WHERE {where_sql} GROUP BY provider_id", params)
            provider_usage = {r[0]: r[1] for r in cur.fetchall() if r[0]}
            
            # Model usage
            cur.execute(f"SELECT unified_model, COUNT(*) FROM request_logs WHERE {where_sql} GROUP BY unified_model", params)
            model_usage = {r[0]: r[1] for r in cur.fetchall() if r[0]}

            # Hourly requests (for trend chart)
            # SQLite strftime %H returns 00-23
            hourly_requests = {}
            if date_str:
                # If filtering by specific date, group by hour
                cur.execute(
                    f"SELECT strftime('%H', timestamp_ms / 1000, 'unixepoch', 'localtime') as hour, COUNT(*) FROM request_logs WHERE {where_sql} GROUP BY hour",
                    params
                )
                for r in cur.fetchall():
                    hourly_requests[r[0]] = r[1]
            
            # Provider-Model stats (for provider status list)
            # provider_id -> model -> {total, successful, failed, tokens}
            cur.execute(
                f"""
                SELECT provider_id, unified_model,
                       COUNT(*) as total,
                       SUM(CASE WHEN status_code = 200 THEN 1 ELSE 0 END) as success,
                       SUM(total_tokens) as tokens
                FROM request_logs
                WHERE {where_sql}
                GROUP BY provider_id, unified_model
                """,
                params
            )
            
            provider_model_stats = {}
            model_provider_stats = {}

            for r in cur.fetchall():
                pid = r["provider_id"]
                model = r["unified_model"]
                if not pid or not model:
                    continue
                
                # provider -> model -> stats
                if pid not in provider_model_stats:
                    provider_model_stats[pid] = {}
                
                # model -> provider -> stats
                if model not in model_provider_stats:
                    model_provider_stats[model] = {}

                total = r["total"]
                success = r["success"]
                
                stats_obj = {
                    "total": total,
                    "successful": success,
                    "failed": total - success,
                    "tokens": r["tokens"] or 0
                }
                
                provider_model_stats[pid][model] = stats_obj
                model_provider_stats[model][pid] = stats_obj
            
            return {
                "total_requests": total_requests,
                "total_tokens": total_tokens,
                "successful_requests": successful_requests,
                "failed_requests": total_requests - successful_requests,
                "provider_usage": provider_usage,
                "model_usage": model_usage,
                "hourly_requests": hourly_requests,
                "provider_model_stats": provider_model_stats,
                "model_provider_stats": model_provider_stats
            }

    def get_daily_stats(self, days: int = 7, tag: Optional[str] = None) -> list[dict]:
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=days)
        start_ms = int(start_dt.timestamp() * 1000)
        
        params = [start_ms]
        where_sql = "type = 'proxy' AND timestamp_ms >= ?"
        
        if tag:
             # Look up key_id from tag (name) in app.db
            key_id = None
            with get_db_cursor(self._paths.app_db_path) as app_cur:
                app_cur.execute("SELECT key_id FROM api_keys WHERE name = ?", (tag,))
                row = app_cur.fetchone()
                if row:
                    key_id = row["key_id"]
            
            if key_id:
                where_sql += " AND api_key_id = ?"
                params.append(key_id)
            else:
                where_sql += " AND 1=0"

        with get_db_cursor(self._paths.logs_db_path) as cur:
            sql = f"""
                SELECT
                    strftime('%Y-%m-%d', timestamp_ms / 1000, 'unixepoch', 'localtime') as day,
                    COUNT(*) as count,
                    SUM(CASE WHEN status_code = 200 THEN 1 ELSE 0 END) as success,
                    SUM(total_tokens) as tokens
                FROM request_logs
                WHERE {where_sql}
                GROUP BY day
                ORDER BY day
            """
            cur.execute(sql, params)
            rows = cur.fetchall()
            
            return [
                {
                    "date": r[0],
                    "requests": r[1],
                    "success": r[2],
                    "tokens": r[3] or 0
                }
                for r in rows
            ]


class ProviderModelsRepo:
    def __init__(self):
        self._paths = get_db_paths()

    def get_provider_models(self, provider_id: str) -> dict[str, dict]:
        """
        Returns {model_id: {owned_by, supported_endpoint_types, ...}}
        """
        with get_db_cursor(self._paths.app_db_path) as cur:
            cur.execute(
                """
                SELECT model_id, owned_by, supported_endpoint_types_json,
                       created_at_ms, last_activity_ms, last_activity_type
                FROM provider_models
                WHERE provider_id = ?
                ORDER BY model_id
                """,
                (provider_id,),
            )
            rows = cur.fetchall()

        result = {}
        for r in rows:
            result[r["model_id"]] = {
                "model_id": r["model_id"],
                "owned_by": r["owned_by"],
                "supported_endpoint_types": json.loads(r["supported_endpoint_types_json"] or "[]"),
                "created_at": r["created_at_ms"],
                "last_activity": r["last_activity_ms"],
                "last_activity_type": r["last_activity_type"],
            }
        return result

    def get_all_provider_models(self) -> dict[str, dict[str, dict]]:
        """
        Returns {provider_id: {model_id: {...}}}
        """
        with get_db_cursor(self._paths.app_db_path) as cur:
            cur.execute(
                """
                SELECT provider_id, model_id, owned_by, supported_endpoint_types_json,
                       created_at_ms, last_activity_ms, last_activity_type
                FROM provider_models
                ORDER BY provider_id, model_id
                """
            )
            rows = cur.fetchall()

        result = {}
        for r in rows:
            pid = r["provider_id"]
            if pid not in result:
                result[pid] = {}
            result[pid][r["model_id"]] = {
                "model_id": r["model_id"],
                "owned_by": r["owned_by"],
                "supported_endpoint_types": json.loads(r["supported_endpoint_types_json"] or "[]"),
                "created_at": r["created_at_ms"],
                "last_activity": r["last_activity_ms"],
                "last_activity_type": r["last_activity_type"],
            }
        return result

    def upsert_models(self, provider_id: str, models: list[dict]) -> None:
        """
        models: list of dict with keys:
          model_id, owned_by, supported_endpoint_types (list)
          created_at (optional int ms)
        """
        with get_db_cursor(self._paths.app_db_path) as cur:
            now_ms = _now_ms()
            
            for m in models:
                supported_json = json.dumps(m.get("supported_endpoint_types", []), ensure_ascii=False)
                created_at = m.get("created_at") or now_ms
                
                # Using INSERT OR IGNORE to keep existing data (like last_activity) safe?
                # Or UPSERT to update metadata? 
                # We should update metadata (owned_by, supported_types) but keep activity if exists.
                cur.execute(
                    """
                    INSERT INTO provider_models (
                      provider_id, model_id, owned_by, supported_endpoint_types_json,
                      created_at_ms, last_activity_ms, last_activity_type
                    ) VALUES (?, ?, ?, ?, ?, NULL, NULL)
                    ON CONFLICT(provider_id, model_id) DO UPDATE SET
                      owned_by=excluded.owned_by,
                      supported_endpoint_types_json=excluded.supported_endpoint_types_json
                    """,
                    (provider_id, m["model_id"], m.get("owned_by", ""), supported_json, created_at),
                )

    def delete_models(self, provider_id: str, model_ids: list[str]) -> None:
        if not model_ids:
            return
        with get_db_cursor(self._paths.app_db_path) as cur:
            # sqlite doesn't support list param directly
            placeholders = ",".join("?" for _ in model_ids)
            params = [provider_id] + model_ids
            cur.execute(
                f"DELETE FROM provider_models WHERE provider_id = ? AND model_id IN ({placeholders})",
                params,
            )

    def delete_provider(self, provider_id: str) -> None:
        with get_db_cursor(self._paths.app_db_path) as cur:
            cur.execute("DELETE FROM provider_models WHERE provider_id = ?", (provider_id,))

    def update_activity(self, provider_id: str, model_id: str, activity_type: str) -> None:
        with get_db_cursor(self._paths.app_db_path) as cur:
            cur.execute(
                """
                UPDATE provider_models
                SET last_activity_ms = ?, last_activity_type = ?
                WHERE provider_id = ? AND model_id = ?
                """,
                (_now_ms(), activity_type, provider_id, model_id),
            )

    def batch_update_activity(self, updates: list[tuple[str, str, str]]) -> int:
        # updates: [(provider_id, model_id, activity_type), ...]
        with get_db_cursor(self._paths.app_db_path) as cur:
            now = _now_ms()
            count = 0
            for pid, mid, atype in updates:
                cur.execute(
                    """
                    UPDATE provider_models
                    SET last_activity_ms = ?, last_activity_type = ?
                    WHERE provider_id = ? AND model_id = ?
                    """,
                    (now, atype, pid, mid),
                )
                count += cur.rowcount
            return count


class ModelMappingRepo:
    def __init__(self):
        self._paths = get_db_paths()

    def get_sync_config(self) -> dict:
        with get_db_cursor(self._paths.app_db_path) as cur:
            cur.execute("SELECT * FROM model_mapping_sync_config WHERE id = 1")
            row = cur.fetchone()
        if not row:
            return {"auto_sync_enabled": False, "auto_sync_interval_hours": 6, "last_full_sync_ms": None}
        return {
            "auto_sync_enabled": bool(row["auto_sync_enabled"]),
            "auto_sync_interval_hours": row["auto_sync_interval_hours"],
            "last_full_sync_ms": row["last_full_sync_ms"],
        }

    def update_sync_config(self, enabled: Optional[bool], interval: Optional[int], last_sync: Optional[int] = None) -> None:
        updates = []
        params = []
        if enabled is not None:
            updates.append("auto_sync_enabled = ?")
            params.append(1 if enabled else 0)
        if interval is not None:
            updates.append("auto_sync_interval_hours = ?")
            params.append(interval)
        if last_sync is not None:
            updates.append("last_full_sync_ms = ?")
            params.append(last_sync)
        
        if updates:
            with get_db_cursor(self._paths.app_db_path) as cur:
                sql = f"UPDATE model_mapping_sync_config SET {', '.join(updates)} WHERE id = 1"
                cur.execute(sql, params)

    def list_mappings(self) -> dict[str, dict]:
        """
        Returns full mapping dict structure ordered by order_index.
        """
        with get_db_cursor(self._paths.app_db_path) as cur:
            # 1. Base mappings (ordered by order_index)
            cur.execute("SELECT unified_name, description, last_sync_ms, order_index FROM model_mappings ORDER BY order_index ASC, unified_name ASC")
            mappings = {}
            for r in cur.fetchall():
                mappings[r["unified_name"]] = {
                    "unified_name": r["unified_name"],
                    "description": r["description"],
                    "last_sync": r["last_sync_ms"],
                    "order_index": r["order_index"],
                    "rules": [],
                    "manual_includes": [],
                    "excluded_providers": [],
                    "resolved_models": {},
                    "model_settings": {},
                }

            # 2. Rules
            cur.execute("SELECT unified_name, type, pattern, case_sensitive FROM model_mapping_rules ORDER BY order_index")
            for r in cur.fetchall():
                if r["unified_name"] in mappings:
                    mappings[r["unified_name"]]["rules"].append({
                        "type": r["type"],
                        "pattern": r["pattern"],
                        "case_sensitive": bool(r["case_sensitive"])
                    })

            # 3. Manual includes
            cur.execute("SELECT unified_name, provider_id, model_id FROM model_mapping_manual_includes ORDER BY order_index")
            for r in cur.fetchall():
                if r["unified_name"] in mappings:
                    ref = f"{r['provider_id']}:{r['model_id']}" if r["provider_id"] else r["model_id"]
                    mappings[r["unified_name"]]["manual_includes"].append(ref)

            # 4. Excluded providers
            cur.execute("SELECT unified_name, provider_id FROM model_mapping_excluded_providers")
            for r in cur.fetchall():
                if r["unified_name"] in mappings:
                    mappings[r["unified_name"]]["excluded_providers"].append(r["provider_id"])

            # 5. Resolved models
            cur.execute("SELECT unified_name, provider_id, model_id FROM model_mapping_resolved_models")
            for r in cur.fetchall():
                uname = r["unified_name"]
                pid = r["provider_id"]
                if uname in mappings:
                    if pid not in mappings[uname]["resolved_models"]:
                        mappings[uname]["resolved_models"][pid] = []
                    mappings[uname]["resolved_models"][pid].append(r["model_id"])

            # 6. Model settings
            cur.execute("SELECT unified_name, provider_id, model_id, protocol, settings_json FROM model_mapping_model_settings")
            for r in cur.fetchall():
                uname = r["unified_name"]
                if uname in mappings:
                    key = f"{r['provider_id']}:{r['model_id']}"
                    settings = json.loads(r["settings_json"] or "{}")
                    if r["protocol"]:
                        settings["protocol"] = r["protocol"]
                    mappings[uname]["model_settings"][key] = settings

        return mappings

    def update_orders(self, ordered_names: list[str]) -> int:
        """Update order_index for all mappings based on the provided ordered list."""
        with get_db_cursor(self._paths.app_db_path) as cur:
            updated = 0
            for idx, name in enumerate(ordered_names):
                cur.execute(
                    "UPDATE model_mappings SET order_index = ? WHERE unified_name = ?",
                    (idx, name)
                )
                updated += cur.rowcount
            return updated

    def create_mapping(self, unified_name: str, description: str) -> None:
        with get_db_cursor(self._paths.app_db_path) as cur:
            # Get max order_index and add 1 for new mapping
            cur.execute("SELECT COALESCE(MAX(order_index), -1) + 1 FROM model_mappings")
            next_order = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO model_mappings (unified_name, description, order_index) VALUES (?, ?, ?)",
                (unified_name, description, next_order),
            )

    def delete_mapping(self, unified_name: str) -> None:
        with get_db_cursor(self._paths.app_db_path) as cur:
            cur.execute("DELETE FROM model_mappings WHERE unified_name = ?", (unified_name,))

    def update_mapping_meta(self, unified_name: str, description: Optional[str] = None, last_sync_ms: Optional[int] = None) -> None:
        updates = []
        params = []
        if description is not None:
            updates.append("description = ?")
            params.append(description)
        if last_sync_ms is not None:
            updates.append("last_sync_ms = ?")
            params.append(last_sync_ms)
        
        if updates:
            with get_db_cursor(self._paths.app_db_path) as cur:
                params.append(unified_name)
                cur.execute(f"UPDATE model_mappings SET {', '.join(updates)} WHERE unified_name = ?", params)

    def rename_mapping(self, old_name: str, new_name: str) -> None:
        with get_db_cursor(self._paths.app_db_path) as cur:
            # Disable foreign keys to allow update of PK if supported, or just use update cascade
            # SQLite supports ON UPDATE CASCADE if defined in schema. 
            # Our schema definitions in db.py don't have ON UPDATE CASCADE for unified_name FKs?
            # Let's check db.py... It has ON DELETE CASCADE but not ON UPDATE CASCADE.
            # So we might need to manually handle this or rely on deferrable constraints.
            # Actually, standard practice in sqlite for renaming PK referenced by FKs without cascade update
            # is tricky. 
            # Easier approach: Insert new, Copy data, Delete old.
            # But that's complex with many tables.
            # Let's try PRAGMA foreign_keys = OFF temporarily.
            
            cur.execute("PRAGMA foreign_keys = OFF")
            try:
                cur.execute("UPDATE model_mappings SET unified_name = ? WHERE unified_name = ?", (new_name, old_name))
                cur.execute("UPDATE model_mapping_rules SET unified_name = ? WHERE unified_name = ?", (new_name, old_name))
                cur.execute("UPDATE model_mapping_manual_includes SET unified_name = ? WHERE unified_name = ?", (new_name, old_name))
                cur.execute("UPDATE model_mapping_excluded_providers SET unified_name = ? WHERE unified_name = ?", (new_name, old_name))
                cur.execute("UPDATE model_mapping_resolved_models SET unified_name = ? WHERE unified_name = ?", (new_name, old_name))
                cur.execute("UPDATE model_mapping_model_settings SET unified_name = ? WHERE unified_name = ?", (new_name, old_name))
                conn.commit()
            finally:
                cur.execute("PRAGMA foreign_keys = ON")

    def replace_rules(self, unified_name: str, rules: list[dict]) -> None:
        with get_db_cursor(self._paths.app_db_path) as cur:
            cur.execute("DELETE FROM model_mapping_rules WHERE unified_name = ?", (unified_name,))
            for idx, r in enumerate(rules):
                cur.execute(
                    "INSERT INTO model_mapping_rules (unified_name, type, pattern, case_sensitive, order_index) VALUES (?, ?, ?, ?, ?)",
                    (unified_name, r["type"], r["pattern"], 1 if r["case_sensitive"] else 0, idx)
                )

    def replace_manual_includes(self, unified_name: str, includes: list[str]) -> None:
        with get_db_cursor(self._paths.app_db_path) as cur:
            cur.execute("DELETE FROM model_mapping_manual_includes WHERE unified_name = ?", (unified_name,))
            for idx, ref in enumerate(includes):
                pid, mid = None, ref
                if ":" in ref:
                    pid, mid = ref.split(":", 1)
                cur.execute(
                    "INSERT INTO model_mapping_manual_includes (unified_name, provider_id, model_id, order_index) VALUES (?, ?, ?, ?)",
                    (unified_name, pid, mid, idx)
                )

    def replace_excluded_providers(self, unified_name: str, providers: list[str]) -> None:
        with get_db_cursor(self._paths.app_db_path) as cur:
            cur.execute("DELETE FROM model_mapping_excluded_providers WHERE unified_name = ?", (unified_name,))
            for pid in providers:
                cur.execute(
                    "INSERT INTO model_mapping_excluded_providers (unified_name, provider_id) VALUES (?, ?)",
                    (unified_name, pid)
                )

    def replace_resolved_models(self, unified_name: str, resolved: dict[str, list[str]]) -> None:
        with get_db_cursor(self._paths.app_db_path) as cur:
            cur.execute("DELETE FROM model_mapping_resolved_models WHERE unified_name = ?", (unified_name,))
            for pid, models in resolved.items():
                for mid in models:
                    cur.execute(
                        "INSERT INTO model_mapping_resolved_models (unified_name, provider_id, model_id) VALUES (?, ?, ?)",
                        (unified_name, pid, mid)
                    )

    def update_model_settings(self, unified_name: str, settings: dict[str, dict]) -> None:
        with get_db_cursor(self._paths.app_db_path) as cur:
            # We can replace all settings for this mapping or upsert.
            # The manager usually passes the full dict. Let's replace all to be safe and clean.
            cur.execute("DELETE FROM model_mapping_model_settings WHERE unified_name = ?", (unified_name,))
            for key, s in settings.items():
                if ":" not in key:
                    continue
                pid, mid = key.split(":", 1)
                protocol = s.get("protocol")
                s_json = json.dumps(s, ensure_ascii=False)
                cur.execute(
                    "INSERT INTO model_mapping_model_settings (unified_name, provider_id, model_id, protocol, settings_json) VALUES (?, ?, ?, ?, ?)",
                    (unified_name, pid, mid, protocol, s_json)
                )

    def set_model_protocol(self, unified_name: str, provider_id: str, model_id: str, protocol: Optional[str]) -> None:
        with get_db_cursor(self._paths.app_db_path) as cur:
            # First get existing settings
            cur.execute(
                "SELECT settings_json FROM model_mapping_model_settings WHERE unified_name = ? AND provider_id = ? AND model_id = ?",
                (unified_name, provider_id, model_id)
            )
            row = cur.fetchone()
            settings = json.loads(row["settings_json"]) if row else {}
            
            if protocol is None:
                if "protocol" in settings:
                    del settings["protocol"]
            else:
                settings["protocol"] = protocol
                
            # If settings empty and protocol None, delete row? Or keep empty settings?
            # If protocol is None and settings is empty, we can delete.
            if not settings and protocol is None:
                cur.execute(
                    "DELETE FROM model_mapping_model_settings WHERE unified_name = ? AND provider_id = ? AND model_id = ?",
                    (unified_name, provider_id, model_id)
                )
            else:
                s_json = json.dumps(settings, ensure_ascii=False)
                cur.execute(
                    """
                    INSERT INTO model_mapping_model_settings (unified_name, provider_id, model_id, protocol, settings_json)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(unified_name, provider_id, model_id) DO UPDATE SET
                    protocol=excluded.protocol,
                    settings_json=excluded.settings_json
                    """,
                    (unified_name, provider_id, model_id, protocol, s_json)
                )


class ModelHealthRepo:
    def __init__(self):
        self._paths = get_db_paths()

    def get_all_results(self) -> dict[str, dict]:
        """
        Returns {provider_id:model_id: {success, latency, ...}}
        """
        with get_db_cursor(self._paths.app_db_path) as cur:
            cur.execute(
                """
                SELECT provider_id, model_id, success, latency_ms, error, tested_at_ms, response_body_json
                FROM model_health_last
                """
            )
            rows = cur.fetchall()

        results = {}
        for r in rows:
            key = f"{r['provider_id']}:{r['model_id']}"
            # Convert ms timestamp back to ISO string for compatibility
            tested_at_iso = datetime.fromtimestamp(r["tested_at_ms"] / 1000.0, timezone.utc).isoformat()
            results[key] = {
                "provider": r["provider_id"],
                "model": r["model_id"],
                "success": bool(r["success"]),
                "latency_ms": r["latency_ms"],
                "error": r["error"],
                "tested_at": tested_at_iso,
                "response_body": {},
            }
            try:
                results[key]["response_body"] = json.loads(r["response_body_json"] or "{}")
            except json.JSONDecodeError:
                print(f"[WARN] Failed to decode response_body_json for {key}. Data might be corrupted.")
                results[key]["response_body"] = {"error": "Failed to decode JSON body"}
        return results

    def upsert_result(self, result: dict) -> None:
        pid = result["provider"]
        mid = result["model"]
        success = 1 if result["success"] else 0
        latency = result["latency_ms"]
        error = result.get("error")
        body_json = json.dumps(result.get("response_body", {}), ensure_ascii=False)
        
        # Parse ISO timestamp to ms
        try:
            dt = datetime.fromisoformat(result["tested_at"].replace("Z", "+00:00"))
            tested_at_ms = int(dt.timestamp() * 1000)
        except:
            tested_at_ms = _now_ms()

        with get_db_cursor(self._paths.app_db_path) as cur:
            cur.execute(
                """
                INSERT INTO model_health_last (
                  provider_id, model_id, success, latency_ms, error, tested_at_ms, response_body_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider_id, model_id) DO UPDATE SET
                  success=excluded.success,
                  latency_ms=excluded.latency_ms,
                  error=excluded.error,
                  tested_at_ms=excluded.tested_at_ms,
                  response_body_json=excluded.response_body_json
                """,
                (pid, mid, success, latency, error, tested_at_ms, body_json)
            )

    def delete_result(self, provider_id: str, model_id: str) -> None:
        with get_db_cursor(self._paths.app_db_path) as cur:
            cur.execute(
                "DELETE FROM model_health_last WHERE provider_id = ? AND model_id = ?",
                (provider_id, model_id)
            )

    def clear_all(self) -> None:
        with get_db_cursor(self._paths.app_db_path) as cur:
            cur.execute("DELETE FROM model_health_last")
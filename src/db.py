import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from cryptography.fernet import Fernet

DEFAULT_APP_DB_PATH = "data/app.db"
DEFAULT_LOGS_DB_PATH = "data/logs.db"

# 模块级 Fernet 实例缓存
_fernet_instance: Optional[Fernet] = None


@dataclass(frozen=True)
class DbPaths:
    app_db_path: str = DEFAULT_APP_DB_PATH
    logs_db_path: str = DEFAULT_LOGS_DB_PATH


def _ensure_parent_dir(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def get_db_paths() -> DbPaths:
    return DbPaths()


def init_fernet(key: str) -> None:
    """
    初始化 Fernet 加密实例。必须在应用启动时调用一次。
    
    Args:
        key: Fernet 加密密钥字符串
        
    Raises:
        ValueError: 密钥为空或格式无效
    """
    global _fernet_instance
    if not key:
        raise ValueError("加密密钥不能为空。请在 config.json 中设置 db_encryption_key。")
    try:
        _fernet_instance = Fernet(key.encode("utf-8"))
    except Exception:
        raise ValueError(
            "db_encryption_key 格式无效。\n"
            "请运行 `python scripts/gen_fernet_key.py` 生成有效密钥，\n"
            "然后将生成的密钥复制到 config.json 的 db_encryption_key 字段中。"
        )


def get_fernet() -> Fernet:
    """
    获取已初始化的 Fernet 实例。
    
    Returns:
        Fernet 实例
        
    Raises:
        RuntimeError: 如果 Fernet 尚未初始化
    """
    if _fernet_instance is None:
        raise RuntimeError(
            "Fernet 尚未初始化。请确保在应用启动时调用 init_fernet() 或检查 config.json 中的 db_encryption_key 配置。"
        )
    return _fernet_instance


def connect_sqlite(path: str) -> sqlite3.Connection:
    _ensure_parent_dir(path)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _apply_pragmas(conn)
    return conn


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    statements: Sequence[str] = (
        "PRAGMA journal_mode=WAL;",
        "PRAGMA synchronous=NORMAL;",
        "PRAGMA foreign_keys=ON;",
        "PRAGMA busy_timeout=5000;",
    )
    cur = conn.cursor()
    for stmt in statements:
        cur.execute(stmt)
    cur.close()


def init_schema_app(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS admin_users (
          id INTEGER PRIMARY KEY CHECK (id = 1),
          username TEXT NOT NULL,
          password_hash TEXT NOT NULL,
          created_at_ms INTEGER NOT NULL,
          updated_at_ms INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS api_keys (
          key_id TEXT PRIMARY KEY,
          key_enc BLOB NOT NULL,
          name TEXT NOT NULL,
          created_at_ms INTEGER NOT NULL,
          enabled INTEGER NOT NULL DEFAULT 1,
          last_used_ms INTEGER,
          total_requests INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS providers (
          provider_id TEXT PRIMARY KEY,
          name TEXT NOT NULL UNIQUE,
          base_url TEXT NOT NULL,
          api_key_enc BLOB NOT NULL,
          weight INTEGER NOT NULL DEFAULT 1,
          timeout_ms INTEGER,
          enabled INTEGER NOT NULL DEFAULT 1,
          allow_health_check INTEGER NOT NULL DEFAULT 1,
          allow_model_update INTEGER NOT NULL DEFAULT 1,
          default_protocol TEXT,
          updated_at_ms INTEGER NOT NULL,
          models_updated_at_ms INTEGER
        );

        CREATE TABLE IF NOT EXISTS provider_models (
          provider_id TEXT NOT NULL,
          model_id TEXT NOT NULL,
          owned_by TEXT,
          supported_endpoint_types_json TEXT,
          created_at_ms INTEGER,
          last_activity_ms INTEGER,
          last_activity_type TEXT,
          PRIMARY KEY (provider_id, model_id),
          FOREIGN KEY (provider_id) REFERENCES providers(provider_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_provider_models_last_activity
          ON provider_models(last_activity_ms);

        CREATE TABLE IF NOT EXISTS model_health_last (
          provider_id TEXT NOT NULL,
          model_id TEXT NOT NULL,
          success INTEGER NOT NULL,
          latency_ms REAL,
          error TEXT,
          tested_at_ms INTEGER NOT NULL,
          response_body_json TEXT,
          PRIMARY KEY (provider_id, model_id),
          FOREIGN KEY (provider_id, model_id)
            REFERENCES provider_models(provider_id, model_id)
            ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS model_mappings (
          unified_name TEXT PRIMARY KEY,
          description TEXT,
          last_sync_ms INTEGER,
          order_index INTEGER NOT NULL DEFAULT 0,
          enabled INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS model_mapping_rules (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          unified_name TEXT NOT NULL,
          type TEXT NOT NULL,
          pattern TEXT NOT NULL,
          case_sensitive INTEGER NOT NULL DEFAULT 0,
          order_index INTEGER NOT NULL DEFAULT 0,
          FOREIGN KEY (unified_name) REFERENCES model_mappings(unified_name) ON DELETE CASCADE ON UPDATE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_mapping_rules_unified
          ON model_mapping_rules(unified_name, order_index);

        CREATE TABLE IF NOT EXISTS model_mapping_manual_includes (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          unified_name TEXT NOT NULL,
          provider_id TEXT,
          model_id TEXT NOT NULL,
          order_index INTEGER NOT NULL DEFAULT 0,
          FOREIGN KEY (unified_name) REFERENCES model_mappings(unified_name) ON DELETE CASCADE ON UPDATE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_mapping_includes_unified
          ON model_mapping_manual_includes(unified_name, order_index);

        CREATE TABLE IF NOT EXISTS model_mapping_excluded_providers (
          unified_name TEXT NOT NULL,
          provider_id TEXT NOT NULL,
          PRIMARY KEY (unified_name, provider_id),
          FOREIGN KEY (unified_name) REFERENCES model_mappings(unified_name) ON DELETE CASCADE ON UPDATE CASCADE
        );

        CREATE TABLE IF NOT EXISTS model_mapping_resolved_models (
          unified_name TEXT NOT NULL,
          provider_id TEXT NOT NULL,
          model_id TEXT NOT NULL,
          PRIMARY KEY (unified_name, provider_id, model_id),
          FOREIGN KEY (unified_name) REFERENCES model_mappings(unified_name) ON DELETE CASCADE ON UPDATE CASCADE,
          FOREIGN KEY (provider_id, model_id) REFERENCES provider_models(provider_id, model_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_mapping_resolved_unified
          ON model_mapping_resolved_models(unified_name);

        CREATE TABLE IF NOT EXISTS model_mapping_model_settings (
          unified_name TEXT NOT NULL,
          provider_id TEXT NOT NULL,
          model_id TEXT NOT NULL,
          protocol TEXT,
          settings_json TEXT,
          PRIMARY KEY (unified_name, provider_id, model_id),
          FOREIGN KEY (unified_name) REFERENCES model_mappings(unified_name) ON DELETE CASCADE ON UPDATE CASCADE,
          FOREIGN KEY (provider_id, model_id) REFERENCES provider_models(provider_id, model_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS model_mapping_sync_config (
          id INTEGER PRIMARY KEY CHECK (id = 1),
          auto_sync_enabled INTEGER NOT NULL DEFAULT 0,
          auto_sync_interval_hours INTEGER NOT NULL DEFAULT 6,
          last_full_sync_ms INTEGER
        );

        INSERT OR IGNORE INTO model_mapping_sync_config (id) VALUES (1);
        """
    )
    conn.commit()


def init_schema_logs(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS request_logs (
          id TEXT PRIMARY KEY,
          timestamp_ms INTEGER NOT NULL,
          level TEXT NOT NULL,
          type TEXT NOT NULL,
          method TEXT NOT NULL,
          path TEXT NOT NULL,
          protocol TEXT,
          status_code INTEGER,
          duration_ms REAL,
          message TEXT,
          error TEXT,
          client_ip TEXT,
          api_key_id TEXT,
          provider_id TEXT,
          unified_model TEXT,
          actual_model TEXT,
          prompt_tokens INTEGER,
          completion_tokens INTEGER,
          total_tokens INTEGER
        );

        CREATE INDEX IF NOT EXISTS idx_logs_ts ON request_logs(timestamp_ms);
        CREATE INDEX IF NOT EXISTS idx_logs_type_ts ON request_logs(type, timestamp_ms);
        CREATE INDEX IF NOT EXISTS idx_logs_api_key_ts ON request_logs(api_key_id, timestamp_ms);
        CREATE INDEX IF NOT EXISTS idx_logs_provider_ts ON request_logs(provider_id, timestamp_ms);
        CREATE INDEX IF NOT EXISTS idx_logs_unified_model_ts ON request_logs(unified_model, timestamp_ms);
        CREATE INDEX IF NOT EXISTS idx_logs_status ON request_logs(status_code);
        """
    )
    conn.commit()


def init_all_schemas() -> tuple[sqlite3.Connection, sqlite3.Connection]:
    paths = get_db_paths()
    app_conn = connect_sqlite(paths.app_db_path)
    logs_conn = connect_sqlite(paths.logs_db_path)
    init_schema_app(app_conn)
    init_schema_logs(logs_conn)
    return app_conn, logs_conn
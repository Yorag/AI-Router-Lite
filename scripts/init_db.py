import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import load_config_file
from src.db import init_fernet, init_all_schemas


def main() -> None:
    try:
        config = load_config_file()
    except RuntimeError as e:
        raise SystemExit(str(e))
    
    db_encryption_key = config.get("db_encryption_key")
    if not db_encryption_key:
        raise SystemExit(
            "配置中缺少 'db_encryption_key'。\n"
            "请使用 `python scripts/gen_fernet_key.py` 生成密钥并添加到 config.json 中。"
        )
    
    # 初始化 Fernet 加密实例
    init_fernet(db_encryption_key)
    
    # 初始化数据库 schema
    app_conn, logs_conn = init_all_schemas()
    app_conn.close()
    logs_conn.close()
    print("Initialized schemas: data/app.db and data/logs.db")


if __name__ == "__main__":
    main()

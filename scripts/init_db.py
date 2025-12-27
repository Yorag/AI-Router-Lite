import os
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import ENV_ENCRYPTION_KEY
from src.db import init_fernet, init_all_schemas


def main() -> None:
    # 从环境变量读取加密密钥
    db_encryption_key = os.getenv(ENV_ENCRYPTION_KEY)
    if not db_encryption_key:
        raise SystemExit(
            f"环境变量 {ENV_ENCRYPTION_KEY} 未设置。\n"
            f"请使用 `python scripts/gen_fernet_key.py` 生成密钥，然后设置环境变量。"
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

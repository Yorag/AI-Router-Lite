import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.db import init_fernet, init_all_schemas


def main() -> None:
    # 初始化 Fernet 加密实例（自动获取或生成密钥）
    init_fernet()

    # 初始化数据库 schema
    app_conn, logs_conn = init_all_schemas()
    app_conn.close()
    logs_conn.close()
    print("Initialized schemas: data/app.db and data/logs.db")


if __name__ == "__main__":
    main()

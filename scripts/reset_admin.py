"""重置管理员密码脚本"""
import sys
sys.path.insert(0, ".")

from src.db import get_db_paths
from src.sqlite_repos import get_db_cursor

paths = get_db_paths()
with get_db_cursor(paths.app_db_path) as cur:
    cur.execute("DELETE FROM admin_users WHERE id=1")
    print("管理员账户已重置，请重启服务后访问 /admin 重新设置密码")

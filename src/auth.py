"""
管理面板认证模块

提供管理员用户认证功能，包括：
- 密码哈希与验证
- JWT 令牌生成与验证
- 管理员用户管理
"""

import time
import secrets
from typing import Optional
from datetime import datetime, timezone, timedelta

import bcrypt
import jwt
from fastapi import Request, Response

from .constants import (
    AUTH_COOKIE_NAME,
    AUTH_PASSWORD_MIN_LENGTH,
    AUTH_MAX_LOGIN_ATTEMPTS,
)
from .config import get_config
from .sqlite_repos import get_db_cursor
from .db import get_db_paths
from .exceptions import UnauthorizedException
from .key_manager import get_jwt_secret


def _now_ms() -> int:
    return int(time.time() * 1000)


class AdminAuthManager:
    """管理员认证管理器"""

    def __init__(self):
        self._paths = get_db_paths()
        self._jwt_secret: Optional[str] = None
        self._failed_attempts: int = 0
        self._lockout_until: float = 0

    def _get_jwt_secret(self) -> str:
        """获取 JWT 密钥"""
        if self._jwt_secret:
            return self._jwt_secret

        self._jwt_secret = get_jwt_secret()
        return self._jwt_secret

    def _hash_password(self, password: str) -> str:
        """哈希密码"""
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    def _verify_password(self, password: str, password_hash: str) -> bool:
        """验证密码"""
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))

    def is_initialized(self) -> bool:
        """检查是否已初始化管理员账户"""
        with get_db_cursor(self._paths.app_db_path) as cur:
            cur.execute("SELECT COUNT(*) FROM admin_users WHERE id = 1")
            return cur.fetchone()[0] > 0

    def initialize_admin(self, password: str) -> tuple[bool, str]:
        """初始化管理员账户（首次设置密码）"""
        if len(password) < AUTH_PASSWORD_MIN_LENGTH:
            return False, f"Password must be at least {AUTH_PASSWORD_MIN_LENGTH} characters"

        if self.is_initialized():
            return False, "Admin account already exists"

        now_ms = _now_ms()
        password_hash = self._hash_password(password)

        with get_db_cursor(self._paths.app_db_path) as cur:
            cur.execute(
                """
                INSERT INTO admin_users (id, username, password_hash, created_at_ms, updated_at_ms)
                VALUES (1, 'admin', ?, ?, ?)
                """,
                (password_hash, now_ms, now_ms),
            )
        return True, "Admin account created successfully"

    def verify_credentials(self, password: str) -> bool:
        """验证管理员密码"""
        with get_db_cursor(self._paths.app_db_path) as cur:
            cur.execute("SELECT password_hash FROM admin_users WHERE id = 1")
            row = cur.fetchone()
            if not row:
                return False
            return self._verify_password(password, row["password_hash"])

    def change_password(self, old_password: str, new_password: str) -> tuple[bool, str]:
        """修改管理员密码"""
        if not self.verify_credentials(old_password):
            return False, "Incorrect current password"

        if len(new_password) < AUTH_PASSWORD_MIN_LENGTH:
            return False, f"New password must be at least {AUTH_PASSWORD_MIN_LENGTH} characters"

        password_hash = self._hash_password(new_password)
        now_ms = _now_ms()

        with get_db_cursor(self._paths.app_db_path) as cur:
            cur.execute(
                "UPDATE admin_users SET password_hash = ?, updated_at_ms = ? WHERE id = 1",
                (password_hash, now_ms),
            )
        return True, "Password changed successfully"

    def create_token(self) -> str:
        """创建 JWT 令牌"""
        config = get_config()
        expire = datetime.now(timezone.utc) + timedelta(hours=config.auth.token_expire_hours)
        payload = {
            "sub": "admin",
            "exp": expire,
            "iat": datetime.now(timezone.utc),
            "jti": secrets.token_hex(8),
        }
        return jwt.encode(payload, self._get_jwt_secret(), algorithm="HS256")

    def verify_token(self, token: str) -> bool:
        """验证 JWT 令牌"""
        try:
            jwt.decode(token, self._get_jwt_secret(), algorithms=["HS256"])
            return True
        except jwt.ExpiredSignatureError:
            return False
        except jwt.InvalidTokenError:
            return False

    def _is_locked_out(self) -> bool:
        """检查是否处于锁定状态"""
        if self._lockout_until > time.time():
            return True
        return False

    def _record_failed_attempt(self) -> None:
        """记录失败尝试"""
        self._failed_attempts += 1
        if self._failed_attempts >= AUTH_MAX_LOGIN_ATTEMPTS:
            config = get_config()
            self._lockout_until = time.time() + config.auth.lockout_duration_seconds

    def _reset_failed_attempts(self) -> None:
        """重置失败计数"""
        self._failed_attempts = 0
        self._lockout_until = 0

    def login(self, password: str, response: Response) -> tuple[bool, str]:
        """登录并设置 Cookie"""
        if self._is_locked_out():
            remaining = int(self._lockout_until - time.time())
            return False, f"Too many login attempts. Please try again in {remaining} seconds"

        config = get_config()
        if not self.verify_credentials(password):
            self._record_failed_attempt()
            remaining_attempts = AUTH_MAX_LOGIN_ATTEMPTS - self._failed_attempts
            if remaining_attempts > 0:
                return False, f"Incorrect password. {remaining_attempts} attempts remaining"
            return False, f"Too many login attempts. Please try again in {config.auth.lockout_duration_seconds} seconds"

        self._reset_failed_attempts()
        token = self.create_token()
        response.set_cookie(
            key=AUTH_COOKIE_NAME,
            value=token,
            httponly=True,
            max_age=config.auth.token_expire_hours * 3600,
            samesite="lax",
            path="/",
        )
        return True, "Login successful"

    def logout(self, response: Response) -> None:
        """登出并清除 Cookie"""
        response.delete_cookie(key=AUTH_COOKIE_NAME, path="/")

    def get_token_from_request(self, request: Request) -> Optional[str]:
        """从请求中获取令牌"""
        # 优先从 Cookie 获取
        token = request.cookies.get(AUTH_COOKIE_NAME)
        if token:
            return token

        # 其次从 Authorization 头获取
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            return auth_header[7:]

        return None

    def require_auth(self, request: Request) -> None:
        """验证请求是否已认证，未认证则抛出异常"""
        token = self.get_token_from_request(request)
        if not token or not self.verify_token(token):
            raise UnauthorizedException("Not authenticated or session expired")


admin_auth_manager = AdminAuthManager()
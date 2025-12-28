"""
统一常量管理模块

所有可配置的常量都应在此文件中定义，便于集中管理和维护

注意：以下配置已迁移到 config.json，通过 get_config() 获取：
- server_port, server_host (服务器配置)
- timezone_offset (时区配置)
- log_retention_days (日志保留天数)
- cooldown.* (熔断器冷却时间)
- auth.token_expire_hours, auth.lockout_duration_seconds (认证配置)
"""

# ==================== 应用信息 ====================

# 应用名称
APP_NAME: str = "AI-Router-Lite"

# 应用版本
APP_VERSION: str = "0.9.1"

# 应用描述
APP_DESCRIPTION: str = "轻量级 AI 聚合路由 + 管理面板"

# 模型所有者标识
MODEL_OWNED_BY: str = "ai-router-lite"


# ==================== 熔断器常量 ====================

# 永久禁用标记（用于 401/403 鉴权失败、404 模型不存在）
# 注意：其他冷却时间已迁移到 config.json 的 cooldown 配置
COOLDOWN_PERMANENT: int = -1


# ==================== 日志系统配置 ====================

# 内存中保留的最大日志条数
LOG_MAX_MEMORY_ENTRIES: int = 1000

# SSE 订阅队列大小
LOG_SUBSCRIBE_QUEUE_SIZE: int = 100

# 最近日志查询默认限制
LOG_RECENT_LIMIT_DEFAULT: int = 100

# 小时统计默认天数
LOG_HOURLY_STATS_DEFAULT_DAYS: int = 7


# ==================== 代理错误配置 ====================

# 代理错误消息最大长度（字符），超过将被截断
PROXY_ERROR_MESSAGE_MAX_LENGTH: int = 300


# ==================== 模型映射配置 ====================

# 自动同步检查间隔（秒）- 后台任务轮询检查是否需要同步的频率
AUTO_SYNC_CHECK_INTERVAL_SECONDS: int = 60


# ==================== API 密钥配置 ====================


# API 密钥 ID 前缀
API_KEY_PREFIX: str = "sk-"

# API 密钥 ID 随机部分长度（字节，实际显示为双倍十六进制字符）
API_KEY_ID_RANDOM_BYTES: int = 4

# API 密钥 Secret 长度（字节，实际显示为双倍十六进制字符）
API_KEY_SECRET_BYTES: int = 16


# ==================== HTTP 请求配置 ====================

# 管理 API 的 HTTP 超时时间（秒）
ADMIN_HTTP_TIMEOUT: float = 30.0

# 默认 User-Agent（当客户端未提供时使用）
DEFAULT_USER_AGENT: str = "ai-router-lite/" + APP_VERSION

# 不允许穿透的请求头（小写），这些头由网关控制
BLOCKED_HEADERS: tuple[str, ...] = (
    # 认证相关 - 上游使用 provider 的 key
    "authorization",
    "x-api-key",
    # HTTP 协议控制 - httpx 自动处理
    "host",
    "content-length",
    "content-type",
    "connection",
    "transfer-encoding",
    "accept-encoding",
    # 中转相关
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",
    "x-forwarded-port",
    "x-real-ip",
    "forwarded",
    "via",
    "proxy-connection",
    "proxy-authorization",
    # 其他客户端类
    "x-title",
    "http-referer",
    "cookie"
)

# 健康测试请求的 max_tokens
HEALTH_TEST_MAX_TOKENS: int = 10

# 健康测试请求的消息内容
HEALTH_TEST_MESSAGE: str = "hi"


# ==================== 认证配置 ====================

# JWT Cookie 名称
AUTH_COOKIE_NAME: str = "admin_session"

# 密码最小长度
AUTH_PASSWORD_MIN_LENGTH: int = 8

# 登录失败锁定阈值（连续失败次数）
AUTH_MAX_LOGIN_ATTEMPTS: int = 5




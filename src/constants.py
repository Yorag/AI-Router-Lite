"""
统一常量管理模块

所有可配置的常量都应在此文件中定义，便于集中管理和维护
"""

# ==================== 应用信息 ====================

# 应用名称
APP_NAME: str = "AI-Router-Lite"

# 应用版本
APP_VERSION: str = "0.8.0"

# 应用描述
APP_DESCRIPTION: str = "轻量级 AI 聚合路由 + 管理面板"

# 模型所有者标识
MODEL_OWNED_BY: str = "ai-router-lite"


# ==================== 时区配置 ====================

# 默认时区偏移量（小时），用于日志记录、统计等时间处理
# 例如：8 表示 UTC+8（北京时间），0 表示 UTC，-5 表示 UTC-5（美东时间）
DEFAULT_TIMEZONE_OFFSET: int = 8


# ==================== 服务器默认配置 ====================

# 默认服务端口
DEFAULT_SERVER_PORT: int = 8000

# 默认服务主机
DEFAULT_SERVER_HOST: str = "0.0.0.0"



# ==================== 健康检测配置 ====================

# 健康检测跳过的时间阈值（小时）
# 如果模型在此时间内有活动记录（调用或测试），自动健康检测会跳过该模型
HEALTH_CHECK_SKIP_THRESHOLD_HOURS: float = 6.0

# 健康测试失败时的冷却时间（秒）
HEALTH_TEST_FAILURE_COOLDOWN_SECONDS: int = 60


# ==================== 熔断器冷却时间配置（秒） ====================

# 429 超频冷却时间
COOLDOWN_RATE_LIMITED: int = 180

# 5xx 服务器错误冷却时间
COOLDOWN_SERVER_ERROR: int = 600

# 超时冷却时间
COOLDOWN_TIMEOUT: int = 300

# 网络错误冷却时间
COOLDOWN_NETWORK_ERROR: int = 60

# 永久禁用标记（用于 401/403 鉴权失败、404 模型不存在）
COOLDOWN_PERMANENT: int = -1


# ==================== 日志系统配置 ====================

# 内存中保留的最大日志条数
LOG_MAX_MEMORY_ENTRIES: int = 1000

# 日志保留天数
LOG_RETENTION_DAYS: int = 15

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
API_KEY_SECRET_BYTES: int = 24


# ==================== HTTP 请求配置 ====================

# 管理 API 的 HTTP 超时时间（秒）
ADMIN_HTTP_TIMEOUT: float = 30.0

# 健康测试请求的 max_tokens
HEALTH_TEST_MAX_TOKENS: int = 10

# 健康测试请求的消息内容
HEALTH_TEST_MESSAGE: str = "hi"




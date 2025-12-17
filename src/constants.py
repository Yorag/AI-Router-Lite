"""
统一常量管理模块

所有可配置的常量都应在此文件中定义，便于集中管理和维护
"""

# ==================== 应用信息 ====================

# 应用名称
APP_NAME: str = "AI-Router-Lite"

# 应用版本
APP_VERSION: str = "0.7.0"

# 应用描述
APP_DESCRIPTION: str = "轻量级 AI 聚合路由 + 管理面板"

# 模型所有者标识
MODEL_OWNED_BY: str = "ai-router-lite"


# ==================== 服务器默认配置 ====================

# 默认服务端口
DEFAULT_SERVER_PORT: int = 8000

# 默认服务主机
DEFAULT_SERVER_HOST: str = "0.0.0.0"

# 配置文件路径
CONFIG_FILE_PATH: str = "config.json"


# ==================== 健康检测配置 ====================

# 健康检测跳过的时间阈值（小时）
# 如果模型在此时间内有活动记录（调用或测试），自动健康检测会跳过该模型
HEALTH_CHECK_SKIP_THRESHOLD_HOURS: float = 6.0

# 自动健康检测间隔（小时）
AUTO_HEALTH_CHECK_INTERVAL_HOURS: float = 6.0

# 健康测试失败时的冷却时间（秒）
HEALTH_TEST_FAILURE_COOLDOWN_SECONDS: int = 60


# ==================== 熔断器冷却时间配置（秒） ====================

# 429 超频冷却时间
COOLDOWN_RATE_LIMITED: int = 180

# 5xx 服务器错误冷却时间
COOLDOWN_SERVER_ERROR: int = 300

# 超时冷却时间
COOLDOWN_TIMEOUT: int = 120

# 网络错误冷却时间
COOLDOWN_NETWORK_ERROR: int = 20

# 永久禁用标记（用于 401/403 鉴权失败、404 模型不存在）
COOLDOWN_PERMANENT: int = -1


# ==================== 日志系统配置 ====================

# 日志存储目录
LOG_STORAGE_DIR: str = "data/logs"

# 内存中保留的最大日志条数
LOG_MAX_MEMORY_ENTRIES: int = 1000

# 单个日志文件最大大小（MB）
LOG_MAX_FILE_SIZE_MB: int = 1

# 日志保留天数
LOG_RETENTION_DAYS: int = 15

# 统计数据保存间隔（每多少条请求保存一次）
LOG_STATS_SAVE_INTERVAL: int = 10

# SSE 订阅队列大小
LOG_SUBSCRIBE_QUEUE_SIZE: int = 100

# 最近日志查询默认限制
LOG_RECENT_LIMIT_DEFAULT: int = 100

# 日期日志查询默认限制
LOG_DATE_LIMIT_DEFAULT: int = 1000

# 小时统计默认天数
LOG_HOURLY_STATS_DEFAULT_DAYS: int = 7


# ==================== 代理错误配置 ====================

# 代理错误消息最大长度（字符），超过将被截断
PROXY_ERROR_MESSAGE_MAX_LENGTH: int = 300


# ==================== 模型健康检测配置 ====================

# 模型健康检测结果存储路径
MODEL_HEALTH_STORAGE_PATH: str = "data/model_health.json"
MODEL_HEALTH_FILE: str = MODEL_HEALTH_STORAGE_PATH  # 别名


# ==================== Provider 模型元信息配置 ====================

# Provider 模型元信息存储路径
PROVIDER_MODELS_STORAGE_PATH: str = "data/provider_models.json"
PROVIDER_MODELS_FILE: str = PROVIDER_MODELS_STORAGE_PATH  # 别名


# ==================== 模型映射配置 ====================

# 模型映射存储路径
MODEL_MAPPINGS_STORAGE_PATH: str = "data/model_mappings.json"
MODEL_MAPPINGS_FILE: str = MODEL_MAPPINGS_STORAGE_PATH  # 别名


# ==================== API 密钥配置 ====================

# API 密钥存储路径
API_KEYS_STORAGE_PATH: str = "data/api_keys.json"

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


# ==================== 前端 Toast 通知时长配置（毫秒） ====================

# 信息/成功通知显示时长
TOAST_DURATION_DEFAULT: int = 2000

# 警告通知显示时长
TOAST_DURATION_WARNING: int = 4000

# 错误通知显示时长
TOAST_DURATION_ERROR: int = 5000


# ==================== 前端自动刷新配置 ====================

# 自动健康检测间隔（毫秒）
AUTO_HEALTH_CHECK_INTERVAL_MS: int = int(AUTO_HEALTH_CHECK_INTERVAL_HOURS * 60 * 60 * 1000)


# ==================== 持久化存储配置 ====================

# 缓冲保存间隔（秒）- 高频统计数据的定时保存间隔
STORAGE_BUFFER_INTERVAL_SECONDS: float = 300.0

# 是否在关闭时强制刷盘
STORAGE_FLUSH_ON_SHUTDOWN: bool = True
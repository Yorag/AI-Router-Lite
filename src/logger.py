"""
日志记录模块

负责记录和存储 API 请求日志，支持实时推送和历史查询
"""

import json
import time
import asyncio
from pathlib import Path
from typing import Optional, AsyncIterator
from dataclasses import dataclass, asdict
from datetime import datetime
from collections import deque
from enum import Enum

from .constants import (
    LOG_STORAGE_DIR,
    LOG_MAX_MEMORY_ENTRIES,
    LOG_MAX_FILE_SIZE_MB,
    LOG_RETENTION_DAYS,
    LOG_STATS_SAVE_INTERVAL,
    LOG_SUBSCRIBE_QUEUE_SIZE,
    LOG_RECENT_LIMIT_DEFAULT,
    LOG_DATE_LIMIT_DEFAULT,
)


class LogLevel(Enum):
    """日志级别"""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class RequestLog:
    """请求日志"""
    id: str
    timestamp: float
    level: str
    type: str  # request, response, error, system
    method: str
    path: str
    model: Optional[str] = None  # 用户请求的模型名
    provider: Optional[str] = None  # 实际使用的 Provider 名称
    actual_model: Optional[str] = None  # 实际使用的模型名（Provider 实际调用的模型）
    status_code: Optional[int] = None
    duration_ms: Optional[float] = None
    message: Optional[str] = None
    error: Optional[str] = None
    client_ip: Optional[str] = None
    api_key_id: Optional[str] = None
    api_key_name: Optional[str] = None  # API 密钥标签名
    request_tokens: Optional[int] = None
    response_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    
    def to_dict(self) -> dict:
        """转换为字典"""
        data = asdict(self)
        data["timestamp_str"] = datetime.fromtimestamp(self.timestamp).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        # 添加格式化的实际模型信息（Provider:Model格式）
        if self.provider and self.actual_model:
            data["actual_model_full"] = f"{self.provider}:{self.actual_model}"
        return data


class LogManager:
    """日志管理器"""
    
    def __init__(self,
                 storage_dir: str = LOG_STORAGE_DIR,
                 max_memory_logs: int = LOG_MAX_MEMORY_ENTRIES,
                 max_file_size_mb: int = LOG_MAX_FILE_SIZE_MB):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        self.max_memory_logs = max_memory_logs
        self.max_file_size_mb = max_file_size_mb
        
        # 内存中的日志缓存（用于实时查看）
        self._logs: deque[RequestLog] = deque(maxlen=max_memory_logs)
        
        # SSE 订阅者
        self._subscribers: list[asyncio.Queue] = []
        
        # 日志计数器
        self._log_counter = 0
        
        # 统计数据变更标记（用于判断是否需要保存）
        self._stats_dirty = False
        
        # 统计数据
        self._stats = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "total_tokens": 0,
            "hourly_requests": {},  # hour -> count
            "model_usage": {},  # model -> count
            "provider_usage": {},  # provider -> count
        }
        
        # 加载今天的统计数据
        self._load_today_stats()
        
        # 加载今天的日志到内存
        self._load_today_logs()
    
    def _get_log_file_path(self, date: Optional[str] = None) -> Path:
        """获取日志文件路径"""
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        return self.storage_dir / f"requests_{date}.jsonl"
    
    def _get_stats_file_path(self, date: Optional[str] = None) -> Path:
        """获取统计文件路径"""
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        return self.storage_dir / f"stats_{date}.json"
    
    def _load_today_stats(self) -> None:
        """加载今天的统计数据"""
        stats_file = self._get_stats_file_path()
        if stats_file.exists():
            try:
                with open(stats_file, "r", encoding="utf-8") as f:
                    self._stats = json.load(f)
            except Exception:
                pass
    
    def _load_today_logs(self) -> None:
        """加载今天的日志到内存"""
        log_file = self._get_log_file_path()
        if log_file.exists():
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            data = json.loads(line)
                            log_entry = RequestLog(
                                id=data.get("id", ""),
                                timestamp=data.get("timestamp", 0),
                                level=data.get("level", "info"),
                                type=data.get("type", ""),
                                method=data.get("method", ""),
                                path=data.get("path", ""),
                                model=data.get("model"),
                                provider=data.get("provider"),
                                actual_model=data.get("actual_model"),
                                status_code=data.get("status_code"),
                                duration_ms=data.get("duration_ms"),
                                message=data.get("message"),
                                error=data.get("error"),
                                client_ip=data.get("client_ip"),
                                api_key_id=data.get("api_key_id"),
                                api_key_name=data.get("api_key_name"),
                                request_tokens=data.get("request_tokens"),
                                response_tokens=data.get("response_tokens"),
                                total_tokens=data.get("total_tokens")
                            )
                            self._logs.append(log_entry)
            except Exception as e:
                print(f"[LogManager] 加载日志失败: {e}")
    
    def _save_stats(self, force: bool = False) -> None:
        """保存统计数据
        
        Args:
            force: 是否强制保存（忽略 dirty 标记）
        """
        if not force and not self._stats_dirty:
            return
            
        stats_file = self._get_stats_file_path()
        try:
            with open(stats_file, "w", encoding="utf-8") as f:
                json.dump(self._stats, f, indent=2, ensure_ascii=False)
            self._stats_dirty = False
        except Exception as e:
            print(f"[LogManager] 保存统计数据失败: {e}")
    
    def flush_stats(self) -> None:
        """强制保存统计数据到磁盘
        
        应在服务关闭时调用，确保所有统计数据被持久化
        """
        if self._stats_dirty:
            self._save_stats(force=True)
            print("[LogManager] 统计数据已保存")
    
    def _generate_log_id(self) -> str:
        """生成日志 ID"""
        self._log_counter += 1
        return f"log_{int(time.time() * 1000)}_{self._log_counter}"
    
    def log(self,
            level: LogLevel,
            log_type: str,
            method: str,
            path: str,
            model: Optional[str] = None,
            provider: Optional[str] = None,
            actual_model: Optional[str] = None,
            status_code: Optional[int] = None,
            duration_ms: Optional[float] = None,
            message: Optional[str] = None,
            error: Optional[str] = None,
            client_ip: Optional[str] = None,
            api_key_id: Optional[str] = None,
            api_key_name: Optional[str] = None,
            request_tokens: Optional[int] = None,
            response_tokens: Optional[int] = None,
            total_tokens: Optional[int] = None) -> RequestLog:
        """记录日志"""
        log_entry = RequestLog(
            id=self._generate_log_id(),
            timestamp=time.time(),
            level=level.value,
            type=log_type,
            method=method,
            path=path,
            model=model,
            provider=provider,
            actual_model=actual_model,
            status_code=status_code,
            duration_ms=duration_ms,
            message=message,
            error=error,
            client_ip=client_ip,
            api_key_id=api_key_id,
            api_key_name=api_key_name,
            request_tokens=request_tokens,
            response_tokens=response_tokens,
            total_tokens=total_tokens
        )
        
        # 添加到内存缓存
        self._logs.append(log_entry)
        
        # 写入文件
        self._write_to_file(log_entry)
        
        # 更新统计
        self._update_stats(log_entry)
        
        # 推送给订阅者
        self._notify_subscribers(log_entry)
        
        return log_entry
    
    def _write_to_file(self, log_entry: RequestLog) -> None:
        """写入日志文件"""
        try:
            log_file = self._get_log_file_path()
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"[LogManager] 写入日志失败: {e}")
    
    def _update_stats(self, log_entry: RequestLog) -> None:
        """更新统计数据
        
        注意：只在 response 或 error 类型的日志时更新统计，
        避免 request + response 两条日志导致重复计数。
        - response: 请求成功完成
        - error: 请求失败
        """
        if log_entry.type in ("response", "error"):
            self._stats["total_requests"] += 1
            
            if log_entry.status_code and 200 <= log_entry.status_code < 400:
                self._stats["successful_requests"] += 1
            elif log_entry.status_code and log_entry.status_code >= 400:
                self._stats["failed_requests"] += 1
            elif log_entry.type == "error":
                # error 类型但没有 status_code 的情况，也计入失败
                self._stats["failed_requests"] += 1
            
            # 小时统计
            hour = datetime.fromtimestamp(log_entry.timestamp).strftime("%H")
            self._stats["hourly_requests"][hour] = self._stats["hourly_requests"].get(hour, 0) + 1
            
            # 模型使用统计
            if log_entry.model:
                self._stats["model_usage"][log_entry.model] = \
                    self._stats["model_usage"].get(log_entry.model, 0) + 1
            
            # Provider 使用统计
            if log_entry.provider:
                self._stats["provider_usage"][log_entry.provider] = \
                    self._stats["provider_usage"].get(log_entry.provider, 0) + 1
            
            # Token 统计（只有 response 才有 token 信息）
            if log_entry.request_tokens:
                self._stats["total_tokens"] += log_entry.request_tokens
            if log_entry.response_tokens:
                self._stats["total_tokens"] += log_entry.response_tokens
            
            # 标记统计数据已变更
            self._stats_dirty = True
        
        # 定期保存统计
        if self._stats_dirty and self._stats["total_requests"] % LOG_STATS_SAVE_INTERVAL == 0:
            self._save_stats()
    
    def _notify_subscribers(self, log_entry: RequestLog) -> None:
        """通知所有订阅者"""
        dead_subscribers = []
        for queue in self._subscribers:
            try:
                queue.put_nowait(log_entry)
            except asyncio.QueueFull:
                dead_subscribers.append(queue)
        
        # 清理死亡的订阅者
        for queue in dead_subscribers:
            self._subscribers.remove(queue)
    
    async def subscribe(self) -> AsyncIterator[RequestLog]:
        """订阅日志流"""
        queue: asyncio.Queue = asyncio.Queue(maxsize=LOG_SUBSCRIBE_QUEUE_SIZE)
        self._subscribers.append(queue)
        
        try:
            while True:
                log_entry = await queue.get()
                yield log_entry
        finally:
            if queue in self._subscribers:
                self._subscribers.remove(queue)
    
    def get_recent_logs(self,
                        limit: int = LOG_RECENT_LIMIT_DEFAULT,
                        level: Optional[str] = None,
                        log_type: Optional[str] = None,
                        keyword: Optional[str] = None,
                        provider: Optional[str] = None) -> list[dict]:
        """获取最近的日志
        
        Args:
            limit: 返回日志数量限制
            level: 日志级别过滤
            log_type: 日志类型过滤
            keyword: 关键词过滤，在 message、model、provider、actual_model、error、api_key_name 字段中搜索
            provider: Provider 过滤
        """
        logs = list(self._logs)
        
        # 过滤
        if level:
            logs = [l for l in logs if l.level == level]
        if log_type:
            logs = [l for l in logs if l.type == log_type]
        if keyword:
            # 关键词过滤：在多个字段中搜索
            keyword_lower = keyword.lower()
            filtered_logs = []
            for l in logs:
                # 收集所有可搜索的字段
                searchable_fields = [
                    l.message or "",
                    l.model or "",
                    l.provider or "",
                    l.actual_model or "",
                    l.error or "",
                    l.api_key_name or ""
                ]
                combined_text = " ".join(searchable_fields).lower()
                if keyword_lower in combined_text:
                    filtered_logs.append(l)
            logs = filtered_logs
        if provider:
            logs = [l for l in logs if l.provider == provider]
        
        # 限制数量并按时间倒序
        logs = sorted(logs, key=lambda x: x.timestamp, reverse=True)[:limit]
        
        return [l.to_dict() for l in logs]
    
    def get_logs_by_date(self, date: str, limit: int = LOG_DATE_LIMIT_DEFAULT) -> list[dict]:
        """获取指定日期的日志"""
        log_file = self._get_log_file_path(date)
        logs = []
        
        if log_file.exists():
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            logs.append(json.loads(line))
                            if len(logs) >= limit:
                                break
            except Exception as e:
                print(f"[LogManager] 读取日志失败: {e}")
        
        return logs
    
    def get_stats(self, date: Optional[str] = None) -> dict:
        """获取统计数据"""
        if date is None:
            return self._stats.copy()
        
        stats_file = self._get_stats_file_path(date)
        if stats_file.exists():
            try:
                with open(stats_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        
        return {}
    
    def get_daily_stats(self, days: int = 7) -> list[dict]:
        """获取最近N天的每日统计数据
        
        Args:
            days: 天数，默认7天
            
        Returns:
            list[dict]: 每日统计列表，按日期升序排列
            [
                {
                    "date": "2023-10-27",
                    "total_requests": 100,
                    "successful_requests": 90,
                    "failed_requests": 10,
                    "total_tokens": 5000,
                    "model_usage": {...}
                },
                ...
            ]
        """
        from datetime import timedelta
        
        results = []
        now = datetime.now()
        
        # 遍历最近N天（包含今天）
        # 注意：reversed让结果按日期升序排列
        for i in reversed(range(days)):
            date_str = (now - timedelta(days=i)).strftime("%Y-%m-%d")
            stats = self.get_stats(date_str)
            
            if not stats:
                # 如果没有当天的统计文件，尝试从内存中的stats获取（如果是今天）
                if i == 0:
                    stats = self._stats.copy()
                else:
                    # 否则返回空统计
                    stats = {
                        "total_requests": 0,
                        "successful_requests": 0,
                        "failed_requests": 0,
                        "total_tokens": 0,
                        "hourly_requests": {},
                        "model_usage": {},
                        "provider_usage": {}
                    }
            
            # 添加日期字段
            daily_data = {
                "date": date_str,
                "total_requests": stats.get("total_requests", 0),
                "successful_requests": stats.get("successful_requests", 0),
                "failed_requests": stats.get("failed_requests", 0),
                "total_tokens": stats.get("total_tokens", 0),
                "model_usage": stats.get("model_usage", {})
            }
            results.append(daily_data)
            
        return results

    def clear_old_logs(self, keep_days: int = LOG_RETENTION_DAYS) -> int:
        """清理旧日志"""
        from datetime import timedelta
        
        cutoff = datetime.now() - timedelta(days=keep_days)
        deleted = 0
        
        for file in self.storage_dir.glob("*.jsonl"):
            try:
                # 从文件名提取日期
                date_str = file.stem.split("_")[-1]
                file_date = datetime.strptime(date_str, "%Y-%m-%d")
                
                if file_date < cutoff:
                    file.unlink()
                    deleted += 1
            except Exception:
                pass
        
        return deleted


# 全局实例
log_manager = LogManager()
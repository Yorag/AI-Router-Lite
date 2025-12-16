"""
统一存储管理模块

提供两种存储策略：
1. 即时落盘 (Immediate) - 用于配置变更等低频但关键的操作
2. 缓冲落盘 (Buffered) - 用于高频统计数据，定期批量写入

包含：
- BaseStorageManager: 存储管理器基类
- PersistenceManager: 全局持久化管理器，负责定时保存和优雅关闭
"""

import json
import time
import signal
import atexit
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Any
import filelock

from .constants import (
    STORAGE_BUFFER_INTERVAL_SECONDS,
    STORAGE_FLUSH_ON_SHUTDOWN,
)


class BaseStorageManager(ABC):
    """
    存储管理器基类
    
    提供两种保存模式：
    - save(immediate=True): 立即写入磁盘，用于配置变更
    - save(immediate=False): 检查是否需要保存（基于脏标记和时间间隔）
    
    子类需要实现：
    - _do_load(): 加载数据
    - _do_save(): 保存数据
    - _get_default_data(): 返回默认数据结构
    """
    
    def __init__(
        self,
        data_path: str,
        save_interval: float = STORAGE_BUFFER_INTERVAL_SECONDS,
        use_file_lock: bool = True
    ):
        """
        初始化存储管理器
        
        Args:
            data_path: 数据文件路径
            save_interval: 缓冲保存间隔（秒）
            use_file_lock: 是否使用文件锁
        """
        self.data_path = Path(data_path)
        self.lock_path = self.data_path.with_suffix(".json.lock")
        self.save_interval = save_interval
        self.use_file_lock = use_file_lock
        
        # 状态标记
        self._dirty = False
        self._last_save_time: float = 0.0
        self._loaded = False
        
        # 线程安全锁
        self._lock = threading.RLock()
    
    def _ensure_file_exists(self) -> None:
        """确保数据文件和目录存在"""
        if not self.data_path.exists():
            self.data_path.parent.mkdir(parents=True, exist_ok=True)
            self._write_to_file(self._get_default_data())
    
    def _read_from_file(self) -> dict:
        """从文件读取数据"""
        self._ensure_file_exists()
        try:
            with open(self.data_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return self._get_default_data()
    
    def _write_to_file(self, data: dict) -> None:
        """写入数据到文件（带可选文件锁）"""
        self.data_path.parent.mkdir(parents=True, exist_ok=True)
        
        if self.use_file_lock:
            lock = filelock.FileLock(self.lock_path, timeout=10)
            with lock:
                self._do_write(data)
        else:
            self._do_write(data)
    
    def _do_write(self, data: dict) -> None:
        """实际执行写入"""
        with open(self.data_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    @abstractmethod
    def _get_default_data(self) -> dict:
        """返回默认数据结构（子类实现）"""
        pass
    
    @abstractmethod
    def _do_load(self) -> None:
        """加载数据到内存（子类实现）"""
        pass
    
    @abstractmethod
    def _do_save(self) -> None:
        """保存内存数据到文件（子类实现）"""
        pass
    
    def _ensure_loaded(self) -> None:
        """确保数据已加载"""
        if not self._loaded:
            self.load()
    
    def load(self) -> None:
        """加载数据"""
        with self._lock:
            self._do_load()
            self._loaded = True
    
    def mark_dirty(self) -> None:
        """标记数据已修改（需要保存）"""
        self._dirty = True
    
    def save(self, immediate: bool = False) -> bool:
        """
        保存数据
        
        Args:
            immediate: True=立即写盘; False=检查间隔决定是否写盘
            
        Returns:
            是否执行了保存操作
        """
        with self._lock:
            if not self._dirty and not immediate:
                return False
            
            current_time = time.time()
            
            # 缓冲模式：检查时间间隔
            if not immediate:
                if current_time - self._last_save_time < self.save_interval:
                    return False
            
            # 执行保存
            try:
                self._do_save()
                self._dirty = False
                self._last_save_time = current_time
                return True
            except Exception as e:
                print(f"[Storage] 保存失败 ({self.data_path}): {e}")
                return False
    
    def flush(self) -> bool:
        """
        强制刷盘（用于关闭时）
        
        Returns:
            是否执行了保存操作
        """
        with self._lock:
            if not self._dirty:
                return False
            
            try:
                self._do_save()
                self._dirty = False
                self._last_save_time = time.time()
                print(f"[Storage] 已刷盘: {self.data_path.name}")
                return True
            except Exception as e:
                print(f"[Storage] 刷盘失败 ({self.data_path}): {e}")
                return False
    
    @property
    def is_dirty(self) -> bool:
        """检查是否有未保存的数据"""
        return self._dirty


class PersistenceManager:
    """
    全局持久化管理器（单例）
    
    功能：
    1. 注册所有存储管理器
    2. 定时触发缓冲保存
    3. 监听关闭信号，执行优雅关闭
    """
    
    _instance: Optional["PersistenceManager"] = None
    _initialized: bool = False
    
    def __new__(cls) -> "PersistenceManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if PersistenceManager._initialized:
            return
        
        self._managers: list[BaseStorageManager] = []
        self._timer: Optional[threading.Timer] = None
        self._running = False
        self._shutdown_registered = False
        
        PersistenceManager._initialized = True
    
    def register(self, manager: BaseStorageManager) -> None:
        """
        注册存储管理器
        
        Args:
            manager: 存储管理器实例
        """
        if manager not in self._managers:
            self._managers.append(manager)
            print(f"[Persistence] 已注册: {manager.data_path.name}")
    
    def unregister(self, manager: BaseStorageManager) -> None:
        """
        注销存储管理器
        
        Args:
            manager: 存储管理器实例
        """
        if manager in self._managers:
            self._managers.remove(manager)
    
    def start(self, interval: float = STORAGE_BUFFER_INTERVAL_SECONDS) -> None:
        """
        启动定时保存任务
        
        Args:
            interval: 保存间隔（秒）
        """
        if self._running:
            return
        
        self._running = True
        self._schedule_next_tick(interval)
        
        # 注册关闭处理
        if STORAGE_FLUSH_ON_SHUTDOWN and not self._shutdown_registered:
            self._register_shutdown_handlers()
            self._shutdown_registered = True
        
        print(f"[Persistence] 定时保存已启动，间隔 {interval} 秒")
    
    def stop(self) -> None:
        """停止定时保存任务"""
        self._running = False
        if self._timer:
            self._timer.cancel()
            self._timer = None
        print("[Persistence] 定时保存已停止")
    
    def _schedule_next_tick(self, interval: float) -> None:
        """调度下一次保存"""
        if not self._running:
            return
        
        self._timer = threading.Timer(interval, self._tick, args=[interval])
        self._timer.daemon = True
        self._timer.start()
    
    def _tick(self, interval: float) -> None:
        """定时保存触发"""
        if not self._running:
            return
        
        saved_count = 0
        for manager in self._managers:
            try:
                if manager.save(immediate=False):
                    saved_count += 1
            except Exception as e:
                print(f"[Persistence] 定时保存出错: {e}")
        
        if saved_count > 0:
            print(f"[Persistence] 定时保存完成，{saved_count} 个管理器已保存")
        
        # 调度下一次
        self._schedule_next_tick(interval)
    
    def _register_shutdown_handlers(self) -> None:
        """注册关闭处理函数"""
        # 注册 atexit
        atexit.register(self.shutdown)
        
        # 注册信号处理（仅在主线程中）
        try:
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)
        except ValueError:
            # 非主线程中无法设置信号处理
            pass
    
    def _signal_handler(self, signum: int, frame: Any) -> None:
        """信号处理函数"""
        print(f"\n[Persistence] 收到信号 {signum}，正在保存数据...")
        self.shutdown()
        # 重新抛出信号以便正常退出
        signal.signal(signum, signal.SIG_DFL)
        signal.raise_signal(signum)
    
    def shutdown(self) -> None:
        """
        优雅关闭：停止定时任务并刷盘所有数据
        """
        self.stop()
        
        flushed_count = 0
        for manager in self._managers:
            try:
                if manager.flush():
                    flushed_count += 1
            except Exception as e:
                print(f"[Persistence] 关闭时保存出错: {e}")
        
        if flushed_count > 0:
            print(f"[Persistence] 关闭完成，{flushed_count} 个管理器已刷盘")
    
    def tick_now(self) -> int:
        """
        立即触发一次保存检查（用于测试或手动触发）
        
        Returns:
            保存的管理器数量
        """
        saved_count = 0
        for manager in self._managers:
            try:
                if manager.save(immediate=False):
                    saved_count += 1
            except Exception as e:
                print(f"[Persistence] 手动保存出错: {e}")
        return saved_count
    
    def flush_all(self) -> int:
        """
        强制刷盘所有管理器
        
        Returns:
            刷盘的管理器数量
        """
        flushed_count = 0
        for manager in self._managers:
            try:
                if manager.flush():
                    flushed_count += 1
            except Exception as e:
                print(f"[Persistence] 刷盘出错: {e}")
        return flushed_count
    
    def get_status(self) -> dict:
        """
        获取持久化状态
        
        Returns:
            状态字典
        """
        return {
            "running": self._running,
            "managers": [
                {
                    "name": m.data_path.name,
                    "dirty": m.is_dirty,
                    "last_save": m._last_save_time
                }
                for m in self._managers
            ]
        }


# 全局单例
persistence_manager = PersistenceManager()
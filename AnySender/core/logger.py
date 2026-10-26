import json
import logging
import logging.handlers
import os
import threading
from collections import deque
from datetime import datetime
from itertools import count
from typing import List, Optional

import yaml

from .event_bus import EventBus

LOG_RECORD_ATTRS = {
    "task_name",
    "plugin_name",
    "duration_ms",
    "detail",
    "retryable",
    "artifacts",
    "event",
    "run_id",
    "dry_run",
    "skipped",
}

MAX_RING = 500
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class StructuredFormatter(logging.Formatter):
    def __init__(self, fmt_type: str = "json"):
        super().__init__()
        self.fmt_type = fmt_type

    def format(self, record: logging.LogRecord) -> str:
        if self.fmt_type == "json":
            payload = {
                "ts": datetime.fromtimestamp(record.created).astimezone().isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
            }
            for attr in LOG_RECORD_ATTRS:
                val = getattr(record, attr, None)
                if val is not None:
                    payload[attr] = val
            if record.exc_info and record.exc_info[1]:
                payload["exception"] = str(record.exc_info[1])
            return json.dumps(payload, ensure_ascii=False, default=str)
        ts = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        return f"[{ts}] [{record.levelname}] [{record.name}] {record.getMessage()}"


class RingHandler(logging.Handler):
    """内存日志环 —— Web SSE 的唯一数据源，带自增 seq 供断线续传。"""

    def __init__(self, maxlen: int = MAX_RING):
        super().__init__()
        self._ring = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._seq = count(1)

    def emit(self, record: logging.LogRecord):
        try:
            payload = {
                "seq": next(self._seq),
                "ts": datetime.fromtimestamp(record.created).astimezone().isoformat(),
                "level": record.levelname,
                "msg": record.getMessage(),
            }
            for attr in LOG_RECORD_ATTRS:
                val = getattr(record, attr, None)
                if val is not None:
                    payload[attr] = val
            with self._lock:
                self._ring.append(payload)
        except Exception:
            pass

    def recent(self, since_seq: int = 0, limit: int = MAX_RING) -> List[dict]:
        with self._lock:
            items = list(self._ring)
        return [item for item in items if item["seq"] > int(since_seq)][-int(limit):]

    def latest_seq(self) -> int:
        with self._lock:
            return self._ring[-1]["seq"] if self._ring else 0


class Logger:
    def __init__(
        self,
        event_bus: EventBus,
        config_path: str = "config/base.yaml",
        log_dir: str = None,
    ):
        self._event_bus = event_bus
        self._logger = logging.getLogger("AnySender")
        self._logger.setLevel(logging.DEBUG)
        self._ring_handler = RingHandler(MAX_RING)
        # 兼容旧代码：外部只读访问 _ring 时拿到 handler，而不是一份永远为空的 deque
        self._ring = self._ring_handler
        self._setup_handlers(config_path, log_dir)
        self._subscribe_events()

    @property
    def log_dir(self) -> str:
        return self._log_dir

    def _read_level(self, config_path: str) -> int:
        try:
            if os.path.isfile(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                level = str(
                    (data.get("logging") or {}).get("level", "INFO")
                ).upper()
                return getattr(logging, level, logging.INFO)
        except Exception:
            pass
        return logging.INFO

    def _setup_handlers(self, config_path: str, log_dir: Optional[str]):
        self._log_dir = os.path.abspath(
            log_dir
            if log_dir
            else os.path.join(_PROJECT_ROOT, "logs")
        )
        os.makedirs(self._log_dir, exist_ok=True)

        # 清理同一进程内重复创建的处理器（测试/多次实例化时避免重复输出）
        for handler in list(self._logger.handlers):
            if getattr(handler, "_anysender", False):
                self._logger.removeHandler(handler)
                try:
                    handler.close()
                except Exception:
                    pass

        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(self._read_level(config_path))
        stream_handler.setFormatter(StructuredFormatter("text"))
        stream_handler._anysender = True
        self._logger.addHandler(stream_handler)

        file_handler = logging.handlers.RotatingFileHandler(
            os.path.join(self._log_dir, "anySender.log"),
            maxBytes=10 * 1024 * 1024,
            backupCount=30,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(StructuredFormatter("json"))
        file_handler._anysender = True
        self._logger.addHandler(file_handler)

        error_handler = logging.handlers.RotatingFileHandler(
            os.path.join(self._log_dir, "errors.log"),
            maxBytes=10 * 1024 * 1024,
            backupCount=30,
            encoding="utf-8",
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(StructuredFormatter("json"))
        error_handler._anysender = True
        self._logger.addHandler(error_handler)

        self._ring_handler.setLevel(logging.DEBUG)
        self._ring_handler._anysender = True
        self._logger.addHandler(self._ring_handler)

    def recent(self, since_seq: int = 0, limit: int = MAX_RING) -> List[dict]:
        return self._ring_handler.recent(since_seq, limit)

    def latest_seq(self) -> int:
        return self._ring_handler.latest_seq()

    def _subscribe_events(self):
        self._event_bus.subscribe("task_completed", self._on_task_completed)
        self._event_bus.subscribe("task_failed", self._on_task_failed)
        self._event_bus.subscribe("task_skipped", self._on_task_skipped)
        self._event_bus.subscribe("plugin_health_issue", self._on_health_issue)
        self._event_bus.subscribe("plugin_health_restored", self._on_health_restored)
        self._event_bus.subscribe("plugin_loaded", self._on_plugin_loaded)
        self._event_bus.subscribe("plugin_unloaded", self._on_plugin_unloaded)

    def _on_task_completed(self, **data):
        self.info("任务完成", extra={"event": "task_completed", **data})

    def _on_task_failed(self, **data):
        self.error("任务失败", extra={"event": "task_failed", **data})

    def _on_task_skipped(self, **data):
        self.warning("任务跳过", extra={"event": "task_skipped", **data})

    def _on_health_issue(self, **data):
        self.warning("插件健康异常", extra={"event": "plugin_health_issue", **data})

    def _on_health_restored(self, **data):
        self.info("插件健康恢复", extra={"event": "plugin_health_restored", **data})

    def _on_plugin_loaded(self, **data):
        self.info(
            f"插件已加载: {data.get('plugin_name', '?')}",
            extra={"event": "plugin_loaded", **data},
        )

    def _on_plugin_unloaded(self, **data):
        self.info(
            f"插件已卸载: {data.get('plugin_name', '?')}",
            extra={"event": "plugin_unloaded", **data},
        )

    def debug(self, msg: str, extra: Optional[dict] = None):
        self._logger.debug(msg, extra=extra or {})

    def info(self, msg: str, extra: Optional[dict] = None):
        self._logger.info(msg, extra=extra or {})

    def warning(self, msg: str, extra: Optional[dict] = None):
        self._logger.warning(msg, extra=extra or {})

    def error(self, msg: str, extra: Optional[dict] = None):
        self._logger.error(msg, extra=extra or {})

    def close(self) -> None:
        """释放文件句柄（测试/重启时避免 Windows 下无法删除日志目录）。"""
        for handler in list(self._logger.handlers):
            if getattr(handler, "_anysender", False):
                self._logger.removeHandler(handler)
                try:
                    handler.close()
                except Exception:
                    pass

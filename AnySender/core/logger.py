import json
import logging
import logging.handlers
import os
from datetime import datetime, timezone as tz
from typing import Optional

from .event_bus import EventBus

LOG_RECORD_ATTRS = {
    "task_name", "plugin_name", "duration_ms", "detail",
    "retryable", "artifacts", "event",
}


class StructuredFormatter(logging.Formatter):
    def __init__(self, fmt_type: str = "json"):
        super().__init__()
        self.fmt_type = fmt_type

    def format(self, record: logging.LogRecord) -> str:
        if self.fmt_type == "json":
            payload = {
                "ts": datetime.fromtimestamp(record.created, tz=tz.utc).isoformat(),
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
            return json.dumps(payload, ensure_ascii=False)
        else:
            ts = datetime.fromtimestamp(record.created, tz=tz.utc).strftime("%Y-%m-%d %H:%M:%S")
            return f"[{ts}] [{record.levelname}] [{record.name}] {record.getMessage()}"


class Logger:
    def __init__(self, event_bus: EventBus, config_path: str = "config/base.yaml"):
        self._event_bus = event_bus
        self._logger = logging.getLogger("AnySender")
        self._logger.setLevel(logging.DEBUG)
        self._setup_handlers()
        self._subscribe_events()

    def _setup_handlers(self):
        log_dir = "logs"
        os.makedirs(log_dir, exist_ok=True)

        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(logging.INFO)
        stream_handler.setFormatter(StructuredFormatter("text"))
        self._logger.addHandler(stream_handler)

        file_handler = logging.handlers.RotatingFileHandler(
            os.path.join(log_dir, "anySender.log"),
            maxBytes=10 * 1024 * 1024,
            backupCount=30,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(StructuredFormatter("json"))
        self._logger.addHandler(file_handler)

        error_handler = logging.handlers.RotatingFileHandler(
            os.path.join(log_dir, "errors.log"),
            maxBytes=10 * 1024 * 1024,
            backupCount=30,
            encoding="utf-8",
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(StructuredFormatter("json"))
        self._logger.addHandler(error_handler)

    def _subscribe_events(self):
        self._event_bus.subscribe("task_completed", self._on_task_completed)
        self._event_bus.subscribe("task_failed", self._on_task_failed)
        self._event_bus.subscribe("task_skipped", self._on_task_skipped)
        self._event_bus.subscribe("plugin_health_issue", self._on_health_issue)
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

    def _on_plugin_loaded(self, **data):
        self.info(f"插件已加载: {data.get('plugin_name', '?')}", extra={"event": "plugin_loaded", **data})

    def _on_plugin_unloaded(self, **data):
        self.info(f"插件已卸载: {data.get('plugin_name', '?')}", extra={"event": "plugin_unloaded", **data})

    def debug(self, msg: str, extra: Optional[dict] = None):
        self._logger.debug(msg, extra=extra or {})

    def info(self, msg: str, extra: Optional[dict] = None):
        self._logger.info(msg, extra=extra or {})

    def warning(self, msg: str, extra: Optional[dict] = None):
        self._logger.warning(msg, extra=extra or {})

    def error(self, msg: str, extra: Optional[dict] = None):
        self._logger.error(msg, extra=extra or {})

import os
import threading
import time
from typing import Optional

from .event_bus import EventBus
from .plugin_manager import PluginManager


class Watchdog:
    def __init__(
        self,
        event_bus: EventBus,
        plugin_manager: PluginManager,
        config_dir: str = "config",
    ):
        self._event_bus = event_bus
        self._plugin_manager = plugin_manager
        self._config_dir = os.path.abspath(config_dir)
        self._config_mtimes: dict = {}
        self._health_interval = 30
        self._health_state: dict = {}
        self._shutdown_flag = threading.Event()
        self._watcher_thread: Optional[threading.Thread] = None
        self._health_thread: Optional[threading.Thread] = None
        self._reload_timer: Optional[threading.Timer] = None
        self._reload_delay = 300

    def _scan_mtimes(self) -> dict:
        result = {}
        for root, _, files in os.walk(self._config_dir):
            for f in files:
                if f.endswith((".yaml", ".yml", ".json")):
                    full = os.path.join(root, f)
                    try:
                        result[full] = os.path.getmtime(full)
                    except OSError:
                        pass
        return result

    def _watcher_loop(self):
        self._config_mtimes = self._scan_mtimes()
        while not self._shutdown_flag.wait(timeout=2.0):
            current = self._scan_mtimes()
            changed = False
            for path, mtime in current.items():
                if path not in self._config_mtimes or self._config_mtimes.get(path) != mtime:
                    changed = True
                    break
            for path in self._config_mtimes:
                if path not in current:
                    changed = True
                    break
            self._config_mtimes = current
            if changed:
                self._on_config_change()

    def _on_config_change(self):
        if self._reload_timer is not None:
            self._reload_timer.cancel()
        self._reload_timer = threading.Timer(self._reload_delay, self._trigger_reload)
        self._reload_timer.start()

    def _trigger_reload(self):
        # 注意：目前没有订阅方，热重载是后续批次的工作（见 Bug 清单 P1-1）。
        self._event_bus.emit("config_changed")

    def _health_loop(self):
        while not self._shutdown_flag.wait(timeout=self._health_interval):
            results = self._plugin_manager.health_check_all()
            for name, (ok, detail) in results.items():
                previous = self._health_state.get(name)
                self._health_state[name] = ok
                # 只在状态翻转时发事件，避免每 30s 刷一条健康异常
                if not ok and previous is not False:
                    self._event_bus.emit(
                        "plugin_health_issue", plugin_name=name, detail=detail
                    )
                elif ok and previous is False:
                    self._event_bus.emit(
                        "plugin_health_restored",
                        plugin_name=name,
                        detail="健康检查已恢复",
                    )

    def start(self, health_interval: int = 30) -> None:
        self._health_interval = max(5, int(health_interval))
        self._watcher_thread = threading.Thread(target=self._watcher_loop, daemon=True)
        self._health_thread = threading.Thread(target=self._health_loop, daemon=True)
        self._watcher_thread.start()
        self._health_thread.start()

    def stop(self) -> None:
        self._shutdown_flag.set()
        if self._reload_timer:
            self._reload_timer.cancel()
        if self._watcher_thread:
            self._watcher_thread.join(timeout=5)
        if self._health_thread:
            self._health_thread.join(timeout=5)

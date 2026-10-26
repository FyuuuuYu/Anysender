import importlib
import os
import sys
from typing import Dict, List, Optional, Tuple

from .event_bus import EventBus
from .plugin_interface import SenderPlugin
from .exceptions import PluginLoadError

BUILTIN_PLUGINS_DIR = "plugins"
CUSTOM_PLUGINS_DIR = "custom_plugins"
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class PluginManager:
    def __init__(
        self,
        plugins_dir: str = BUILTIN_PLUGINS_DIR,
        custom_dir: str = CUSTOM_PLUGINS_DIR,
        event_bus: Optional[EventBus] = None,
        project_root: str = None,
    ):
        root = os.path.abspath(project_root or _PROJECT_ROOT)
        self._plugins_dir = self._abs(root, plugins_dir)
        self._custom_dir = self._abs(root, custom_dir)
        self._event_bus = event_bus
        self._plugins: Dict[str, SenderPlugin] = {}
        self._plugin_configs: Dict[str, dict] = {}
        self._discovered: List[str] = []
        self._discovered_sources: Dict[str, str] = {}

    @staticmethod
    def _abs(root: str, path: str) -> str:
        return os.path.abspath(path if os.path.isabs(path) else os.path.join(root, path))

    def _scan_plugin_dir(self, dir_path: str) -> List[str]:
        names = []
        if not os.path.isdir(dir_path):
            return names
        for entry in os.listdir(dir_path):
            full = os.path.join(dir_path, entry)
            if (
                os.path.isdir(full)
                and not entry.startswith("_")
                and not entry.startswith(".")
                and os.path.isfile(os.path.join(full, "plugin.py"))
            ):
                names.append(entry)
        return names

    def discover(self) -> List[str]:
        self._discovered = []
        self._discovered_sources = {}

        for name in self._scan_plugin_dir(self._custom_dir):
            self._discovered.append(name)
            self._discovered_sources[name] = self._custom_dir

        for name in self._scan_plugin_dir(self._plugins_dir):
            if name not in self._discovered_sources:
                self._discovered.append(name)
                self._discovered_sources[name] = self._plugins_dir

        return list(self._discovered)

    def _module_prefix(self, source_dir: str) -> str:
        parent = os.path.dirname(source_dir)
        if parent not in sys.path:
            sys.path.insert(0, parent)
        return os.path.basename(source_dir)

    def load(self, name: str, config: dict) -> SenderPlugin:
        if name in self._plugins:
            return self._plugins[name]

        source = self._discovered_sources.get(name)
        if source is None:
            if not self._discovered:
                self.discover()
            source = self._discovered_sources.get(name, self._plugins_dir)

        module_path = f"{self._module_prefix(source)}.{name}.plugin"
        try:
            module = importlib.import_module(module_path)
        except Exception as exc:
            raise PluginLoadError(
                f"加载插件 [{name}] 失败（{module_path}）: {exc}"
            ) from exc

        plugin_class = self._find_plugin_class(module, name)
        instance = plugin_class()

        # 关键：先校验，再注册。校验失败不能留下“幽灵插件”。
        ok, detail = instance.validate_config(config)
        if not ok:
            raise PluginLoadError(f"插件 [{name}] 配置校验失败: {detail}")

        instance.on_load()
        self._plugins[name] = instance
        self._plugin_configs[name] = config

        if self._event_bus:
            self._event_bus.emit(
                "plugin_loaded", plugin_name=name, version=instance.get_version()
            )

        return instance

    def _find_plugin_class(self, module, name: str) -> type:
        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            if (
                isinstance(obj, type)
                and issubclass(obj, SenderPlugin)
                and obj is not SenderPlugin
            ):
                return obj
        raise PluginLoadError(f"插件 [{name}] 的 plugin.py 中未找到 SenderPlugin 子类")

    def unload(self, name: str) -> None:
        if name not in self._plugins:
            return
        try:
            self._plugins[name].on_unload()
        except Exception:
            pass
        del self._plugins[name]
        self._plugin_configs.pop(name, None)
        if self._event_bus:
            self._event_bus.emit("plugin_unloaded", plugin_name=name)

    def unload_all(self) -> None:
        for name in list(self._plugins.keys()):
            self.unload(name)

    def get(self, name: str) -> Optional[SenderPlugin]:
        return self._plugins.get(name)

    def get_config(self, name: str) -> dict:
        return self._plugin_configs.get(name, {})

    def loaded_names(self) -> List[str]:
        return list(self._plugins.keys())

    def discovered_names(self) -> List[str]:
        return list(self._discovered)

    def health_check_all(self) -> Dict[str, Tuple[bool, str]]:
        results: Dict[str, Tuple[bool, str]] = {}
        for name, plugin in self._plugins.items():
            try:
                outcome = plugin.health_check()
            except Exception as exc:
                results[name] = (False, f"健康检查异常: {exc}")
                continue
            if isinstance(outcome, tuple):
                ok, detail = outcome
            else:
                ok, detail = bool(outcome), ""
            results[name] = (ok, str(detail))
        return results

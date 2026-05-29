import importlib
import os
from typing import Dict, List, Optional, Tuple

from .event_bus import EventBus
from .plugin_interface import SenderPlugin
from .exceptions import PluginLoadError

BUILTIN_PLUGINS_DIR = "plugins"
CUSTOM_PLUGINS_DIR = "custom_plugins"


class PluginManager:
    def __init__(
        self,
        plugins_dir: str = BUILTIN_PLUGINS_DIR,
        custom_dir: str = CUSTOM_PLUGINS_DIR,
        event_bus: Optional[EventBus] = None,
    ):
        self._plugins_dir = plugins_dir
        self._custom_dir = custom_dir
        self._event_bus = event_bus
        self._plugins: Dict[str, SenderPlugin] = {}
        self._plugin_configs: Dict[str, dict] = {}
        self._discovered: List[str] = []
        self._discovered_sources: Dict[str, str] = {}

    def _scan_plugin_dir(self, dir_path: str) -> List[str]:
        names = []
        base = os.path.join(dir_path)
        if not os.path.isdir(base):
            return names
        for entry in os.listdir(base):
            full = os.path.join(base, entry)
            if os.path.isdir(full) and not entry.startswith("_") and not entry.startswith("."):
                if os.path.isfile(os.path.join(full, "plugin.py")):
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

    def load(self, name: str, config: dict) -> SenderPlugin:
        if name in self._plugins:
            return self._plugins[name]

        source = self._discovered_sources.get(name, self._plugins_dir)
        module_path = f"{source.replace('/', '.')}.{name}.plugin"
        try:
            module = importlib.import_module(module_path)
        except Exception as e:
            raise PluginLoadError(f"加载插件 [{name}] 失败: {e}")

        plugin_class = self._find_plugin_class(module, name)
        instance = plugin_class()
        instance.on_load()
        self._plugins[name] = instance
        self._plugin_configs[name] = config

        ok, detail = instance.validate_config(config)
        if not ok:
            raise PluginLoadError(f"插件 [{name}] 配置校验失败: {detail}")

        if self._event_bus:
            self._event_bus.emit("plugin_loaded", plugin_name=name, version=instance.get_version())

        return instance

    def _find_plugin_class(self, module, name: str) -> type:
        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            if isinstance(obj, type) and issubclass(obj, SenderPlugin) and obj is not SenderPlugin:
                return obj
        raise PluginLoadError(f"插件 [{name}] 的 plugin.py 中未找到 SenderPlugin 子类")

    def unload(self, name: str) -> None:
        if name not in self._plugins:
            return
        self._plugins[name].on_unload()
        del self._plugins[name]
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
        results = {}
        for name, plugin in self._plugins.items():
            ok, detail = plugin.health_check()
            results[name] = (ok, detail)
        return results

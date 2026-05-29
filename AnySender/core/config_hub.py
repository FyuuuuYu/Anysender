import os
import yaml
from typing import List


class ConfigHub:
    def __init__(self, config_dir: str = "config", presets_dir: str = "presets"):
        self._config_dir = config_dir
        self._presets_dir = presets_dir

    def _load_yaml(self, path: str) -> dict:
        if not os.path.isfile(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _deep_merge(self, base: dict, override: dict) -> dict:
        result = dict(base)
        for key, val in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(val, dict):
                result[key] = self._deep_merge(result[key], val)
            else:
                result[key] = val
        return result

    def load_core_config(self) -> dict:
        preset = self._load_yaml(os.path.join(self._presets_dir, "base.yaml"))
        user = self._load_yaml(os.path.join(self._config_dir, "base.yaml"))
        return self._deep_merge(preset, user)

    def load_tasks(self) -> List[dict]:
        preset = self._load_yaml(os.path.join(self._presets_dir, "tasks.yaml"))
        user = self._load_yaml(os.path.join(self._config_dir, "tasks.yaml"))
        merged = self._deep_merge(preset, user)
        return merged.get("tasks", [])

    def load_plugin_config(self, plugin_name: str) -> dict:
        preset = self._load_yaml(os.path.join(self._presets_dir, "plugins", f"{plugin_name}.yaml"))
        user = self._load_yaml(os.path.join(self._config_dir, "plugins", f"{plugin_name}.yaml"))
        return self._deep_merge(preset, user)

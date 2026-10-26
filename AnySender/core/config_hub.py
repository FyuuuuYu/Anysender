"""配置中心 —— 预设 → 本地 → 代码默认 的三级合并。

路径一律基于项目根解析，避免从任意 cwd 启动时读到错的配置。
"""

import copy
import os

import yaml

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ConfigValidationError(Exception):
    """配置结构不合法（不是 YAML 语法错误）。"""


def _deep_merge(base: dict, override: dict) -> dict:
    result = copy.deepcopy(base or {})
    for key, value in (override or {}).items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


class ConfigHub:
    def __init__(
        self,
        config_dir: str = "config",
        presets_dir: str = "presets",
        project_root: str = None,
    ) -> None:
        self._project_root = os.path.abspath(project_root or _PROJECT_ROOT)
        self._config_dir = self._resolve(config_dir)
        self._presets_dir = self._resolve(presets_dir)

    @property
    def project_root(self) -> str:
        return self._project_root

    def _resolve(self, path: str) -> str:
        if os.path.isabs(path):
            return os.path.abspath(path)
        return os.path.abspath(os.path.join(self._project_root, path))

    @staticmethod
    def _read_yaml(path: str) -> dict:
        if not os.path.isfile(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except yaml.YAMLError as exc:
            raise ConfigValidationError(f"YAML 解析失败: {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ConfigValidationError(f"配置文件根节点必须是映射: {path}")
        return data

    def load(self, config_name: str, preset_name: str = None) -> dict:
        preset_name = preset_name or config_name
        preset = self._read_yaml(os.path.join(self._presets_dir, f"{preset_name}.yaml"))
        local = self._read_yaml(os.path.join(self._config_dir, f"{config_name}.yaml"))
        return _deep_merge(preset, local)

    def load_core_config(self) -> dict:
        return self.load("base")

    def load_tasks(self) -> list:
        data = self._read_yaml(os.path.join(self._config_dir, "tasks.yaml"))
        tasks = data.get("tasks", [])
        if not isinstance(tasks, list):
            raise ConfigValidationError("tasks.yaml 的 tasks 必须是列表")
        return tasks

    def load_plugin_config(self, plugin_name: str) -> dict:
        return self.load(f"plugins/{plugin_name}")

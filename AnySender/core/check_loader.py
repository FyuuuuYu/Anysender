"""
Check 发现与加载引擎

发现策略（按优先级，高到低）:
    1. user_checks/   — 用户自定义校验，覆盖同名内置
    2. checks/        — 内置校验模块（随项目分发）

每个 Python 文件中的 Check 子类会被自动发现并注册。
文件扫描异常被隔离——单个文件出错不影响其他文件加载。
"""

import importlib
import importlib.util
import os
from typing import Dict, List, Optional

from checks.base import Check


class CheckLoader:
    def __init__(self, builtin_dir: str = "checks", user_dir: str = "user_checks"):
        self._builtin_dir = builtin_dir
        self._user_dir = user_dir
        self._checks: Dict[str, Check] = {}
        self._load_order: List[str] = []

    def discover(self) -> Dict[str, Check]:
        """
        扫描 builtin_dir → user_dir，后发现的覆盖先发现的（同名覆盖）。

        Returns:
            {check_name: Check instance}
        """
        self._checks = {}
        self._load_order = []

        builtin = self._scan_dir(self._builtin_dir, source="builtin")
        for name, check in builtin.items():
            self._checks[name] = check
            self._load_order.append(name)

        user_checks = self._scan_dir(self._user_dir, source="user")
        for name, check in user_checks.items():
            if name in self._checks:
                print(f"[CheckLoader] User override for: '{name}'")
            self._checks[name] = check

        return self._checks

    def _scan_dir(self, dir_path: str, source: str) -> Dict[str, Check]:
        result = {}
        if not os.path.isdir(dir_path):
            return result

        for fname in sorted(os.listdir(dir_path)):
            if fname.startswith("_") or not fname.endswith(".py"):
                continue

            module_name = fname[:-3]
            filepath = os.path.join(dir_path, fname)

            try:
                check = self._load_check_from_file(filepath, module_name, dir_path)
                if check is not None:
                    result[check.get_name()] = check
            except Exception as e:
                print(f"[CheckLoader] Failed to load '{source}/{module_name}': {e}")

        return result

    def _load_check_from_file(self, filepath: str, module_name: str, package_dir: str) -> Optional[Check]:
        """
        动态加载 Python 文件，提取其中第一个 Check 子类实例。
        使用 spec_from_file_location 避免模块名冲突。
        """
        full_name = f"check_{package_dir.replace(os.sep, '_')}_{module_name}"

        spec = importlib.util.spec_from_file_location(full_name, filepath)
        if spec is None or spec.loader is None:
            return None

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            if (
                isinstance(obj, type)
                and issubclass(obj, Check)
                and obj is not Check
            ):
                return obj()

        return None

    def get(self, name: str) -> Optional[Check]:
        return self._checks.get(name)

    def get_all(self) -> Dict[str, Check]:
        return dict(self._checks)

    def register(self, check: Check) -> None:
        self._checks[check.get_name()] = check

    @property
    def count(self) -> int:
        return len(self._checks)

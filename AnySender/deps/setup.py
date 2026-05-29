"""
AnySender dependency auto-detect & install.

Strategy:
  1. core.txt       — always needed
  2. notify.txt     — install when any task is enabled
  3. qq.txt         — install when qq plugin is used by any enabled task
  4. future wechat.txt — same pattern

Usage:
  python deps/setup.py          # auto-detect & install
  python deps/setup.py --all    # install everything
  python deps/setup.py --check  # dry-run, report only
"""

import importlib
import os
import subprocess
import sys
from pathlib import Path

DEPS_DIR = Path(__file__).resolve().parent
PROJECT_DIR = DEPS_DIR.parent
_pip_extra_args = []


def get_python_version() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def get_os_info() -> str:
    if sys.platform == "win32":
        return "Windows"
    elif sys.platform == "darwin":
        return "macOS"
    elif sys.platform.startswith("linux"):
        return "Linux"
    return sys.platform


def _strip_version(pkg: str) -> str:
    for sep in ("==", ">=", "<=", "~=", "!=", ">", "<"):
        if sep in pkg:
            return pkg.split(sep)[0].strip()
    return pkg


def is_package_installed(pkg_name: str) -> bool:
    pkg_name = _strip_version(pkg_name)
    # Normalize name for import check
    import_name = pkg_name.replace("-", "_").lower()
    # Map common pip→import name mismatches
    name_map = {
        "opencv_python": "cv2",
        "scikit_image": "skimage",
        "pyyaml": "yaml",
        "apscheduler": "apscheduler",
        "pillow": "PIL",
        "paddlepaddle": "paddle",
        "paddleocr": "paddleocr",
        "pyperclip": "pyperclip",
        "windows_toasts": "windows_toasts",
        "jsonschema": "jsonschema",
        "pywin32": "win32clipboard",
    }
    import_name = name_map.get(import_name, import_name)
    try:
        importlib.import_module(import_name)
        return True
    except ImportError:
        return False


def read_requirements(filepath: Path) -> list:
    if not filepath.exists():
        return []
    pkgs = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                pkgs.append(line)
    return pkgs


def detect_enabled_plugins() -> set:
    plugins = set()
    tasks_path = PROJECT_DIR / "config" / "tasks.yaml"
    preset_tasks_path = PROJECT_DIR / "presets" / "tasks.yaml"

    for path in (tasks_path, preset_tasks_path):
        if not path.exists():
            continue
        try:
            import yaml
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            for task in data.get("tasks", []):
                if task.get("enabled", False):
                    plugins.add(task.get("plugin", "").lower())
        except Exception:
            # 解析不了就跳过
            pass

    return {p for p in plugins if p}


def has_any_enabled_task() -> bool:
    tasks_path = PROJECT_DIR / "config" / "tasks.yaml"
    preset_tasks_path = PROJECT_DIR / "presets" / "tasks.yaml"

    for path in (tasks_path, preset_tasks_path):
        if not path.exists():
            continue
        try:
            import yaml
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            for task in data.get("tasks", []):
                if task.get("enabled", False):
                    return True
        except Exception:
            pass
    return False


def resolve_dep_groups(all_mode: bool = False) -> dict:
    groups = {}
    groups["core"] = DEPS_DIR / "core.txt"

    if all_mode:
        groups["notify"] = DEPS_DIR / "notify.txt"
        for f in DEPS_DIR.glob("*.txt"):
            name = f.stem
            if name not in groups and name != "dev":
                groups[name] = f
    else:
        if has_any_enabled_task():
            groups["notify"] = DEPS_DIR / "notify.txt"

        enabled_plugins = detect_enabled_plugins()
        for p in enabled_plugins:
            dep_file = DEPS_DIR / f"{p}.txt"
            if dep_file.exists():
                groups[p] = dep_file

    return groups


def check_all(groups: dict) -> dict:
    result = {}
    for name, path in groups.items():
        pkgs = read_requirements(path)
        missing = [p for p in pkgs if not is_package_installed(p)]
        result[name] = {
            "total": len(pkgs),
            "installed": len(pkgs) - len(missing),
            "missing": missing,
        }
    return result


def install_missing(groups: dict) -> bool:
    all_missing = []
    for name, path in groups.items():
        pkgs = read_requirements(path)
        missing = [p for p in pkgs if not is_package_installed(p)]
        all_missing.extend(missing)

    if not all_missing:
        print("All dependencies ready, nothing to install.")
        return True

    print(f"Installing {len(all_missing)} package(s)...")
    cmd = [sys.executable, "-m", "pip", "install"] + _pip_extra_args + all_missing

    try:
        subprocess.check_call(cmd)
        print("Installation complete.")
        return True
    except subprocess.CalledProcessError:
        # 一些二进制包（opencv、scikit-image）在较新 Python 下可能没有精确版本的 wheel
        # 自动回退：去掉版本号再试一次
        unpinned = [_strip_version(p) for p in all_missing]
        if unpinned == all_missing:
            print("Installation failed (no fallback available).")
            return False

        print(f"Pinned versions failed, retrying with latest...")
        cmd2 = [sys.executable, "-m", "pip", "install"] + _pip_extra_args + unpinned
        try:
            subprocess.check_call(cmd2)
            print("Installation complete (latest versions).")
            # 写入一个 marker，下次检查时若版本不完全匹配也视为已安装
            _write_fallback_marker(all_missing)
            return True
        except subprocess.CalledProcessError as e:
            print(f"Installation failed: {e}")
            return False


def _write_fallback_marker(packages: list) -> None:
    marker = DEPS_DIR / ".fallback"
    try:
        marker.write_text("\n".join(packages), encoding="utf-8")
    except Exception:
        pass


def print_report(groups, status):
    print(f"Python: {get_python_version()}  |  OS: {get_os_info()}")
    print(f"Project: {PROJECT_DIR}")
    print()

    total_missing = 0
    for name, info in status.items():
        tag = "OK" if not info["missing"] else "!!"
        print(f"  [{tag}] {name}: {info['installed']}/{info['total']} installed")
        for pkg in info["missing"]:
            print(f"       missing: {pkg}")
            total_missing += 1

    print()
    if total_missing == 0:
        print("All dependencies ready.")
        print("DEPS_READY")
    else:
        print(f"Total missing: {total_missing} package(s).")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="AnySender dependency manager")
    parser.add_argument("--all", action="store_true", help="Install all deps")
    parser.add_argument("--check", action="store_true", help="Check only, no install")
    parser.add_argument("--install-core", action="store_true", help="Install core deps only")
    parser.add_argument("--mirror", action="store_true", help="Use Tsinghua mirror (faster in China)")
    args = parser.parse_args()

    if args.mirror:
        global _pip_extra_args
        _pip_extra_args = ["-i", "https://pypi.tuna.tsinghua.edu.cn/simple", "--trusted-host", "pypi.tuna.tsinghua.edu.cn"]

    groups = resolve_dep_groups(all_mode=args.all)

    if args.install_core:
        groups = {"core": DEPS_DIR / "core.txt"}

    status = check_all(groups)
    print_report(groups, status)

    if args.check:
        return

    has_missing = any(info["missing"] for info in status.values())
    if has_missing:
        install_missing(groups)


if __name__ == "__main__":
    main()

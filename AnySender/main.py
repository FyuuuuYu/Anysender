#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""AnySender 入口。

常用参数：
  python main.py                 正常启动（含 Web 控制台）
  python main.py --check         只做配置/插件校验，不启动调度与 Web
  python main.py --dry-run       试运行：只定位窗口与生成报告，绝不点击/输入/发送
  python main.py --no-web        不启动 Web 控制台
"""

import argparse
import os
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from core.config_hub import ConfigHub  # noqa: E402
from core.event_bus import EventBus  # noqa: E402
from core.logger import Logger  # noqa: E402
from core.plugin_manager import PluginManager  # noqa: E402
from core.scheduler import Scheduler  # noqa: E402
from core.watchdog import Watchdog  # noqa: E402
from notifier import create_notifier  # noqa: E402


def ensure_deps():
    setup_script = os.path.join(BASE_DIR, "deps", "setup.py")
    if not os.path.isfile(setup_script):
        return
    try:
        result = subprocess.run(
            [sys.executable, setup_script, "--check"],
            capture_output=True,
            text=True,
            cwd=BASE_DIR,
        )
        if "DEPS_READY" not in result.stdout:
            print("[AnySender] 检测到缺失依赖，自动安装中...")
            subprocess.check_call([sys.executable, setup_script], cwd=BASE_DIR)
    except Exception:
        pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AnySender 定时发送器")
    parser.add_argument(
        "--check", action="store_true", help="只校验配置与插件，然后退出"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="试运行模式：只定位窗口，不点击、不输入、不发送",
    )
    parser.add_argument("--no-web", action="store_true", help="不启动 Web 控制台")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--port", type=int, default=None, help="Web 控制台端口")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if args.dry_run:
        os.environ["ANYSENDER_DRY_RUN"] = "1"

    if not args.check:
        ensure_deps()

    event_bus = EventBus()
    logger = Logger(
        event_bus,
        config_path=os.path.join(BASE_DIR, "config", "base.yaml"),
        log_dir=os.path.join(BASE_DIR, "logs"),
    )
    config_hub = ConfigHub(
        os.path.join(BASE_DIR, "config"),
        os.path.join(BASE_DIR, "presets"),
        project_root=BASE_DIR,
    )

    core_config = config_hub.load_core_config()
    logger.info("AnySender 启动中...")
    if args.dry_run:
        logger.warning("试运行模式已开启：任何任务都不会真实点击/输入/发送消息")

    plugin_manager = PluginManager(
        os.path.join(BASE_DIR, "plugins"),
        os.path.join(BASE_DIR, "custom_plugins"),
        event_bus=event_bus,
        project_root=BASE_DIR,
    )
    discovered = plugin_manager.discover()
    logger.info(f"发现插件: {discovered if discovered else '无'}")

    # 关键修复：加载全部已发现插件，而不是只加载“启用任务”引用的插件。
    # 这样 Web 新建/启用的任务、手动执行都不会遇到“插件未加载”。
    plugin_errors = 0
    for pname in discovered:
        try:
            pconfig = config_hub.load_plugin_config(pname)
            plugin_manager.load(pname, pconfig)
        except Exception as exc:
            plugin_errors += 1
            logger.error(f"插件 [{pname}] 加载失败: {exc}")
    logger.info(
        f"已加载插件: {plugin_manager.loaded_names() or '无'}"
    )

    tasks = config_hub.load_tasks()
    notifier = create_notifier(event_bus=event_bus)

    notify_cfg = core_config.get("notify") or {}
    scheduler = Scheduler(
        config_hub,
        plugin_manager,
        event_bus,
        notifier=notifier,
        notify_enabled=bool(notify_cfg.get("enabled", True)),
        early_seconds=int(notify_cfg.get("early_seconds", 300)),
        soon_seconds=int(notify_cfg.get("soon_seconds", 30)),
        max_workers=int(
            (core_config.get("scheduler") or {}).get("max_workers", 8)
        ),
        timezone=str(
            (core_config.get("app") or {}).get("timezone", "Asia/Shanghai")
        ),
    )

    task_errors = 0
    for task in tasks:
        if not task.get("enabled", True):
            continue
        try:
            scheduler.add_task(task)
        except Exception as exc:
            task_errors += 1
            logger.error(f"任务 [{task.get('name', '?')}] 注册失败: {exc}")

    if args.check:
        logger.info(
            f"配置校验完成：插件 {plugin_manager.loaded_names()}，"
            f"插件失败 {plugin_errors}，有效任务 {scheduler.job_count()}，"
            f"失败任务 {task_errors}"
        )
        scheduler.shutdown()
        return 1 if (task_errors or plugin_errors) else 0

    watchdog = Watchdog(event_bus, plugin_manager, os.path.join(BASE_DIR, "config"))
    watchdog.start(
        health_interval=int(
            (core_config.get("watchdog") or {}).get("health_interval", 30)
        )
    )

    logger.info(f"AnySender 启动完成，共 {scheduler.job_count()} 个任务")

    if not args.no_web:
        import threading

        from web import app as web_app

        web_app.bind(
            scheduler,
            plugin_manager,
            event_bus,
            logger,
            ledger=scheduler.ledger,
            config_tasks_path=os.path.join(BASE_DIR, "config", "tasks.yaml"),
            sys_path=BASE_DIR,
        )
        web_thread = threading.Thread(
            target=web_app.run,
            kwargs={
                "host": "127.0.0.1",
                "port": args.port or 8765,
                "open_browser": not args.no_browser,
            },
            daemon=True,
        )
        web_thread.start()

    try:
        scheduler.start()
        while True:
            import time

            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("收到退出信号...")
    finally:
        scheduler.shutdown()
        watchdog.stop()
        plugin_manager.unload_all()
        logger.info("AnySender 已退出")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

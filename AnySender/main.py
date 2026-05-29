#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import subprocess
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.config_hub import ConfigHub
from core.plugin_manager import PluginManager
from core.scheduler import Scheduler
from core.event_bus import EventBus
from core.logger import Logger
from core.watchdog import Watchdog
from notifier import create_notifier


def ensure_deps():
    setup_script = os.path.join(os.path.dirname(__file__), "deps", "setup.py")
    if not os.path.isfile(setup_script):
        return
    try:
        result = subprocess.run(
            [sys.executable, setup_script, "--check"],
            capture_output=True, text=True, cwd=os.path.dirname(__file__)
        )
        if "DEPS_READY" not in result.stdout:
            print("[AnySender] 检测到缺失依赖，自动安装中...")
            subprocess.check_call(
                [sys.executable, setup_script], cwd=os.path.dirname(__file__)
            )
    except Exception:
        pass


def main():
    ensure_deps()

    event_bus = EventBus()
    logger = Logger(event_bus)
    config_hub = ConfigHub("config", "presets")

    core_config = config_hub.load_core_config()
    logger.info("AnySender 启动中...")

    plugin_manager = PluginManager("plugins", event_bus=event_bus)
    plugin_manager.discover()
    discovered = plugin_manager.discovered_names()
    logger.info(f"发现插件: {discovered if discovered else '无'}")

    tasks = config_hub.load_tasks()
    loaded_plugins = set()
    for task in tasks:
        if not task.get("enabled", True):
            continue
        pname = task["plugin"]
        if pname not in loaded_plugins:
            pconfig = config_hub.load_plugin_config(pname)
            plugin_manager.load(pname, pconfig)
            loaded_plugins.add(pname)
    logger.info(f"已加载插件: {list(loaded_plugins) if loaded_plugins else '无'}")

    notifier = create_notifier(event_bus=event_bus)

    scheduler = Scheduler(
        config_hub, plugin_manager, event_bus,
        notifier=notifier,
        notify_enabled=True,
        early_seconds=300,
        soon_seconds=30,
        max_workers=core_config.get("scheduler", {}).get("max_workers", 8),
        timezone=core_config.get("app", {}).get("timezone", "Asia/Shanghai"),
    )
    for task in tasks:
        if task.get("enabled", True):
            scheduler.add_task(task)

    watchdog = Watchdog(event_bus, plugin_manager, "config")
    watchdog.start(health_interval=core_config.get("watchdog", {}).get("health_interval", 30))

    logger.info(f"AnySender 启动完成，共 {scheduler.job_count()} 个任务")
    try:
        scheduler.start()
        while True:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("收到退出信号...")
        scheduler.shutdown()
        watchdog.stop()
        plugin_manager.unload_all()
        logger.info("AnySender 已退出")


if __name__ == "__main__":
    main()

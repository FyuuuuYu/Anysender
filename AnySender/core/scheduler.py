import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone as tz
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler as APSBackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from .event_bus import EventBus
from .plugin_manager import PluginManager
from .exceptions import ConfigValidationError


class Scheduler:
    def __init__(
        self,
        config_hub,
        plugin_manager: PluginManager,
        event_bus: EventBus,
        notifier=None,
        notify_enabled: bool = True,
        early_seconds: int = 300,
        soon_seconds: int = 30,
        max_workers: int = 8,
        timezone: str = "Asia/Shanghai",
    ):
        self._notify_enabled = notify_enabled
        self._early_seconds = early_seconds
        self._soon_seconds = soon_seconds
        self._config_hub = config_hub
        self._plugin_manager = plugin_manager
        self._event_bus = event_bus
        self._notifier = notifier
        self._timezone_str = timezone

        self._scheduler = APSBackgroundScheduler(timezone=timezone)
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._shutdown = threading.Event()

        self._event_bus.subscribe("notify_postpone", self._on_postpone)
        self._event_bus.subscribe("notify_run_now", self._on_run_now)

    def add_task(self, task: dict) -> None:
        if not task.get("enabled", True):
            return

        cron_expr = task.get("schedule", "")
        trigger = self._parse_schedule(cron_expr)
        if trigger is None:
            raise ConfigValidationError(f"任务 [{task.get('name','?')}] schedule 格式无效: {cron_expr}")

        task_name = task.get("name", "unnamed")

        # 主任务：cron 准时执行
        self._scheduler.add_job(
            self._on_main_trigger,
            trigger=trigger,
            args=[task],
            id=f"task_{task_name}",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60,
        )

        # 预通知：cron - pre_notify_seconds
        self._schedule_pre_notify(task, trigger)

    def _schedule_pre_notify(self, task: dict, trigger: CronTrigger) -> None:
        if not self._notify_enabled or self._notifier is None:
            return
        try:
            now = datetime.now(tz.utc)
            next_fire = trigger.get_next_fire_time(None, now)
            if next_fire is None:
                return

            # Level 1: 提前提醒「有计划中的任务」
            if self._early_seconds > 0:
                early_time = next_fire - timedelta(seconds=self._early_seconds)
                if early_time > now:
                    self._scheduler.add_job(
                        lambda t=task: self._notifier.notify_task_planned(
                            t.get("name", "?"), self._early_seconds),
                        DateTrigger(run_date=early_time),
                        id=f"pre_early_{task.get('name', 'unnamed')}",
                        replace_existing=True, max_instances=1,
                    )

            # Level 2: 即将执行「请勿移动鼠标」+ 按钮
            if self._soon_seconds > 0:
                soon_time = next_fire - timedelta(seconds=self._soon_seconds)
                if soon_time > now:
                    self._scheduler.add_job(
                        self._on_pre_notify,
                        DateTrigger(run_date=soon_time),
                        args=[task],
                        id=f"pre_soon_{task.get('name', 'unnamed')}",
                        replace_existing=True, max_instances=1,
                    )
        except Exception:
            pass

    def _on_pre_notify(self, task: dict) -> None:
        if self._notifier:
            self._notifier.notify_task_soon(
                task.get("name", "unknown"),
                task.get("plugin", ""),
                self._soon_seconds,
            )

    def _on_main_trigger(self, task: dict) -> None:
        task_name = task.get("name", "unknown")
        plugin_name = task.get("plugin", "")
        plugin = self._plugin_manager.get(plugin_name)
        if plugin is None:
            self._event_bus.emit("task_failed",
                task_name=task_name, plugin_name=plugin_name,
                detail=f"插件 [{plugin_name}] 未加载",
            )
            return

        if self._notifier:
            self._notifier.notify_sending(task_name)

        self._executor.submit(self._do_work, task, plugin)

    def _do_work(self, task: dict, plugin) -> None:
        cfg = self._plugin_manager.get_config(task.get("plugin", ""))
        merged = {**cfg, **task.get("plugin_config", {})}
        task["resolved_config"] = merged

        result = plugin.send_with_lock(task)
        task_name = task.get("name", "unknown")

        if self._notifier:
            self._notifier.notify_done(task_name, result.success, result.detail)

        if result.success:
            self._event_bus.emit("task_completed",
                task_name=result.task_name, plugin_name=result.plugin_name,
                duration_ms=result.duration_ms, detail=result.detail,
                artifacts=result.artifacts,
            )
        elif result.retryable:
            self._event_bus.emit("task_failed",
                task_name=result.task_name, plugin_name=result.plugin_name,
                duration_ms=result.duration_ms, detail=result.detail,
                retryable=True,
            )
        else:
            self._event_bus.emit("task_skipped",
                task_name=result.task_name, plugin_name=result.plugin_name,
                detail=result.detail,
            )

        # 重新预约下一次预通知
        cron_expr = task.get("schedule", "")
        trigger = self._parse_schedule(cron_expr)
        if trigger:
            self._schedule_pre_notify(task, trigger)

    def _on_postpone(self, task_id: str, delay_seconds: int, **kwargs):
        task = self._find_task_by_id(task_id)
        if not task:
            return
        def _delayed():
            if self._shutdown.wait(timeout=delay_seconds):
                return
            self._on_main_trigger(task)
        self._executor.submit(_delayed)

    def _on_run_now(self, task_id: str, **kwargs):
        task = self._find_task_by_id(task_id)
        if task:
            self._on_main_trigger(task)

    def _find_task_by_id(self, task_id: str) -> Optional[dict]:
        tasks = self._config_hub.load_tasks()
        for t in tasks:
            if t.get("name") == task_id:
                return t
        return None

    def _parse_schedule(self, cron_expr: str) -> Optional[CronTrigger]:
        parts = cron_expr.strip().split()
        if len(parts) == 6:
            try:
                return CronTrigger(
                    second=parts[0], minute=parts[1], hour=parts[2],
                    day=parts[3], month=parts[4], day_of_week=parts[5],
                    timezone=self._timezone_str,
                )
            except Exception:
                return None
        return None

    def start(self) -> None:
        self._scheduler.start()

    def shutdown(self) -> None:
        self._shutdown.set()
        self._scheduler.shutdown(wait=False)
        self._executor.shutdown(wait=False)

    def job_count(self) -> int:
        return len([j for j in self._scheduler.get_jobs() if j.id.startswith("task_")])

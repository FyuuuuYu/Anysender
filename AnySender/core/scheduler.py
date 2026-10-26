import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler as APSBackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from .event_bus import EventBus
from .exceptions import ConfigValidationError
from .ledger import RunLedger
from .plugin_manager import PluginManager


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
        ledger: Optional[RunLedger] = None,
    ):
        self._notify_enabled = notify_enabled
        self._early_seconds = early_seconds
        self._soon_seconds = soon_seconds
        self._config_hub = config_hub
        self._plugin_manager = plugin_manager
        self._event_bus = event_bus
        self._notifier = notifier
        self._timezone_str = timezone
        self._tz = ZoneInfo(timezone)
        self._ledger = ledger or RunLedger(
            os.path.join(config_hub.project_root, "logs", "runs.jsonl")
        )

        self._scheduler = APSBackgroundScheduler(timezone=timezone)
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._shutdown = threading.Event()
        self._running = 0
        self._running_lock = threading.Lock()

        self._event_bus.subscribe("notify_postpone", self._on_postpone)
        self._event_bus.subscribe("notify_run_now", self._on_run_now)

    @property
    def ledger(self) -> RunLedger:
        return self._ledger

    def add_task(self, task: dict) -> None:
        if not task.get("enabled", True):
            return

        cron_expr = task.get("schedule", "")
        trigger = self._parse_schedule(cron_expr)
        if trigger is None:
            raise ConfigValidationError(
                f"任务 [{task.get('name', '?')}] schedule 格式无效: {cron_expr}"
            )

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

    def reload_tasks(self) -> list:
        """按 tasks.yaml 重建所有任务 job（WebUI 增删改后调用）。"""
        for job in list(self._scheduler.get_jobs()):
            if (
                job.id.startswith("task_")
                or job.id.startswith("pre_early_")
                or job.id.startswith("pre_soon_")
                or job.id.startswith("postpone_")
            ):
                try:
                    job.remove()
                except Exception:
                    pass
        errors = []
        for task in self._config_hub.load_tasks():
            try:
                self.add_task(task)
            except Exception as exc:
                errors.append(f"[{task.get('name', '?')}] {exc}")
        return errors

    def _schedule_pre_notify(self, task: dict, trigger: CronTrigger) -> None:
        if not self._notify_enabled or self._notifier is None:
            return
        try:
            now = datetime.now(self._tz)
            next_fire = trigger.get_next_fire_time(None, now)
            if next_fire is None:
                return

            # Level 1: 提前提醒「有计划中的任务」
            if self._early_seconds > 0:
                early_time = next_fire - timedelta(seconds=self._early_seconds)
                if early_time > now:
                    self._scheduler.add_job(
                        lambda t=task: self._notifier.notify_task_planned(
                            t.get("name", "?"), self._early_seconds
                        ),
                        DateTrigger(run_date=early_time),
                        id=f"pre_early_{task.get('name', 'unnamed')}",
                        replace_existing=True,
                        max_instances=1,
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
                        replace_existing=True,
                        max_instances=1,
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

    def _resolve_plugin(self, plugin_name: str):
        """取得插件；未加载时按需加载（修复 Web 新建任务时插件缺失）。"""
        plugin = self._plugin_manager.get(plugin_name)
        if plugin is not None:
            return plugin, ""
        try:
            config = self._config_hub.load_plugin_config(plugin_name)
            plugin = self._plugin_manager.load(plugin_name, config)
            return plugin, ""
        except Exception as exc:
            return None, f"插件 [{plugin_name}] 未加载且无法按需加载: {exc}"

    def _submit(self, task: dict, plugin) -> str:
        run_id = task.get("run_id") or uuid.uuid4().hex[:8]
        task["run_id"] = run_id
        with self._running_lock:
            self._running += 1
        self._executor.submit(self._do_work, task, plugin)
        return run_id

    def _on_main_trigger(self, task: dict) -> None:
        task_name = task.get("name", "unknown")
        plugin_name = task.get("plugin", "")
        plugin, error = self._resolve_plugin(plugin_name)
        if plugin is None:
            run_id = uuid.uuid4().hex[:8]
            self._ledger.append(
                {
                    "run_id": run_id,
                    "task": task_name,
                    "plugin": plugin_name,
                    "success": False,
                    "skipped": False,
                    "retryable": True,
                    "dry_run": False,
                    "duration_ms": 0,
                    "detail": error,
                    "artifacts": [],
                }
            )
            self._event_bus.emit(
                "task_failed",
                task_name=task_name,
                plugin_name=plugin_name,
                detail=error,
                retryable=True,
                run_id=run_id,
            )
            return
        self._submit(dict(task), plugin)

    def run_now(self, task_name: str, dry_run: bool = False) -> dict:
        """Web / API 手动执行入口：异步提交，立即返回 run_id。"""
        task = self._find_task_by_id(task_name)
        if not task:
            return {"ok": False, "status": 404, "error": f"任务 [{task_name}] 不存在"}

        plugin_name = task.get("plugin", "")
        if not plugin_name:
            return {"ok": False, "status": 400, "error": f"任务 [{task_name}] 未配置插件"}

        plugin, error = self._resolve_plugin(plugin_name)
        if plugin is None:
            return {"ok": False, "status": 500, "error": error}

        job_task = dict(task)
        job_task["dry_run"] = bool(dry_run or task.get("dry_run"))
        run_id = self._submit(job_task, plugin)
        mode = "（试运行）" if job_task["dry_run"] else ""
        return {
            "ok": True,
            "run_id": run_id,
            "dry_run": job_task["dry_run"],
            "detail": f"已提交任务 [{task_name}]{mode}",
        }

    def _do_work(self, task: dict, plugin) -> None:
        task_name = task.get("name", "unknown")
        plugin_name = task.get("plugin", "")
        run_id = task.get("run_id", "")
        dry_run = bool(task.get("dry_run"))
        started = time.monotonic()
        try:
            cfg = self._plugin_manager.get_config(plugin_name)
            merged = dict(cfg)
            # WebUI 把 group_name/message/images 存在任务顶层；合并进插件配置。
            for key in ("group_name", "message", "images"):
                if key in task:
                    merged[key] = task.get(key)
            merged.update(task.get("plugin_config") or {})
            task["resolved_config"] = merged

            if self._notifier and not dry_run:
                self._notifier.notify_sending(task_name)

            result = plugin.send_with_lock(task)
            if not result.duration_ms:
                result.duration_ms = int((time.monotonic() - started) * 1000)
            if not result.task_name:
                result.task_name = task_name
            if not result.plugin_name:
                result.plugin_name = plugin_name

            self._ledger.append(
                {
                    "run_id": run_id,
                    "task": task_name,
                    "plugin": plugin_name,
                    "success": bool(result.success),
                    "skipped": bool(result.skipped),
                    "retryable": bool(result.retryable),
                    "dry_run": dry_run,
                    "duration_ms": result.duration_ms,
                    "detail": result.detail,
                    "artifacts": result.artifacts,
                }
            )

            if self._notifier and not dry_run:
                self._notifier.notify_done(task_name, result.success, result.detail)

            base = dict(
                task_name=result.task_name,
                plugin_name=result.plugin_name,
                duration_ms=result.duration_ms,
                detail=result.detail,
                dry_run=dry_run,
                run_id=run_id,
            )
            if result.success:
                self._event_bus.emit(
                    "task_completed", artifacts=result.artifacts, **base
                )
            elif result.skipped:
                self._event_bus.emit("task_skipped", **base)
            else:
                self._event_bus.emit(
                    "task_failed", retryable=result.retryable, **base
                )

            # 重新预约下一次预通知
            trigger = self._parse_schedule(task.get("schedule", ""))
            if trigger:
                self._schedule_pre_notify(task, trigger)
        except Exception as exc:  # 调度器自身异常不能让线程池吞掉且无记录
            self._ledger.append(
                {
                    "run_id": run_id,
                    "task": task_name,
                    "plugin": plugin_name,
                    "success": False,
                    "skipped": False,
                    "retryable": True,
                    "dry_run": dry_run,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                    "detail": f"调度执行异常: {exc}",
                    "artifacts": [],
                }
            )
            self._event_bus.emit(
                "task_failed",
                task_name=task_name,
                plugin_name=plugin_name,
                detail=f"调度执行异常: {exc}",
                retryable=True,
                dry_run=dry_run,
                run_id=run_id,
            )
        finally:
            with self._running_lock:
                self._running = max(0, self._running - 1)

    def _on_postpone(self, task_id: str, delay_seconds: int, **kwargs):
        """推迟任务：交给 APScheduler 定时，不占用发送线程池。

        旧实现用 `executor.submit(_delayed)` 在 worker 里 wait，会把 8 个发送
        worker 之一占住数分钟，多任务同时推迟时会挤掉正常发送。
        """
        task = self._find_task_by_id(task_id)
        if not task or not task.get("enabled", True):
            return
        delay_seconds = max(0, int(delay_seconds))
        run_at = datetime.now(self._tz) + timedelta(seconds=delay_seconds)
        self._scheduler.add_job(
            self._postpone_fire,
            trigger=DateTrigger(run_date=run_at),
            args=[task_id],
            id=f"postpone_{task_id}",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60,
        )

    def _postpone_fire(self, task_id: str) -> None:
        """推迟到点后重新读取配置，避免执行停用/已删除任务的旧快照。"""
        task = self._find_task_by_id(task_id)
        if not task:
            self._event_bus.emit(
                "task_skipped",
                task_name=task_id,
                plugin_name="",
                detail="推迟执行时任务已不存在",
            )
            return
        if not task.get("enabled", True):
            self._event_bus.emit(
                "task_skipped",
                task_name=task_id,
                plugin_name=task.get("plugin", ""),
                detail="任务已停用，取消本次推迟执行",
            )
            return
        self._on_main_trigger(task)

    def _on_run_now(self, task_id: str, **kwargs):
        result = self.run_now(task_id)
        if not result.get("ok"):
            self._event_bus.emit(
                "task_failed",
                task_name=task_id,
                plugin_name="",
                detail=result.get("error", "手动执行失败"),
                retryable=False,
            )

    def _find_task_by_id(self, task_id: str) -> Optional[dict]:
        tasks = self._config_hub.load_tasks()
        for t in tasks:
            if t.get("name") == task_id:
                return t
        return None

    def _parse_schedule(self, cron_expr: str) -> Optional[CronTrigger]:
        parts = (cron_expr or "").strip().split()
        if len(parts) == 5:  # 兼容标准 5 段 cron（秒固定 0）
            parts = ["0"] + parts
        if len(parts) == 6:
            try:
                return CronTrigger(
                    second=parts[0],
                    minute=parts[1],
                    hour=parts[2],
                    day=parts[3],
                    month=parts[4],
                    day_of_week=parts[5],
                    timezone=self._timezone_str,
                )
            except Exception:
                return None
        return None

    def start(self) -> None:
        self._scheduler.start()

    def shutdown(self) -> None:
        self._shutdown.set()
        try:
            self._scheduler.shutdown(wait=False)
        except Exception:
            pass
        self._executor.shutdown(wait=False)

    def job_count(self) -> int:
        return len([j for j in self._scheduler.get_jobs() if j.id.startswith("task_")])

    def running_count(self) -> int:
        with self._running_lock:
            return self._running

    def next_run(self) -> Optional[str]:
        jobs = [j for j in self._scheduler.get_jobs() if j.id.startswith("task_")]
        times = [j.next_run_time for j in jobs if getattr(j, "next_run_time", None)]
        return min(times).isoformat(timespec="seconds") if times else None

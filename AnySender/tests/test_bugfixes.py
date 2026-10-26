# -*- coding: utf-8 -*-
"""回归测试：覆盖本轮修复的 Bug（不触碰真实鼠标/键盘/QQ）。

运行：python -m unittest discover -s tests -p "test_*.py" -v
"""

import json
import os
import sys
import tempfile
import textwrap
import time
import unittest
from unittest import mock

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from core.config_hub import ConfigHub  # noqa: E402
from core.event_bus import EventBus  # noqa: E402
from core.ledger import RunLedger  # noqa: E402
from core.logger import Logger  # noqa: E402
from core.plugin_interface import SendResult, SenderPlugin  # noqa: E402
from core.plugin_manager import PluginManager  # noqa: E402
from core.scheduler import Scheduler  # noqa: E402


def wait_for(fn, timeout=4.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = fn()
        if value:
            return value
        time.sleep(0.02)
    return None


class FakePlugin(SenderPlugin):
    def get_name(self):
        return "fake"

    def get_version(self):
        return "0.0.1"

    def get_default_config(self):
        return {}

    def validate_config(self, config):
        return True, "ok"

    def send(self, task):
        mode = (task.get("resolved_config") or {}).get("mode", "ok")
        if mode == "skip":
            return SendResult(
                False, task["name"], "fake", detail="正忙", skipped=True
            )
        if mode == "fail":
            return SendResult(
                False, task["name"], "fake", detail="失败", retryable=False
            )
        return SendResult(True, task["name"], "fake", detail="ok")


class ConfigAndPluginManagerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(textwrap.dedent(text))
        return path

    def test_config_hub_abs_paths_and_merge(self):
        self._write("presets/base.yaml", "app:\n  timezone: UTC\n  name: preset\n")
        self._write("config/base.yaml", "app:\n  name: local\n")
        hub = ConfigHub(
            os.path.join(self.root, "config"),
            os.path.join(self.root, "presets"),
            project_root=self.root,
        )
        cfg = hub.load_core_config()
        self.assertEqual(cfg["app"]["timezone"], "UTC")
        self.assertEqual(cfg["app"]["name"], "local")

    def test_plugin_not_registered_when_validate_fails(self):
        self._write(
            "myplugins/bad/plugin.py",
            """
            from core.plugin_interface import SenderPlugin, SendResult

            class BadPlugin(SenderPlugin):
                def get_name(self):
                    return "bad"

                def get_version(self):
                    return "0"

                def get_default_config(self):
                    return {}

                def validate_config(self, config):
                    return False, "配置不对"

                def send(self, task):
                    return SendResult(True, task.get("name", ""))
            """,
        )
        self._write("myplugins/bad/__init__.py", "")
        pm = PluginManager(
            plugins_dir="myplugins",
            custom_dir="mycustom",
            project_root=self.root,
        )
        pm.discover()
        with self.assertRaises(Exception):
            pm.load("bad", {})
        self.assertIsNone(pm.get("bad"))
        self.assertNotIn("bad", pm.loaded_names())


class SchedulerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        os.makedirs(os.path.join(self.root, "config"), exist_ok=True)
        os.makedirs(os.path.join(self.root, "presets"), exist_ok=True)
        with open(
            os.path.join(self.root, "config", "tasks.yaml"), "w", encoding="utf-8"
        ) as f:
            f.write(
                "tasks:\n"
                "  - name: t1\n"
                "    plugin: fake\n"
                "    enabled: false\n"
                "    schedule: '0 0 8 * * *'\n"
                "    message: hello\n"
            )
        self.bus = EventBus()
        self.hub = ConfigHub(
            os.path.join(self.root, "config"),
            os.path.join(self.root, "presets"),
            project_root=self.root,
        )
        self.pm = PluginManager(project_root=self.root)
        self.pm._plugins["fake"] = FakePlugin()
        self.pm._plugin_configs["fake"] = {}
        self.ledger = RunLedger(os.path.join(self.root, "logs", "runs.jsonl"))
        self.scheduler = Scheduler(
            self.hub,
            self.pm,
            self.bus,
            ledger=self.ledger,
            timezone="Asia/Hong_Kong",
        )

    def tearDown(self):
        self.scheduler.shutdown()
        self.tmp.cleanup()

    def _wait_record(self, run_id):
        return wait_for(
            lambda: next(
                (
                    r
                    for r in self.ledger.tail(50)
                    if r.get("run_id") == run_id
                ),
                None,
            )
        )

    def test_run_now_success_and_ledger(self):
        result = self.scheduler.run_now("t1")
        self.assertTrue(result["ok"])
        record = self._wait_record(result["run_id"])
        self.assertIsNotNone(record, "台账未写入")
        self.assertTrue(record["success"])
        self.assertFalse(record["dry_run"])

    def test_run_now_dry_run_flagged(self):
        result = self.scheduler.run_now("t1", dry_run=True)
        record = self._wait_record(result["run_id"])
        self.assertIsNotNone(record)
        self.assertTrue(record["dry_run"])

    def test_non_retryable_failure_is_task_failed_not_skipped(self):
        task = self.scheduler._find_task_by_id("t1")
        task["plugin_config"] = {"mode": "fail"}
        failed, skipped = [], []
        self.bus.subscribe("task_failed", lambda **kw: failed.append(kw))
        self.bus.subscribe("task_skipped", lambda **kw: skipped.append(kw))
        # 直接走内部触发，确保读取的是刚刚改过的任务
        self.scheduler._on_main_trigger(task)
        self.assertTrue(wait_for(lambda: failed), "未收到 task_failed")
        self.assertEqual(skipped, [])

    def test_bad_cron_does_not_kill_add_task_caller(self):
        errors = self.scheduler.reload_tasks()
        self.assertEqual(errors, [])


class LoggerTest(unittest.TestCase):
    def test_ring_is_shared_and_monotonic(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            bus = EventBus()
            logger = Logger(bus, config_path="", log_dir=tmp.name)
            logger.info("第一条")
            logger.warning("第二条")
            items = logger.recent(0)
            self.assertGreaterEqual(len(items), 2)
            seqs = [item["seq"] for item in items]
            self.assertEqual(seqs, sorted(seqs))
            self.assertGreaterEqual(logger.latest_seq(), seqs[-1])
            logger.close()
        finally:
            tmp.cleanup()


class QQPluginTest(unittest.TestCase):
    def setUp(self):
        from plugins.qq.plugin import QQPlugin

        self.plugin = QQPlugin()
        self.cfg = dict(self.plugin.get_default_config())
        self.cfg["chat_header"] = {
            "relative_x": 0.3,
            "relative_y": 0.07,
            "relative_w": 0.4,
            "relative_h": 0.08,
        }
        self.cfg["validation"] = dict(self.cfg["validation"], enabled=False)
        self.cfg["require_chat_verify"] = True

    def test_validate_config_missing_template_disables_instead_of_failing(self):
        cfg = dict(self.cfg)
        cfg["validation"] = dict(
            cfg["validation"], enabled=True, template_path="Z:/no/such.png"
        )
        ok, detail = self.plugin.validate_config(cfg)
        self.assertTrue(ok, detail)
        self.assertFalse(cfg["validation"]["enabled"])

    def test_requires_chat_header_when_verify_enabled(self):
        cfg = dict(self.cfg)
        cfg.pop("chat_header", None)
        ok, _ = self.plugin.validate_config(cfg)
        self.assertFalse(ok)

    def test_ocr_unavailable_aborts_before_any_ui_action(self):
        from plugins.qq import ocr

        task = {
            "name": "t",
            "resolved_config": dict(self.cfg, group_name="测试群", message="hi"),
        }
        with mock.patch(
            "plugins.qq.ocr.get_reader",
            side_effect=ocr.OCRUnavailable("dll missing"),
        ), mock.patch(
            "plugins.qq.locator.activate_qq_window"
        ) as activate, mock.patch(
            "plugins.qq.plugin._capture_failure_screenshot"
        ):
            result = self.plugin.send(task)
        self.assertFalse(result.success)
        self.assertIn("OCR 引擎不可用", result.detail)
        self.assertTrue(result.retryable)
        activate.assert_not_called()

    def test_text_only_does_not_require_images(self):
        from plugins.qq import locator

        task = {
            "name": "t",
            "resolved_config": dict(self.cfg, group_name="测试群", message="hi"),
            "dry_run": True,
        }
        with mock.patch(
            "plugins.qq.locator.find_qq_window",
            return_value=locator.WindowInfo(
                1, 123, "QQ.exe", "QQ", (0, 0, 100, 100)
            ),
        ):
            result = self.plugin.send(task)
        self.assertTrue(result.success, result.detail)
        self.assertIn("未点击", result.detail)

    def test_dry_run_without_window_fails_gracefully(self):
        task = {
            "name": "t",
            "resolved_config": dict(self.cfg, group_name="测试群", message="hi"),
            "dry_run": True,
        }
        with mock.patch(
            "plugins.qq.locator.find_qq_window",
            side_effect=RuntimeError("未找到 QQ 窗口（测试）"),
        ):
            result = self.plugin.send(task)
        self.assertFalse(result.success)
        self.assertIn("未找到 QQ 窗口", result.detail)

    def test_verify_failure_aborts_before_input(self):
        import plugins.qq.browser as browser
        import plugins.qq.locator as locator

        class FakePyAutoGUI:
            def __init__(self):
                self.clicks = []
                self.hotkeys = []
                self.presses = []

            def click(self, *a, **k):
                self.clicks.append(a)

            def hotkey(self, *a, **k):
                self.hotkeys.append(a)

            def press(self, *a, **k):
                self.presses.append(a)

        fake = FakePyAutoGUI()
        task = {
            "name": "t",
            "resolved_config": dict(
                self.cfg, group_name="测试群", message="hi", search_mode="search"
            ),
        }
        with mock.patch.dict(sys.modules, {"pyautogui": fake}), mock.patch.object(
            locator,
            "activate_qq_window",
            return_value=locator.WindowInfo(
                1, 123, "QQ.exe", "QQ", (0, 0, 1000, 1000)
            ),
        ), mock.patch.object(locator, "open_group_chat"), mock.patch.object(
            locator, "get_input_target", return_value=(500, 500)
        ), mock.patch.object(
            locator, "point_in_rect", return_value=True
        ), mock.patch.object(
            locator, "get_foreground_window_title", return_value="QQ"
        ), mock.patch.object(
            browser, "verify_chat_opened", return_value=False
        ), mock.patch.object(
            browser, "select_search_result", return_value=None
        ), mock.patch.object(
            browser, "browse_to_group", return_value=None
        ), mock.patch(
            "plugins.qq.ocr.get_reader", return_value=object()
        ), mock.patch(
            "plugins.qq.plugin._capture_failure_screenshot"
        ):
            result = self.plugin.send(task)
        self.assertFalse(result.success)
        self.assertIn("未能确认进入群聊", result.detail)
        self.assertEqual(fake.clicks, [], "校验失败后不应点击输入框")


class LocatorAndSenderTest(unittest.TestCase):
    def test_input_target_uses_region_center(self):
        from plugins.qq import locator

        cfg = {
            "input_target": {
                "mode": "relative",
                "relative_x": 0.2,
                "relative_y": 0.8,
                "relative_w": 0.4,
                "relative_h": 0.1,
            }
        }
        x, y = locator.get_input_target((0, 0, 1000, 1000), cfg)
        self.assertEqual((x, y), (400, 850))

    def test_send_message_clear_input_false_keeps_images(self):
        from plugins.qq import sender

        class FakeGUI:
            def __init__(self):
                self.hotkeys = []
                self.presses = []

            def click(self, *a, **k):
                pass

            def hotkey(self, *a, **k):
                self.hotkeys.append(a)

            def press(self, *a, **k):
                self.presses.append(a)

            def write(self, *a, **k):
                pass

        class FakeClip:
            def copy(self, text):
                pass

        gui = FakeGUI()
        with mock.patch.object(sender, "pyautogui", gui), mock.patch.object(
            sender, "pyperclip", FakeClip()
        ):
            sender.send_message("hello", (1, 1), {}, clear_input=False)
        self.assertNotIn(("ctrl", "a"), gui.hotkeys)


class WebApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        os.makedirs(os.path.join(root, "config"), exist_ok=True)
        os.makedirs(os.path.join(root, "presets"), exist_ok=True)
        tasks_path = os.path.join(root, "config", "tasks.yaml")
        with open(tasks_path, "w", encoding="utf-8") as f:
            f.write(
                "tasks:\n"
                "  - name: t1\n"
                "    plugin: fake\n"
                "    enabled: false\n"
                "    schedule: '0 0 8 * * *'\n"
                "    message: hello\n"
            )
        self.bus = EventBus()
        self.logger = Logger(self.bus, config_path="", log_dir=root)
        self.hub = ConfigHub(
            os.path.join(root, "config"),
            os.path.join(root, "presets"),
            project_root=root,
        )
        self.pm = PluginManager(project_root=root)
        self.pm._plugins["fake"] = FakePlugin()
        self.pm._plugin_configs["fake"] = {}
        self.ledger = RunLedger(os.path.join(root, "logs", "runs.jsonl"))
        self.scheduler = Scheduler(
            self.hub, self.pm, self.bus, ledger=self.ledger
        )
        from web import app as web_app

        web_app.bind(
            self.scheduler,
            self.pm,
            self.bus,
            self.logger,
            config_tasks_path=tasks_path,
            sys_path=root,
            ledger=self.ledger,
        )
        self.client = web_app.app.test_client()
        self.app = web_app.app
        self.app.config["TESTING"] = True

    def tearDown(self):
        self.scheduler.shutdown()
        self.logger.close()
        self.tmp.cleanup()

    def test_status_and_run(self):
        resp = self.client.get("/api/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        for key in ("job_count", "running", "next_run", "plugins"):
            self.assertIn(key, data)
        run = self.client.post("/api/tasks/t1/run", json={"dry_run": True})
        self.assertEqual(run.status_code, 202, run.get_data(as_text=True))
        payload = run.get_json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["dry_run"])

    def test_create_task_reloads_jobs(self):
        resp = self.client.post(
            "/api/tasks",
            json={
                "name": "t2",
                "plugin": "fake",
                "enabled": True,
                "schedule": "0 30 9 * * *",
                "group_name": "g",
                "message": "m",
            },
        )
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        tasks = self.client.get("/api/tasks").get_json()
        self.assertEqual(len(tasks), 2)

    def test_sse_first_chunk_has_data(self):
        self.logger.info("sse-hello")
        resp = self.client.get("/api/logs/stream", buffered=False)
        try:
            chunk = next(resp.response)
        finally:
            resp.close()
        self.assertIn(b"data:", chunk)


if __name__ == "__main__":
    unittest.main()

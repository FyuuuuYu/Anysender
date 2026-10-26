# -*- coding: utf-8 -*-
"""窗口选择逻辑测试：不枚举真实窗口，纯函数验证 PID/进程/标题策略。"""

import os
import sys
import unittest
from unittest import mock

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from plugins.qq import locator  # noqa: E402
from plugins.qq.locator import WindowInfo, choose_window, window_config  # noqa: E402


def win(hwnd, pid, process, title, window_class="Chrome_WidgetWin_1"):
    return WindowInfo(hwnd, pid, process, title, (0, 0, 800, 600), window_class)


class ChooseWindowTest(unittest.TestCase):
    def test_exact_title_wins_over_prefix_and_substring(self):
        windows = [
            win(1, 100, "QQ.exe", "QQ音乐"),
            win(2, 200, "QQ.exe", "QQ工作群"),
            win(3, 300, "QQ.exe", "QQ"),
        ]
        target = choose_window(windows, window_config({}))
        self.assertEqual(target.hwnd, 3)

    def test_rejects_blacklisted_title_even_with_qq_process(self):
        windows = [win(1, 100, "QQ.exe", "QQ浏览器"), win(2, 200, "QQ.exe", "QQ")]
        target = choose_window(windows, window_config({}))
        self.assertEqual(target.hwnd, 2)

    def test_rejects_non_qq_process(self):
        windows = [
            win(1, 100, "QQMusic.exe", "QQ"),
            win(2, 200, "WeChat.exe", "QQ"),
        ]
        with self.assertRaises(RuntimeError) as ctx:
            choose_window(windows, window_config({}))
        self.assertIn("未找到 QQ 窗口", str(ctx.exception))

    def test_pid_filter_disambiguates_two_accounts(self):
        windows = [
            win(1, 100, "QQ.exe", "QQ"),
            win(2, 200, "QQ.exe", "QQ"),
        ]
        cfg = window_config({"qq_window": {"pid": 200}})
        target = choose_window(windows, cfg)
        self.assertEqual(target.pid, 200)
        self.assertEqual(target.hwnd, 2)

    def test_ambiguous_without_pid_raises(self):
        windows = [
            win(1, 100, "QQ.exe", "QQ"),
            win(2, 200, "QQ.exe", "QQ"),
        ]
        with self.assertRaises(RuntimeError) as ctx:
            choose_window(windows, window_config({}))
        self.assertIn("多个匹配", str(ctx.exception))
        self.assertIn("pid", str(ctx.exception).lower())

    def test_class_filter(self):
        windows = [
            win(1, 100, "QQ.exe", "QQ", "Chrome_WidgetWin_1"),
            win(2, 200, "QQ.exe", "QQ", "TXGuiFoundation"),
        ]
        cfg = window_config({"qq_window": {"class_names": ["TXGuiFoundation"]}})
        self.assertEqual(choose_window(windows, cfg).hwnd, 2)

    def test_window_config_falls_back_to_legacy_keywords(self):
        cfg = window_config({"qq_window_keywords": ["Tencent QQ"]})
        self.assertEqual(cfg["title_keywords"], ["Tencent QQ"])
        windows = [win(1, 100, "QQ.exe", "Tencent QQ")]
        self.assertEqual(choose_window(windows, cfg).hwnd, 1)

    def test_empty_candidates_has_actionable_message(self):
        with self.assertRaises(RuntimeError) as ctx:
            choose_window([], window_config({}))
        message = str(ctx.exception)
        self.assertIn("未找到 QQ 窗口", message)
        self.assertIn("进程名", message)

    def test_activate_qq_window_returns_refreshed_rect(self):
        target = win(7, 700, "QQ.exe", "QQ")
        with mock.patch.object(
            locator, "find_qq_window", return_value=target
        ), mock.patch.object(
            locator, "_force_foreground", return_value=True
        ), mock.patch.object(
            locator, "_window_rect", return_value=(10, 20, 810, 620)
        ), mock.patch.object(locator.time, "sleep"):
            active = locator.activate_qq_window({})
        self.assertEqual(active.hwnd, 7)
        self.assertEqual(active.rect, (10, 20, 810, 620))

    def test_activate_qq_window_fails_when_foreground_denied(self):
        target = win(7, 700, "QQ.exe", "QQ")
        with mock.patch.object(
            locator, "find_qq_window", return_value=target
        ), mock.patch.object(
            locator, "_force_foreground", return_value=False
        ), mock.patch.object(locator.time, "sleep"):
            with self.assertRaises(RuntimeError):
                locator.activate_qq_window({})


class WindowEnumSmokeTest(unittest.TestCase):
    def test_enum_windows_returns_windowinfo_objects(self):
        # 只验证本机枚举不抛异常且字段类型正确，不依赖 QQ 是否在运行。
        windows = locator.enum_windows()
        self.assertIsInstance(windows, list)
        for item in windows[:3]:
            self.assertIsInstance(item, WindowInfo)
            self.assertIsInstance(item.pid, int)
            self.assertIsInstance(item.title, str)


if __name__ == "__main__":
    unittest.main()

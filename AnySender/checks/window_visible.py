"""
窗口可见性校验

context 要求:
    keywords: list[str] — 窗口标题关键词（大小写不敏感）
"""

import ctypes
from typing import Any, Dict, List, Tuple

from .base import Check


class WindowVisibleCheck(Check):
    def get_name(self) -> str:
        return "window_visible"

    def run(self, context: Dict[str, Any]) -> Tuple[bool, str]:
        keywords = context.get("keywords", [])

        found = []
        for hwnd, title in self._enum_visible_windows():
            if any(k.lower() in title.lower() for k in keywords):
                found.append((hwnd, title))

        if found:
            hwnd, title = found[0]
            if context.get("activate", False):
                SW_RESTORE = 9
                ctypes.windll.user32.ShowWindow(hwnd, SW_RESTORE)
                ctypes.windll.user32.SetForegroundWindow(hwnd)
            return True, title

        return False, f"未找到匹配窗口: {keywords}"

    @staticmethod
    def _enum_visible_windows() -> List[Tuple[int, str]]:
        titles = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def enum_proc(hwnd, lparam):
            if ctypes.windll.user32.IsWindowVisible(hwnd):
                length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
                    t = buff.value.strip()
                    if t:
                        titles.append((hwnd, t))
            return True

        ctypes.windll.user32.EnumWindows(enum_proc, 0)
        return titles

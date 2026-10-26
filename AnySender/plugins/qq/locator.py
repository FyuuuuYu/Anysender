import ctypes
import ctypes.wintypes
import time
from difflib import SequenceMatcher
from typing import List, Tuple

import pyautogui


def enum_window_titles() -> List[Tuple[int, str]]:
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


def _force_foreground(hwnd: int) -> bool:
    """三层兜底强制窗口到前台，绝不要求用户手动介入。"""
    SW_RESTORE = 9
    VK_MENU = 0x12

    ctypes.windll.user32.ShowWindow(hwnd, SW_RESTORE)

    # 第一层：AttachThreadInput（标准方案）
    current_thread = ctypes.windll.kernel32.GetCurrentThreadId()
    fg = ctypes.windll.user32.GetForegroundWindow()
    fg_thread = ctypes.windll.user32.GetWindowThreadProcessId(fg, None)
    if current_thread != fg_thread:
        ctypes.windll.user32.AttachThreadInput(current_thread, fg_thread, True)
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        ctypes.windll.user32.AttachThreadInput(current_thread, fg_thread, False)
    else:
        ctypes.windll.user32.SetForegroundWindow(hwnd)

    time.sleep(0.15)
    if ctypes.windll.user32.GetForegroundWindow() == hwnd:
        return True

    # 第二层：模拟 Alt 键（给自己授予前台激活权限）
    ctypes.windll.user32.keybd_event(VK_MENU, 0, 0, 0)
    ctypes.windll.user32.keybd_event(VK_MENU, 0, 2, 0)
    time.sleep(0.05)
    ctypes.windll.user32.SetForegroundWindow(hwnd)

    time.sleep(0.2)
    if ctypes.windll.user32.GetForegroundWindow() == hwnd:
        return True

    # 第三层：AllowSetForegroundWindow + BringWindowToTop（终极兜底）
    ctypes.windll.user32.AllowSetForegroundWindow(-1)
    ctypes.windll.user32.BringWindowToTop(hwnd)
    ctypes.windll.user32.SetForegroundWindow(hwnd)
    time.sleep(0.2)

    return ctypes.windll.user32.GetForegroundWindow() == hwnd


def activate_qq_window(keywords: List[str]) -> Tuple[int, int, int, int]:
    windows = enum_window_titles()
    target = None
    for hwnd, title in windows:
        if any(k.lower() in title.lower() for k in keywords):
            target = hwnd
            break

    if not target:
        raise RuntimeError("未找到 QQ 窗口，请先手动打开 QQ")

    if not _force_foreground(target):
        raise RuntimeError("QQ 窗口无法激活到前台，请检查是否有其他程序锁定了焦点")

    time.sleep(0.5)

    rect = ctypes.wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(target, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def get_search_box_target(qq_rect: Tuple[int, int, int, int],
                          search_cfg: dict) -> Tuple[int, int]:
    left, top, right, bottom = qq_rect
    width, height = right - left, bottom - top
    rx = float(search_cfg.get("relative_x", 0.50))
    ry = float(search_cfg.get("relative_y", 0.08))
    rw = float(search_cfg.get("relative_w", 0))
    rh = float(search_cfg.get("relative_h", 0))
    x = int(left + width * (rx + rw / 2))
    y = int(top + height * (ry + rh / 2))
    return x, y


def get_input_target(qq_rect: Tuple[int, int, int, int],
                     cfg: dict) -> Tuple[int, int]:
    sec = cfg.get("input_target", {})
    mode = sec.get("mode", "relative")
    conf = float(cfg.get("confidence", 0.85))

    if mode == "template":
        tpl = sec.get("template_path", "")
        p = pyautogui.locateCenterOnScreen(tpl, confidence=conf)
        if p:
            return p.x, p.y
        raise RuntimeError(f"模板匹配失败: {tpl}")

    left, top, right, bottom = qq_rect
    width, height = right - left, bottom - top
    rx = float(sec.get("relative_x", 0.50))
    ry = float(sec.get("relative_y", 0.86))
    rw = float(sec.get("relative_w", 0) or 0)
    rh = float(sec.get("relative_h", 0) or 0)
    # 校准器存的是整个输入区域的 bbox；点在区域中心而不是左上角。
    # 旧实现忽略 relative_w/h，点击点会落在区域左上边缘（按钮/边框上）。
    cx = rx + rw / 2 if rw > 0 else rx
    cy = ry + rh / 2 if rh > 0 else ry
    if not (0.0 <= cx <= 1.0 and 0.0 <= cy <= 1.0):
        raise RuntimeError(
            f"input_target 相对坐标越界: ({cx:.4f}, {cy:.4f})"
        )
    x = int(left + width * cx)
    y = int(top + height * cy)
    if not point_in_rect(x, y, qq_rect):
        raise RuntimeError(
            f"input_target 点击点落在 QQ 窗口外: ({x}, {y}) / {qq_rect}"
        )
    return x, y


def point_in_rect(x: int, y: int, rect: Tuple[int, int, int, int],
                  margin: int = 2) -> bool:
    left, top, right, bottom = rect
    return (left + margin) <= x <= (right - margin) and (
        top + margin
    ) <= y <= (bottom - margin)


def get_validation_region(qq_rect: Tuple[int, int, int, int],
                          cfg: dict) -> Tuple[int, int, int, int]:
    sec = cfg.get("validation_region", {})
    left, top, right, bottom = qq_rect
    width, height = right - left, bottom - top

    x = int(left + width * float(sec.get("relative_x", 0.22)))
    y = int(top + height * float(sec.get("relative_y", 0.79)))
    w = max(20, int(width * float(sec.get("relative_w", 0.70))))
    h = max(20, int(height * float(sec.get("relative_h", 0.17))))
    return x, y, w, h


def open_group_chat(group_name: str, wait_sec: float,
                    cfg: dict, qq_rect: Tuple[int, int, int, int]) -> None:
    pyautogui.hotkey("ctrl", "f")
    time.sleep(0.5)  # 等 QQ 搜索面板完全渲染

    search_cfg = cfg.get("search_box_target") or cfg.get("search_box", {})
    # 点搜索框偏右内侧（避开边框和图标，命中文字输入区）
    rx = float(search_cfg.get("relative_x", 0.05))
    ry = float(search_cfg.get("relative_y", 0.08))
    rw = float(search_cfg.get("relative_w", 0.20))
    rh = float(search_cfg.get("relative_h", 0.05))
    left, top, right, bottom = qq_rect
    win_w, win_h = right - left, bottom - top
    click_x = int(left + win_w * (rx + rw * 0.6))
    click_y = int(top + win_h * (ry + rh * 0.5))
    pyautogui.click(click_x, click_y)
    time.sleep(0.15)

    import pyperclip
    pyperclip.copy(group_name)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.1)
    pyautogui.press("enter")
    time.sleep(wait_sec)


def verify_group_chat_opened(group_name: str, min_similarity: float = 0.6) -> bool:
    """检查当前前台窗口标题是否包含目标群名（精确 + 模糊两段匹配）。"""
    time.sleep(0.3)
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return False
    buff = ctypes.create_unicode_buffer(length + 1)
    ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
    title = buff.value
    target = group_name.lower()

    # 第一段：精确包含
    if target in title.lower():
        return True

    # 第二段：滑窗模糊匹配
    if len(title) >= len(target):
        for i in range(len(title) - len(target) + 1):
            sub = title[i:i + len(target)].lower()
            if SequenceMatcher(None, target, sub).ratio() >= min_similarity:
                return True

    return False


def get_foreground_window_title() -> str:
    """获取当前前台窗口标题（调试用）。"""
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return ""
    buff = ctypes.create_unicode_buffer(length + 1)
    ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
    return buff.value

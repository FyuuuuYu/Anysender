import ctypes
import ctypes.wintypes
import os
import time
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from typing import List, Optional, Tuple

import pyautogui

# ---- 默认窗口识别策略 -------------------------------------------------
DEFAULT_PROCESS_NAMES = ["QQ.exe", "QQNT.exe"]
DEFAULT_TITLE_KEYWORDS = ["QQ", "Tencent QQ"]
DEFAULT_TITLE_EXCLUDE = ["QQ音乐", "QQ浏览器", "QQ频道", "QQ游戏", "QQ空间"]

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

_kernel32 = ctypes.windll.kernel32
_user32 = ctypes.windll.user32
_kernel32.OpenProcess.restype = ctypes.wintypes.HANDLE
_kernel32.OpenProcess.argtypes = [
    ctypes.wintypes.DWORD,
    ctypes.wintypes.BOOL,
    ctypes.wintypes.DWORD,
]
_kernel32.QueryFullProcessImageNameW.restype = ctypes.wintypes.BOOL
_kernel32.QueryFullProcessImageNameW.argtypes = [
    ctypes.wintypes.HANDLE,
    ctypes.wintypes.DWORD,
    ctypes.wintypes.LPWSTR,
    ctypes.POINTER(ctypes.wintypes.DWORD),
]
_kernel32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
_kernel32.CloseHandle.restype = ctypes.wintypes.BOOL


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    pid: int
    process: str
    title: str
    rect: Tuple[int, int, int, int]
    window_class: str = ""


def _process_name(pid: int) -> str:
    """返回进程映像文件名（如 QQ.exe）；拿不到时返回空串。"""
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = ctypes.wintypes.DWORD(len(buf))
        ok = _kernel32.QueryFullProcessImageNameW(
            handle, 0, buf, ctypes.byref(size)
        )
        return os.path.basename(buf.value) if ok else ""
    finally:
        _kernel32.CloseHandle(handle)


def _window_title(hwnd: int) -> str:
    length = _user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buff = ctypes.create_unicode_buffer(length + 1)
    _user32.GetWindowTextW(hwnd, buff, length + 1)
    return buff.value.strip()


def _window_class(hwnd: int) -> str:
    buff = ctypes.create_unicode_buffer(256)
    _user32.GetClassNameW(hwnd, buff, 256)
    return buff.value


def _window_rect(hwnd: int) -> Tuple[int, int, int, int]:
    rect = ctypes.wintypes.RECT()
    _user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def enum_windows() -> List[WindowInfo]:
    """枚举所有可见、有标题、面积为正的顶层窗口，附带 PID/进程名/类名。"""
    windows: List[WindowInfo] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def enum_proc(hwnd, _lparam):
        if not _user32.IsWindowVisible(hwnd):
            return True
        title = _window_title(hwnd)
        if not title:
            return True
        pid = ctypes.wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        rect = _window_rect(hwnd)
        if rect[2] - rect[0] <= 0 or rect[3] - rect[1] <= 0:
            return True
        windows.append(
            WindowInfo(
                hwnd=int(hwnd),
                pid=int(pid.value),
                process=_process_name(pid.value),
                title=title,
                rect=rect,
                window_class=_window_class(hwnd),
            )
        )
        return True

    _user32.EnumWindows(enum_proc, 0)
    return windows


def enum_window_titles() -> List[Tuple[int, str]]:
    """兼容旧调用：只返回 (hwnd, title)。"""
    return [(w.hwnd, w.title) for w in enum_windows()]


def window_config(cfg: dict) -> dict:
    """从插件配置提取窗口识别参数，兼容旧的 qq_window_keywords。"""
    raw = cfg.get("qq_window") or {}
    wc = dict(raw) if isinstance(raw, dict) else {}
    wc.setdefault(
        "title_keywords",
        cfg.get("qq_window_keywords") or list(DEFAULT_TITLE_KEYWORDS),
    )
    wc.setdefault("title_exclude", list(DEFAULT_TITLE_EXCLUDE))
    wc.setdefault("process_names", list(DEFAULT_PROCESS_NAMES))
    wc.setdefault("class_names", [])
    try:
        wc["pid"] = int(wc.get("pid") or 0)
    except (TypeError, ValueError):
        wc["pid"] = 0
    return wc


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value if str(v).strip()]


def _title_score(title: str, keywords: List[str]) -> int:
    t = title.lower()
    best = 0
    for keyword in keywords:
        k = str(keyword).strip().lower()
        if not k:
            continue
        if t == k:
            return 3
        if t.startswith(k):
            best = max(best, 2)
        elif k in t:
            best = max(best, 1)
    return best


def choose_window(windows: List[WindowInfo], cfg: dict) -> WindowInfo:
    """在候选窗口中选择目标；纯函数，便于单测。

    过滤顺序：PID → 进程名 → 类名 → 标题黑名单 → 标题关键词评分。
    评分相同且不止一个时拒绝猜测，要求用 qq_window.pid 指定。
    """
    keywords = _as_list(cfg.get("title_keywords")) or list(DEFAULT_TITLE_KEYWORDS)
    excludes = _as_list(cfg.get("title_exclude"))
    process_names = {p.lower() for p in _as_list(cfg.get("process_names"))}
    class_names = {c.lower() for c in _as_list(cfg.get("class_names"))}
    pid_filter = int(cfg.get("pid") or 0)

    candidates = list(windows)
    if pid_filter:
        candidates = [w for w in candidates if w.pid == pid_filter]
    if process_names:
        candidates = [
            w for w in candidates if w.process.lower() in process_names
        ]
    if class_names:
        candidates = [
            w for w in candidates if w.window_class.lower() in class_names
        ]
    if excludes:
        lowered = [e.lower() for e in excludes]
        candidates = [
            w
            for w in candidates
            if not any(e in w.title.lower() for e in lowered)
        ]

    scored = [(w, _title_score(w.title, keywords)) for w in candidates]
    scored = [(w, s) for w, s in scored if s > 0]
    if not scored:
        parts = []
        if pid_filter:
            parts.append(f"PID={pid_filter}")
        if process_names:
            parts.append("进程名=" + "/".join(sorted(process_names)))
        parts.append("标题包含=" + "/".join(keywords))
        hint = "，".join(parts)
        visible = "；".join(
            f"{w.title}({w.process or '?'},pid={w.pid})" for w in windows[:5]
        )
        raise RuntimeError(
            f"未找到 QQ 窗口（{hint}）。当前可见窗口：{visible or '无'}"
        )

    top_score = max(score for _, score in scored)
    top = [w for w, score in scored if score == top_score]
    if len(top) > 1:
        detail = "；".join(
            f"{w.title}(pid={w.pid},{w.process})" for w in top
        )
        raise RuntimeError(
            f"找到多个匹配的 QQ 窗口，无法确定目标：{detail}。"
            "请在 config/plugins/qq.yaml 的 qq_window.pid 指定其中一个。"
        )
    return top[0]


def find_qq_window(cfg: dict) -> WindowInfo:
    return choose_window(enum_windows(), window_config(cfg))


def is_foreground(hwnd: int) -> bool:
    return int(_user32.GetForegroundWindow() or 0) == int(hwnd)


def _force_foreground(hwnd: int) -> bool:
    """三层兜底强制窗口到前台，绝不要求用户手动介入。"""
    SW_RESTORE = 9
    VK_MENU = 0x12

    # 只在最小化时恢复；否则不动用户已有的最大化/尺寸状态。
    if _user32.IsIconic(hwnd):
        _user32.ShowWindow(hwnd, SW_RESTORE)

    # 第一层：AttachThreadInput（标准方案）
    current_thread = _kernel32.GetCurrentThreadId()
    fg = _user32.GetForegroundWindow()
    fg_thread = _user32.GetWindowThreadProcessId(fg, None)
    if current_thread != fg_thread:
        _user32.AttachThreadInput(current_thread, fg_thread, True)
        _user32.SetForegroundWindow(hwnd)
        _user32.AttachThreadInput(current_thread, fg_thread, False)
    else:
        _user32.SetForegroundWindow(hwnd)

    time.sleep(0.15)
    if is_foreground(hwnd):
        return True

    # 第二层：模拟 Alt 键（给自己授予前台激活权限）
    _user32.keybd_event(VK_MENU, 0, 0, 0)
    _user32.keybd_event(VK_MENU, 0, 2, 0)
    time.sleep(0.05)
    _user32.SetForegroundWindow(hwnd)

    time.sleep(0.2)
    if is_foreground(hwnd):
        return True

    # 第三层：AllowSetForegroundWindow + BringWindowToTop（终极兜底）
    _user32.AllowSetForegroundWindow(-1)
    _user32.BringWindowToTop(hwnd)
    _user32.SetForegroundWindow(hwnd)
    time.sleep(0.2)

    return is_foreground(hwnd)


def activate_qq_window(cfg) -> WindowInfo:
    """按 PID/进程名/标题定位并激活 QQ，返回带最新 rect 的目标窗口。

    兼容旧签名：cfg 也可以直接是关键词列表。
    """
    if isinstance(cfg, (list, tuple)):
        cfg = {"title_keywords": list(cfg)}
    target = find_qq_window(cfg)
    if not _force_foreground(target.hwnd):
        raise RuntimeError(
            f"QQ 窗口无法激活到前台（hwnd={target.hwnd}, pid={target.pid}），"
            "请检查是否有其他程序锁定了焦点"
        )
    time.sleep(0.5)
    return replace(target, rect=_window_rect(target.hwnd))


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
    hwnd = _user32.GetForegroundWindow()
    length = _user32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return False
    buff = ctypes.create_unicode_buffer(length + 1)
    _user32.GetWindowTextW(hwnd, buff, length + 1)
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
    hwnd = _user32.GetForegroundWindow()
    length = _user32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return ""
    buff = ctypes.create_unicode_buffer(length + 1)
    _user32.GetWindowTextW(hwnd, buff, length + 1)
    return buff.value

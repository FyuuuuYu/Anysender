"""
列表遍历模式 & OCR 辅助函数

用 easyocr 识别文字。
"""

import os
import time
from difflib import SequenceMatcher
from typing import Optional, Tuple

import numpy as np
import pyautogui

_reader = None


def _get_reader():
    global _reader
    if _reader is None:
        import easyocr
        _reader = easyocr.Reader(["ch_sim", "en"], gpu=False)
    return _reader


def _ocr_region(screenshot, target: str, min_ratio: float = 0.5, save_path: str = ""):
    """OCR 识别截图文字，返回最佳匹配的 (cx_local, cy_local, ratio) 或 None。"""
    import cv2
    reader = _get_reader()
    img = np.array(screenshot)

    try:
        results = reader.readtext(img)
    except Exception as e:
        import traceback, logging
        logging.getLogger("AnySender").warning(f"OCR 异常: {e}\n{traceback.format_exc()}")
        return None

    if save_path:
        cv2.imwrite(save_path, cv2.cvtColor(img, cv2.COLOR_RGB2BGR))

    if not results:
        import logging
        logging.getLogger("AnySender").warning("OCR 未识别到任何文字")
        return None

    best, best_ratio = None, 0.0
    for bbox, text, conf in results:
        text = text.strip()
        if not text:
            continue
        ratio = SequenceMatcher(None, target.lower(), text.lower()).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            best = (int(sum(xs) / len(xs)), int(sum(ys) / len(ys)), ratio)

    if best and best[2] >= min_ratio:
        import logging
        logging.getLogger("AnySender").info(f"OCR 匹配: {target} ratio={best[2]:.2f}")
        return best
    import logging
    logging.getLogger("AnySender").info(f"OCR 未匹配: best={best_ratio:.2f} >={min_ratio}")
    return None


def _failed_path(name: str, ts: str) -> str:
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    d = os.path.join(base, "screenshots", "failed", name)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{name}_{ts}_ocr.png")


def browse_to_group(
    group_name: str,
    contact_list_cfg: dict,
    qq_rect: Tuple[int, int, int, int],
    max_scrolls: int = 10,
) -> Optional[Tuple[int, int]]:
    left, top, right, bottom = qq_rect
    win_w, win_h = right - left, bottom - top

    rx = float(contact_list_cfg.get("relative_x", 0.05))
    ry = float(contact_list_cfg.get("relative_y", 0.15))
    rw = float(contact_list_cfg.get("relative_w", 0.25))
    rh = float(contact_list_cfg.get("relative_h", 0.80))

    region_x = int(left + win_w * rx)
    region_y = int(top + win_h * ry)
    region_w = int(win_w * rw)
    region_h = int(win_h * rh)

    pyautogui.click(region_x + region_w // 2, region_y + 40)
    time.sleep(0.15)
    pyautogui.press("home")
    time.sleep(0.2)

    for _ in range(max_scrolls):
        shot = pyautogui.screenshot(region=(region_x, region_y, region_w, region_h))
        match = _ocr_region(shot, group_name)
        if match:
            cx, cy, _ = match
            return (region_x + cx, region_y + cy)
        pyautogui.press("pagedown")
        time.sleep(0.15)

    return None


def select_search_result(
    group_name: str,
    search_box_cfg: dict,
    qq_rect: Tuple[int, int, int, int],
) -> Optional[Tuple[int, int]]:
    left, top, right, bottom = qq_rect
    win_w, win_h = right - left, bottom - top

    sb_rx = float(search_box_cfg.get("relative_x", 0.05))
    sb_ry = float(search_box_cfg.get("relative_y", 0.08))
    sb_rw = float(search_box_cfg.get("relative_w", 0.20))
    sb_rh = float(search_box_cfg.get("relative_h", 0.05))

    region_x = int(left + win_w * sb_rx)
    region_y = int(top + win_h * (sb_ry + sb_rh))
    region_w = int(win_w * sb_rw)
    region_h = int(win_h * 0.25)

    shot = pyautogui.screenshot(region=(region_x, region_y, region_w, region_h))
    match = _ocr_region(shot, group_name, min_ratio=0.6)
    if match:
        cx, cy, _ = match
        return (region_x + cx, region_y + cy)
    from datetime import datetime
    _ocr_region(shot, group_name, min_ratio=0.6,
                save_path=_failed_path("search_ocr", datetime.now().strftime("%Y%m%d_%H%M%S")))
    return None


def verify_chat_opened(
    group_name: str,
    chat_header_cfg: dict,
    qq_rect: Tuple[int, int, int, int],
) -> bool:
    left, top, right, bottom = qq_rect
    win_w, win_h = right - left, bottom - top

    rx = float(chat_header_cfg.get("relative_x", 0.30))
    ry = float(chat_header_cfg.get("relative_y", 0.05))
    rw = float(chat_header_cfg.get("relative_w", 0.45))
    rh = float(chat_header_cfg.get("relative_h", 0.08))

    region_x = int(left + win_w * rx)
    region_y = int(top + win_h * ry)
    region_w = int(win_w * rw)
    region_h = int(win_h * rh)

    shot = pyautogui.screenshot(region=(region_x, region_y, region_w, region_h))
    match = _ocr_region(shot, group_name)
    if match is None:
        from datetime import datetime
        _ocr_region(shot, group_name,
                     save_path=_failed_path("chat_verify", datetime.now().strftime("%Y%m%d_%H%M%S")))
        return False
    return True

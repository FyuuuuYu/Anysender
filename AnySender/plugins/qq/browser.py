"""
列表遍历模式 & OCR 辅助函数

OCR 引擎细节见 ocr.py：小图放大、失败重试、统一 numpy 输入。
"""

import logging
import os
import re
import time
import unicodedata
from difflib import SequenceMatcher
from typing import Optional, Tuple

import numpy as np
import pyautogui

from . import ocr

logger = logging.getLogger("AnySender")

# 去掉空白与常见中英文标点，只留下文字本身，避免「飞鱼的记事本（12）」
# 因为括号/空格导致 SequenceMatcher 分数被拉低。
_STRIP_RE = re.compile(
    r"[\s\u3000·•\-—_.,，。:：;；!！?？'\"“”‘’"
    r"()\[\]{}<>《》【】、|/\\]+"
)


def _get_reader():
    return ocr.get_reader()


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text or "")).lower()
    return _STRIP_RE.sub("", text)


def _similarity(target: str, text: str) -> float:
    a, b = _normalize(target), _normalize(text)
    if not a or not b:
        return 0.0
    ratio = SequenceMatcher(None, a, b).ratio()
    # OCR 常把群名读成「群名(12)」「群名 12人」；包含关系应视为高匹配。
    if len(a) >= 2 and (a in b or b in a):
        ratio = max(
            ratio, 0.85 + 0.15 * min(len(a), len(b)) / max(len(a), len(b))
        )
    return ratio


def _confident_match(target: str, text: str) -> bool:
    """群头校验用的严格匹配：宁可漏认，也不把「工作群2」当成「工作群」。"""
    raw = str(text or "")
    a, b = _normalize(target), _normalize(raw)
    if not a or not b:
        return False
    if a == b:
        return True
    # 「群名（12）」「群名(3人)」这类成员数后缀是允许的；裸数字后缀不算。
    if re.search(r"[（(]\s*\d{1,5}\s*人?\s*[)）]\s*$", raw) and a in b:
        return True
    # OCR 漏字/多字但整体高度相似（长度差 ≤2，相似度 ≥0.9）。
    if abs(len(a) - len(b)) <= 2:
        return SequenceMatcher(None, a, b).ratio() >= 0.9
    return False


def _ocr_region(
    screenshot,
    target: str,
    min_ratio: float = 0.5,
    save_path: str = "",
    confident: bool = False,
):
    """OCR 识别截图文字，返回最佳匹配的 (cx_local, cy_local, ratio) 或 None。

    confident=True 时使用 _confident_match（群头校验），否则使用相似度阈值。
    """
    try:
        results = ocr.recognize(screenshot)
    except ocr.OCRUnavailable as exc:
        logger.error("OCR 不可用，本次无法定位/校验: %s", exc)
        return None
    except Exception as exc:
        logger.warning("OCR 输入异常: %s", exc)
        return None

    if save_path:
        ocr.save_image(screenshot, save_path)

    if not results:
        logger.warning("OCR 未识别到任何文字（目标=%s）", target)
        return None

    best, best_ratio = None, 0.0
    for bbox, text, _conf in results:
        text = (text or "").strip()
        if not text:
            continue
        ratio = _similarity(target, text)
        passed = _confident_match(target, text) if confident else ratio >= min_ratio
        if passed and ratio > best_ratio:
            best_ratio = ratio
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            best = (int(sum(xs) / len(xs)), int(sum(ys) / len(ys)), ratio)

    if best:
        logger.info("OCR 匹配: %s ratio=%.2f", target, best[2])
        return best
    logger.info(
        "OCR 未匹配: target=%s best=%.2f 阈值=%.2f confident=%s",
        target,
        best_ratio,
        min_ratio,
        confident,
    )
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

    path = _failed_path("search_ocr", datetime.now().strftime("%Y%m%d_%H%M%S"))
    ocr.save_image(shot, path)
    logger.warning("搜索结果未匹配目标群，截图: %s", path)
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
    match = _ocr_region(shot, group_name, confident=True)
    if match is not None:
        return True

    from datetime import datetime

    path = _failed_path("chat_verify", datetime.now().strftime("%Y%m%d_%H%M%S"))
    ocr.save_image(shot, path)
    logger.warning("群头校验失败，截图: %s", path)
    return False

import os
import re
from datetime import datetime
from typing import Any, Dict, Tuple

import cv2
import numpy as np
import pyautogui
from skimage.metrics import structural_similarity as ssim

_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _slug(name: str, max_len: int = 60) -> str:
    """任务名用于目录/文件名时做安全化，避免中文标点与非法字符。"""
    value = _BAD_CHARS.sub("_", str(name or "unnamed")).strip(" .")
    return (value or "unnamed")[:max_len]


def _imread_unicode(path: str):
    """cv2.imread 不支持中文路径，用 imdecode 绕过去。"""
    data = np.fromfile(path, dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def hdr_robust_similarity(img_a_bgr: np.ndarray,
                          img_b_bgr: np.ndarray,
                          cfg: Dict[str, Any]) -> Tuple[float, Dict[str, float]]:
    size = (420, 220)
    a = cv2.resize(img_a_bgr, size, interpolation=cv2.INTER_AREA)
    b = cv2.resize(img_b_bgr, size, interpolation=cv2.INTER_AREA)

    a_l = cv2.cvtColor(a, cv2.COLOR_BGR2LAB)[:, :, 0]
    b_l = cv2.cvtColor(b, cv2.COLOR_BGR2LAB)[:, :, 0]
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    a_l = clahe.apply(a_l)
    b_l = clahe.apply(b_l)

    a_l = cv2.GaussianBlur(a_l, (3, 3), 0)
    b_l = cv2.GaussianBlur(b_l, (3, 3), 0)
    luma_score = float(ssim(a_l, b_l, data_range=255))

    a_e = cv2.Canny(a_l, 60, 140)
    b_e = cv2.Canny(b_l, 60, 140)
    edge_score = float(ssim(a_e, b_e, data_range=255))

    hist_a = cv2.calcHist([a_l], [0], None, [64], [0, 256])
    hist_b = cv2.calcHist([b_l], [0], None, [64], [0, 256])
    cv2.normalize(hist_a, hist_a)
    cv2.normalize(hist_b, hist_b)
    hist_score = float(cv2.compareHist(hist_a, hist_b, cv2.HISTCMP_CORREL))
    hist_score = max(0.0, min(1.0, (hist_score + 1.0) / 2.0))

    vw = cfg.get("validation", {})
    luma_w = float(vw.get("luma_weight", 0.65))
    edge_w = float(vw.get("edge_weight", 0.25))
    hist_w = float(vw.get("hist_weight", 0.10))

    total = luma_score * luma_w + edge_score * edge_w + hist_score * hist_w
    total = max(0.0, min(1.0, total))
    return total, {
        "luma": luma_score,
        "edge": edge_score,
        "hist": hist_score,
        "total": total,
    }


def validate_input_effect(task: dict, cfg: dict, qq_rect: tuple,
                          base_dir: str) -> Tuple[bool, str]:
    val_cfg = cfg.get("validation", {})
    task_name = _slug(task.get("name", "unnamed"))
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    from .locator import get_validation_region
    x, y, w, h = get_validation_region(qq_rect, cfg)
    shot = pyautogui.screenshot(region=(x, y, w, h))

    # 校验关闭时：截图存档但不校验
    if not bool(val_cfg.get("enabled", True)):
        done_dir = os.path.join(base_dir, "screenshots", "done")
        os.makedirs(done_dir, exist_ok=True)
        path = os.path.join(done_dir, f"{task_name}_{ts}_ok.png")
        shot.save(path)
        return True, f"截图已保存: {path}"

    tpl = val_cfg.get("template_path", "")
    if not tpl:
        return False, "validation.template_path 为空"

    min_score = float(val_cfg.get("min_similarity", 0.82))

    shot_bgr = cv2.cvtColor(np.array(shot), cv2.COLOR_RGB2BGR)
    ref_bgr = _imread_unicode(tpl)
    if ref_bgr is None:
        raise RuntimeError(f"无法读取校验模板图: {tpl}")

    temp_dir = os.path.join(base_dir, "screenshots", "temp")
    failed_root = os.path.join(base_dir, "screenshots", "failed")
    os.makedirs(temp_dir, exist_ok=True)
    os.makedirs(failed_root, exist_ok=True)

    temp_path = os.path.join(temp_dir, f"{task_name}_{ts}.png")
    cv2.imwrite(temp_path, shot_bgr)

    score, detail = hdr_robust_similarity(shot_bgr, ref_bgr, cfg)
    if score >= min_score:
        os.remove(temp_path)
        return True, (
            f"total={detail['total']:.4f} "
            f"(luma={detail['luma']:.4f}, edge={detail['edge']:.4f}, hist={detail['hist']:.4f})"
        )

    failed_dir = os.path.join(failed_root, task_name, datetime.now().strftime("%Y%m%d"))
    os.makedirs(failed_dir, exist_ok=True)
    dst = os.path.join(failed_dir, f"{task_name}_{ts}_LOW_{score:.4f}.png")
    os.replace(temp_path, dst)
    return False, f"total={detail['total']:.4f} < {min_score:.4f}，截图保留: {dst}"

"""OCR 引擎封装：延迟加载、失败重试、小图自适应放大。

设计目标：
- 只暴露 recognize(image) 一个入口，输入统一为 RGB numpy / PIL / 路径；
- 群头截图通常只有 30–50px 高，13px 字在原始尺度下 easyocr 很容易把
  「飞」认成「7」；这里按高度自动放大 2–3 倍，实测置信度从 0.19 回到 0.93；
- easyocr/torch 的 DLL 初始化偶发 WinError 1114，加载失败重试 3 次并缓存
  错误，避免每次发送都卡在同一个坏状态上；
- 失败时抛 OCRUnavailable，由调用方决定「中止发送」还是「跳过 OCR」。
"""

import logging
import os
import time
import warnings

import cv2
import numpy as np

logger = logging.getLogger("AnySender")

READER_LANGS = ["ch_sim", "en"]
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SEC = 1.0
FAIL_COOLDOWN_SEC = 60.0
MAX_SIDE = 2400

_reader = None
_init_error = None
_failed_at = 0.0


class OCRUnavailable(RuntimeError):
    """OCR 引擎不可用（模型加载失败/识别过程异常）。"""


def reset():
    """测试或热修复时重置缓存的 Reader。"""
    global _reader, _init_error, _failed_at
    _reader = None
    _init_error = None
    _failed_at = 0.0


def status():
    return {
        "ready": _reader is not None,
        "error": _init_error or "",
        "langs": list(READER_LANGS),
    }


def _load_easyocr():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        import easyocr

        return easyocr.Reader(READER_LANGS, gpu=False, verbose=False)


def get_reader(force: bool = False):
    """返回缓存的 easyocr.Reader；失败重试并抛 OCRUnavailable。"""
    global _reader, _init_error, _failed_at

    if _reader is not None and not force:
        return _reader

    now = time.time()
    if (
        not force
        and _init_error
        and now - _failed_at < FAIL_COOLDOWN_SEC
    ):
        raise OCRUnavailable(f"OCR 引擎不可用（{_init_error}）")

    last_exc = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            _reader = _load_easyocr()
            _init_error = None
            _failed_at = 0.0
            logger.info("OCR 引擎就绪（easyocr: %s）", "+".join(READER_LANGS))
            return _reader
        except Exception as exc:  # DLL/模型/依赖异常都走重试
            last_exc = exc
            logger.warning(
                "OCR 引擎初始化失败（第 %d/%d 次）: %s",
                attempt,
                RETRY_ATTEMPTS,
                exc,
            )
            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_BACKOFF_SEC * attempt)

    _init_error = f"{type(last_exc).__name__}: {last_exc}"
    _failed_at = time.time()
    raise OCRUnavailable(f"OCR 引擎不可用：{_init_error}") from last_exc


def _to_rgb(image):
    """把 PIL / 路径 / numpy（RGB、RGBA、灰度）统一成 RGB uint8。"""
    if isinstance(image, (str, bytes, os.PathLike)):
        path = os.fspath(image)
        raw = np.fromfile(path, dtype=np.uint8)
        bgr = cv2.imdecode(raw, cv2.IMREAD_COLOR)
        if bgr is None:
            raise ValueError(f"无法读取图片: {path}")
        return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

    img = np.asarray(image)
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
    elif img.ndim == 3 and img.shape[2] == 4:
        img = cv2.cvtColor(img, cv2.COLOR_RGBA2RGB)
    elif img.ndim == 3 and img.shape[2] == 3:
        pass
    else:
        raise ValueError(f"不支持的图片形状: {img.shape}")

    if img.dtype != np.uint8:
        img = np.clip(img, 0, 255).astype(np.uint8)
    return np.ascontiguousarray(img)


def _maybe_upscale(img):
    """小截图放大后再 OCR；群头/搜索结果这类窄条收益最明显。"""
    h, w = img.shape[:2]
    if h <= 0 or w <= 0:
        return img
    if h < 80:
        scale = 3
    elif h < 160:
        scale = 2
    else:
        scale = 1
    longest = max(h, w)
    if longest * scale > MAX_SIDE:
        scale = max(1, MAX_SIDE // longest)
    if scale > 1:
        img = cv2.resize(
            img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC
        )
    return img


def recognize(image):
    """返回 easyocr 的 [(bbox, text, confidence), ...]。

    失败抛 OCRUnavailable；调用方应记录并中止发送，而不是静默跳过校验。
    """
    reader = get_reader()
    img = _maybe_upscale(_to_rgb(image))
    try:
        return reader.readtext(img)
    except Exception as exc:
        raise OCRUnavailable(f"OCR 识别失败: {exc}") from exc


def warm_up() -> bool:
    """后台预热用；失败只记日志，不抛异常。"""
    try:
        get_reader()
        return True
    except OCRUnavailable as exc:
        logger.error("%s", exc)
        return False


def save_image(image, path: str) -> bool:
    """用 imencode + tofile 保存，兼容中文路径。"""
    try:
        img = _to_rgb(image)
        ok, buf = cv2.imencode(".png", cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
        if not ok:
            return False
        buf.tofile(path)
        return True
    except Exception as exc:
        logger.warning("保存 OCR 截图失败 %s: %s", path, exc)
        return False

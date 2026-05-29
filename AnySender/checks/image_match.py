"""
图像相似度校验（HDR 鲁棒）

算法: LAB-L 通道 + CLAHE 均衡化 + SSIM 结构比较 + Canny 边缘 + 灰度直方图
目标: 在屏幕亮度变化（HDR/自动亮度）下仍保持高判别力。

context 要求:
    screenshot:    np.ndarray (BGR) — 屏幕截取区域
    template:      np.ndarray (BGR) — 参考模板图
    min_similarity: float (0-1)     — 通过阈值
    luma_weight:   float (0-1)      — 亮度结构权重
    edge_weight:   float (0-1)      — 边缘结构权重
    hist_weight:   float (0-1)      — 直方图权重
"""

from typing import Any, Dict, Tuple

import cv2
import numpy as np
from skimage.metrics import structural_similarity as ssim

from .base import Check


class ImageMatchCheck(Check):
    def get_name(self) -> str:
        return "image_match"

    def run(self, context: Dict[str, Any]) -> Tuple[bool, str]:
        screenshot = context["screenshot"]
        template = context["template"]
        min_sim = float(context.get("min_similarity", 0.82))
        luma_w = float(context.get("luma_weight", 0.65))
        edge_w = float(context.get("edge_weight", 0.25))
        hist_w = float(context.get("hist_weight", 0.10))

        size = (420, 220)
        a = cv2.resize(screenshot, size, interpolation=cv2.INTER_AREA)
        b = cv2.resize(template, size, interpolation=cv2.INTER_AREA)

        # LAB-L + CLAHE: 消除亮度偏移干扰
        a_l = cv2.cvtColor(a, cv2.COLOR_BGR2LAB)[:, :, 0]
        b_l = cv2.cvtColor(b, cv2.COLOR_BGR2LAB)[:, :, 0]
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        a_l = clahe.apply(a_l)
        b_l = clahe.apply(b_l)

        # 去噪后结构比较
        a_l = cv2.GaussianBlur(a_l, (3, 3), 0)
        b_l = cv2.GaussianBlur(b_l, (3, 3), 0)
        luma_score = float(ssim(a_l, b_l, data_range=255))

        # 边缘结构（弱化亮度偏移）
        a_e = cv2.Canny(a_l, 60, 140)
        b_e = cv2.Canny(b_l, 60, 140)
        edge_score = float(ssim(a_e, b_e, data_range=255))

        # 灰度直方图相关性
        hist_a = cv2.calcHist([a_l], [0], None, [64], [0, 256])
        hist_b = cv2.calcHist([b_l], [0], None, [64], [0, 256])
        cv2.normalize(hist_a, hist_a)
        cv2.normalize(hist_b, hist_b)
        raw = cv2.compareHist(hist_a, hist_b, cv2.HISTCMP_CORREL)
        hist_score = max(0.0, min(1.0, (float(raw) + 1.0) / 2.0))

        total = luma_score * luma_w + edge_score * edge_w + hist_score * hist_w
        total = max(0.0, min(1.0, total))

        detail = (
            f"total={total:.4f} "
            f"(luma={luma_score:.4f}, edge={edge_score:.4f}, hist={hist_score:.4f})"
        )

        if total >= min_sim:
            return True, detail
        return False, detail

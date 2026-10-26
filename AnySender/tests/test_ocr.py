import os
import sys
import unittest
from unittest import mock

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.qq import browser, ocr  # noqa: E402


class OcrWrapperTest(unittest.TestCase):
    def setUp(self):
        ocr.reset()

    def tearDown(self):
        ocr.reset()

    def test_to_rgb_accepts_gray_and_rgba(self):
        gray = np.zeros((10, 12), dtype=np.uint8)
        rgb = ocr._to_rgb(gray)
        self.assertEqual(rgb.shape, (10, 12, 3))

        rgba = np.zeros((10, 12, 4), dtype=np.uint8)
        rgba[..., 3] = 255
        self.assertEqual(ocr._to_rgb(rgba).shape, (10, 12, 3))

    def test_to_rgb_rejects_path_string(self):
        with self.assertRaises(Exception):
            ocr._to_rgb("Z:/definitely/missing.png")

    def test_small_image_is_upscaled(self):
        img = np.zeros((44, 600, 3), dtype=np.uint8)
        out = ocr._maybe_upscale(img)
        self.assertEqual(out.shape[0], 44 * 3)
        self.assertEqual(out.shape[1], 600 * 3)

    def test_long_image_not_upscaled(self):
        img = np.zeros((300, 600, 3), dtype=np.uint8)
        self.assertEqual(ocr._maybe_upscale(img).shape, img.shape)

    def test_normalize_and_similarity(self):
        self.assertEqual(browser._normalize("飞鱼的记事本（12）"), "飞鱼的记事本12")
        high = browser._similarity("飞鱼的记事本", "飞鱼的记事本（12）")
        self.assertGreater(high, 0.9)
        low = browser._similarity("飞鱼的记事本", "工作群")
        self.assertLess(low, 0.5)

    def test_ocr_unavailable_returns_none(self):
        with mock.patch.object(
            ocr, "recognize", side_effect=ocr.OCRUnavailable("boom")
        ):
            self.assertIsNone(
                browser._ocr_region(np.zeros((40, 300, 3), dtype=np.uint8), "群")
            )

    def test_reader_retries_then_succeeds(self):
        fake = object()
        with mock.patch.object(
            ocr, "_load_easyocr", side_effect=[RuntimeError("dll"), fake]
        ) as loader, mock.patch.object(ocr.time, "sleep", return_value=None):
            self.assertIs(ocr.get_reader(force=True), fake)
        self.assertEqual(loader.call_count, 2)
        self.assertIsNone(ocr._init_error)

    def test_reader_failure_is_cached_for_cooldown(self):
        with mock.patch.object(
            ocr, "_load_easyocr", side_effect=RuntimeError("dll")
        ) as loader, mock.patch.object(ocr.time, "sleep", return_value=None):
            with self.assertRaises(ocr.OCRUnavailable):
                ocr.get_reader(force=True)
            first_calls = loader.call_count
            with self.assertRaises(ocr.OCRUnavailable):
                ocr.get_reader()
        self.assertEqual(first_calls, 3)
        self.assertEqual(loader.call_count, first_calls, "冷却期内不应再次加载")

    def test_confident_match_accepts_member_count_suffix(self):
        self.assertTrue(browser._confident_match("飞鱼的记事本", "飞鱼的记事本（12）"))
        self.assertTrue(browser._confident_match("飞鱼的记事本", "飞鱼的记事本 (3人)"))
        self.assertTrue(browser._confident_match("飞鱼的记事本", "飞鱼的记事本"))

    def test_confident_match_rejects_lookalike_group(self):
        # 不能把「工作群2」当成「工作群」：裸数字后缀可能是另一个群名
        self.assertFalse(browser._confident_match("工作群", "工作群2"))
        self.assertFalse(browser._confident_match("财务", "财务部"))

    def test_confident_match_tolerates_ocr_one_char_drop(self):
        self.assertTrue(browser._confident_match("飞鱼的记事本", "飞鱼的记事"))

    def test_confident_region_skips_lenient_false_positive(self):
        results = [
            ([[0, 0], [10, 0], [10, 10], [0, 10]], "工作群2", 0.99),
            ([[20, 0], [30, 0], [30, 10], [20, 10]], "飞鱼的记事本（12）", 0.75),
        ]
        with mock.patch.object(ocr, "recognize", return_value=results):
            found = browser._ocr_region(
                np.zeros((40, 300, 3), dtype=np.uint8),
                "飞鱼的记事本",
                confident=True,
            )
        self.assertIsNotNone(found)
        self.assertEqual(found[0], 25)
        # 候选一「工作群2」原始相似度更高（0.99），但严格模式拒绝；
        # 候选二因「（12）」成员数后缀被接受（containment 加权后约 0.96）。
        self.assertGreater(found[2], 0.9)


if __name__ == "__main__":
    unittest.main()

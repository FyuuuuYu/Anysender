"""OCR 真实引擎自检（不发消息、不点击、不需要 QQ）。

用法：
    python tools/ocr_selftest.py
覆盖：引擎加载重试、中文截图识别、群名相似匹配、负样本拒绝、中文路径保存。
"""

import os
import shutil
import sys
import tempfile
import time

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from plugins.qq import browser, ocr  # noqa: E402

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
]


def _font(size: int):
    for path in FONT_CANDIDATES:
        if os.path.isfile(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _fake_header(text: str) -> Image.Image:
    img = Image.new("RGB", (560, 46), "white")
    draw = ImageDraw.Draw(img)
    draw.text((8, 7), text, font=_font(26), fill="black")
    return img


def main() -> int:
    print("[1/5] OCR 引擎状态:", ocr.status())
    started = time.time()
    ocr.get_reader(force=True)
    print(f"      加载耗时 {time.time() - started:.2f}s")

    img = _fake_header("飞鱼的记事本（12）")
    started = time.time()
    results = ocr.recognize(img)
    texts = [t for _, t, _ in results]
    print(f"[2/5] 识别 {len(results)} 段，耗时 {time.time() - started:.2f}s: {texts}")
    if not any("飞鱼" in t for t in texts):
        print("      失败：未识别出「飞鱼」")
        return 1

    match = browser._ocr_region(img, "飞鱼的记事本", min_ratio=0.5)
    print("[3/5] 正样本匹配:", match)
    if match is None:
        print("      失败：正样本未匹配")
        return 1

    miss = browser._ocr_region(img, "完全不存在的群名", min_ratio=0.5)
    print("[4/5] 负样本匹配:", miss)
    if miss is not None:
        print("      失败：负样本误匹配")
        return 1

    tmp = tempfile.mkdtemp(prefix="anyocr_")
    path = os.path.join(tmp, "中文截图.png")
    ok = ocr.save_image(img, path)
    size = os.path.getsize(path) if ok and os.path.isfile(path) else 0
    print(f"[5/5] 中文路径保存: {ok} -> {path} ({size} B)")
    if not ok or not os.path.isfile(path):
        print("      失败：中文路径保存失败")
        shutil.rmtree(tmp, ignore_errors=True)
        return 1
    shutil.rmtree(tmp, ignore_errors=True)

    print("PASS：OCR 引擎与匹配逻辑正常")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

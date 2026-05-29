"""
区域校准工具 —— 从标注截图自动提取相对坐标

用法：
  1. 截一张目标窗口的完整截图
  2. 用画图工具在上面画不同颜色的矩形框：
       红色 → 搜索框区域
       绿色 → 输入框位置
       蓝色 → 校验区域
       黄色 → 聊天标题区
       紫色 → 联系人列表区
  3. 保存（支持 PNG / JPG / BMP 等常见格式）
  4. 运行：python tools/calibrate.py 截图.png --plugin qq --desaturate

  --desaturate  先转黑白再识别，消除 UI 自带颜色的误识别

脚本会自动识别色块 → 计算相对坐标 → 写入 config/plugins/<plugin>.yaml
"""

import argparse
import os
import sys
from pathlib import Path

import cv2
import numpy as np
import yaml

PROJECT_DIR = Path(__file__).resolve().parent.parent

# 颜色定义（BGR 参考值，实际匹配用 HSV 色相范围）
COLOR_DEFS = {
    "search_box_target": {
        "color": (0, 0, 255),
        "hue_name": "red",
        "comment": "搜索框",
    },
    "input_target": {
        "color": (0, 255, 0),
        "hue_name": "green",
        "comment": "输入框光标位置",
    },
    "validation_region": {
        "color": (255, 0, 0),
        "hue_name": "blue",
        "comment": "发送后校验区",
    },
    "chat_header": {
        "color": (0, 255, 255),
        "hue_name": "yellow",
        "comment": "聊天标题区（验证群聊）",
    },
    "contact_list": {
        "color": (255, 0, 255),
        "hue_name": "magenta",
        "comment": "联系人列表区域（预留：列表遍历）",
    },
}

# 色相范围（OpenCV HSV: H 0-180, S 0-255, V 0-255）
HUE_RANGES = {
    "red":     [(0, 15), (165, 180)],
    "green":   [(45, 80)],
    "blue":    [(95, 130)],
    "yellow":  [(22, 38)],
    "magenta": [(130, 170)],
}

HSV_S_MIN = 60   # 最低饱和度（排除灰/白/黑）
HSV_V_MIN = 60   # 最低亮度


def find_color_bbox(image: np.ndarray, hue_name: str) -> dict:
    """按色相范围在图像中定位色块包围盒，返回相对坐标。"""
    h, w = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

    ranges = HUE_RANGES.get(hue_name, [])
    if not ranges:
        return None

    mask = None
    for lo, hi in ranges:
        lower = np.array([lo, HSV_S_MIN, HSV_V_MIN], dtype=np.uint8)
        upper = np.array([hi, 255, 255], dtype=np.uint8)
        piece = cv2.inRange(hsv, lower, upper)
        mask = piece if mask is None else cv2.bitwise_or(mask, piece)

    ys, xs = np.where(mask > 0)
    if len(xs) < 4:
        return None

    x1, x2 = xs.min(), xs.max()
    y1, y2 = ys.min(), ys.max()

    return {
        "relative_x": round(float(x1) / w, 4),
        "relative_y": round(float(y1) / h, 4),
        "relative_w": round(float(x2 - x1) / w, 4),
        "relative_h": round(float(y2 - y1) / h, 4),
    }


def load_config(plugin: str) -> dict:
    path = PROJECT_DIR / "config" / "plugins" / f"{plugin}.yaml"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def save_config(plugin: str, config: dict) -> None:
    path = PROJECT_DIR / "config" / "plugins" / f"{plugin}.yaml"
    os.makedirs(path.parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def nested_set(d: dict, keys: list, value) -> None:
    for key in keys[:-1]:
        d = d.setdefault(key, {})
    d[keys[-1]] = value


def main():
    parser = argparse.ArgumentParser(description="区域校准工具")
    parser.add_argument("image", help="标注截图路径")
    parser.add_argument("--plugin", default="qq", help="目标插件名 (默认 qq)")
    parser.add_argument("--desaturate", action="store_true",
                        help="先转黑白再识别（消除 UI 自带颜色的误识别）")
    args = parser.parse_args()

    image_path = Path(args.image)
    if not image_path.exists():
        print(f"图片不存在: {image_path}")
        sys.exit(1)

    img = cv2.imread(str(image_path))
    if img is None:
        print(f"无法读取图片: {image_path}")
        sys.exit(1)

    if args.desaturate:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        print("已转为黑白，UI 颜色已忽略")
        print()

    print(f"图片尺寸: {img.shape[1]} x {img.shape[0]}")
    print()

    config = load_config(args.plugin)
    updated = 0

    for name, defn in COLOR_DEFS.items():
        result = find_color_bbox(img, defn["hue_name"])
        if result is None:
            print(f"  [!!] {name} ({defn['comment']}): 未检测到色块")
            continue

        print(f"  [OK] {name} ({defn['comment']}):")
        for k, v in result.items():
            print(f"         {k} = {v}")

        path_keys = [name, "relative_x"]  # 统一写入顶层 key
        if name not in config:
            config[name] = {}
        config[name].update(result)
        updated += 1

    if updated == 0:
        print()
        print("未检测到任何色块。请确认标注颜色正确：")
        print("  红=搜索框  绿=输入框  蓝=校验区  黄=标题区  紫=联系人列表")
        print("  (search_box_target / input_target / validation_region / chat_header / contact_list)")
        sys.exit(1)

    save_config(args.plugin, config)
    print()
    print(f"已写入 config/plugins/{args.plugin}.yaml ({updated} 个区域)")

    schema_hint = {
        "search_box_target": {"relative_x", "relative_y"},
        "input_target": {"relative_x", "relative_y", "mode"},
        "validation_region": {"relative_x", "relative_y", "relative_w", "relative_h"},
        "chat_header": {"relative_x", "relative_y", "relative_w", "relative_h"},
        "contact_list": {"relative_x", "relative_y", "relative_w", "relative_h"},
    }
    print()
    print("提示：请确保对应 JSON Schema 中包含这些字段，否则启动校验会跳过。")


if __name__ == "__main__":
    main()

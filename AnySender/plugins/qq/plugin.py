import os
import json
import time
from typing import Any, Dict, List, Tuple

from core.plugin_interface import SenderPlugin, SendResult


class QQPlugin(SenderPlugin):
    def __init__(self):
        super().__init__()
        self._base_dir = os.path.dirname(os.path.abspath(__file__))
        self._qq_rect = None

    def get_name(self) -> str:
        return "qq"

    def get_version(self) -> str:
        return "2.0.0"

    def get_performance_profile(self) -> str:
        return "accurate"

    def get_config_schema(self) -> dict:
        """
        JSON Schema 多路径查找（优先级从高到低）：
          1. <project>/schemas/qq.json              — 用户自定义 schema
          2. <project>/schemas/default/qq.json      — 内置默认 schema
          3. 返回 {}，跳过 Schema 校验，仅用 validate_config()
        """
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        search_paths = [
            os.path.join(project_root, "schemas", f"{self.get_name()}.json"),
            os.path.join(project_root, "schemas", "default", f"{self.get_name()}.json"),
        ]
        for path in search_paths:
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
        return {}

    def get_default_config(self) -> dict:
        return {
            "qq_window_keywords": ["QQ", "Tencent QQ"],
            "confidence": 0.85,
            "search_wait_sec": 1.2,
            "paste_wait_sec": 0.6,
            "send_mode": "enter",
            "text_interval_sec": 0.02,
            "search_mode": "search",
            "input_target": {
                "mode": "relative",
                "template_path": "",
                "relative_x": 0.50,
                "relative_y": 0.86,
            },
            "validation": {
                "enabled": True,
                "min_similarity": 0.82,
                "luma_weight": 0.65,
                "edge_weight": 0.25,
                "hist_weight": 0.10,
            },
            "validation_region": {
                "relative_x": 0.22,
                "relative_y": 0.79,
                "relative_w": 0.70,
                "relative_h": 0.17,
            },
        }

    def validate_config(self, config: dict) -> Tuple[bool, str]:
        import re

        schema = self.get_config_schema()
        if schema:
            try:
                from jsonschema import Draft202012Validator
                validator = Draft202012Validator(schema)
                errors = sorted(validator.iter_errors(config), key=lambda e: list(e.path))
                if errors:
                    msgs = []
                    for e in errors:
                        path = ".".join([str(x) for x in e.path]) or "<root>"
                        msgs.append(f"{path}: {e.message}")
                    return False, "; ".join(msgs)
            except Exception as e:
                return False, f"Schema 校验异常: {e}"

        it = config.get("input_target", {})
        if it.get("mode") == "template":
            tpl = it.get("template_path", "")
            if not os.path.isfile(tpl):
                return False, f"input_target template_path 不存在: {tpl}"

        val = config.get("validation", {})
        if val.get("enabled"):
            vt = val.get("template_path", "")
            if not os.path.isfile(vt):
                return False, f"validation template_path 不存在: {vt}"
            wsum = (
                float(val.get("luma_weight", 0))
                + float(val.get("edge_weight", 0))
                + float(val.get("hist_weight", 0))
            )
            if abs(wsum - 1.0) > 1e-6:
                return False, "validation 权重之和必须等于 1.0"

        return True, "ok"

    def on_load(self) -> None:
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        for sub in ["screenshots/temp", "screenshots/failed"]:
            os.makedirs(os.path.join(base, sub), exist_ok=True)

    def warm_up(self) -> None:
        from .locator import activate_qq_window
        keywords = (self.get_default_config().get("qq_window_keywords", ["QQ"]))
        activate_qq_window(keywords)

    def send(self, task: dict) -> SendResult:
        from .locator import activate_qq_window, open_group_chat, get_input_target
        from .browser import browse_to_group, select_search_result, verify_chat_opened
        from .sender import paste_images_to_input, send_message
        from .validator import validate_input_effect
        import pyautogui

        name = task.get("name", "unnamed")
        cfg = task.get("resolved_config", {})
        group_name = task.get("plugin_config", {}).get("group_name", "").strip()
        message = task.get("plugin_config", {}).get("message", "")
        images = task.get("plugin_config", {}).get("images", [])

        def _fail(detail: str, retryable: bool = True) -> SendResult:
            _capture_failure_screenshot(name, detail)
            return SendResult(False, name, detail=detail, retryable=retryable)

        if not group_name:
            return _fail("group_name 为空", False)
        if not images:
            return _fail("images 为空", False)

        try:
            keywords = cfg.get("qq_window_keywords", ["QQ"])
            qq_rect = activate_qq_window(keywords)
            search_mode = cfg.get("search_mode", "search")
            chat_header_cfg = cfg.get("chat_header") or cfg.get("chat_header_region", {})

            if search_mode == "browse":
                contact_cfg = cfg.get("contact_list") or cfg.get("contact_list_region", {})
                if not contact_cfg:
                    return _fail("browse 模式需要先校准 contact_list 区域")
                result = browse_to_group(group_name, contact_cfg, qq_rect)
                if result is None:
                    return _fail(f"列表遍历失败：未找到「{group_name}」", retryable=True)
                pyautogui.click(result[0], result[1])
                time.sleep(float(cfg.get("search_wait_sec", 2.0)))
            else:
                open_group_chat(group_name, float(cfg.get("search_wait_sec", 1.2)), cfg, qq_rect)
                time.sleep(0.5)

                if chat_header_cfg and verify_chat_opened(group_name, chat_header_cfg, qq_rect):
                    pass  # 搜索直接成功
                else:
                    search_cfg = cfg.get("search_box_target") or cfg.get("search_box", {})
                    sr = select_search_result(group_name, search_cfg, qq_rect)
                    if sr:
                        import logging
                        logging.getLogger("AnySender").info(f"OCR 搜索结果: {group_name}")
                        pyautogui.click(sr[0], sr[1])
                        time.sleep(0.5)

                    if not (chat_header_cfg and verify_chat_opened(group_name, chat_header_cfg, qq_rect)):
                        contact_cfg = cfg.get("contact_list") or cfg.get("contact_list_region", {})
                        if contact_cfg:
                            import logging
                            logging.getLogger("AnySender").info(f"回退遍历: {group_name}")
                            pyautogui.press("escape")
                            time.sleep(0.3)
                            activate_qq_window(keywords)
                            time.sleep(0.2)
                            result = browse_to_group(group_name, contact_cfg, qq_rect)
                            if result is None:
                                return _fail(f"遍历失败: {group_name}", retryable=True)
                            pyautogui.click(result[0], result[1])
                            time.sleep(float(cfg.get("search_wait_sec", 2.0)))
                        else:
                            return _fail(f"未能进入群聊「{group_name}」\n请校准 chat_header 或 contact_list")
            input_xy = get_input_target(qq_rect, cfg)

            abs_images = [os.path.abspath(p) for p in images]
            paste_images_to_input(abs_images, input_xy, cfg)
            send_message(message, input_xy, cfg)

            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            ok, detail = validate_input_effect(task, cfg, qq_rect, base_dir)
            if not ok:
                return _fail(f"校验失败: {detail}")

            return SendResult(True, name, detail=f"已发送 {len(abs_images)} 张图片到 {group_name}")
        except Exception as e:
            return _fail(str(e))

    def validate(self, task: dict) -> Tuple[bool, str]:
        return True, ""

    def cool_down(self) -> None:
        pass

    def health_check(self) -> Tuple[bool, str]:
        from .locator import enum_window_titles
        titles = [t for _, t in enum_window_titles()]
        for t in titles:
            if "qq" in t.lower():
                return True, "QQ 窗口在线"
        return False, "未检测到 QQ 窗口"


def _capture_failure_screenshot(task_name: str, error: str) -> None:
    try:
        import pyautogui
        from datetime import datetime
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        failed_dir = os.path.join(base, "screenshots", "failed", task_name)
        os.makedirs(failed_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(failed_dir, f"{task_name}_{ts}_ERROR.png")
        pyautogui.screenshot(path)
        import logging
        logging.getLogger("AnySender").warning(f"失败截图已保存: {path}")
    except Exception as ex:
        import logging
        logging.getLogger("AnySender").warning(f"截图保存失败: {ex}")

import json
import logging
import os
import time
from typing import Dict, List, Tuple

from core.plugin_interface import SenderPlugin, SendResult

_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp")


class QQPlugin(SenderPlugin):
    def __init__(self):
        super().__init__()
        self._base_dir = os.path.dirname(os.path.abspath(__file__))
        self._qq_rect = None
        self._log = logging.getLogger("AnySender")
        self._last_config: dict = {}

    def get_name(self) -> str:
        return "qq"

    def get_version(self) -> str:
        return "2.1.0"

    def get_performance_profile(self) -> Dict:
        return {"cpu": "low", "io": "medium", "needs_desktop": True}

    def get_config_schema(self) -> dict:
        """
        JSON Schema 多路径查找（优先级从高到低）：
          1. <project>/schemas/qq.json              — 用户自定义 schema
          2. <project>/schemas/default/qq.json      — 内置默认 schema
          3. 返回 {}，跳过 Schema 校验，仅用 validate_config()
        """
        search_paths = [
            os.path.join(_PROJECT_ROOT, "schemas", f"{self.get_name()}.json"),
            os.path.join(
                _PROJECT_ROOT, "schemas", "default", f"{self.get_name()}.json"
            ),
        ]
        for path in search_paths:
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
        return {}

    def get_default_config(self) -> dict:
        return {
            "qq_window_keywords": ["QQ", "Tencent QQ"],
            "qq_window": {
                "process_names": ["QQ.exe", "QQNT.exe"],
                "title_keywords": ["QQ", "Tencent QQ"],
                "title_exclude": ["QQ音乐", "QQ浏览器", "QQ频道", "QQ游戏", "QQ空间"],
                "pid": 0,
            },
            "confidence": 0.85,
            "search_wait_sec": 1.2,
            "paste_wait_sec": 0.6,
            "send_mode": "enter",
            "text_interval_sec": 0.02,
            "search_mode": "search",
            "require_chat_verify": True,
            "pre_send_check": True,
            "ocr_precheck": True,
            "dry_run": False,
            "input_target": {
                "mode": "relative",
                "template_path": "",
                "relative_x": 0.50,
                "relative_y": 0.86,
            },
            "validation": {
                "enabled": True,
                "template_path": "",
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
        self._last_config = config or {}
        schema = self.get_config_schema()
        if schema:
            try:
                from jsonschema import Draft202012Validator

                validator = Draft202012Validator(schema)
                errors = sorted(
                    validator.iter_errors(config), key=lambda e: list(e.path)
                )
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

        # 群聊校验：没有校准 chat_header 时，宁可不发，也不冒险发错群。
        header = config.get("chat_header") or config.get("chat_header_region")
        if bool(config.get("require_chat_verify", True)) and not header:
            return (
                False,
                "未配置 chat_header，无法确认目标群聊；请先校准，"
                "或在 plugins/qq.yaml 设置 require_chat_verify: false",
            )

        search_mode = str(config.get("search_mode", "search")).lower()
        if search_mode not in ("search", "browse"):
            return False, f"未知 search_mode: {search_mode}"
        if search_mode == "browse" and not (
            config.get("contact_list") or config.get("contact_list_region")
        ):
            return False, "browse 模式需要先校准 contact_list 区域"

        val = config.get("validation", {})
        if val.get("enabled", True):
            vt = val.get("template_path", "")
            if not os.path.isfile(vt):
                # 降级而不是阻断：模板缺失时关闭校验并显式告警。
                val["enabled"] = False
                val["disabled_reason"] = f"validation template 不存在: {vt}"
                config["validation"] = val
                self._log.warning(
                    "[qq] validation 模板不存在，已自动关闭输入校验: %s", vt
                )
            else:
                wsum = (
                    float(val.get("luma_weight", 0))
                    + float(val.get("edge_weight", 0))
                    + float(val.get("hist_weight", 0))
                )
                if abs(wsum - 1.0) > 1e-6:
                    return False, "validation 权重之和必须等于 1.0"

        return True, "ok"

    def on_load(self) -> None:
        for sub in [
            "screenshots/temp",
            "screenshots/failed",
            "screenshots/done",
        ]:
            os.makedirs(os.path.join(_PROJECT_ROOT, sub), exist_ok=True)
        super().on_load()

    def warm_up(self) -> None:
        # 不在启动时抢焦点，也不提前加载 OCR（easyocr 首次加载很重）。
        return None

    def _is_dry_run(self, task: dict, cfg: dict) -> bool:
        env = os.environ.get("ANYSENDER_DRY_RUN", "").lower()
        return bool(task.get("dry_run")) or bool(cfg.get("dry_run")) or env in (
            "1",
            "true",
            "yes",
            "on",
        )

    def send(self, task: dict) -> SendResult:
        name = task.get("name", "unnamed")
        cfg = task.get("resolved_config") or {}
        group_name = str(cfg.get("group_name") or "").strip()
        message = str(cfg.get("message") or "")
        raw_images = cfg.get("images") or []
        if isinstance(raw_images, str):
            raw_images = [raw_images]
        images = [str(p).strip() for p in raw_images if str(p).strip()]

        def _fail(detail: str, retryable: bool = True, screenshot: bool = True):
            if screenshot:
                _capture_failure_screenshot(name, detail)
            return SendResult(
                success=False,
                task_name=name,
                plugin_name=self.get_name(),
                detail=detail,
                retryable=retryable,
            )

        if not group_name:
            return _fail("group_name 为空", retryable=False, screenshot=False)
        if not message.strip() and not images:
            return _fail(
                "message 与 images 均为空，至少填写一项",
                retryable=False,
                screenshot=False,
            )

        abs_images: List[str] = []
        missing: List[str] = []
        for raw in images:
            path = os.path.abspath(os.path.expanduser(raw))
            if os.path.isfile(path):
                abs_images.append(path)
            else:
                missing.append(path)
        if missing:
            return _fail(
                "图片不存在: " + "; ".join(missing[:3]), retryable=False, screenshot=False
            )

        if self._is_dry_run(task, cfg):
            return self._dry_run(task, cfg, group_name, message, abs_images)

        from .browser import browse_to_group, select_search_result, verify_chat_opened
        from .locator import (
            activate_qq_window,
            get_foreground_window_title,
            get_input_target,
            is_foreground,
            open_group_chat,
            point_in_rect,
            window_config,
        )
        from .sender import paste_images_to_input, send_message
        from .validator import validate_input_effect

        import pyautogui

        try:
            window_cfg = window_config(cfg)
            header_cfg = (
                cfg.get("chat_header") or cfg.get("chat_header_region") or {}
            )
            search_cfg = cfg.get("search_box_target") or cfg.get("search_box") or {}
            contact_cfg = (
                cfg.get("contact_list") or cfg.get("contact_list_region") or {}
            )
            wait_sec = float(cfg.get("search_wait_sec", 1.2))
            require_verify = bool(cfg.get("require_chat_verify", True))

            # OCR 预检：引擎不可用时在动 UI 之前就停下，避免「点了一圈却无法校验」。
            if require_verify and bool(cfg.get("ocr_precheck", True)):
                from . import ocr

                try:
                    ocr.get_reader()
                except ocr.OCRUnavailable as exc:
                    return _fail(
                        f"OCR 引擎不可用，已中止发送（避免盲发）: {exc}",
                        retryable=True,
                        screenshot=False,
                    )

            target = activate_qq_window(window_cfg)
            qq_rect = target.rect
            search_mode = str(cfg.get("search_mode", "search")).lower()

            def _verify() -> bool:
                if not header_cfg:
                    return False
                try:
                    return bool(verify_chat_opened(group_name, header_cfg, qq_rect))
                except Exception as exc:
                    self._log.warning("[qq] 群聊标题 OCR 校验异常: %s", exc)
                    return False

            verified = False
            if search_mode == "browse":
                if not contact_cfg:
                    return _fail("browse 模式需要先校准 contact_list 区域", screenshot=False)
                result = browse_to_group(group_name, contact_cfg, qq_rect)
                if result is None:
                    return _fail(f"列表遍历失败：未找到「{group_name}」")
                pyautogui.click(result[0], result[1])
                time.sleep(wait_sec)
                verified = _verify()
                if not verified and require_verify:
                    return _fail(
                        f"点击联系人后未能确认进入「{group_name}」，已中止发送"
                    )
            else:
                open_group_chat(group_name, wait_sec, cfg, qq_rect)
                time.sleep(0.4)
                verified = _verify()

                if not verified and search_cfg:
                    sr = select_search_result(group_name, search_cfg, qq_rect)
                    if sr:
                        self._log.info("[qq] 点击搜索结果: %s", group_name)
                        pyautogui.click(sr[0], sr[1])
                        time.sleep(0.5)
                        verified = _verify()

                if not verified and contact_cfg:
                    self._log.info("[qq] 搜索结果未确认，回退联系人遍历: %s", group_name)
                    pyautogui.press("escape")
                    time.sleep(0.3)
                    target = activate_qq_window(window_cfg)
                    qq_rect = target.rect
                    time.sleep(0.2)
                    result = browse_to_group(group_name, contact_cfg, qq_rect)
                    if result:
                        pyautogui.click(result[0], result[1])
                        time.sleep(wait_sec)
                        verified = _verify()

                if not verified:
                    if require_verify:
                        return _fail(
                            f"未能确认进入群聊「{group_name}」，已中止发送。"
                            "请校准 chat_header，或确认群名完全一致"
                        )
                    self._log.warning(
                        "[qq] 未确认群聊标题但 require_chat_verify=false，继续发送"
                    )

            input_xy = get_input_target(qq_rect, cfg)

            # 发送前二次确认：前台窗口、点击点、群聊标题都对，才允许点下去。
            if bool(cfg.get("pre_send_check", True)):
                if not is_foreground(target.hwnd):
                    fg_title = get_foreground_window_title()
                    return _fail(
                        "发送前检查失败：前台窗口已不是已绑定的 QQ 窗口"
                        f"（hwnd={target.hwnd}, 当前={fg_title!r}）"
                    )
                if not point_in_rect(input_xy[0], input_xy[1], qq_rect):
                    return _fail(
                        f"发送前检查失败：输入点 {input_xy} 不在 QQ 窗口内"
                    )
                if header_cfg and require_verify and not _verify():
                    return _fail("发送前复核失败：群聊标题已变化，已中止发送")

            if abs_images:
                paste_images_to_input(abs_images, input_xy, cfg)
            # 有图片时不能再 ctrl+a/backspace，否则会把刚粘贴的图片清空
            send_message(message, input_xy, cfg, clear_input=not abs_images)

            ok, detail = validate_input_effect(task, cfg, qq_rect, _PROJECT_ROOT)
            if not ok:
                return _fail(f"发送后校验失败: {detail}")

            kind = f"{len(abs_images)} 张图片" if abs_images else "纯文本"
            if abs_images and message.strip():
                kind += " + 文本"
            return SendResult(
                success=True,
                task_name=name,
                plugin_name=self.get_name(),
                detail=f"已发送{kind}到「{group_name}」",
            )
        except Exception as exc:
            self._log.error("[qq] 发送异常: %s", exc, exc_info=True)
            return _fail(f"{exc}", retryable=True)

    def _dry_run(
        self,
        task: dict,
        cfg: dict,
        group_name: str,
        message: str,
        abs_images: List[str],
    ) -> SendResult:
        from .locator import find_qq_window

        name = task.get("name", "unnamed")
        mode = str(cfg.get("search_mode", "search"))
        try:
            target = find_qq_window(cfg)
        except Exception as exc:
            return SendResult(
                success=False,
                task_name=name,
                plugin_name=self.get_name(),
                detail=(
                    f"[试运行] 未找到 QQ 窗口：{exc}；"
                    "未点击、未输入、未发送"
                ),
                retryable=False,
            )
        return SendResult(
            success=True,
            task_name=name,
            plugin_name=self.get_name(),
            detail=(
                f"[试运行] 目标群=「{group_name}」；文本={len(message)} 字；"
                f"图片={len(abs_images)} 张；模式={mode}；"
                f"QQ 窗口={target.title!r}"
                f"(pid={target.pid},进程={target.process or '?'})；"
                "未点击、未输入、未发送"
            ),
        )

    def health_check(self) -> Tuple[bool, str]:
        from .locator import find_qq_window

        try:
            target = find_qq_window(self._last_config or {})
            return True, f"QQ 窗口在线（pid={target.pid}, {target.process or '?'}）"
        except Exception as exc:
            return False, str(exc)


def _capture_failure_screenshot(task_name: str, error: str) -> None:
    try:
        import re

        import pyautogui
        from datetime import datetime

        slug = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(task_name or "unnamed"))
        slug = (slug.strip(" .") or "unnamed")[:60]
        failed_dir = os.path.join(_PROJECT_ROOT, "screenshots", "failed", slug)
        os.makedirs(failed_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = os.path.join(failed_dir, f"{ts}_ERROR.png")
        pyautogui.screenshot(path)
        logging.getLogger("AnySender").warning(f"失败截图已保存: {path}")
    except Exception as ex:
        logging.getLogger("AnySender").warning(f"截图保存失败: {ex}")

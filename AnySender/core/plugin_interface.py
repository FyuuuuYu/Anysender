"""插件公共接口 —— 所有平台插件的抽象基类。

设计约束（见 ARCHITECTURE.md）：
- 本模块及 core/ 下其它模块不得导入任何平台专属库（pyautogui / cv2 / win32gui ...）；
- 平台差异全部封装在 plugins/<name>/ 内部。
"""

import threading
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class PluginLifecycle(Enum):
    UNLOADED = "unloaded"
    LOADED = "loaded"
    READY = "ready"
    ERROR = "error"


# 所有插件实现都应返回本结构，上层调度/日志/台账只认它。
@dataclass
class SendResult:
    success: bool
    task_name: str = ""
    plugin_name: str = ""
    duration_ms: int = 0
    detail: str = ""
    artifacts: List[str] = field(default_factory=list)
    retryable: bool = False
    # 跳过（窗口忙 / 条件不满足）与“尝试后失败”区分开，调度器据此记 task_skipped。
    skipped: bool = False


class SenderPlugin(ABC):
    """平台发送插件基类。

    子类至少实现：get_name / get_version / get_default_config /
    validate_config / send。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._lifecycle = PluginLifecycle.UNLOADED
        self._last_error: Optional[BaseException] = None

    # ---- 元信息 ----
    @abstractmethod
    def get_name(self) -> str:
        """插件唯一名，也是配置目录名，如 'qq'。"""

    @abstractmethod
    def get_version(self) -> str:
        return "0.0.0"

    def get_performance_profile(self) -> Dict[str, Any]:
        """可选：声明本插件的资源占用特征，供调度器排班。"""
        return {"cpu": "low", "io": "low", "needs_desktop": True}

    # ---- 生命周期 ----
    def on_load(self) -> None:
        self._lifecycle = PluginLifecycle.LOADED

    def warm_up(self) -> None:
        """可选预热（如懒加载 OCR）。失败不应导致插件加载失败。"""

    def health_check(self) -> bool:
        """可选健康检查，默认认为健康。"""
        return True

    def on_unload(self) -> None:
        self._lifecycle = PluginLifecycle.UNLOADED

    # ---- 配置与发送 ----
    @abstractmethod
    def get_default_config(self) -> Dict[str, Any]:
        """返回本插件的默认配置（会被 presets/config 覆盖）。"""

    @abstractmethod
    def validate_config(self, config: Dict[str, Any]) -> tuple:
        """返回 (ok: bool, detail: str)。必须在真正发送前调用。"""

    @abstractmethod
    def send(self, task: Dict[str, Any]) -> SendResult:
        """执行一次发送。task 至少包含 name / resolved_config。"""

    def send_with_lock(self, task: Dict[str, Any]) -> SendResult:
        """带非阻塞锁与异常兜底的发送入口，调度器只调用这个方法。"""
        task_name = (task or {}).get("name", "")
        cfg = (task or {}).get("resolved_config") or {}
        try:
            ok, detail = self.validate_config(cfg)
        except Exception as exc:  # 校验本身出错也按配置错误处理，绝不发起点击
            return SendResult(
                success=False,
                task_name=task_name,
                plugin_name=self.get_name(),
                detail=f"配置校验异常: {exc}",
            )
        if not ok:
            return SendResult(
                success=False,
                task_name=task_name,
                plugin_name=self.get_name(),
                detail=f"配置校验失败: {detail}",
            )

        if not self._lock.acquire(blocking=False):
            return SendResult(
                success=False,
                task_name=task_name,
                plugin_name=self.get_name(),
                detail=f"[{self.get_name()}] 正忙，本次跳过",
                retryable=False,
                skipped=True,
            )
        try:
            result = self.send(task)
            if not isinstance(result, SendResult):
                result = SendResult(
                    success=False,
                    task_name=task_name,
                    plugin_name=self.get_name(),
                    detail="插件未返回 SendResult",
                )
            self._lifecycle = (
                PluginLifecycle.READY if result.success else PluginLifecycle.ERROR
            )
            return result
        except Exception as exc:
            self._last_error = exc
            self._lifecycle = PluginLifecycle.ERROR
            return SendResult(
                success=False,
                task_name=task_name,
                plugin_name=self.get_name(),
                detail=f"{exc}\n{traceback.format_exc()}",
                retryable=True,
            )
        finally:
            self._lock.release()

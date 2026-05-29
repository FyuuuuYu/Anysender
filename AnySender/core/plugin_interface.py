import time
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple


class PluginLifecycle(Enum):
    IDLE = "idle"
    WARMING_UP = "warming_up"
    SENDING = "sending"
    VALIDATING = "validating"
    COOLING = "cooling"
    ERROR = "error"


@dataclass
class SendResult:
    success: bool
    task_name: str
    plugin_name: str = ""
    duration_ms: float = 0.0
    detail: str = ""
    artifacts: List[str] = field(default_factory=list)
    retryable: bool = False


class SenderPlugin(ABC):
    def __init__(self):
        self._send_lock = threading.Lock()
        self._lifecycle_state = PluginLifecycle.IDLE

    @abstractmethod
    def get_name(self) -> str:
        ...

    @abstractmethod
    def get_version(self) -> str:
        ...

    @abstractmethod
    def get_performance_profile(self) -> str:
        ...

    @abstractmethod
    def validate_config(self, config: dict) -> Tuple[bool, str]:
        ...

    def get_config_schema(self) -> Optional[dict]:
        return None

    def get_default_config(self) -> dict:
        return {}

    def on_load(self) -> None:
        pass

    def warm_up(self) -> None:
        pass

    @abstractmethod
    def send(self, task: dict) -> SendResult:
        ...

    def validate(self, task: dict) -> Tuple[bool, str]:
        return True, ""

    def cool_down(self) -> None:
        pass

    def on_unload(self) -> None:
        pass

    def send_with_lock(self, task: dict) -> SendResult:
        if not self._send_lock.acquire(blocking=False):
            return SendResult(
                success=False,
                task_name=task.get("name", "unknown"),
                plugin_name=self.get_name(),
                duration_ms=0.0,
                detail=f"[{self.get_name()}] 正忙，本次跳过",
                retryable=False,
            )

        t0 = time.time()
        try:
            self._lifecycle_state = PluginLifecycle.WARMING_UP
            self.warm_up()

            self._lifecycle_state = PluginLifecycle.SENDING
            result = self.send(task)
            result.plugin_name = self.get_name()
            result.duration_ms = (time.time() - t0) * 1000

            if result.success:
                self._lifecycle_state = PluginLifecycle.VALIDATING
                ok, detail = self.validate(task)
                if not ok:
                    result.success = False
                    result.detail = f"校验失败: {detail}"

            return result

        except Exception as e:
            return SendResult(
                success=False,
                task_name=task.get("name", "unknown"),
                plugin_name=self.get_name(),
                duration_ms=(time.time() - t0) * 1000,
                detail=f"插件异常: {e}",
                retryable=True,
            )

        finally:
            self._lifecycle_state = PluginLifecycle.COOLING
            try:
                self.cool_down()
            except Exception:
                pass
            finally:
                self._lifecycle_state = PluginLifecycle.IDLE
                self._send_lock.release()

    def get_lifecycle_state(self) -> PluginLifecycle:
        return self._lifecycle_state

    def health_check(self) -> Tuple[bool, str]:
        return True, "ok"

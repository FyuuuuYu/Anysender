import threading
from collections import defaultdict
from typing import Any, Callable, Dict, List


class EventBus:
    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(self, event: str, callback: Callable[..., None]) -> None:
        with self._lock:
            self._subscribers[event].append(callback)

    def unsubscribe(self, event: str, callback: Callable[..., None]) -> None:
        with self._lock:
            if event in self._subscribers:
                self._subscribers[event] = [
                    cb for cb in self._subscribers[event] if cb is not callback
                ]

    def emit(self, event: str, **data: Any) -> None:
        with self._lock:
            callbacks = list(self._subscribers.get(event, []))
        for cb in callbacks:
            try:
                cb(**data)
            except Exception:
                pass

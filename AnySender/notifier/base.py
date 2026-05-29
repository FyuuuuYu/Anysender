from abc import ABC, abstractmethod


class AbstractNotifier(ABC):
    @abstractmethod
    def notify(self, title: str, body: str) -> None:
        ...

    @abstractmethod
    def notify_task_planned(self, task_name: str, seconds: int) -> None:
        ...

    @abstractmethod
    def notify_task_soon(self, task_name: str, plugin_name: str, seconds: int) -> None:
        ...

    @abstractmethod
    def notify_sending(self, task_name: str) -> None:
        ...

    @abstractmethod
    def notify_done(self, task_name: str, success: bool, detail: str = "") -> None:
        ...

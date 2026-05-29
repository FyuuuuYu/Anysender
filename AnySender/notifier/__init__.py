from .base import AbstractNotifier
from .win32_toast import Win32ToastNotifier


def create_notifier(event_bus=None) -> AbstractNotifier:
    return Win32ToastNotifier(event_bus=event_bus)

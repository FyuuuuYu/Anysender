"""
Windows toast 通知（windows-toasts）
支持按钮交互：「立即执行」「推迟 5 分钟」
"""

from windows_toasts import Toast, ToastButton, InteractableWindowsToaster

from .base import AbstractNotifier

APP_NAME = "AnySender"


class Win32ToastNotifier(AbstractNotifier):
    def __init__(self, event_bus=None):
        self._event_bus = event_bus
        self._toaster = InteractableWindowsToaster(APP_NAME)

    def notify(self, title: str, body: str, *, buttons=None) -> None:
        try:
            toast = Toast()
            toast.text_fields = [title, body]
            if buttons:
                for label, args in buttons:
                    toast.AddAction(ToastButton(label, arguments=args))
            self._toaster.show_toast(toast)
        except Exception as e:
            import traceback
            print(f"[Notifier] 通知发送失败: {e}")
            traceback.print_exc()

    def notify_task_planned(self, task_name: str, seconds: int) -> None:
        minutes = max(1, seconds // 60)
        self.notify(
            title="AnySender 任务计划",
            body=f"[{task_name}] 预计 {minutes} 分钟后执行",
        )

    def notify_task_soon(self, task_name: str, plugin_name: str, seconds: int) -> None:
        bus = self._event_bus

        def on_activated(event_args):
            if not bus:
                return
            args = getattr(event_args, "arguments", "")
            if args.startswith("run:"):
                bus.emit("notify_run_now", task_id=args[4:])
            elif args.startswith("postpone:"):
                bus.emit("notify_postpone", task_id=args[9:], delay_seconds=300)

        try:
            toast = Toast()
            toast.text_fields = ["AnySender 任务预告",
                                 f"[{task_name}] 将于 {seconds} 秒后执行\n请勿移动鼠标"]
            toast.AddAction(ToastButton("立即执行", arguments=f"run:{task_name}"))
            toast.AddAction(ToastButton("推迟 5 分钟", arguments=f"postpone:{task_name}"))
            toast.on_activated = on_activated
            self._toaster.show_toast(toast)
        except Exception as e:
            import traceback
            print(f"[Notifier] 通知发送失败: {e}")
            traceback.print_exc()

    def notify_sending(self, task_name: str) -> None:
        self.notify(
            title="AnySender 发送中",
            body=f"[{task_name}] 正在发送，切勿操作键鼠",
        )

    def notify_done(self, task_name: str, success: bool, detail: str = "") -> None:
        if success:
            self.notify(title="AnySender", body=f"[{task_name}] 发送成功")
        else:
            self.notify(title="AnySender", body=f"[{task_name}] 发送失败\n{detail}")

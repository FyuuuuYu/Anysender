import time
from typing import List, Tuple

import pyautogui
import pyperclip

from plugins._base.win32_plugin import Win32Plugin


def paste_images_to_input(file_paths: List[str],
                          input_xy: Tuple[int, int],
                          cfg: dict) -> None:
    Win32Plugin.clipboard_operation(file_paths)
    pyautogui.click(input_xy[0], input_xy[1])
    time.sleep(0.12)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(float(cfg.get("paste_wait_sec", 0.6)))


def send_message(message: str, input_xy: Tuple[int, int],
                 cfg: dict, clear_input: bool = True) -> None:
    """点击输入框并发送。

    clear_input=False 用于“先粘贴图片、再补文字”的场景：
    否则 ctrl+a / backspace 会把刚粘贴的图片清掉。
    """
    send_mode = str(cfg.get("send_mode", "enter")).lower()

    pyautogui.click(input_xy[0], input_xy[1])
    time.sleep(0.1)
    if clear_input:
        pyautogui.hotkey("ctrl", "a")
        pyautogui.press("backspace")
        time.sleep(0.05)
    if message:
        # pyautogui.write 只能输入 ASCII；中文/emoji 必须走剪贴板粘贴。
        try:
            pyperclip.copy(message)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.15)
        except Exception:
            pyautogui.write(
                message, interval=float(cfg.get("text_interval_sec", 0.02))
            )

    if send_mode == "enter":
        pyautogui.press("enter")
    elif send_mode == "ctrl_enter":
        pyautogui.hotkey("ctrl", "enter")
    elif send_mode == "none":
        pass
    else:
        raise RuntimeError(f"未知 send_mode: {send_mode}")

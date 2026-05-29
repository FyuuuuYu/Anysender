import threading
import struct
from typing import List

import win32clipboard
import win32con


class Win32Plugin:
    _clipboard_lock = threading.Lock()

    @classmethod
    def clipboard_operation(cls, file_paths: List[str]) -> None:
        abs_paths = []
        for p in file_paths:
            import os
            path = os.path.abspath(p)
            if not os.path.isfile(path):
                raise FileNotFoundError(f"文件不存在: {path}")
            abs_paths.append(path)
        if not abs_paths:
            raise RuntimeError("没有可复制的文件路径")

        with cls._clipboard_lock:
            files_utf16 = ("\0".join(abs_paths) + "\0\0").encode("utf-16le")
            dropfiles = struct.pack("IiiII", 20, 0, 0, 0, 1)
            payload = dropfiles + files_utf16

            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_HDROP, payload)
            finally:
                win32clipboard.CloseClipboard()

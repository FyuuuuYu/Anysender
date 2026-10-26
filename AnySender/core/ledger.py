"""发送台账 —— 每次运行一行 JSONL，便于回放与排查。

不依赖数据库，文件小、易 grep、易备份。
"""

import json
import os
import threading
from datetime import datetime


class RunLedger:
    def __init__(self, path: str):
        self._path = os.path.abspath(path)
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        self._lock = threading.Lock()

    @property
    def path(self) -> str:
        return self._path

    def append(self, record: dict) -> dict:
        item = dict(record)
        item.setdefault(
            "ts", datetime.now().astimezone().isoformat(timespec="seconds")
        )
        line = json.dumps(item, ensure_ascii=False)
        with self._lock:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        return item

    def tail(self, limit: int = 50) -> list:
        limit = max(1, int(limit))
        if not os.path.isfile(self._path):
            return []
        with self._lock:
            with open(self._path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        records = []
        for line in lines[-limit:]:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return records

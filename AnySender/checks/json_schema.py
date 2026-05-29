"""
JSON Schema 校验

context 要求:
    data:        dict  — 待校验数据
    schema_path: str   — JSON Schema 文件路径（绝对或相对）
"""

import json
import os
from typing import Any, Dict, Tuple

from .base import Check


class JsonSchemaCheck(Check):
    def get_name(self) -> str:
        return "json_schema"

    def run(self, context: Dict[str, Any]) -> Tuple[bool, str]:
        data = context.get("data", {})
        schema_path = context.get("schema_path", "")

        if not os.path.isfile(schema_path):
            return False, f"Schema 文件不存在: {schema_path}"

        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)

        from jsonschema import Draft202012Validator

        validator = Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))

        if errors:
            msgs = []
            for e in errors:
                path = ".".join([str(x) for x in e.path]) or "<root>"
                msgs.append(f"{path}: {e.message}")
            return False, "; ".join(msgs)

        return True, "ok"

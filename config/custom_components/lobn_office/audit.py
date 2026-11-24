"""只追加审计：谁、何时、理由、结果、关联号。先落审计再对外动作的调用方负责顺序。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class AuditLog:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "audit.jsonl"

    def append(self, action: str, **fields: Any) -> dict:
        row = {"ts": time.time(), "action": action, **fields}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row

    def recent(self, limit: int = 50) -> list[dict]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        out = []
        for line in lines[-limit:]:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

"""只追加审计：谁、何时、理由、结果、关联号。先落审计再对外动作的调用方负责顺序。

按日轮转 audit-YYYYMMDD.jsonl，默认保留 14 天。
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_RETAIN_DAYS = 14


def audit_path_for_day(directory: Path, day: datetime | None = None) -> Path:
    day = day or datetime.now(timezone.utc)
    return directory / f"audit-{day.strftime('%Y%m%d')}.jsonl"


def prune_audit_files(directory: Path, retain_days: int = _RETAIN_DAYS) -> int:
    """删除早于 retain_days 的 audit-*.jsonl，返回删除数量。"""
    if not directory.exists():
        return 0
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=retain_days)
    removed = 0
    for path in directory.glob("audit-*.jsonl"):
        stem = path.stem  # audit-YYYYMMDD
        if not stem.startswith("audit-") or len(stem) < 14:
            continue
        day_s = stem[6:14]
        try:
            day = datetime.strptime(day_s, "%Y%m%d").date()
        except ValueError:
            continue
        if day < cutoff:
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue
    return removed


def append_audit_row(directory: Path, row: dict[str, Any], retain_days: int = _RETAIN_DAYS) -> Path:
    """追加一行到当日 audit-YYYYMMDD.jsonl，并按需清理旧文件。"""
    directory.mkdir(parents=True, exist_ok=True)
    path = audit_path_for_day(directory)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    prune_audit_files(directory, retain_days=retain_days)
    return path


def flush_door_audit(
    directory: Path,
    entries: list[dict[str, Any]],
    *,
    retain_days: int = _RETAIN_DAYS,
) -> int:
    """把门禁内存审计列表刷入 data/lobn_office/audit-YYYYMMDD.jsonl，清空已写入项。"""
    if not entries:
        prune_audit_files(directory, retain_days=retain_days)
        return 0
    directory.mkdir(parents=True, exist_ok=True)
    written = 0
    # 按条目时间戳落到对应日期文件
    by_day: dict[str, list[dict[str, Any]]] = {}
    for entry in list(entries):
        ts = float(entry.get("ts") or time.time())
        day = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y%m%d")
        by_day.setdefault(day, []).append({"source": "door", **entry})
    for day, rows in by_day.items():
        path = directory / f"audit-{day}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                written += 1
    entries.clear()
    prune_audit_files(directory, retain_days=retain_days)
    return written


class AuditLog:
    def __init__(self, directory: Path, retain_days: int = _RETAIN_DAYS) -> None:
        self.directory = directory
        self.retain_days = retain_days
        self.directory.mkdir(parents=True, exist_ok=True)
        # 兼容旧调用方：path 指向当日文件
        self.path = audit_path_for_day(self.directory)

    def append(self, action: str, **fields: Any) -> dict:
        row = {"ts": time.time(), "action": action, **fields}
        self.path = append_audit_row(self.directory, row, retain_days=self.retain_days)
        return row

    def recent(self, limit: int = 50) -> list[dict]:
        """从近几日文件倒序读取最近 limit 条。"""
        if not self.directory.exists():
            return []
        files = sorted(self.directory.glob("audit-*.jsonl"), reverse=True)
        # 兼容历史单文件 audit.jsonl
        legacy = self.directory / "audit.jsonl"
        if legacy.exists():
            files.append(legacy)
        out: list[dict] = []
        for path in files:
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in reversed(lines):
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
                if len(out) >= limit:
                    return out
        return out

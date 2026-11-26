from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from .store import GalleryStore

_LOGGER = logging.getLogger(__name__)


async def backup_loop(store: GalleryStore, backup_dir: Path, interval_hours: float) -> None:
    backup_dir.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            name = time.strftime("smartcenter-%Y%m%d-%H%M%S.sqlite3", time.gmtime())
            dest = backup_dir / name
            store.online_backup(dest)
            _LOGGER.info("backup ok %s", dest)
            # 只留最近 10 份
            files = sorted(backup_dir.glob("smartcenter-*.sqlite3"), reverse=True)
            for old in files[10:]:
                old.unlink(missing_ok=True)
        except Exception:
            _LOGGER.exception("backup failed")
        await asyncio.sleep(max(60.0, interval_hours * 3600.0))

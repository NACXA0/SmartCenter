from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED = False


def setup_logging(
    data_dir: Path,
    *,
    level: int = logging.INFO,
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 5,
) -> Path:
    """控制台 + 滚动文件日志。可重复调用（幂等）。"""
    global _CONFIGURED
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "smartcenter.log"

    root = logging.getLogger()
    root.setLevel(level)

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 清掉 basicConfig 留下的无上限 Handler，避免重复刷屏
    if _CONFIGURED:
        return log_path

    for h in list(root.handlers):
        root.removeHandler(h)

    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(level)
    sh.setFormatter(fmt)
    root.addHandler(sh)

    fh = RotatingFileHandler(
        log_path,
        maxBytes=max(256 * 1024, max_bytes),
        backupCount=max(1, backup_count),
        encoding="utf-8",
    )
    fh.setLevel(level)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # 压低嘈杂第三方库
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("aiomqtt").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    _CONFIGURED = True
    logging.getLogger("smartcenter").info(
        "logging → %s (rotate %d×%dMB)",
        log_path,
        backup_count,
        max(1, max_bytes // (1024 * 1024)),
    )
    return log_path

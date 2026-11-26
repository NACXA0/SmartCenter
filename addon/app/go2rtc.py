from __future__ import annotations

import logging

import httpx
import numpy as np
from PIL import Image
import io

_LOGGER = logging.getLogger(__name__)


async def grab_jpeg_frames(go2rtc_url: str, stream: str, count: int = 3) -> list[np.ndarray]:
    """从 go2rtc 取若干 JPEG 快照。失败返回空列表（调用方放弃本次）。"""
    base = go2rtc_url.rstrip("/")
    out: list[np.ndarray] = []
    async with httpx.AsyncClient(timeout=3.0) as client:
        for _ in range(count):
            try:
                r = await client.get(f"{base}/api/frame.jpeg", params={"src": stream})
                if r.status_code != 200:
                    _LOGGER.warning("go2rtc frame status=%s", r.status_code)
                    break
                img = Image.open(io.BytesIO(r.content)).convert("RGB")
                out.append(np.asarray(img)[:, :, ::-1].copy())
            except Exception:
                _LOGGER.exception("go2rtc grab failed")
                break
    return out

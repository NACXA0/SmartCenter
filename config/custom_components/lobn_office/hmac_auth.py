"""HMAC-SHA256 服务鉴权：时间窗 + nonce 防重放。"""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from collections import OrderedDict


class NonceCache:
    def __init__(self, ttl_sec: float = 600, max_size: int = 10000) -> None:
        self.ttl = ttl_sec
        self.max_size = max_size
        self._items: OrderedDict[str, float] = OrderedDict()

    def seen(self, nonce: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        self._purge(now)
        if nonce in self._items:
            return True
        self._items[nonce] = now
        while len(self._items) > self.max_size:
            self._items.popitem(last=False)
        return False

    def _purge(self, now: float) -> None:
        while self._items:
            k, ts = next(iter(self._items.items()))
            if now - ts <= self.ttl:
                break
            self._items.popitem(last=False)


def body_sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def sign(
    secret: str,
    timestamp: str,
    nonce: str,
    method: str,
    path: str,
    body: bytes,
) -> str:
    payload = f"{timestamp}\n{nonce}\n{method.upper()}\n{path}\n{body_sha256(body)}"
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def verify(
    secret: str,
    timestamp: str,
    nonce: str,
    signature: str,
    method: str,
    path: str,
    body: bytes,
    *,
    now: float | None = None,
    window_sec: float = 60,
    nonce_cache: NonceCache | None = None,
) -> tuple[bool, str]:
    now = time.time() if now is None else now
    try:
        ts = float(timestamp)
    except ValueError:
        return False, "时间戳无效"
    if abs(now - ts) > window_sec:
        return False, "时间窗超时"
    if nonce_cache is not None and nonce_cache.seen(nonce, now):
        return False, "nonce 重放"
    expected = sign(secret, timestamp, nonce, method, path, body)
    if not hmac.compare_digest(expected, signature or ""):
        return False, "签名错误"
    return True, ""


def make_headers(
    secret: str,
    method: str,
    path: str,
    body: bytes,
    *,
    store_id: int | None = None,
) -> dict[str, str]:
    ts = str(int(time.time()))
    nonce = str(uuid.uuid4())
    headers = {
        "X-Lobn-Timestamp": ts,
        "X-Lobn-Nonce": nonce,
        "X-Lobn-Signature": sign(secret, ts, nonce, method, path, body),
        "Content-Type": "application/json",
    }
    if store_id is not None:
        headers["X-Lobn-Store-Id"] = str(int(store_id))
    return headers

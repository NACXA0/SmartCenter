import time

from lobn_office.hmac_auth import NonceCache, make_headers, sign, verify


def test_sign_verify_roundtrip():
    secret = "s3cret"
    body = b'{"a":1}'
    headers = make_headers(secret, "POST", "/api/lobn_office/events", body)
    ok, err = verify(
        secret,
        headers["X-Lobn-Timestamp"],
        headers["X-Lobn-Nonce"],
        headers["X-Lobn-Signature"],
        "POST",
        "/api/lobn_office/events",
        body,
        nonce_cache=NonceCache(),
    )
    assert ok and err == ""


def test_replay_rejected():
    secret = "s3cret"
    cache = NonceCache()
    body = b"{}"
    ts = str(int(time.time()))
    nonce = "n1"
    sig = sign(secret, ts, nonce, "GET", "/p", body)
    ok1, _ = verify(secret, ts, nonce, sig, "GET", "/p", body, nonce_cache=cache)
    ok2, err2 = verify(secret, ts, nonce, sig, "GET", "/p", body, nonce_cache=cache)
    assert ok1 and not ok2 and "重放" in err2


def test_window_rejected():
    secret = "s"
    body = b""
    ts = str(int(time.time()) - 120)
    nonce = "n2"
    sig = sign(secret, ts, nonce, "GET", "/p", body)
    ok, err = verify(secret, ts, nonce, sig, "GET", "/p", body)
    assert not ok and "时间" in err

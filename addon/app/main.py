from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .auth import Actor, require_staff
from .backup import backup_loop
from .config import load_settings
from .face.embedder import build_embedder
from .face.match import DoorMatcher, MatchConfig
from .face.session import SessionManager
from .go2rtc import grab_jpeg_frames
from .logging_setup import setup_logging
from .maintenance import maintenance_loop, refresh_disk_full, run_maintenance_once
from .mqtt_bus import MqttBus
from .store import GalleryStore

_LOGGER = logging.getLogger("smartcenter")

WEB = Path(__file__).resolve().parent / "webui"


async def _push_face_status(settings, user_id: str, store: GalleryStore, client: httpx.AsyncClient | None = None) -> None:
    """把本地 face_status 回写云端展示；失败不影响开门。"""
    base = (settings.cloud_base_url or "").rstrip("/")
    if not base or not settings.cloud_hmac_secret:
        return
    p = store.get_person(user_id)
    if not p:
        return
    own = client is None
    http = client or httpx.AsyncClient(timeout=5.0)
    try:
        await http.post(
            f"{base}/api/face/status/push",
            headers={"X-Lobn-Relay-Token": settings.cloud_hmac_secret},
            json={"user_id": int(user_id) if str(user_id).isdigit() else user_id, "face_status": p.face_status},
        )
    except Exception:
        _LOGGER.warning("cloud face_status push failed for %s", user_id)
    finally:
        if own:
            await http.aclose()


class StartBody(BaseModel):
    user_id: str
    display_name: str = ""
    channel: str = Field(default="staff", pattern="^(staff|student)$")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.frames_dir.mkdir(parents=True, exist_ok=True)
    settings.backup_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(
        settings.data_dir,
        max_bytes=max(1, settings.log_max_mb) * 1024 * 1024,
        backup_count=max(1, settings.log_backup_count),
    )

    store = GalleryStore(settings.db_path)
    embedder = build_embedder(settings.embedder, settings.model_version)
    sessions = SessionManager(
        store,
        embedder,
        settings.frames_dir,
        needed=settings.required_enroll_frames,
    )
    matcher = DoorMatcher(
        store,
        embedder,
        MatchConfig(
            match_threshold=settings.match_threshold,
            verify_threshold=settings.verify_threshold,
            cooldown_sec=settings.cooldown_sec,
            required_match_frames=settings.required_match_frames,
            door_node=settings.door_node,
            door_cameras=list(settings.door_cameras),
            door_zones=list(settings.door_zones),
        ),
    )
    bus = MqttBus(settings.mqtt_host, settings.mqtt_port, settings.mqtt_user, settings.mqtt_password)
    match_sem = asyncio.Semaphore(max(1, settings.match_concurrency))
    disk_flag: dict[str, Any] = {"disk_full": False}

    app.state.settings = settings
    app.state.store = store
    app.state.embedder = embedder
    app.state.sessions = sessions
    app.state.matcher = matcher
    app.state.bus = bus
    app.state.disk_full = False
    app.state.http = httpx.AsyncClient(timeout=8.0)

    # 启动即收敛一次，避免上次异常退出留下的脏数据立刻膨胀
    try:
        boot = run_maintenance_once(store, settings, sessions, matcher)
        _LOGGER.info("boot maintenance %s", boot)
    except Exception:
        _LOGGER.exception("boot maintenance failed")
    disk_flag["disk_full"] = refresh_disk_full(settings)
    app.state.disk_full = bool(disk_flag["disk_full"])

    async def on_frigate(payload: dict[str, Any]) -> None:
        if not embedder.ready or disk_flag.get("disk_full"):
            return
        typ = payload.get("type")
        after = payload.get("after") or payload.get("before") or {}
        if typ not in ("new", "update"):
            return
        label = after.get("label") or ""
        if label != "person":
            return
        camera = after.get("camera") or ""
        zones = list(after.get("current_zones") or after.get("entered_zones") or [])
        event_id = after.get("id")
        ok, _why = matcher.should_handle(camera, zones, event_id)
        if not ok:
            return
        # 限流：门口抓帧+推理不排队堆积（忙则丢，下一事件再试）
        try:
            await asyncio.wait_for(match_sem.acquire(), timeout=0.001)
        except TimeoutError:
            return
        try:
            frames = await grab_jpeg_frames(settings.go2rtc_url, camera, count=settings.required_match_frames)
            if not frames:
                store.audit(None, camera, 0.0, "skip", {"reason": "go2rtc_empty"})
                return
            result = await asyncio.to_thread(matcher.match_frames, camera, frames, event_id)
            if result.user_id and result.decision in ("grant", "deny"):
                await _push_face_status(settings, result.user_id, store, client=app.state.http)
            if result.decision == "grant" and result.grant:
                await bus.publish_grant(result.grant)
        finally:
            match_sem.release()

    await bus.start(on_frigate)

    backup_task = asyncio.create_task(backup_loop(store, settings.backup_dir, settings.backup_interval_hours))
    maint_task = asyncio.create_task(
        maintenance_loop(store, settings, sessions, matcher, disk_flag, settings.maintenance_interval_sec)
    )

    async def _sync_disk_flag() -> None:
        while True:
            try:
                app.state.disk_full = bool(disk_flag.get("disk_full"))
            except Exception:
                pass
            await asyncio.sleep(5.0)

    disk_task = asyncio.create_task(_sync_disk_flag())
    try:
        yield
    finally:
        for t in (backup_task, maint_task, disk_task):
            t.cancel()
        await bus.stop()
        try:
            await app.state.http.aclose()
        except Exception:
            pass
        store.close()


app = FastAPI(title="SmartCenter", version="0.1.0", lifespan=lifespan)

# 本地「仅前端」静态页跨端口调 API 时需要 CORS（生产 Ingress 同域可忽略）
try:
    from fastapi.middleware.cors import CORSMiddleware

    _dev = __import__("os").environ.get("SMARTCENTER_DEV_AUTH", "").lower() in ("1", "true", "yes")
    if _dev:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
except Exception:
    pass

# Vite 构建产物：/assets/* ；旧静态兼容 /static/*
if (WEB / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=str(WEB / "assets")), name="assets")
if WEB.is_dir():
    app.mount("/static", StaticFiles(directory=str(WEB)), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


@app.get("/favicon.ico")
async def favicon() -> Response:
    return Response(status_code=204)


@app.get("/healthz")
async def healthz(request: Request) -> JSONResponse:
    emb = request.app.state.embedder
    bus = request.app.state.bus
    store: GalleryStore = request.app.state.store
    settings = request.app.state.settings
    try:
        request.app.state.disk_full = refresh_disk_full(settings)
    except Exception:
        pass
    code = 200 if emb.ready and not request.app.state.disk_full else 503
    body: dict[str, Any] = {
        "ok": emb.ready and not request.app.state.disk_full,
        "embedder_ready": emb.ready,
        "model_version": emb.model_version,
        "disk_full": request.app.state.disk_full,
        "mqtt_enabled": bus.enabled,
        "mqtt_host": bus.host if bus.enabled else "off",
    }
    try:
        body["store"] = store.stats()
        body["open_sessions"] = len(getattr(request.app.state.sessions, "_sessions", {}))
    except Exception:
        pass
    return JSONResponse(body, status_code=code)


def _person_item(p, store: GalleryStore | None = None) -> dict:
    item = {
        "user_id": p.user_id,
        "display_name": p.display_name,
        "face_status": p.face_status,
        "enabled": p.enabled,
        "verify_ok_count": p.verify_ok_count,
        "verify_fail_streak": p.verify_fail_streak,
        "has_thumb": False,
    }
    if store:
        paths = store.frame_paths_for_user(p.user_id)
        item["has_thumb"] = bool(paths)
    return item


@app.get("/api/persons")
async def persons(
    request: Request,
    q: str = "",
    actor: Actor = Depends(require_staff),
) -> dict:
    store = request.app.state.store
    rows = store.search_persons(q) if q.strip() else store.list_persons()
    return {"items": [_person_item(p, store) for p in rows]}


@app.get("/api/persons/search")
async def persons_search(
    request: Request,
    q: str = "",
    actor: Actor = Depends(require_staff),
) -> dict:
    """本地底库 + 可选云端反查，供采集页选人。"""
    store = request.app.state.store
    settings = request.app.state.settings
    local = [_person_item(p, store) for p in store.search_persons(q)]
    cloud: list[dict] = []
    base = (settings.cloud_base_url or "").rstrip("/")
    if q.strip() and base and settings.cloud_hmac_secret:
        try:
            r = await request.app.state.http.get(
                f"{base}/api/face/users/search",
                params={"q": q.strip(), "limit": 20},
                headers={"X-Lobn-Relay-Token": settings.cloud_hmac_secret},
            )
            if r.status_code < 400:
                cloud = list((r.json() or {}).get("items") or [])
        except Exception:
            _LOGGER.warning("cloud person search failed")
    # 合并：云端优先展示名，本地状态覆盖
    by_id: dict[str, dict] = {}
    for c in cloud:
        uid = str(c.get("user_id") or "")
        if not uid:
            continue
        by_id[uid] = {
            "user_id": uid,
            "display_name": c.get("display_name") or "",
            "face_status": c.get("face_status") or "none",
            "enabled": True,
            "source": "cloud",
            "has_thumb": False,
        }
    for p in local:
        uid = p["user_id"]
        if uid in by_id:
            by_id[uid].update({**p, "source": "both", "display_name": p["display_name"] or by_id[uid]["display_name"]})
        else:
            by_id[uid] = {**p, "source": "local"}
    items = list(by_id.values())
    # 纯数字且未命中：允许按 user_id 直接选
    if q.strip().isdigit() and q.strip() not in by_id:
        items.insert(
            0,
            {
                "user_id": q.strip(),
                "display_name": "",
                "face_status": "none",
                "enabled": True,
                "source": "manual",
                "has_thumb": False,
            },
        )
    return {"items": items[:40]}


@app.get("/api/stats")
async def stats_dashboard(request: Request, actor: Actor = Depends(require_staff)) -> dict:
    """概览页：底库分布、开门统计、待重采队列。"""
    store: GalleryStore = request.app.state.store
    bus = request.app.state.bus
    emb = request.app.state.embedder
    data = store.dashboard()
    data["runtime"] = {
        "embedder_ready": emb.ready,
        "model_version": emb.model_version,
        "mqtt_enabled": bus.enabled,
        "mqtt_host": bus.host if bus.enabled else "off",
        "disk_full": bool(request.app.state.disk_full),
        "open_sessions": len(getattr(request.app.state.sessions, "_sessions", {})),
    }
    return data


@app.get("/api/persons/{user_id}")
async def person_detail(user_id: str, request: Request, actor: Actor = Depends(require_staff)) -> dict:
    store = request.app.state.store
    p = store.get_person(user_id)
    if not p:
        raise HTTPException(404, "not_found")
    paths = store.frame_paths_for_user(user_id)
    item = _person_item(p, store)
    item["frame_count"] = len(paths)
    item["frames"] = [
        {"index": i, "url": f"/api/persons/{user_id}/frame/{i}"} for i in range(len(paths))
    ]
    return item


@app.get("/api/persons/{user_id}/frame/{index}")
async def person_frame(user_id: str, index: int, request: Request, actor: Actor = Depends(require_staff)):
    paths = request.app.state.store.frame_paths_for_user(user_id)
    if index < 0 or index >= len(paths):
        raise HTTPException(404, "no_frame")
    path = Path(paths[index])
    if not path.is_file():
        raise HTTPException(404, "missing_file")
    return FileResponse(path, media_type="image/jpeg")


class RenameBody(BaseModel):
    display_name: str = Field(min_length=0, max_length=120)


@app.patch("/api/persons/{user_id}")
async def patch_person(
    user_id: str,
    body: RenameBody,
    request: Request,
    actor: Actor = Depends(require_staff),
) -> dict:
    store = request.app.state.store
    if not store.get_person(user_id):
        raise HTTPException(404, "not_found")
    store.set_display_name(user_id, body.display_name.strip())
    p = store.get_person(user_id)
    return _person_item(p, store)  # type: ignore[arg-type]


@app.post("/api/persons/{user_id}/disable")
async def disable_person(user_id: str, request: Request, actor: Actor = Depends(require_staff)) -> dict:
    request.app.state.store.set_enabled(user_id, False)
    request.app.state.store.set_status(user_id, "rejected")
    request.app.state.store.clear_cooldown(user_id)
    return {"ok": True, "user_id": user_id, "enabled": False}


@app.post("/api/persons/{user_id}/enable")
async def enable_person(user_id: str, request: Request, actor: Actor = Depends(require_staff)) -> dict:
    store = request.app.state.store
    p = store.get_person(user_id)
    if not p:
        raise HTTPException(404, "not_found")
    store.set_enabled(user_id, True)
    if p.face_status == "rejected":
        store.set_status(user_id, "accepted")
    return {"ok": True, "user_id": user_id, "enabled": True}


@app.delete("/api/persons/{user_id}")
async def delete_person(user_id: str, request: Request, actor: Actor = Depends(require_staff)) -> dict:
    request.app.state.store.delete_person(user_id)
    return {"ok": True, "user_id": user_id}


@app.get("/api/persons/{user_id}/thumb")
async def person_thumb(user_id: str, request: Request, actor: Actor = Depends(require_staff)):
    paths = request.app.state.store.frame_paths_for_user(user_id)
    if not paths:
        raise HTTPException(404, "no_thumb")
    path = Path(paths[0])
    if not path.is_file():
        raise HTTPException(404, "missing_file")
    return FileResponse(path, media_type="image/jpeg")


@app.get("/api/audit")
async def audit_list(
    request: Request,
    decision: str | None = None,
    limit: int = 50,
    actor: Actor = Depends(require_staff),
) -> dict:
    rows = request.app.state.store.list_audit(limit=min(200, max(1, limit)), decision=decision or None)
    return {"items": rows}


class SyncBody(BaseModel):
    enabled: bool | None = None
    face_status: str | None = None
    display_name: str | None = None


@app.post("/api/persons/{user_id}/sync")
async def sync_person(
    user_id: str,
    body: SyncBody,
    request: Request,
    actor: Actor = Depends(require_staff),
) -> dict:
    """云端停用/状态同步：停用优先于本地旧状态。"""
    store = request.app.state.store
    p = store.get_person(user_id)
    name = body.display_name or (p.display_name if p else user_id)
    if body.enabled is False:
        store.set_enabled(user_id, False)
        store.set_status(user_id, body.face_status or "rejected")
        store.clear_cooldown(user_id)
        return {"ok": True, "user_id": user_id, "enabled": False, "face_status": body.face_status or "rejected"}
    if body.face_status:
        store.upsert_person(user_id, name, body.face_status, enabled=True if body.enabled is None else body.enabled)
    elif body.enabled is True:
        store.set_enabled(user_id, True)
    return {
        "ok": True,
        "user_id": user_id,
        "enabled": body.enabled,
        "face_status": body.face_status,
    }


@app.post("/api/admin/reembed")
async def reembed(request: Request, actor: Actor = Depends(require_staff)) -> dict:
    """换模型后用本地合格帧批量重嵌；不要求全员重采。"""
    if not actor.is_admin and actor.kind != "dev":
        raise HTTPException(403, "admin_required")
    store = request.app.state.store
    emb = request.app.state.embedder
    if not emb.ready:
        raise HTTPException(503, "model_not_loaded")
    from PIL import Image
    import io
    import numpy as np

    done, skipped = 0, 0
    for p in store.list_persons():
        paths = store.frame_paths_for_user(p.user_id)
        if not paths:
            skipped += 1
            continue
        vecs, kept = [], []
        for fp in paths:
            try:
                raw = Path(fp).read_bytes()
                img = Image.open(io.BytesIO(raw)).convert("RGB")
                arr = np.asarray(img)[:, :, ::-1].copy()
                vec, meta = emb.embed(arr)
                if vec is None or not meta.get("ok"):
                    continue
                vecs.append(vec)
                kept.append(fp)
            except Exception:
                continue
        if not vecs:
            skipped += 1
            continue
        store.commit_enrollment(p.user_id, p.display_name, emb.model_version, vecs, kept)
        store.set_status(p.user_id, p.face_status if p.face_status in ("accepted", "verified") else "accepted")
        done += 1
    return {"ok": True, "reembedded": done, "skipped": skipped}


@app.post("/api/enroll/start")
async def enroll_start(
    body: StartBody,
    request: Request,
    actor: Actor = Depends(require_staff),
    x_lobn_user_id: str | None = Header(default=None, alias="X-Lobn-User-Id"),
) -> dict:
    request.app.state.disk_full = refresh_disk_full(request.app.state.settings)
    if request.app.state.disk_full:
        raise HTTPException(507, "disk_full")
    if not request.app.state.embedder.ready:
        raise HTTPException(503, "model_not_loaded")
    if body.channel == "staff" and actor.kind == "relay":
        raise HTTPException(403, "staff_channel_requires_ha")
    user_id = body.user_id
    if actor.kind == "relay":
        if not x_lobn_user_id:
            raise HTTPException(400, "relay_requires_user_id")
        if body.channel != "student":
            raise HTTPException(403, "relay_student_only")
        if str(body.user_id) != str(x_lobn_user_id):
            raise HTTPException(403, "user_mismatch")
        user_id = str(x_lobn_user_id)
    try:
        sess = request.app.state.sessions.start(user_id, body.display_name, body.channel, actor.id)
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    return {
        "session_id": sess.session_id,
        "user_id": sess.user_id,
        "needed": sess.needed,
        "progress": 0,
    }


@app.post("/api/enroll/{session_id}/frame")
async def enroll_frame(
    session_id: str,
    request: Request,
    file: UploadFile = File(...),
    actor: Actor = Depends(require_staff),
    x_lobn_user_id: str | None = Header(default=None, alias="X-Lobn-User-Id"),
) -> dict:
    if request.app.state.disk_full:
        raise HTTPException(507, "disk_full")
    data = await file.read()
    expected = None
    if actor.kind == "relay":
        expected = x_lobn_user_id
        if not expected:
            raise HTTPException(400, "relay_requires_user_id")
    result = request.app.state.sessions.push_jpeg(session_id, data, expected_user_id=expected)
    # 不回向量/阈值
    return {
        "ok": bool(result.get("ok")),
        "reason": result.get("reason"),
        "hint": result.get("hint"),
        "progress": result.get("progress"),
        "needed": result.get("needed"),
        "done": bool(result.get("done")),
        "face_status": result.get("face_status"),
    }


@app.post("/api/enroll/{session_id}/cancel")
async def enroll_cancel(session_id: str, request: Request, actor: Actor = Depends(require_staff)) -> dict:
    request.app.state.sessions.cancel(session_id)
    return {"ok": True}


@app.post("/api/internal/match_test")
async def match_test(request: Request, actor: Actor = Depends(require_staff)) -> dict:
    """开发用：用上传的多帧跑门口仲裁（不经 MQTT）。"""
    form = await request.form()
    files = form.getlist("files")
    camera = str(form.get("camera") or "front_desk")
    frames = []
    from PIL import Image
    import io
    import numpy as np

    for f in files:
        raw = await f.read()  # type: ignore[attr-defined]
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        frames.append(np.asarray(img)[:, :, ::-1].copy())
    result = request.app.state.matcher.match_frames(camera, frames, event_id="test")
    out = {"decision": result.decision, "reason": result.reason, "user_id": result.user_id, "similarity": result.similarity}
    if result.grant and actor.is_admin:
        out["command_id"] = result.grant.get("command_id")
    return out

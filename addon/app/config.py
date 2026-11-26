from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class Settings(BaseModel):
    school_id: int = 1
    door_cameras: list[str] = Field(default_factory=lambda: ["front_desk"])
    door_zones: list[str] = Field(default_factory=lambda: ["front_desk_zone"])
    door_node: str = "front_gate"
    match_threshold: float = 0.42
    verify_threshold: float = 0.48
    cooldown_sec: float = 30.0
    required_enroll_frames: int = 5
    required_match_frames: int = 3
    model_version: str = "mock-v1"
    frigate_url: str = "http://127.0.0.1:5000"
    go2rtc_url: str = "http://127.0.0.1:1984"
    cloud_base_url: str = ""
    cloud_hmac_secret: str = ""
    backup_interval_hours: float = 6.0
    # —— 长时间运行容量 ——
    audit_max_rows: int = 5000
    audit_max_age_days: float = 30.0
    grants_seen_max_age_hours: float = 48.0
    session_ttl_sec: float = 1800.0
    maintenance_interval_sec: float = 900.0
    log_max_mb: int = 5
    log_backup_count: int = 5
    match_concurrency: int = 1
    data_dir: Path = Path("/data")
    mqtt_host: str = "core-mosquitto"
    mqtt_port: int = 1883
    mqtt_user: str = ""
    mqtt_password: str = ""
    # 开发态：跳过 HA Ingress 鉴权
    allow_dev_auth: bool = False
    embedder: str = "mock"  # mock | onnx

    @property
    def mqtt_enabled(self) -> bool:
        h = (self.mqtt_host or "").strip().lower()
        return h not in ("", "off", "disabled", "none", "-")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "smartcenter.sqlite3"

    @property
    def frames_dir(self) -> Path:
        return self.data_dir / "enroll_frames"

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backups"


def _from_options(raw: dict[str, Any], *, local_dev: bool = False) -> Settings:
    data_dir = Path(os.environ.get("SMARTCENTER_DATA", "/data"))
    # 本机开发默认不连 core-mosquitto（HAOS 内网名会 DNS 失败刷屏）
    if "MQTT_HOST" in os.environ:
        mqtt_host = os.environ["MQTT_HOST"]
    elif raw.get("mqtt_host") is not None:
        mqtt_host = str(raw.get("mqtt_host") or "")
    elif local_dev or os.environ.get("SMARTCENTER_DEV_AUTH", "").lower() in ("1", "true", "yes"):
        mqtt_host = "off"
    else:
        mqtt_host = "core-mosquitto"
    return Settings(
        school_id=int(raw.get("school_id", 1)),
        door_cameras=list(raw.get("door_cameras") or ["front_desk"]),
        door_zones=list(raw.get("door_zones") or ["front_desk_zone"]),
        door_node=str(raw.get("door_node", "front_gate")),
        match_threshold=float(raw.get("match_threshold", 0.42)),
        verify_threshold=float(raw.get("verify_threshold", 0.48)),
        cooldown_sec=float(raw.get("cooldown_sec", 30)),
        required_enroll_frames=int(raw.get("required_enroll_frames", 5)),
        required_match_frames=int(raw.get("required_match_frames", 3)),
        model_version=str(raw.get("model_version", "mock-v1")),
        frigate_url=str(raw.get("frigate_url", "http://127.0.0.1:5000")),
        go2rtc_url=str(raw.get("go2rtc_url", "http://127.0.0.1:1984")),
        cloud_base_url=str(raw.get("cloud_base_url", "")),
        cloud_hmac_secret=str(raw.get("cloud_hmac_secret", "")),
        backup_interval_hours=float(raw.get("backup_interval_hours", 6)),
        audit_max_rows=int(raw.get("audit_max_rows", 5000)),
        audit_max_age_days=float(raw.get("audit_max_age_days", 30)),
        grants_seen_max_age_hours=float(raw.get("grants_seen_max_age_hours", 48)),
        session_ttl_sec=float(raw.get("session_ttl_sec", 1800)),
        maintenance_interval_sec=float(raw.get("maintenance_interval_sec", 900)),
        log_max_mb=int(raw.get("log_max_mb", 5)),
        log_backup_count=int(raw.get("log_backup_count", 5)),
        match_concurrency=int(raw.get("match_concurrency", 1)),
        data_dir=data_dir,
        mqtt_host=str(mqtt_host),
        mqtt_port=int(os.environ.get("MQTT_PORT", raw.get("mqtt_port", 1883))),
        mqtt_user=str(os.environ.get("MQTT_USER", raw.get("mqtt_user", ""))),
        mqtt_password=str(os.environ.get("MQTT_PASSWORD", raw.get("mqtt_password", ""))),
        allow_dev_auth=os.environ.get("SMARTCENTER_DEV_AUTH", "").lower() in ("1", "true", "yes"),
        embedder=str(os.environ.get("SMARTCENTER_EMBEDDER", raw.get("embedder", "mock"))),
        # options.json 也可带 mqtt_*；无 Supervisor 注入时回落
        # （run.sh 已 export MQTT_* 时上面分支优先）
    )


def load_settings() -> Settings:
    blob = os.environ.get("SMARTCENTER_OPTIONS", "").strip()
    if blob:
        try:
            return _from_options(json.loads(blob))
        except json.JSONDecodeError:
            pass
    opts_path = Path("/data/options.json")
    if opts_path.is_file():
        return _from_options(json.loads(opts_path.read_text(encoding="utf-8")))
    # 本地开发默认（无 Supervisor options）
    data = Path(os.environ.get("SMARTCENTER_DATA", "./data"))
    s = _from_options({}, local_dev=True)
    s.data_dir = data
    s.allow_dev_auth = True
    if not s.mqtt_enabled:
        s.mqtt_host = "off"
    return s

"""Pydantic 2 载荷模型（契约字段只增不改）。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class CctvEvent(BaseModel):
    schema_name: str = Field(default="smartcctv.event.v1", alias="schema")
    type: str
    level: str = "info"
    cam_id: str | None = None
    ts: float
    mode: str = "day"
    payload: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class DoorCommand(BaseModel):
    schema_name: str = Field(default="door.command.v1", alias="schema")
    command_id: str
    door_id: str = "main"
    action: Literal["open", "close"] = "open"
    seconds: float = 5
    reason: Literal["face_match", "booking_grant", "manual"] = "manual"
    grant_id: str | None = None
    user_id: str | None = None
    person_id: int | None = None
    person_name: str = ""
    token: str | None = None
    ts: float

    model_config = {"populate_by_name": True}


class Grant(BaseModel):
    schema_name: str = Field(default="grant.v1", alias="schema")
    grant_id: str
    user_id: str
    room_id: str = "room_1"
    source: Literal["booking", "voucher"] = "booking"
    order_id: str | None = None
    voucher_id: str | None = None
    window_start: float
    window_end: float
    status: Literal["pending", "opened", "denied", "unknown"] = "pending"
    correlation_id: str = ""
    created_at: float = 0

    model_config = {"populate_by_name": True}

    def active_at(self, now: float) -> bool:
        # pending：尚未首次开门；opened：窗口内可再脉冲（冷却由门控负责）
        return self.status in ("pending", "opened") and self.window_start <= now <= self.window_end


class GrantAck(BaseModel):
    schema_name: str = Field(default="grant.ack.v1", alias="schema")
    grant_id: str
    command_id: str
    result: Literal["opened", "denied", "unknown"]
    correlation_id: str = ""
    ts: float
    detail: str = ""

    model_config = {"populate_by_name": True}


class PersonRecord(BaseModel):
    person_id: int
    user_id: str
    name: str
    enabled: bool = True

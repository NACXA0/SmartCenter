"""开门热路径：只读内存，不访问云端/监控库。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .models import Grant, PersonRecord


@dataclass
class HotPathDecision:
    allow: bool
    reason: str = ""
    person: PersonRecord | None = None
    grant: Grant | None = None


@dataclass
class InMemoryHotPath:
    persons_by_id: dict[int, PersonRecord] = field(default_factory=dict)
    persons_by_user: dict[str, PersonRecord] = field(default_factory=dict)
    grants: dict[str, Grant] = field(default_factory=dict)
    settled_opened: set[str] = field(default_factory=set)  # grant_id 已扣费回执

    def upsert_person(self, person: PersonRecord) -> None:
        self.persons_by_id[person.person_id] = person
        if person.user_id:
            self.persons_by_user[person.user_id] = person

    def disable_person(self, person_id: int) -> None:
        p = self.persons_by_id.get(person_id)
        if p:
            p.enabled = False

    def upsert_grant(self, grant: Grant) -> None:
        self.grants[grant.grant_id] = grant

    def purge_expired(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        dead = [gid for gid, g in self.grants.items() if g.window_end < now - 3600]
        for gid in dead:
            self.grants.pop(gid, None)

    def get_active_grants(self, now: float | None = None) -> list[Grant]:
        now = time.time() if now is None else now
        return [g for g in self.grants.values() if g.active_at(now)]

    def decide_face(self, person_id: int | None, now: float | None = None) -> HotPathDecision:
        if person_id is None:
            return HotPathDecision(False, "无人脸编号")
        person = self.persons_by_id.get(person_id)
        if person is None:
            return HotPathDecision(False, "人员未在热名单")
        if not person.enabled:
            return HotPathDecision(False, "人员已停用")
        return HotPathDecision(True, "face_match", person=person)

    def decide_grant(self, grant_id: str, now: float | None = None) -> HotPathDecision:
        now = time.time() if now is None else now
        grant = self.grants.get(grant_id)
        if grant is None:
            return HotPathDecision(False, "授权不存在")
        if grant.status not in ("pending", "opened"):
            return HotPathDecision(False, f"授权状态 {grant.status}")
        if not (grant.window_start <= now <= grant.window_end):
            return HotPathDecision(False, "不在授权窗口")
        return HotPathDecision(True, "booking_grant", grant=grant)

    def decide_user_grant(self, user_id: str, now: float | None = None) -> HotPathDecision:
        now = time.time() if now is None else now
        for grant in self.get_active_grants(now):
            if grant.user_id == user_id:
                return HotPathDecision(True, "booking_grant", grant=grant)
        return HotPathDecision(False, "无有效授权")

    def mark_opened(self, grant_id: str) -> bool:
        """返回是否第一次 opened（用于只扣费一次）。"""
        if grant_id in self.settled_opened:
            return False
        self.settled_opened.add(grant_id)
        g = self.grants.get(grant_id)
        if g:
            g.status = "opened"
        return True

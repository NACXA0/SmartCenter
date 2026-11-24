import time

from lobn_office.hot_path import InMemoryHotPath
from lobn_office.models import Grant, PersonRecord


def test_face_requires_enabled():
    hot = InMemoryHotPath()
    hot.upsert_person(PersonRecord(person_id=1, user_id="u1", name="张三", enabled=True))
    assert hot.decide_face(1).allow
    hot.disable_person(1)
    d = hot.decide_face(1)
    assert not d.allow


def test_grant_window_and_once_opened():
    hot = InMemoryHotPath()
    now = time.time()
    g = Grant(
        grant_id="g1",
        user_id="u1",
        window_start=now - 10,
        window_end=now + 100,
        status="pending",
        correlation_id="c1",
    )
    hot.upsert_grant(g)
    assert hot.decide_grant("g1", now).allow
    assert hot.mark_opened("g1") is True
    assert hot.mark_opened("g1") is False

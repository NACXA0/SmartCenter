from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np


SCHEMA = """
CREATE TABLE IF NOT EXISTS persons (
  user_id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL DEFAULT '',
  face_status TEXT NOT NULL DEFAULT 'none',
  enabled INTEGER NOT NULL DEFAULT 1,
  verify_ok_count INTEGER NOT NULL DEFAULT 0,
  verify_fail_streak INTEGER NOT NULL DEFAULT 0,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS embeddings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  model_version TEXT NOT NULL,
  dim INTEGER NOT NULL,
  vector BLOB NOT NULL,
  frame_path TEXT,
  created_at REAL NOT NULL,
  FOREIGN KEY(user_id) REFERENCES persons(user_id)
);
CREATE INDEX IF NOT EXISTS idx_emb_user ON embeddings(user_id);
CREATE TABLE IF NOT EXISTS cooldowns (
  user_id TEXT PRIMARY KEY,
  until_mono REAL NOT NULL,
  until_wall REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS grants_seen (
  command_id TEXT PRIMARY KEY,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS match_audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT,
  camera TEXT,
  similarity REAL,
  decision TEXT,
  detail TEXT,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_created ON match_audit(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_decision ON match_audit(decision);
CREATE INDEX IF NOT EXISTS idx_grants_created ON grants_seen(created_at);
"""


@dataclass
class PersonRow:
    user_id: str
    display_name: str
    face_status: str
    enabled: bool
    verify_ok_count: int
    verify_fail_streak: int


class GalleryStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        # 长时间写入友好：WAL + 适度同步
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA temp_store=MEMORY")
        self._conn.execute("PRAGMA busy_timeout=30000")
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self._mem: dict[str, list[np.ndarray]] = {}
        self._model_version: str = ""
        self._last_optimize_at = 0.0
        self._rebase_cooldowns()
        self.reload_memory()

    def _rebase_cooldowns(self) -> None:
        """进程重启后单调钟归零：用 wall 时钟把未过期冷却映射回当前 mono。"""
        now_wall = time.time()
        now_mono = time.monotonic()
        rows = self._conn.execute("SELECT user_id, until_wall FROM cooldowns").fetchall()
        for r in rows:
            remain = float(r["until_wall"]) - now_wall
            if remain <= 0:
                self._conn.execute("DELETE FROM cooldowns WHERE user_id=?", (r["user_id"],))
            else:
                self._conn.execute(
                    "UPDATE cooldowns SET until_mono=? WHERE user_id=?",
                    (now_mono + remain, r["user_id"]),
                )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def reload_memory(self, model_version: str | None = None) -> None:
        mv = model_version
        self._mem.clear()
        q = "SELECT user_id, model_version, vector FROM embeddings e JOIN persons p USING(user_id) WHERE p.enabled=1 AND p.face_status IN ('accepted','verified')"
        rows = self._conn.execute(q).fetchall()
        for r in rows:
            if mv and r["model_version"] != mv:
                continue
            vec = np.frombuffer(r["vector"], dtype=np.float32).copy()
            self._mem.setdefault(r["user_id"], []).append(vec)
        if mv:
            self._model_version = mv
        elif rows:
            self._model_version = rows[0]["model_version"]

    def memory_vectors(self) -> dict[str, list[np.ndarray]]:
        return self._mem

    def get_person(self, user_id: str) -> PersonRow | None:
        r = self._conn.execute("SELECT * FROM persons WHERE user_id=?", (user_id,)).fetchone()
        if not r:
            return None
        return PersonRow(
            user_id=r["user_id"],
            display_name=r["display_name"],
            face_status=r["face_status"],
            enabled=bool(r["enabled"]),
            verify_ok_count=int(r["verify_ok_count"]),
            verify_fail_streak=int(r["verify_fail_streak"]),
        )

    def list_persons(self) -> list[PersonRow]:
        rows = self._conn.execute("SELECT * FROM persons ORDER BY updated_at DESC").fetchall()
        return [
            PersonRow(
                user_id=r["user_id"],
                display_name=r["display_name"],
                face_status=r["face_status"],
                enabled=bool(r["enabled"]),
                verify_ok_count=int(r["verify_ok_count"]),
                verify_fail_streak=int(r["verify_fail_streak"]),
            )
            for r in rows
        ]

    def search_persons(self, q: str, limit: int = 30) -> list[PersonRow]:
        q = (q or "").strip()
        if not q:
            return self.list_persons()[:limit]
        like = f"%{q}%"
        rows = self._conn.execute(
            """
            SELECT * FROM persons
            WHERE user_id LIKE ? OR display_name LIKE ?
            ORDER BY
              CASE WHEN face_status='pending' THEN 0 ELSE 1 END,
              updated_at DESC
            LIMIT ?
            """,
            (like, like, limit),
        ).fetchall()
        return [
            PersonRow(
                user_id=r["user_id"],
                display_name=r["display_name"],
                face_status=r["face_status"],
                enabled=bool(r["enabled"]),
                verify_ok_count=int(r["verify_ok_count"]),
                verify_fail_streak=int(r["verify_fail_streak"]),
            )
            for r in rows
        ]

    def delete_person(self, user_id: str) -> bool:
        paths = self.frame_paths_for_user(user_id)
        cur = self._conn.cursor()
        cur.execute("BEGIN")
        try:
            cur.execute("DELETE FROM embeddings WHERE user_id=?", (user_id,))
            cur.execute("DELETE FROM cooldowns WHERE user_id=?", (user_id,))
            cur.execute("DELETE FROM persons WHERE user_id=?", (user_id,))
            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            raise
        for fp in paths:
            try:
                Path(fp).unlink(missing_ok=True)
            except Exception:
                pass
        self.reload_memory(self._model_version or None)
        return True

    def list_audit(self, limit: int = 50, decision: str | None = None) -> list[dict[str, Any]]:
        if decision:
            rows = self._conn.execute(
                "SELECT * FROM match_audit WHERE decision=? ORDER BY id DESC LIMIT ?",
                (decision, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM match_audit ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        out = []
        for r in rows:
            try:
                detail = json.loads(r["detail"] or "{}")
            except Exception:
                detail = {}
            out.append(
                {
                    "id": r["id"],
                    "user_id": r["user_id"],
                    "camera": r["camera"],
                    "similarity": r["similarity"],
                    "decision": r["decision"],
                    "detail": detail,
                    "created_at": r["created_at"],
                }
            )
        return out

    def upsert_person(self, user_id: str, display_name: str, face_status: str, enabled: bool = True) -> None:
        now = time.time()
        self._conn.execute(
            """
            INSERT INTO persons(user_id, display_name, face_status, enabled, verify_ok_count, verify_fail_streak, updated_at)
            VALUES(?,?,?,?,0,0,?)
            ON CONFLICT(user_id) DO UPDATE SET
              display_name=excluded.display_name,
              face_status=excluded.face_status,
              enabled=excluded.enabled,
              updated_at=excluded.updated_at
            """,
            (user_id, display_name, face_status, 1 if enabled else 0, now),
        )
        self._conn.commit()

    def set_status(self, user_id: str, face_status: str) -> None:
        self._conn.execute(
            "UPDATE persons SET face_status=?, updated_at=? WHERE user_id=?",
            (face_status, time.time(), user_id),
        )
        self._conn.commit()

    def set_enabled(self, user_id: str, enabled: bool) -> None:
        self._conn.execute(
            "UPDATE persons SET enabled=?, updated_at=? WHERE user_id=?",
            (1 if enabled else 0, time.time(), user_id),
        )
        self._conn.commit()
        self.reload_memory(self._model_version or None)

    def commit_enrollment(
        self,
        user_id: str,
        display_name: str,
        model_version: str,
        vectors: Iterable[np.ndarray],
        frame_paths: Iterable[str | None],
    ) -> None:
        """一次事务写入底库；中途失败不留下半套向量。"""
        now = time.time()
        cur = self._conn.cursor()
        try:
            cur.execute("BEGIN")
            cur.execute(
                """
                INSERT INTO persons(user_id, display_name, face_status, enabled, verify_ok_count, verify_fail_streak, updated_at)
                VALUES(?,?, 'accepted', 1, 0, 0, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                  display_name=excluded.display_name,
                  face_status='accepted',
                  enabled=1,
                  verify_ok_count=0,
                  verify_fail_streak=0,
                  updated_at=excluded.updated_at
                """,
                (user_id, display_name, now),
            )
            cur.execute("DELETE FROM embeddings WHERE user_id=?", (user_id,))
            for vec, path in zip(vectors, frame_paths, strict=False):
                arr = np.asarray(vec, dtype=np.float32).reshape(-1)
                cur.execute(
                    "INSERT INTO embeddings(user_id, model_version, dim, vector, frame_path, created_at) VALUES(?,?,?,?,?,?)",
                    (user_id, model_version, int(arr.size), arr.tobytes(), path, now),
                )
            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            raise
        self.reload_memory(model_version)

    def bump_verify(self, user_id: str, ok: bool, need: int = 3) -> str:
        p = self.get_person(user_id)
        if not p:
            return "none"
        if ok:
            ok_c = p.verify_ok_count + 1
            fail = 0
            status = "verified" if ok_c >= need else p.face_status
            if status == "accepted" and ok_c < need:
                status = "accepted"
            self._conn.execute(
                "UPDATE persons SET verify_ok_count=?, verify_fail_streak=?, face_status=?, updated_at=? WHERE user_id=?",
                (ok_c, fail, status, time.time(), user_id),
            )
        else:
            fail = p.verify_fail_streak + 1
            status = "pending" if fail >= need else p.face_status
            self._conn.execute(
                "UPDATE persons SET verify_fail_streak=?, face_status=?, updated_at=? WHERE user_id=?",
                (fail, status, time.time(), user_id),
            )
            if status == "pending":
                self._conn.execute("UPDATE persons SET enabled=1 WHERE user_id=?", (user_id,))
        self._conn.commit()
        if status == "pending":
            self.reload_memory(self._model_version or None)
        return status

    # --- cooldown (monotonic + persisted) ---
    def clear_cooldown(self, user_id: str) -> None:
        self._conn.execute("DELETE FROM cooldowns WHERE user_id=?", (user_id,))
        self._conn.commit()

    def set_cooldown(self, user_id: str, until_mono: float, until_wall: float) -> None:
        self._conn.execute(
            """
            INSERT INTO cooldowns(user_id, until_mono, until_wall) VALUES(?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET until_mono=excluded.until_mono, until_wall=excluded.until_wall
            """,
            (user_id, until_mono, until_wall),
        )
        self._conn.commit()

    def cooldown_active(self, user_id: str, now_mono: float) -> bool:
        r = self._conn.execute(
            "SELECT until_mono, until_wall FROM cooldowns WHERE user_id=?",
            (user_id,),
        ).fetchone()
        if not r:
            return False
        # wall：抗重启；mono：抗改系统时间把冷却清掉
        if float(r["until_wall"]) > time.time():
            return True
        return float(r["until_mono"]) > now_mono

    def mark_grant(self, command_id: str) -> bool:
        """返回 True 表示首次见到该 command_id。"""
        try:
            self._conn.execute(
                "INSERT INTO grants_seen(command_id, created_at) VALUES(?,?)",
                (command_id, time.time()),
            )
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def audit(self, user_id: str | None, camera: str, similarity: float, decision: str, detail: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT INTO match_audit(user_id, camera, similarity, decision, detail, created_at) VALUES(?,?,?,?,?,?)",
            (user_id, camera, similarity, decision, json.dumps(detail, ensure_ascii=False), time.time()),
        )
        self._conn.commit()

    def prune_audit(self, max_rows: int = 5000, max_age_days: float = 30.0) -> dict[str, int]:
        """按条数上限 + 年龄双轨裁剪开门审计。"""
        deleted = 0
        now = time.time()
        if max_age_days > 0:
            cutoff = now - max_age_days * 86400.0
            cur = self._conn.execute("DELETE FROM match_audit WHERE created_at < ?", (cutoff,))
            deleted += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        if max_rows > 0:
            row = self._conn.execute("SELECT COUNT(*) AS c FROM match_audit").fetchone()
            total = int(row["c"] if row else 0)
            if total > max_rows:
                # 保留最新 max_rows：删掉更旧的
                overflow = total - max_rows
                cur = self._conn.execute(
                    """
                    DELETE FROM match_audit WHERE id IN (
                      SELECT id FROM match_audit ORDER BY id ASC LIMIT ?
                    )
                    """,
                    (overflow,),
                )
                deleted += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        self._conn.commit()
        left = int(self._conn.execute("SELECT COUNT(*) AS c FROM match_audit").fetchone()["c"])
        return {"deleted": deleted, "remaining": left}

    def prune_grants_seen(self, max_age_hours: float = 48.0) -> int:
        """command_id 去重只需短期窗口，过期即可删。"""
        cutoff = time.time() - max(1.0, max_age_hours) * 3600.0
        cur = self._conn.execute("DELETE FROM grants_seen WHERE created_at < ?", (cutoff,))
        self._conn.commit()
        return int(cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0)

    def prune_expired_cooldowns(self) -> int:
        now_wall = time.time()
        now_mono = time.monotonic()
        cur = self._conn.execute(
            "DELETE FROM cooldowns WHERE until_wall <= ? AND until_mono <= ?",
            (now_wall, now_mono),
        )
        self._conn.commit()
        return int(cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0)

    def all_frame_paths(self) -> set[str]:
        rows = self._conn.execute(
            "SELECT frame_path FROM embeddings WHERE frame_path IS NOT NULL AND frame_path != ''"
        ).fetchall()
        return {str(r["frame_path"]) for r in rows if r["frame_path"]}

    def maybe_optimize(self, min_interval_sec: float = 6 * 3600.0) -> bool:
        """低频 PRAGMA optimize（非全量 VACUUM，避免长时间锁库）。"""
        now = time.time()
        if now - self._last_optimize_at < min_interval_sec:
            return False
        try:
            self._conn.execute("PRAGMA optimize")
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self._conn.commit()
            self._last_optimize_at = now
            return True
        except Exception:
            return False

    def stats(self) -> dict[str, Any]:
        def _count(table: str) -> int:
            return int(self._conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"])

        db_bytes = self.db_path.stat().st_size if self.db_path.is_file() else 0
        wal = self.db_path.with_suffix(self.db_path.suffix + "-wal")
        wal_bytes = wal.stat().st_size if wal.is_file() else 0
        return {
            "persons": _count("persons"),
            "embeddings": _count("embeddings"),
            "match_audit": _count("match_audit"),
            "grants_seen": _count("grants_seen"),
            "cooldowns": _count("cooldowns"),
            "db_bytes": db_bytes,
            "wal_bytes": wal_bytes,
        }

    def dashboard(self) -> dict[str, Any]:
        """工作台概览：底库分布 + 开门统计 + 待办队列。"""
        by_status: dict[str, int] = {}
        for r in self._conn.execute(
            "SELECT face_status, COUNT(*) AS c FROM persons GROUP BY face_status"
        ).fetchall():
            by_status[str(r["face_status"])] = int(r["c"])
        total = sum(by_status.values())
        enabled = int(
            self._conn.execute(
                "SELECT COUNT(*) AS c FROM persons WHERE enabled=1 AND face_status IN ('accepted','verified')"
            ).fetchone()["c"]
        )
        pending = [
            {
                "user_id": r["user_id"],
                "display_name": r["display_name"],
                "face_status": r["face_status"],
                "updated_at": r["updated_at"],
            }
            for r in self._conn.execute(
                """
                SELECT user_id, display_name, face_status, updated_at FROM persons
                WHERE face_status='pending'
                ORDER BY updated_at DESC LIMIT 20
                """
            ).fetchall()
        ]
        now = time.time()

        def _decisions(since: float) -> dict[str, int]:
            out = {"grant": 0, "deny": 0, "skip": 0}
            for r in self._conn.execute(
                """
                SELECT decision, COUNT(*) AS c FROM match_audit
                WHERE created_at >= ? GROUP BY decision
                """,
                (since,),
            ).fetchall():
                k = str(r["decision"])
                if k in out:
                    out[k] = int(r["c"])
            return out

        top_grant = [
            {"user_id": r["user_id"], "n": int(r["c"])}
            for r in self._conn.execute(
                """
                SELECT user_id, COUNT(*) AS c FROM match_audit
                WHERE decision='grant' AND created_at >= ? AND user_id IS NOT NULL
                GROUP BY user_id ORDER BY c DESC LIMIT 8
                """,
                (now - 7 * 86400,),
            ).fetchall()
        ]
        return {
            "persons": {
                "total": total,
                "enabled_door": enabled,
                "by_status": by_status,
                "pending_recollect": pending,
            },
            "access": {
                "h24": _decisions(now - 86400),
                "d7": _decisions(now - 7 * 86400),
                "top_grant_7d": top_grant,
            },
            "store": self.stats(),
        }

    def set_display_name(self, user_id: str, display_name: str) -> None:
        self._conn.execute(
            "UPDATE persons SET display_name=?, updated_at=? WHERE user_id=?",
            (display_name, time.time(), user_id),
        )
        self._conn.commit()

    def online_backup(self, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest = dest if dest.suffix else dest.with_suffix(".sqlite3")
        with sqlite3.connect(str(dest)) as out:
            self._conn.backup(out)
        return dest

    def frame_paths_for_user(self, user_id: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT frame_path FROM embeddings WHERE user_id=? AND frame_path IS NOT NULL",
            (user_id,),
        ).fetchall()
        return [r["frame_path"] for r in rows if r["frame_path"]]

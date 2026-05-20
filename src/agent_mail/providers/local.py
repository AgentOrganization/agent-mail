"""SQLite-backed local message provider.

URI: ``agentmail://local/<agent_id>/<channel>[/<msg_id>]``

Single-file SQLite database (WAL mode) at ``$AGENT_MAIL_LOCAL_DIR/mail.db``
or whatever path is passed to :class:`LocalProvider`. One row per message;
``status`` transitions ``pending → inflight → acked``. ``recv()`` flips
``pending`` rows to ``inflight`` with a visibility timeout; un-acked
``inflight`` rows return to ``pending`` after the timeout.
"""
from __future__ import annotations

import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Optional

from ..core import (
    DEFAULT_CHANNEL,
    Message,
    MessageProvider,
    build_uri,
)


DEFAULT_VISIBILITY_TIMEOUT_S = 60


SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id              TEXT PRIMARY KEY,
    agent_id        TEXT NOT NULL,      -- recipient (owns the row)
    channel         TEXT NOT NULL,
    from_agent      TEXT NOT NULL,
    subject         TEXT NOT NULL DEFAULT '',
    body            TEXT NOT NULL DEFAULT '',
    type            TEXT NOT NULL DEFAULT 'request',
    attachments     TEXT NOT NULL DEFAULT '[]',   -- JSON array
    reply_to        TEXT,
    correlation_id  TEXT,
    ttl_seconds     INTEGER,
    created_at      TEXT NOT NULL,
    protocol_version TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending | inflight | acked
    inflight_until  REAL,                              -- epoch seconds
    raw_json        TEXT NOT NULL                      -- original wire form
);

CREATE INDEX IF NOT EXISTS idx_inbox
    ON messages(agent_id, channel, status, created_at);
"""


class LocalProvider(MessageProvider):
    """SQLite WAL-backed mailbox. Single-machine, multi-process safe."""

    scheme = "local"

    def __init__(self, base_path: str | os.PathLike,
                 visibility_timeout_s: int = DEFAULT_VISIBILITY_TIMEOUT_S):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.db_path = self.base_path / "mail.db"
        self.visibility_timeout_s = visibility_timeout_s
        with self._conn() as c:
            c.executescript(SCHEMA)
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(
            self.db_path, isolation_level=None, timeout=30.0
        )
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    # ------------------------------------------------------------------
    def send(self, message: Message) -> str:
        with self._conn() as c:
            c.execute(
                """INSERT INTO messages(
                    id, agent_id, channel, from_agent, subject, body, type,
                    attachments, reply_to, correlation_id, ttl_seconds,
                    created_at, protocol_version, raw_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    message.id, message.to, message.channel, message.from_,
                    message.subject, message.body, message.type,
                    _json(message.attachments), message.reply_to,
                    message.correlation_id, message.ttl_seconds,
                    message.created_at, message.protocol_version,
                    message.to_json(),
                ),
            )
        return build_uri(self.scheme, message.to, message.channel, message.id)

    # ------------------------------------------------------------------
    def _revive_expired_inflight(self, c: sqlite3.Connection,
                                 agent_id: str, channel: str) -> None:
        c.execute(
            """UPDATE messages
                  SET status='pending', inflight_until=NULL
                WHERE agent_id=? AND channel=? AND status='inflight'
                  AND inflight_until IS NOT NULL
                  AND inflight_until < ?""",
            (agent_id, channel, time.time()),
        )

    def recv(self, agent_id: str, channel: str = DEFAULT_CHANNEL,
             limit: int = 10, peek: bool = False) -> list[Message]:
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            self._revive_expired_inflight(c, agent_id, channel)
            rows = c.execute(
                """SELECT raw_json, id FROM messages
                    WHERE agent_id=? AND channel=? AND status='pending'
                    ORDER BY created_at ASC, id ASC
                    LIMIT ?""",
                (agent_id, channel, limit),
            ).fetchall()
            if not peek and rows:
                ids = [r["id"] for r in rows]
                until = time.time() + self.visibility_timeout_s
                qmarks = ",".join("?" * len(ids))
                c.execute(
                    f"UPDATE messages SET status='inflight', inflight_until=? "
                    f"WHERE id IN ({qmarks})",
                    [until, *ids],
                )
            c.execute("COMMIT")
            return [Message.from_json(r["raw_json"]) for r in rows]

    # ------------------------------------------------------------------
    def ack(self, agent_id: str, msg_id: str) -> bool:
        with self._conn() as c:
            cur = c.execute(
                """UPDATE messages SET status='acked', inflight_until=NULL
                    WHERE id=? AND agent_id=?""",
                (msg_id, agent_id),
            )
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    def list(self, agent_id: str, channel: Optional[str] = None) -> Iterable[dict]:
        with self._conn() as c:
            if channel:
                rows = c.execute(
                    """SELECT id, channel, from_agent, subject, status, created_at
                         FROM messages WHERE agent_id=? AND channel=?
                         ORDER BY created_at DESC""",
                    (agent_id, channel),
                ).fetchall()
            else:
                rows = c.execute(
                    """SELECT id, channel, from_agent, subject, status, created_at
                         FROM messages WHERE agent_id=?
                         ORDER BY created_at DESC""",
                    (agent_id,),
                ).fetchall()
            for r in rows:
                yield {
                    "id": r["id"],
                    "channel": r["channel"],
                    "from": r["from_agent"],
                    "subject": r["subject"],
                    "status": r["status"],
                    "created_at": r["created_at"],
                    "uri": build_uri(self.scheme, agent_id, r["channel"], r["id"]),
                }


def _json(v) -> str:
    import json as _j
    return _j.dumps(v, ensure_ascii=False)

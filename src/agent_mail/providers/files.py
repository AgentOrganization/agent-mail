"""File-backed message provider — the v0.2 default.

**Design philosophy:** *agent-mail is just a directory naming convention
plus a JSON file format.* There is no server, no database, no lock.
Each message is a single JSON file. Synchronization between agents
(git push, rsync, USB stick, email attachment, Cloudflare R2 — pick
your poison) is **out of scope**: agent-mail puts the letter in the
mailbox; carrying the mailbox to another house is the user's job.

URI:   ``agentmail://files/<agent_id>/<channel>[/<msg_id>]``

Layout::

    <base_path>/
    └── <agent_id>/
        ├── inbox/                       channels are subdirectories
        │   ├── <msg_id>.json            one JSON file per message
        │   └── <msg_id>.json
        ├── archive/<channel>/           ack moves files here
        │   └── <msg_id>.json
        └── reply/<correlation_id>/      arbitrary channel names allowed
            └── <msg_id>.json

The ``<msg_id>`` filename starts with a 13-digit millisecond timestamp,
so a plain ``sorted(os.listdir(...))`` yields FIFO order — no DB needed.

Atomicity: ``send()`` writes to ``.tmp/<msg_id>.json`` then ``os.rename``
into the channel directory, so a reader never sees a half-written file
even on a remotely-synced filesystem.
"""
from __future__ import annotations

import errno
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Iterable, Optional

from ..core import (
    DEFAULT_CHANNEL,
    Message,
    MessageProvider,
    build_uri,
)


# msg_id pattern from core._new_msg_id():
#   msg_<13-digit-ms>_<token>
_MSG_ID_RE = re.compile(r"^msg_\d{13}_[A-Za-z0-9_\-]+$")


def _safe_segment(segment: str) -> str:
    """Reject path-traversal / shell-hostile segments. agent_id and channel
    are user-controlled so we have to be paranoid."""
    if not segment:
        raise ValueError("empty path segment")
    if segment in (".", "..") or "/" in segment or "\\" in segment or "\x00" in segment:
        raise ValueError(f"unsafe path segment: {segment!r}")
    return segment


def _safe_channel(channel: str) -> str:
    """Channels may contain a single nested level for replies, e.g.
    ``reply/correlation-001``. Validate piecewise."""
    parts = channel.split("/")
    for p in parts:
        _safe_segment(p)
    return channel


class FileProvider(MessageProvider):
    """Directory-of-JSON-files mailbox. The default v0.2 backend.

    Multi-process safe for the operations we expose because:
      * ``send()`` uses tmp-write + ``os.rename`` (atomic on POSIX).
      * ``recv()`` is read-only (no inflight state).
      * ``ack()`` is a single ``os.rename``.
      * Two readers both calling ``recv()`` will see the same messages —
        that's a feature: this provider is at-least-once, no "lease".
        Consumers should ack what they actually handle.
    """

    scheme = "files"

    def __init__(self, base_path: str | os.PathLike):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------
    def _agent_dir(self, agent_id: str) -> Path:
        return self.base_path / _safe_segment(agent_id)

    def _channel_dir(self, agent_id: str, channel: str) -> Path:
        return self._agent_dir(agent_id) / _safe_channel(channel)

    def _archive_dir(self, agent_id: str, channel: str) -> Path:
        return self._agent_dir(agent_id) / "archive" / _safe_channel(channel)

    def _tmp_dir(self, agent_id: str) -> Path:
        return self._agent_dir(agent_id) / ".tmp"

    # ------------------------------------------------------------------
    # send
    # ------------------------------------------------------------------
    def send(self, message: Message) -> str:
        chan_dir = self._channel_dir(message.to, message.channel)
        tmp_dir = self._tmp_dir(message.to)
        chan_dir.mkdir(parents=True, exist_ok=True)
        tmp_dir.mkdir(parents=True, exist_ok=True)

        if not _MSG_ID_RE.match(message.id):
            raise ValueError(f"unsafe msg_id: {message.id!r}")

        final = chan_dir / f"{message.id}.json"
        # tmp file MUST live on the same filesystem for atomic rename
        with tempfile.NamedTemporaryFile(
            mode="w", dir=tmp_dir, delete=False,
            prefix=f"{message.id}.", suffix=".json.tmp", encoding="utf-8",
        ) as tmp:
            tmp.write(message.to_json())
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_path = tmp.name
        os.rename(tmp_path, final)
        return build_uri(self.scheme, message.to, message.channel, message.id)

    # ------------------------------------------------------------------
    # recv  (read-only — no lease, no inflight)
    # ------------------------------------------------------------------
    def recv(self, agent_id: str, channel: str = DEFAULT_CHANNEL,
             limit: int = 10, peek: bool = False) -> list[Message]:
        # peek is a no-op for FileProvider — recv is *always* non-destructive.
        # Callers who want once-only semantics must ack().
        chan_dir = self._channel_dir(agent_id, channel)
        if not chan_dir.is_dir():
            return []
        files = sorted(
            f for f in chan_dir.iterdir()
            if f.is_file() and f.suffix == ".json"
            and _MSG_ID_RE.match(f.stem)
        )
        out: list[Message] = []
        for f in files[:limit]:
            try:
                raw = f.read_text(encoding="utf-8")
                out.append(Message.from_json(raw))
            except (OSError, json.JSONDecodeError):
                # tolerate races / partial writes — they'll be retried
                continue
        return out

    # ------------------------------------------------------------------
    # ack  — atomic mv to archive/<channel>/
    # ------------------------------------------------------------------
    def ack(self, agent_id: str, msg_id: str) -> bool:
        if not _MSG_ID_RE.match(msg_id):
            return False
        agent_dir = self._agent_dir(agent_id)
        # Search every channel directory for this msg_id (channels are
        # subdirectories; replies live under reply/<correlation>/).
        for chan_dir, channel_name in _iter_channels(agent_dir):
            candidate = chan_dir / f"{msg_id}.json"
            if candidate.is_file():
                archive = self._archive_dir(agent_id, channel_name)
                archive.mkdir(parents=True, exist_ok=True)
                target = archive / candidate.name
                try:
                    os.rename(candidate, target)
                    return True
                except OSError as exc:
                    if exc.errno == errno.ENOENT:
                        return False
                    # cross-device shouldn't happen (same root) but be safe
                    shutil.move(str(candidate), str(target))
                    return True
        return False

    # ------------------------------------------------------------------
    # list  — pending across all channels (skips archive/, .tmp/)
    # ------------------------------------------------------------------
    def list(self, agent_id: str, channel: Optional[str] = None) -> Iterable[dict]:
        agent_dir = self._agent_dir(agent_id)
        if not agent_dir.is_dir():
            return
        rows: list[dict] = []
        # pending (live channels)
        for chan_dir, chan_name in _iter_channels(agent_dir):
            if channel and chan_name != channel:
                continue
            for f in sorted(chan_dir.iterdir()):
                if not (f.is_file() and f.suffix == ".json"
                        and _MSG_ID_RE.match(f.stem)):
                    continue
                rows.append(self._summary(agent_id, chan_name, f, "pending"))
        # archived
        archive_root = agent_dir / "archive"
        if archive_root.is_dir():
            for chan_dir, chan_name in _iter_channels(archive_root):
                if channel and chan_name != channel:
                    continue
                for f in sorted(chan_dir.iterdir()):
                    if not (f.is_file() and f.suffix == ".json"
                            and _MSG_ID_RE.match(f.stem)):
                        continue
                    rows.append(self._summary(agent_id, chan_name, f, "acked"))
        # newest first
        rows.sort(key=lambda r: r["id"], reverse=True)
        yield from rows

    def _summary(self, agent_id: str, channel: str,
                 path: Path, status: str) -> dict:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        return {
            "id": path.stem,
            "channel": channel,
            "from": data.get("from", ""),
            "subject": data.get("subject", ""),
            "status": status,
            "created_at": data.get("created_at", ""),
            "uri": build_uri(self.scheme, agent_id, channel, path.stem),
            "path": str(path),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_RESERVED = {"archive", ".tmp"}


def _iter_channels(root: Path):
    """Yield ``(channel_dir, channel_name)`` for each channel directory
    under ``root``, treating ``reply/<x>`` as a single nested channel.
    Skips reserved dirs (``archive``, ``.tmp``)."""
    if not root.is_dir():
        return
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name in _RESERVED:
            continue
        if entry.name == "reply":
            for sub in sorted(entry.iterdir()):
                if sub.is_dir():
                    yield sub, f"reply/{sub.name}"
        else:
            yield entry, entry.name

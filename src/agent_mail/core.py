"""Core types: Message, parse_uri, MessageProvider abc, AgentMail facade."""
from __future__ import annotations

import abc
import json
import secrets
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Iterable, Optional


PROTOCOL_VERSION = "1"
DEFAULT_CHANNEL = "inbox"


# ---------------------------------------------------------------------------
# URI parsing — agentmail://<scheme>/<agent_id>/<channel>[/<msg_id>]
# ---------------------------------------------------------------------------
def parse_uri(uri: str) -> tuple[str, str, str, Optional[str]]:
    """Parse an ``agentmail://<scheme>/<agent_id>/<channel>[/<msg_id>]`` URI.

    Returns ``(scheme, agent_id, channel, msg_id_or_None)``.
    """
    if not uri.startswith("agentmail://"):
        raise ValueError(f"Not an agentmail URI: {uri}")
    rest = uri[len("agentmail://"):]
    parts = rest.split("/", 3)
    if len(parts) < 3:
        raise ValueError(
            f"URI must be agentmail://<scheme>/<agent_id>/<channel>[/<msg_id>]: {uri}"
        )
    scheme, agent_id, channel = parts[0], parts[1], parts[2]
    msg_id = parts[3] if len(parts) == 4 and parts[3] else None
    if not scheme or not agent_id or not channel:
        raise ValueError(f"URI has empty segment: {uri}")
    return scheme, agent_id, channel, msg_id


def build_uri(scheme: str, agent_id: str, channel: str,
              msg_id: Optional[str] = None) -> str:
    base = f"agentmail://{scheme}/{agent_id}/{channel}"
    return f"{base}/{msg_id}" if msg_id else base


# ---------------------------------------------------------------------------
# Message — wire format
# ---------------------------------------------------------------------------
def _new_msg_id() -> str:
    # Sortable, URL-safe: <ms-timestamp>-<8 random>. ULID-ish without the dep.
    ts = int(time.time() * 1000)
    return f"msg_{ts:013d}_{secrets.token_urlsafe(6)}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Message:
    """A single agent-to-agent message.

    Matches the wire schema documented in the project IDEA notes. Attachments
    are *references* (typically ``agentdrive://...`` URIs); large payloads
    belong in agent-drive, not here.
    """
    to: str
    from_: str = ""
    subject: str = ""
    body: str = ""
    channel: str = DEFAULT_CHANNEL
    type: str = "request"          # request | response | event | broadcast
    attachments: list[str] = field(default_factory=list)
    reply_to: Optional[str] = None
    correlation_id: Optional[str] = None
    ttl_seconds: Optional[int] = None
    id: str = field(default_factory=_new_msg_id)
    created_at: str = field(default_factory=_now_iso)
    protocol_version: str = PROTOCOL_VERSION

    def to_dict(self) -> dict:
        d = asdict(self)
        # JSON has no concept of trailing underscore — rename for the wire.
        d["from"] = d.pop("from_")
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_dict(cls, d: dict) -> "Message":
        d = dict(d)
        if "from" in d:
            d["from_"] = d.pop("from")
        # Drop unknown keys so we tolerate forward-compatible additions.
        allowed = {f.name for f in cls.__dataclass_fields__.values()}
        d = {k: v for k, v in d.items() if k in allowed}
        return cls(**d)

    @classmethod
    def from_json(cls, raw: str) -> "Message":
        return cls.from_dict(json.loads(raw))


# ---------------------------------------------------------------------------
# Provider abstraction
# ---------------------------------------------------------------------------
class MessageProvider(abc.ABC):
    """Backend that actually stores/transports messages.

    Mirrors agent-drive's StorageProvider pattern: subclasses override
    ``scheme`` and the four CRUD methods; CLI + SDK route URI → provider.
    """
    scheme: str = ""

    @abc.abstractmethod
    def send(self, message: Message) -> str:
        """Persist ``message`` to ``message.to``'s ``message.channel``. Returns URI."""

    @abc.abstractmethod
    def recv(self, agent_id: str, channel: str = DEFAULT_CHANNEL,
             limit: int = 10, peek: bool = False) -> list[Message]:
        """Return up to ``limit`` un-acked messages from ``agent_id``'s ``channel``.

        With ``peek=False`` (default), messages move into "in-flight" state and
        must be acked or they'll reappear after a visibility timeout. With
        ``peek=True``, no state change — used by ``ls``.
        """

    @abc.abstractmethod
    def ack(self, agent_id: str, msg_id: str) -> bool:
        """Mark ``msg_id`` as processed. Returns True if it existed."""

    @abc.abstractmethod
    def list(self, agent_id: str, channel: Optional[str] = None) -> Iterable[dict]:
        """Yield ``{id, channel, from, subject, status, created_at}`` summaries."""


# ---------------------------------------------------------------------------
# AgentMail facade — what users actually import
# ---------------------------------------------------------------------------
class AgentMail:
    """Identity-aware async message bus for AI agents.

    Two usage modes:

    1. **Identity-scoped** (preferred): pass ``identity=<agent_id>`` so that
       ``send()`` stamps the ``from`` field automatically and ``recv()``
       defaults to your own inbox.

    2. **Explicit**: pass ``from_=...`` to ``send()`` and ``agent_id=...``
       to ``recv()`` per call.
    """

    def __init__(self, provider: MessageProvider, identity: Optional[str] = None):
        self.provider = provider
        self.identity = identity

    # -- send --------------------------------------------------------------
    def send(
        self,
        to: str,
        subject: str = "",
        body: str = "",
        attachments: Optional[list[str]] = None,
        channel: str = DEFAULT_CHANNEL,
        type: str = "request",
        from_: Optional[str] = None,
        reply_to: Optional[str] = None,
        correlation_id: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
    ) -> str:
        sender = from_ or self.identity
        if not sender:
            raise ValueError(
                "send() requires either an identity on AgentMail or from_=... per call"
            )
        msg = Message(
            to=to, from_=sender, subject=subject, body=body,
            attachments=list(attachments or []),
            channel=channel, type=type, reply_to=reply_to,
            correlation_id=correlation_id, ttl_seconds=ttl_seconds,
        )
        return self.provider.send(msg)

    # -- recv --------------------------------------------------------------
    def recv(
        self,
        channel: str = DEFAULT_CHANNEL,
        limit: int = 10,
        agent_id: Optional[str] = None,
        peek: bool = False,
        ack: bool = False,
    ) -> list[Message]:
        who = agent_id or self.identity
        if not who:
            raise ValueError(
                "recv() requires either an identity on AgentMail or agent_id=... per call"
            )
        messages = self.provider.recv(who, channel=channel, limit=limit, peek=peek)
        if ack and not peek:
            for m in messages:
                self.provider.ack(who, m.id)
        return messages

    # -- ack ---------------------------------------------------------------
    def ack(self, msg_id: str, agent_id: Optional[str] = None) -> bool:
        who = agent_id or self.identity
        if not who:
            raise ValueError(
                "ack() requires either an identity on AgentMail or agent_id=... per call"
            )
        return self.provider.ack(who, msg_id)

    # -- ls ----------------------------------------------------------------
    def ls(self, agent_id: Optional[str] = None,
           channel: Optional[str] = None) -> Iterable[dict]:
        who = agent_id or self.identity
        if not who:
            raise ValueError(
                "ls() requires either an identity on AgentMail or agent_id=... per call"
            )
        return self.provider.list(who, channel=channel)

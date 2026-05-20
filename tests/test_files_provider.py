"""Tests for the v0.2 FileProvider (the default, "mailbox is just a folder").

Distinct from test_v01.py (which exercises LocalProvider/SQLite + visibility
timeout). FileProvider is deliberately simpler: no lease, no inflight, just
JSON files on disk. recv() is non-destructive; ack() moves to archive/.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from agent_mail import AgentMail, FileProvider, Message, __version__


@pytest.fixture
def provider(tmp_path):
    return FileProvider(tmp_path)


def test_send_creates_json_file(provider, tmp_path):
    uri = provider.send(Message(to="bob", from_="alice", subject="ping"))
    assert uri.startswith("agentmail://files/bob/inbox/msg_")
    inbox = tmp_path / "bob" / "inbox"
    files = list(inbox.glob("msg_*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text())
    assert data["from"] == "alice"
    assert data["subject"] == "ping"
    assert data["protocol_version"] == "1"


def test_send_is_atomic_no_tmp_leftover(provider, tmp_path):
    provider.send(Message(to="bob", from_="alice"))
    tmp = tmp_path / "bob" / ".tmp"
    # .tmp dir may exist but should have no .tmp leftovers after success
    if tmp.exists():
        assert list(tmp.glob("*.tmp")) == []


def test_recv_is_nondestructive(provider):
    alice = AgentMail(provider, identity="alice")
    bob = AgentMail(provider, identity="bob")
    alice.send(to="bob", subject="hi")
    a = bob.recv()
    b = bob.recv()
    # FileProvider has no lease — recv is idempotent. The user must ack().
    assert len(a) == 1 and len(b) == 1
    assert a[0].id == b[0].id


def test_ack_moves_to_archive(provider, tmp_path):
    alice = AgentMail(provider, identity="alice")
    bob = AgentMail(provider, identity="bob")
    alice.send(to="bob", subject="x")
    [msg] = bob.recv()
    assert bob.ack(msg.id) is True
    assert bob.recv() == []  # inbox now empty
    archived = tmp_path / "bob" / "archive" / "inbox" / f"{msg.id}.json"
    assert archived.is_file()


def test_ack_unknown_returns_false(provider):
    bob = AgentMail(provider, identity="bob")
    assert bob.ack("msg_9999999999999_nope") is False


def test_inbox_isolation(provider):
    a = AgentMail(provider, identity="a")
    b = AgentMail(provider, identity="b")
    c = AgentMail(provider, identity="c")
    a.send(to="b", body="for-b")
    a.send(to="c", body="for-c")
    assert [m.body for m in b.recv()] == ["for-b"]
    assert [m.body for m in c.recv()] == ["for-c"]


def test_channel_isolation(provider):
    a = AgentMail(provider, identity="a")
    b = AgentMail(provider, identity="b")
    a.send(to="b", body="inbox-msg")
    a.send(to="b", body="events-msg", channel="events")
    assert [m.body for m in b.recv(channel="inbox")] == ["inbox-msg"]
    assert [m.body for m in b.recv(channel="events")] == ["events-msg"]


def test_reply_channel_nested_works(provider, tmp_path):
    a = AgentMail(provider, identity="alice")
    k = AgentMail(provider, identity="karpathy")
    a.send(to="karpathy", subject="please review",
           correlation_id="review-001")
    [msg] = k.recv()
    k.ack(msg.id)
    k.send(to="alice", subject="Re: please review",
           type="response",
           channel="reply/review-001",
           correlation_id="review-001",
           body="looks good")
    [reply] = a.recv(channel="reply/review-001")
    assert reply.from_ == "karpathy"
    assert reply.correlation_id == "review-001"
    # physical layout sanity
    assert (tmp_path / "alice" / "reply" / "review-001").is_dir()


def test_attachments_carry_agentdrive_uris(provider):
    a = AgentMail(provider, identity="alice")
    b = AgentMail(provider, identity="bob")
    a.send(to="bob", body="see attached",
           attachments=["agentdrive://s3/handoffs/alice/data.csv"])
    [m] = b.recv()
    assert m.attachments == ["agentdrive://s3/handoffs/alice/data.csv"]


def test_recv_fifo_order(provider):
    import time
    a = AgentMail(provider, identity="a")
    b = AgentMail(provider, identity="b")
    for i in range(5):
        a.send(to="b", body=str(i))
        time.sleep(0.002)
    pulled = b.recv(limit=5)
    assert [m.body for m in pulled] == ["0", "1", "2", "3", "4"]


def test_ls_shows_pending_and_acked(provider):
    a = AgentMail(provider, identity="a")
    b = AgentMail(provider, identity="b")
    a.send(to="b", subject="one")
    a.send(to="b", subject="two")
    [m1] = b.recv(limit=1)
    b.ack(m1.id)
    entries = list(b.ls())
    statuses = {e["subject"]: e["status"] for e in entries}
    assert statuses["one"] == "acked"
    assert statuses["two"] == "pending"


@pytest.mark.parametrize("evil", ["..", ".", "../escape", "a/b", "x\x00y", ""])
def test_rejects_path_traversal_in_agent_id(provider, evil):
    a = AgentMail(provider, identity="alice")
    with pytest.raises(ValueError):
        a.send(to=evil, body="x")


def test_email_style_agent_id_works(provider, tmp_path):
    # The whole point of v0.2: agent_id can be any opaque string,
    # including emails — they're paths, not network addresses.
    a = AgentMail(provider, identity="vanai-linus@vanaipower.com")
    k = AgentMail(provider, identity="vanai-karpathy@vanaipower.com")
    uri = a.send(to="vanai-karpathy@vanaipower.com",
                 subject="Hello", body="first contact")
    assert "vanai-karpathy@vanaipower.com/inbox" in uri
    [m] = k.recv()
    assert m.from_ == "vanai-linus@vanaipower.com"
    assert (tmp_path / "vanai-karpathy@vanaipower.com" / "inbox").is_dir()


# ---------------------------------------------------------------------------
# Cross-process: two independent agent-mail invocations against the same
# mailbox/ directory — *this* is the v0.2 use case (sync that dir by
# whatever means: git, rsync, zip-and-email, etc.).
# ---------------------------------------------------------------------------
def _cli(args, env_extra=None, check=True):
    env = os.environ.copy()
    env.pop("AGENT_MAIL_IDENTITY", None)
    env.pop("AGENT_MAIL_SCHEME", None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", "agent_mail.cli", *args],
        capture_output=True, text=True, env=env, check=check,
    )


def test_cli_defaults_to_files_provider(tmp_path):
    env = {"AGENT_MAIL_DIR": str(tmp_path)}
    r = _cli(["send", "bob", "-s", "hi", "-b", "x",
              "--as", "alice"], env_extra=env)
    assert r.returncode == 0, r.stderr
    uri = r.stdout.strip()
    assert uri.startswith("agentmail://files/bob/inbox/")
    assert (tmp_path / "bob" / "inbox").is_dir()


def test_cross_process_send_and_recv(tmp_path):
    """The realistic flow: sender writes, recipient (separate invocation)
    reads, exactly as if the mailbox/ was synced between two machines."""
    env = {"AGENT_MAIL_DIR": str(tmp_path)}

    # Process 1: alice sends
    r = _cli(
        ["send", "vanai-karpathy@vanaipower.com",
         "-s", "live test",
         "-b", "hi karpathy",
         "-a", "agentdrive://local/alice/notes.md",
         "--as", "vanai-linus@vanaipower.com"],
        env_extra=env,
    )
    assert r.returncode == 0, r.stderr

    # Process 2: karpathy lists
    r = _cli(["ls", "--as", "vanai-karpathy@vanaipower.com"], env_extra=env)
    assert "live test" in r.stdout
    assert "pending" in r.stdout

    # Process 3: karpathy recv --json
    r = _cli(["recv", "--json",
              "--as", "vanai-karpathy@vanaipower.com"], env_extra=env)
    msg = json.loads(r.stdout.strip().splitlines()[0])
    assert msg["from"] == "vanai-linus@vanaipower.com"
    assert msg["attachments"] == ["agentdrive://local/alice/notes.md"]
    msg_id = msg["id"]

    # Process 4: karpathy acks
    r = _cli(["ack", msg_id, "--as", "vanai-karpathy@vanaipower.com"],
             env_extra=env)
    assert "acked" in r.stdout

    # And subsequent recv is empty
    r = _cli(["recv", "--as", "vanai-karpathy@vanaipower.com"],
             env_extra=env, check=False)
    assert r.returncode == 0


def test_cli_inbox_uri_uses_files_scheme(tmp_path):
    env = {"AGENT_MAIL_DIR": str(tmp_path)}
    r = _cli(["inbox-uri", "--as", "vanai-karpathy@vanaipower.com"],
             env_extra=env)
    assert r.stdout.strip() == (
        "agentmail://files/vanai-karpathy@vanaipower.com/inbox"
    )


def test_local_scheme_still_works(tmp_path):
    """Backward compat: SQLite provider stays addressable via AGENT_MAIL_SCHEME."""
    env = {
        "AGENT_MAIL_SCHEME": "local",
        "AGENT_MAIL_LOCAL_DIR": str(tmp_path / "sqlite"),
    }
    r = _cli(["send", "bob", "-b", "via sqlite", "--as", "alice"],
             env_extra=env)
    assert r.returncode == 0
    assert r.stdout.startswith("agentmail://local/bob/inbox/")

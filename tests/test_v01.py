"""End-to-end tests for agent-mail v0.1: SDK + LocalProvider + CLI."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import pytest

from agent_mail import (
    AgentMail, Message, LocalProvider, parse_uri, build_uri, __version__,
)


# ---------------------------------------------------------------------------
# parse_uri / build_uri
# ---------------------------------------------------------------------------
def test_parse_uri_basic():
    s, a, c, m = parse_uri("agentmail://local/agent_007/inbox")
    assert (s, a, c, m) == ("local", "agent_007", "inbox", None)


def test_parse_uri_with_msg_id():
    s, a, c, m = parse_uri("agentmail://local/agent_007/inbox/msg_abc")
    assert (s, a, c, m) == ("local", "agent_007", "inbox", "msg_abc")


@pytest.mark.parametrize("bad", [
    "http://example.com",
    "agentmail://",
    "agentmail://local",
    "agentmail://local/",
    "agentmail://local/agent_007",
    "agentmail:///agent_007/inbox",
])
def test_parse_uri_rejects_garbage(bad):
    with pytest.raises(ValueError):
        parse_uri(bad)


def test_build_uri_roundtrip():
    uri = build_uri("local", "agent_007", "inbox", "msg_1")
    assert parse_uri(uri) == ("local", "agent_007", "inbox", "msg_1")


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------
def test_message_json_roundtrip():
    m = Message(to="b", from_="a", subject="hi", body="x",
                attachments=["agentdrive://local/ws/x.csv"])
    raw = m.to_json()
    parsed = json.loads(raw)
    assert parsed["from"] == "a"          # wire uses 'from', not 'from_'
    assert "from_" not in parsed
    m2 = Message.from_json(raw)
    assert m2.to == "b" and m2.from_ == "a"
    assert m2.attachments == ["agentdrive://local/ws/x.csv"]
    assert m2.protocol_version == "1"


def test_message_from_dict_tolerates_unknown_keys():
    m = Message.from_dict({
        "to": "b", "from": "a", "future_field": 123, "subject": "s",
    })
    assert m.to == "b" and m.from_ == "a" and m.subject == "s"


def test_message_id_is_sortable_by_time():
    a = Message(to="b")
    time.sleep(0.005)
    c = Message(to="b")
    assert a.id < c.id


# ---------------------------------------------------------------------------
# LocalProvider — roundtrip, ack, visibility, separation
# ---------------------------------------------------------------------------
@pytest.fixture
def provider(tmp_path):
    return LocalProvider(tmp_path, visibility_timeout_s=1)


def test_send_recv_ack_roundtrip(provider):
    alice = AgentMail(provider, identity="alice")
    bob = AgentMail(provider, identity="bob")
    uri = alice.send(to="bob", subject="ping", body="hello")
    assert uri.startswith("agentmail://local/bob/inbox/msg_")

    msgs = bob.recv(limit=10)
    assert len(msgs) == 1
    assert msgs[0].from_ == "alice"
    assert msgs[0].subject == "ping"

    # Inflight: should not reappear immediately.
    assert bob.recv(limit=10) == []

    # Ack drops it permanently.
    assert bob.ack(msgs[0].id) is True
    time.sleep(1.2)  # past visibility timeout
    assert bob.recv(limit=10) == []


def test_unacked_messages_redeliver_after_timeout(provider):
    alice = AgentMail(provider, identity="alice")
    bob = AgentMail(provider, identity="bob")
    alice.send(to="bob", body="will-redeliver")

    first = bob.recv(limit=10)
    assert len(first) == 1
    # Don't ack. Wait past visibility timeout.
    time.sleep(1.2)
    second = bob.recv(limit=10)
    assert len(second) == 1
    assert second[0].id == first[0].id


def test_peek_does_not_consume(provider):
    alice = AgentMail(provider, identity="alice")
    bob = AgentMail(provider, identity="bob")
    alice.send(to="bob", body="x")

    peeked = bob.recv(limit=10, peek=True)
    assert len(peeked) == 1
    # peek=True must not flip status; subsequent real recv still gets it.
    pulled = bob.recv(limit=10)
    assert len(pulled) == 1 and pulled[0].id == peeked[0].id


def test_auto_ack_drains(provider):
    alice = AgentMail(provider, identity="alice")
    bob = AgentMail(provider, identity="bob")
    alice.send(to="bob", body="1")
    alice.send(to="bob", body="2")

    drained = bob.recv(limit=10, ack=True)
    assert len(drained) == 2
    time.sleep(1.2)
    assert bob.recv(limit=10) == []


def test_inboxes_are_isolated(provider):
    a = AgentMail(provider, identity="a")
    b = AgentMail(provider, identity="b")
    c = AgentMail(provider, identity="c")
    a.send(to="b", body="for-b")
    a.send(to="c", body="for-c")
    assert [m.body for m in b.recv()] == ["for-b"]
    assert [m.body for m in c.recv()] == ["for-c"]


def test_channels_are_isolated(provider):
    a = AgentMail(provider, identity="a")
    b = AgentMail(provider, identity="b")
    a.send(to="b", body="inbox-msg")
    a.send(to="b", body="event-msg", channel="events")
    assert [m.body for m in b.recv(channel="inbox")] == ["inbox-msg"]
    assert [m.body for m in b.recv(channel="events")] == ["event-msg"]


def test_attachments_carry_agentdrive_uris(provider):
    a = AgentMail(provider, identity="alice")
    b = AgentMail(provider, identity="bob")
    a.send(to="bob",
           subject="ETL",
           body="see attached",
           attachments=["agentdrive://s3/handoffs/alice/data.csv"])
    [m] = b.recv()
    assert m.attachments == ["agentdrive://s3/handoffs/alice/data.csv"]


def test_ls_returns_summaries(provider):
    a = AgentMail(provider, identity="a")
    b = AgentMail(provider, identity="b")
    a.send(to="b", subject="one")
    a.send(to="b", subject="two")
    entries = list(b.ls())
    assert len(entries) == 2
    assert {e["subject"] for e in entries} == {"one", "two"}
    assert all(e["status"] == "pending" for e in entries)


def test_recv_order_is_fifo(provider):
    a = AgentMail(provider, identity="a")
    b = AgentMail(provider, identity="b")
    for i in range(5):
        a.send(to="b", body=str(i))
        time.sleep(0.002)
    pulled = b.recv(limit=5)
    assert [m.body for m in pulled] == ["0", "1", "2", "3", "4"]


def test_identity_required():
    prov = LocalProvider("/tmp/agent_mail_identity_test")
    mail = AgentMail(prov)  # no identity
    with pytest.raises(ValueError):
        mail.send(to="b", body="x")
    with pytest.raises(ValueError):
        mail.recv()


# ---------------------------------------------------------------------------
# CLI — real subprocess exercising the entry point
# ---------------------------------------------------------------------------
def _cli(args, env_extra=None, check=True):
    env = os.environ.copy()
    env.pop("AGENT_MAIL_IDENTITY", None)
    if env_extra:
        env.update(env_extra)
    result = subprocess.run(
        [sys.executable, "-m", "agent_mail.cli", *args],
        capture_output=True, text=True, env=env,
    )
    if check:
        assert result.returncode == 0, (
            f"cmd failed: {args}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
    return result


def test_cli_version():
    r = _cli(["--version"])
    assert r.stdout.strip() == __version__


def test_cli_send_recv_ack_flow(tmp_path):
    env = {
        "AGENT_MAIL_SCHEME": "local",
        "AGENT_MAIL_LOCAL_DIR": str(tmp_path),
    }
    # alice sends to bob
    r = _cli(
        ["send", "bob", "-s", "ETL", "-b", "run it",
         "-a", "agentdrive://local/alice/data.csv",
         "--as", "alice"],
        env_extra=env,
    )
    uri = r.stdout.strip()
    assert uri.startswith("agentmail://local/bob/inbox/")

    # bob lists and sees one pending
    r = _cli(["ls", "--as", "bob"], env_extra=env)
    assert "pending" in r.stdout
    assert "ETL" in r.stdout

    # bob recv --json
    r = _cli(["recv", "--json", "--as", "bob"], env_extra=env)
    line = r.stdout.strip().splitlines()[0]
    msg = json.loads(line)
    assert msg["from"] == "alice"
    assert msg["subject"] == "ETL"
    assert msg["attachments"] == ["agentdrive://local/alice/data.csv"]
    msg_id = msg["id"]

    # bob ack
    r = _cli(["ack", msg_id, "--as", "bob"], env_extra=env)
    assert "acked" in r.stdout

    # now ls shows acked
    r = _cli(["ls", "--as", "bob"], env_extra=env)
    assert "acked" in r.stdout


def test_cli_inbox_uri():
    r = _cli(["inbox-uri", "--as", "agent_007"],
             env_extra={"AGENT_MAIL_SCHEME": "local"})
    assert r.stdout.strip() == "agentmail://local/agent_007/inbox"


def test_cli_identity_env_var(tmp_path):
    env = {
        "AGENT_MAIL_SCHEME": "local",
        "AGENT_MAIL_LOCAL_DIR": str(tmp_path),
        "AGENT_MAIL_IDENTITY": "alice",
    }
    _cli(["send", "bob", "-b", "hi"], env_extra=env)
    r = _cli(["ls", "--as", "bob", "--json"],
             env_extra={
                 "AGENT_MAIL_SCHEME": "local",
                 "AGENT_MAIL_LOCAL_DIR": str(tmp_path),
             })
    assert any("alice" in line for line in r.stdout.splitlines())


def test_cli_missing_identity_errors():
    r = _cli(["send", "bob", "-b", "x"], check=False)
    assert r.returncode != 0
    assert "identity" in r.stderr.lower()

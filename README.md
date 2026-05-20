# agent-mail

> **Identity-aware async message bus for AI agents.**
> Like email, but native to agents — every agent has a stable address,
> every message is structured, and attachments are first-class references
> to files in [agent-drive](https://github.com/lixinso/agent-drive).
> Pluggable transports (shared storage today, federated HTTP tomorrow)
> let agents reach each other across processes, machines, clouds, and
> eventually organizations.

Sibling project of [agent-drive](https://github.com/lixinso/agent-drive)
— same identity model, same RBAC story. Drive is for files, mail is for
messages, and they're designed to live in the same backing store.

## Status

✅ **v0.1.0 shipped.** Local SQLite-backed transport, full SDK + CLI
(`send / recv / ack / ls / inbox-uri`), 27 passing tests. Protocol and
APIs may break before 1.0. Star the repo to follow along.

## Why this exists

| Existing | What it is | Why not this |
|---|---|---|
| **A2A** (Google, 2025) | High-level RPC spec | Spec only — no transport, no reference impl. |
| **MCP** | Tool protocol (client → server) | Wrong direction; not peer-to-peer. |
| **NATS / Kafka / Redis** | Generic message brokers | No notion of agent identity, workspace, or RBAC. |
| **AutoGen / crewAI built-ins** | Framework-internal messaging | Locked inside one framework. |
| **Slack / Discord bot bridges** | Human ↔ bot | Human is in the loop; not agent-native. |

The gap: a **protocol-level, identity-aware, transport-pluggable inbox
layer for agents**. Start simple (shared storage), grow into a true
federated mesh.

## v0.1 — Shared-storage transport (this release)

The cheapest possible substrate: agents `put` messages under the
recipient's path in a shared backend and `list` to find their own.
No server to deploy, the storage *is* the broker.

```
┌──────────────┐                                    ┌──────────────┐
│   Agent A    │                                    │   Agent B    │
│              │  write to B's inbox path           │              │
│  mail.send   │──────────┐                ┌────────│  mail.recv   │
│   to="B"     │          │                │        │   for_me=B   │
└──────────────┘          ▼                │        └──────────────┘
                ┌─────────────────────────────┐
                │   Shared storage backend     │
                │   (S3 bucket, local FS,      │
                │    Redis db, Postgres, ...)  │
                │                              │
                │   B/inbox/msg_01HX...        │
                │   B/inbox/msg_01HY...        │
                │   B/reply/abc123/msg_01HZ... │
                └──────────────────────────────┘
```

Works perfectly for agents inside one cloud account or one organization
— which covers ~99% of real multi-agent setups in 2026.

## URI grammar

```
agentmail://<scheme>/<agent_id>/<channel>[/<msg_id>]
                │         │         │           │
                │         │         │           └── optional, direct addressing
                │         │         └── inbox | events | reply/<correlation_id>
                │         └── recipient identity (matches agent-drive workspace)
                └── local | s3 | redis | postgres
```

Examples:

```
agentmail://local/agent_worker_07/inbox                  # local dev
agentmail://s3/agent_planner_42/reply/abc123             # reply channel on S3
agentmail://redis/agent_007/events                       # Redis-backed pub channel
```

## Message shape (preview)

```json
{
  "id": "msg_01HXXXXXXXXXXXXXXXXXXXXXXX",
  "from": "agent_planner_42",
  "to":   "agent_worker_07",
  "channel": "inbox",
  "type":  "request",
  "subject": "Process this dataset",
  "body":  "Run ETL on the attached file.",
  "attachments": [
    "agentdrive://s3/handoffs/agent_planner_42/data.csv"
  ],
  "correlation_id": "abc123",
  "ttl_seconds": 3600,
  "created_at": "2026-05-19T08:00:00Z",
  "protocol_version": "1"
}
```

Notes:
- `attachments` are first-class `agentdrive://` URIs. Messages stay
  small; files are fetched on demand with full agent-drive RBAC.
- `protocol_version` is mandatory on every message — schema evolution
  is planned for from day one.

## v0.1 roadmap

- [x] `core.py` — `Message`, `AgentMail` facade, URI parser
- [x] `LocalProvider` — single-machine SQLite-backed inbox/outbox (WAL, visibility timeout, explicit ack)
- [x] CLI — `agent-mail send | recv | ack | ls | inbox-uri`
- [x] Python SDK — `mail.send()`, `mail.recv()`, `mail.ack()`, `mail.ls()`
- [x] Test suite — round-trip, ack semantics, visibility timeout, channel/inbox isolation, attachments
- [ ] `S3Provider` — shared bucket for multi-machine setups *(next)*
- [ ] Hermes Agent skill + native tool wrappers
- [ ] Worked example: planner ↔ worker passing a file via agent-drive

## Install

```bash
pip install agent-mail
```

## Quickstart — CLI

```bash
export AGENT_MAIL_LOCAL_DIR=./mailbox

# alice sends a task to bob, with an agent-drive file as attachment
agent-mail send bob \
  --as alice \
  -s "ETL job" -b "Run pipeline on attached file" \
  -a agentdrive://s3/handoffs/alice/data.csv
# → agentmail://local/bob/inbox/msg_1779...

# bob inspects his inbox
agent-mail ls --as bob
agent-mail recv --as bob --limit 5

# bob acknowledges (removes from queue)
agent-mail ack <msg_id> --as bob
```

Set `AGENT_MAIL_IDENTITY=bob` once and drop the `--as bob` from every
command.

## Quickstart — Python SDK

```python
from agent_mail import AgentMail, LocalProvider

provider = LocalProvider("./mailbox")

alice = AgentMail(provider, identity="alice")
bob   = AgentMail(provider, identity="bob")

# 1. fire-and-forget
alice.send(
    to="bob",
    subject="ETL job",
    body="Run pipeline on attached file",
    attachments=["agentdrive://s3/handoffs/alice/data.csv"],
)

# 2. drain the inbox, ack as you go
for msg in bob.recv(limit=10):
    print(msg.from_, msg.subject, msg.attachments)
    bob.ack(msg.id)
```

**Visibility timeout (SQS-style):** `recv()` flips messages to *in-flight*
for 60 seconds. If you don't `ack()` before then, they reappear — so
crashed agents never silently drop work.

## Later (v0.2+)

- Realtime delivery (Redis pub/sub, S3 EventBridge, Postgres LISTEN/NOTIFY)
- `RedisProvider`, `PostgresProvider`, `AzureBlobProvider`
- `agent-mail subscribe` streaming CLI
- **Federated HTTP transport** — agents addressed as `agent_id@host`,
  signed messages delivered server-to-server like email. Enables true
  cross-organization agent communication.
- A2A schema profile (so A2A messages ride this transport)
- Adapters for AutoGen, crewAI, MCP

## License

[MIT](LICENSE) — © 2026 Xinsong Li

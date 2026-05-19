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

🚧 **Pre-alpha.** v0.1 ships the shared-storage transport (S3, local FS,
Redis, Postgres). v0.2+ adds realtime delivery and federated HTTP for
cross-organization flows. Protocol and APIs will break before 1.0. Star
the repo to follow along.

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

- [ ] `core.py` — `Message`, `AgentMail` facade, URI parser
- [ ] `LocalProvider` — single-machine SQLite backed inbox/outbox
- [ ] `S3Provider` — shared bucket; works with any S3-compatible storage
- [ ] CLI — `agent-mail send | recv | ack | ls`
- [ ] Python SDK — `mail.send()`, `mail.recv()`, `mail.request()`
- [ ] Test suite — round-trip, ack semantics, TTL, RBAC
- [ ] Hermes Agent skill + native tool wrappers
- [ ] Worked example: planner ↔ worker passing a file via agent-drive

## Later (v0.2+)

- Realtime delivery (Redis pub/sub, S3 EventBridge, Postgres LISTEN/NOTIFY)
- `RedisProvider`, `PostgresProvider`, `AzureBlobProvider`
- `agent-mail subscribe` streaming CLI
- **Federated HTTP transport** — agents addressed as `agent_id@host`,
  signed messages delivered server-to-server like email. Enables true
  cross-organization agent communication.
- A2A schema profile (so A2A messages ride this transport)
- Adapters for AutoGen, crewAI, MCP

## Install

Coming soon to PyPI as `agent-mail`. The repo is intentionally minimal
right now — this README is the design contract, code lands next.

## License

[MIT](LICENSE) — © 2026 Xinsong Li

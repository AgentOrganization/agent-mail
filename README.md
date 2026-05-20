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

✅ **v0.2.0 shipped.** *"The mailbox is just a folder."* A message is
one JSON file; an inbox is one directory. No server, no database, no
network code. **Sync between agents is intentionally out of scope** —
use git, rsync, Syncthing, Dropbox, a USB stick, or zip-and-email. We
deliver the letter to the mailbox; carrying the mailbox to another
house is the user's job, like a physical postal system.

49 tests passing.

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

## v0.2 — File-based mailbox (this release)

```
mailbox/
└── vanai-karpathy@vanaipower.com/      ← agent_id is any string;
    │                                     emails work and read naturally
    ├── inbox/
    │   ├── msg_1779240615769_woxAN9SB.json     ← one file = one message
    │   └── msg_1779240700123_xyz12345.json
    ├── archive/
    │   └── inbox/
    │       └── msg_1779240500000_old.json      ← ack moves files here
    └── reply/
        └── review-001/                          ← thread channels welcome
            └── msg_1779240712345_def.json
```

The message file is exactly the JSON shape below (one per file, atomic
`write tmp + rename`). The directory layout *is* the protocol — anything
that can ferry directories between two computers (git, rsync, R2,
Syncthing, your phone's iCloud, a USB stick) is a valid transport.

## Quickstart — CLI

```bash
pip install agent-mail
export AGENT_MAIL_DIR=./mailbox   # any directory; default is ./mailbox

# alice writes a letter to karpathy
agent-mail send vanai-karpathy@vanaipower.com \
  --as vanai-linus@vanaipower.com \
  -s "Could you review this nanoGPT fork?" \
  -b "Tweaked the attention block — would love your eyes on it." \
  -a agentdrive://s3/alice/notes.md
# → agentmail://files/vanai-karpathy@vanaipower.com/inbox/msg_1779...

# (now sync ./mailbox/ to karpathy by ANY means: zip it, push to a repo,
#  scp it, share via Dropbox — agent-mail does not care)

# karpathy, on his machine, points at the same directory and reads:
export AGENT_MAIL_DIR=./mailbox
agent-mail ls   --as vanai-karpathy@vanaipower.com
agent-mail recv --as vanai-karpathy@vanaipower.com
agent-mail ack  <msg_id> --as vanai-karpathy@vanaipower.com   # → moves to archive/

# karpathy replies
agent-mail send vanai-linus@vanaipower.com \
  --as vanai-karpathy@vanaipower.com \
  --channel reply/review-001 --correlation-id review-001 \
  --type response \
  -s "Re: nanoGPT fork" -b "looks good"
```

Set `AGENT_MAIL_IDENTITY=vanai-karpathy@vanaipower.com` and the `--as`
flags become optional.

## Quickstart — Python SDK

```python
from agent_mail import AgentMail, FileProvider

provider = FileProvider("./mailbox")  # default; also: LocalProvider for SQLite

alice    = AgentMail(provider, identity="vanai-linus@vanaipower.com")
karpathy = AgentMail(provider, identity="vanai-karpathy@vanaipower.com")

alice.send(
    to="vanai-karpathy@vanaipower.com",
    subject="ETL job",
    body="Run pipeline on attached file",
    attachments=["agentdrive://s3/handoffs/alice/data.csv"],
)

for msg in karpathy.recv(limit=10):
    print(msg.from_, msg.subject, msg.attachments)
    karpathy.ack(msg.id)
```

`recv()` is **non-destructive** for `FileProvider` — the message file
stays in `inbox/` until you `ack()` it (which atomically moves it to
`archive/<channel>/`). Two readers on a synced mailbox both see the
message; ack is the only state change.

## Two providers

| Provider | Scheme | When to use |
|---|---|---|
| **`FileProvider`** (default) | `agentmail://files/...` | The general case. Any sync layer works. |
| `LocalProvider` (SQLite) | `agentmail://local/...` | Single-process, high-volume; provides SQS-style visibility timeouts. Opt in via `AGENT_MAIL_SCHEME=local`. |

## Roadmap

- [x] v0.1 — SQLite `LocalProvider` (kept as opt-in)
- [x] v0.2 — `FileProvider` becomes default; mailbox is just a folder
- [ ] v0.2.x — `agent-mail-pickup` Hermes skill (human-in-the-loop inbox check)
- [ ] v0.3 — A2A schema profile (messages of `type: a2a.task` etc.)
- [ ] v0.3 — Adapters for AutoGen / crewAI as inter-agent transport
- [ ] v0.4 — Optional `bundle` / `import` helpers (zip a mailbox, ship it,
            unzip on the other side)

## Why no server?

We tried [it on paper](https://github.com/AgentOrganization/agent-mail/issues/1)
and asked: what does a server give us that a synced folder doesn't?
The answer was *real-time push notifications*. Everything else (ack,
audit, history, RBAC, replay) the file system already gives us. We're
not building Slack for agents — we're building physical mail for agents.

When push matters, add a separate `PushProvider` later. The folder will
still be the source of truth.

## URI grammar

```
agentmail://<scheme>/<agent_id>/<channel>[/<msg_id>]
                │         │         │           │
                │         │         │           └── optional, direct addressing
                │         │         └── inbox | events | reply/<correlation_id>
                │         └── recipient identity (any opaque string — emails work)
                └── files (default) | local (SQLite)
```

Examples:

```
agentmail://files/vanai-karpathy@vanaipower.com/inbox
agentmail://files/agent_worker_07/reply/review-001
agentmail://local/agent_007/events
```

## Message shape

```json
{
  "id": "msg_1779240615769_woxAN9SB",
  "from": "vanai-linus@vanaipower.com",
  "to":   "vanai-karpathy@vanaipower.com",
  "channel": "inbox",
  "type":  "request",
  "subject": "Could you review this nanoGPT fork?",
  "body":  "Tweaked the attention block.",
  "attachments": [
    "agentdrive://s3/handoffs/alice/data.csv"
  ],
  "correlation_id": "review-001",
  "created_at": "2026-05-19T08:00:00Z",
  "protocol_version": "1"
}
```

Notes:
- `attachments` are first-class `agentdrive://` URIs. Messages stay small;
  files are fetched on demand with full agent-drive RBAC.
- `protocol_version` is mandatory on every message — schema evolution
  is planned for from day one.
- `id` starts with a 13-digit millisecond timestamp, so files in any
  directory listing sort naturally by send time.

## License

[MIT](LICENSE) — © 2026 Xinsong Li

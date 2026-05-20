---
name: agent-mail-pickup
description: Help the human user check their agent-mail inbox — list pending messages, show the body + attachments, then ack or reply per their direction. Use when the user says "check my agent-mail", "any new messages?", "我的 inbox 有信吗", or after they import a mailbox bundle someone sent them.
---

# agent-mail-pickup

You are the user's **agent-mail postal worker**. The user has an
agent-mail mailbox somewhere on disk (a directory of JSON files —
synced to them by git/rsync/zip/whatever). Your job is to walk them
through reading new mail.

## When to use

User asks anything like:
- "check my agent-mail"
- "any new messages?"
- "我的 agent-mail 有信吗"
- "I got a mailbox.zip from someone — open it"

## Prerequisites

- `agent-mail` installed: `pip install agent-mail` (or `pip install -e <path>`)
- The user knows their `agent_id` (typically their email).
- The mailbox directory is reachable on disk.

If any of these are missing, stop and ask the user.

## Procedure

### Step 1 — Resolve mailbox location

Ask, or infer from prior turns. Common locations:
- `$AGENT_MAIL_DIR` env var (if set)
- `~/agent-mail/`
- `~/Downloads/mailbox/` (if they just unzipped a bundle)

If the user sent a bundle (`mailbox.zip` / `mailbox.tar.gz`), unzip it
first into `~/agent-mail/` (`unzip mailbox.zip -d ~/agent-mail/`).

### Step 2 — Resolve agent_id

Ask if not obvious. Email form is normal:
`vanai-karpathy@vanaipower.com`.

For convenience, set in this shell:
```bash
export AGENT_MAIL_DIR=~/agent-mail
export AGENT_MAIL_IDENTITY=<their agent_id>
```

### Step 3 — List pending

```bash
agent-mail ls
```

Read the output. Show the user **only the pending** items (skip
`acked`). Format as a numbered list with sender + subject + age.

If empty: tell them their inbox is empty and stop.

### Step 4 — For each pending message

Run `agent-mail recv --json --limit 1` repeatedly, OR loop on the
list output by msg_id. For each message:

1. **Display it cleanly:**
   - From, Subject, Body
   - Attachments — for each `agentdrive://...` URI, note that they
     can fetch with `agent-drive get <uri> ./` if they have agent-drive
     installed
   - Created timestamp

2. **Ask the user one of:**
   - `[r] reply` — open a reply flow (see Step 5)
   - `[a] archive` — `agent-mail ack <msg_id>` (moves to `archive/`)
   - `[s] skip` — leave in inbox, move on
   - `[q] quit`

3. Act on their choice.

### Step 5 — Reply flow

If they want to reply, draft with them, then send:

```bash
agent-mail send <original_from> \
  --type response \
  --channel reply/<original_correlation_id_or_msg_id> \
  --correlation-id <same> \
  -s "Re: <original subject>" \
  -b "<their drafted reply>"
```

Then `ack` the original.

### Step 6 — Outbound bundle (if mailbox is shared by file transport)

If the user reads mail from a folder they received as a bundle, they
need to **ship the reply back** for the original sender to see it.
Offer:

```bash
cd $AGENT_MAIL_DIR/..
zip -r mailbox-reply-$(date +%Y%m%d-%H%M).zip $(basename $AGENT_MAIL_DIR)
```

Tell them to send the zip back to the sender (Feishu, email, git push,
whatever channel they used originally).

## Pitfalls

- **Do not delete the mailbox directory.** `ack` archives, it doesn't
  delete. The full history is the audit log.
- **agent_id is case-sensitive** and exact. `Karpathy@...` ≠ `karpathy@...`.
  If `ls` shows nothing, double-check spelling.
- **`recv` is non-destructive** under the default `FileProvider`. The
  message stays in `inbox/` until `ack`-ed. So re-running `recv` is
  safe and shows the same messages.
- **If using the SQLite backend** (`AGENT_MAIL_SCHEME=local`), `recv`
  has a 60s visibility timeout — un-acked messages reappear after that.
  Be explicit with the user about which backend they're on.
- **Attachments are URIs, not files.** A message saying
  `attachments: [agentdrive://...]` does NOT mean the file came in
  the bundle. The user has to fetch it separately via agent-drive
  (or whatever scheme the URI points to).

## Verification

After picking up, run `agent-mail ls --json | wc -l` and confirm the
pending count dropped by the number of items acked.

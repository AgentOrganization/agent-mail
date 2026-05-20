"""agent-mail CLI — send / recv / ack / ls / inbox-uri."""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Optional

from agent_mail import __version__
from agent_mail.core import DEFAULT_CHANNEL, build_uri, parse_uri
from agent_mail.providers import (
    get_provider_for_scheme,
    get_default_scheme,
    ProviderConfigError,
)


def _identity(args_value: Optional[str]) -> str:
    who = args_value or os.getenv("AGENT_MAIL_IDENTITY")
    if not who:
        sys.exit(
            "Error: no identity. Pass --as <agent_id> or set AGENT_MAIL_IDENTITY."
        )
    return who


def _provider(scheme: Optional[str] = None):
    scheme = scheme or get_default_scheme()
    try:
        return get_provider_for_scheme(scheme)
    except ProviderConfigError as exc:
        sys.exit(f"Error: {exc}")


def _print_msg(m, *, pretty: bool) -> None:
    if pretty:
        attach = "  attachments:\n    " + "\n    ".join(m.attachments) \
            if m.attachments else "  attachments: (none)"
        print(
            f"━━ {m.id}\n"
            f"  from:    {m.from_}\n"
            f"  to:      {m.to}\n"
            f"  channel: {m.channel}    type: {m.type}\n"
            f"  subject: {m.subject}\n"
            f"  body:    {m.body}\n"
            f"{attach}\n"
            f"  created: {m.created_at}"
        )
    else:
        print(json.dumps(m.to_dict(), ensure_ascii=False, sort_keys=True))


def cmd_send(args) -> int:
    sender = _identity(args.as_)
    prov = _provider()
    from agent_mail import AgentMail
    mail = AgentMail(prov, identity=sender)
    uri = mail.send(
        to=args.to,
        subject=args.subject or "",
        body=args.body or "",
        attachments=args.attach or [],
        channel=args.channel,
        type=args.type,
        reply_to=args.reply_to,
        correlation_id=args.correlation_id,
    )
    print(uri)
    return 0


def cmd_recv(args) -> int:
    who = _identity(args.as_)
    prov = _provider()
    from agent_mail import AgentMail
    mail = AgentMail(prov, identity=who)
    msgs = mail.recv(
        channel=args.channel,
        limit=args.limit,
        peek=args.peek,
        ack=args.ack,
    )
    if not msgs:
        print(f"(no messages in {who}/{args.channel})", file=sys.stderr)
        return 0
    for m in msgs:
        _print_msg(m, pretty=not args.json)
    return 0


def cmd_ack(args) -> int:
    who = _identity(args.as_)
    prov = _provider()
    from agent_mail import AgentMail
    mail = AgentMail(prov, identity=who)
    ok = mail.ack(args.msg_id)
    if not ok:
        sys.exit(f"Error: msg {args.msg_id!r} not found in {who}'s inbox.")
    print(f"acked {args.msg_id}")
    return 0


def cmd_ls(args) -> int:
    who = _identity(args.as_)
    prov = _provider()
    from agent_mail import AgentMail
    mail = AgentMail(prov, identity=who)
    found = False
    for entry in mail.ls(channel=args.channel):
        found = True
        if args.json:
            print(json.dumps(entry, ensure_ascii=False, sort_keys=True))
        else:
            print(
                f"{entry['status']:8s}  {entry['channel']:12s}  "
                f"{entry['from']:24s}  {entry['subject'][:40]:40s}  {entry['id']}"
            )
    if not found:
        print(f"(empty: {who}{'/'+args.channel if args.channel else ''})",
              file=sys.stderr)
    return 0


def cmd_inbox_uri(args) -> int:
    who = _identity(args.as_)
    print(build_uri(get_default_scheme(), who, args.channel))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agent-mail",
        description="Identity-aware async message bus for AI agents.",
    )
    p.add_argument("-V", "--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)

    def add_identity(sp):
        sp.add_argument("--as", dest="as_", metavar="AGENT_ID",
                        help="Act as this agent_id (or set AGENT_MAIL_IDENTITY).")

    sp = sub.add_parser("send", help="Send a message to another agent's inbox")
    sp.add_argument("to", help="Recipient agent_id")
    sp.add_argument("-s", "--subject", default="")
    sp.add_argument("-b", "--body", default="")
    sp.add_argument("-a", "--attach", action="append", metavar="URI",
                    help="Attachment URI (typically agentdrive://...). Repeatable.")
    sp.add_argument("--channel", default=DEFAULT_CHANNEL)
    sp.add_argument("--type", default="request",
                    choices=["request", "response", "event", "broadcast"])
    sp.add_argument("--reply-to", dest="reply_to", default=None)
    sp.add_argument("--correlation-id", dest="correlation_id", default=None)
    add_identity(sp)
    sp.set_defaults(func=cmd_send)

    sp = sub.add_parser("recv", help="Pull messages from your inbox")
    sp.add_argument("--channel", default=DEFAULT_CHANNEL)
    sp.add_argument("--limit", type=int, default=10)
    sp.add_argument("--peek", action="store_true",
                    help="Don't take messages into in-flight state (no ack needed).")
    sp.add_argument("--ack", action="store_true",
                    help="Auto-ack pulled messages (drains the queue).")
    sp.add_argument("--json", action="store_true",
                    help="Emit one JSON object per line instead of human format.")
    add_identity(sp)
    sp.set_defaults(func=cmd_recv)

    sp = sub.add_parser("ack", help="Acknowledge a previously-received message")
    sp.add_argument("msg_id")
    add_identity(sp)
    sp.set_defaults(func=cmd_ack)

    sp = sub.add_parser("ls", help="List messages in your inbox(es)")
    sp.add_argument("--channel", default=None,
                    help="Filter to one channel (default: all)")
    sp.add_argument("--json", action="store_true")
    add_identity(sp)
    sp.set_defaults(func=cmd_ls)

    sp = sub.add_parser("inbox-uri", help="Print your agentmail:// inbox URI")
    sp.add_argument("--channel", default=DEFAULT_CHANNEL)
    add_identity(sp)
    sp.set_defaults(func=cmd_inbox_uri)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover
        sys.exit(f"Failed: {exc}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

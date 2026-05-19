"""CLI entry point — placeholder for v0.1.

Real subcommands (send / recv / ack / ls) land in a follow-up commit.
"""
from __future__ import annotations

import sys

from agent_mail import __version__


_HELP = """\
agent-mail v{version} — identity-aware async message bus for AI agents

Status: pre-alpha. The CLI is not implemented yet — this binary exists
so that `pip install -e .` succeeds and downstream tooling (Hermes
skill, examples, etc.) can target a stable entry point.

Planned subcommands (see README.md):
  agent-mail send   <to>  -s <subject> -b <body> [-a <agentdrive-uri>]
  agent-mail recv   --channel inbox [--limit N] [--ack]
  agent-mail ack    <msg_id>
  agent-mail ls     [--channel inbox]

Track progress: https://github.com/AgentOrganization/agent-mail
"""


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"-h", "--help", "help"}:
        print(_HELP.format(version=__version__))
        return 0
    if argv[0] in {"-V", "--version"}:
        print(__version__)
        return 0
    print(
        f"agent-mail: subcommand {argv[0]!r} is not implemented in "
        f"v{__version__} yet. Run `agent-mail --help` for the planned API.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

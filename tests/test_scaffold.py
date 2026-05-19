"""Smoke tests: scaffolding works (import, version, CLI help)."""
import subprocess
import sys

import agent_mail


def test_version_string():
    assert isinstance(agent_mail.__version__, str)
    assert agent_mail.__version__.startswith("0.")


def test_cli_help_exits_zero():
    result = subprocess.run(
        [sys.executable, "-m", "agent_mail.cli", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "agent-mail" in result.stdout
    assert "pre-alpha" in result.stdout.lower()


def test_cli_version_flag():
    result = subprocess.run(
        [sys.executable, "-m", "agent_mail.cli", "--version"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == agent_mail.__version__


def test_cli_unknown_subcommand_exits_nonzero():
    result = subprocess.run(
        [sys.executable, "-m", "agent_mail.cli", "bogus"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "not implemented" in result.stderr

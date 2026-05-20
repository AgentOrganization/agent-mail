"""Provider package + shared factory.

``get_provider_for_scheme(scheme)`` returns a configured :class:`MessageProvider`.

v0.2 defaults to ``files`` (a directory of JSON files — no DB, no server).
``local`` (SQLite WAL) is kept for single-process advanced use cases.
"""
from __future__ import annotations

import os


class ProviderConfigError(RuntimeError):
    """Raised when a provider cannot be constructed from current env config."""


def get_provider_for_scheme(scheme: str):
    """Return a MessageProvider for ``scheme``.

    Schemes:
        ``files`` — default. Directory-of-JSON. Path = ``$AGENT_MAIL_DIR``
                    (default ``./mailbox``).
        ``local`` — SQLite-WAL backed. Path = ``$AGENT_MAIL_LOCAL_DIR``
                    (default ``/tmp/agent_mail``). Kept for single-process,
                    high-volume scenarios where you want indexed queries.
    """
    if scheme == "files":
        from agent_mail.providers.files import FileProvider
        base = os.getenv("AGENT_MAIL_DIR", "./mailbox")
        return FileProvider(base)
    if scheme == "local":
        from agent_mail.providers.local import LocalProvider
        base = os.getenv("AGENT_MAIL_LOCAL_DIR", "/tmp/agent_mail")
        return LocalProvider(base)
    raise ProviderConfigError(
        f"Unknown provider scheme: {scheme!r} (v0.2 supports 'files' and 'local')"
    )


def get_default_scheme() -> str:
    """Honor ``AGENT_MAIL_SCHEME`` env var; otherwise ``files``."""
    return os.getenv("AGENT_MAIL_SCHEME", "files")


def get_default_provider():
    """Convenience: build the provider implied by environment."""
    return get_provider_for_scheme(get_default_scheme())

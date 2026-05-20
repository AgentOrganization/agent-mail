"""Provider package + shared factory.

``get_provider_for_scheme(scheme)`` returns a configured :class:`MessageProvider`.
Mirrors agent-drive's ``providers.get_provider_for_uri`` design.
"""
from __future__ import annotations

import os


class ProviderConfigError(RuntimeError):
    """Raised when a provider cannot be constructed from current env config."""


def get_provider_for_scheme(scheme: str):
    """Return a MessageProvider for ``scheme``. v0.1 only ships ``local``."""
    if scheme == "local":
        from agent_mail.providers.local import LocalProvider
        base = os.getenv("AGENT_MAIL_LOCAL_DIR", "/tmp/agent_mail")
        return LocalProvider(base)
    raise ProviderConfigError(
        f"Unknown provider scheme: {scheme!r} (v0.1 supports only 'local')"
    )

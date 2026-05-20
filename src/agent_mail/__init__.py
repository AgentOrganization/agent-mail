"""agent-mail — identity-aware async message bus for AI agents.

v0.2 default backend is :class:`FileProvider` — a directory of JSON files,
no server, no DB. Synchronization between agents (git, rsync, USB, cloud
sync, etc.) is intentionally out of scope. The mailbox is just a folder.
"""
from .core import (
    AgentMail,
    Message,
    MessageProvider,
    parse_uri,
    build_uri,
    DEFAULT_CHANNEL,
    PROTOCOL_VERSION,
)
from .providers.files import FileProvider
from .providers.local import LocalProvider

__version__ = "0.2.0"

__all__ = [
    "AgentMail",
    "Message",
    "MessageProvider",
    "FileProvider",
    "LocalProvider",
    "parse_uri",
    "build_uri",
    "DEFAULT_CHANNEL",
    "PROTOCOL_VERSION",
    "__version__",
]

"""agent-mail — identity-aware async message bus for AI agents."""
from .core import (
    AgentMail,
    Message,
    MessageProvider,
    parse_uri,
    build_uri,
    DEFAULT_CHANNEL,
    PROTOCOL_VERSION,
)
from .providers.local import LocalProvider

__version__ = "0.1.0"

__all__ = [
    "AgentMail",
    "Message",
    "MessageProvider",
    "LocalProvider",
    "parse_uri",
    "build_uri",
    "DEFAULT_CHANNEL",
    "PROTOCOL_VERSION",
    "__version__",
]

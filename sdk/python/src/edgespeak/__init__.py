"""EdgeSpeak's Python SDK for the local CLI runtime."""
from ._client import EdgeSpeak, EdgeSpeakError
from ._process import RuntimeStartError

__version__ = "0.1.0a1"
__all__ = ["EdgeSpeak", "EdgeSpeakError", "RuntimeStartError"]

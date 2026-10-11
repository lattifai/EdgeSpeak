"""EdgeSpeak's Python SDK for the local CLI runtime."""
from ._client import EdgeSpeak, EdgeSpeakError
from ._process import RuntimeStartError
from ._bootstrap import MIN_CLI_VERSION
from ._streaming import EventStream

__version__ = "0.1.0a1"
__all__ = ["EdgeSpeak", "EdgeSpeakError", "RuntimeStartError", "MIN_CLI_VERSION", "EventStream"]

from ._types import AudioChannel, ReferenceFormat, SearchEffort, TimestampGranularity, TranscriptionFormat

__all__ += ["AudioChannel", "ReferenceFormat", "SearchEffort", "TimestampGranularity", "TranscriptionFormat"]

"""EdgeSpeak's Python SDK for the local CLI runtime."""
from ._client import EdgeSpeak, EdgeSpeakError
from ._process import RuntimeStartError
from ._bootstrap import MIN_CLI_VERSION
from ._streaming import EventStream
from ._types import AudioChannel, ReferenceFormat, SearchEffort, TimestampGranularity, TranscriptionFormat

__version__ = "0.6.4"
__all__ = ["EdgeSpeak", "EdgeSpeakError", "RuntimeStartError", "MIN_CLI_VERSION", "EventStream",
           "AudioChannel", "ReferenceFormat", "SearchEffort", "TimestampGranularity", "TranscriptionFormat"]

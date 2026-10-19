"""EdgeSpeak's Python SDK for the local CLI runtime."""
from ._client import EdgeSpeak, EdgeSpeakError
from ._process import RuntimeStartError
from ._bootstrap import MIN_CLI_VERSION
from ._streaming import EventStream
from ._text import slice_utf8
from ._types import NormalizationMode, NormalizationClass, SpeechStreamFormat, Device, AudioResponseFormat, PcmFormat, AudioChannel, ReferenceFormat, SearchEffort, TimestampGranularity, TranscriptionFormat

from ._version import __version__ as __version__
__all__ = ["EdgeSpeak", "EdgeSpeakError", "RuntimeStartError", "MIN_CLI_VERSION", "EventStream",
           "NormalizationMode", "NormalizationClass", "SpeechStreamFormat", "slice_utf8", "Device", "AudioResponseFormat", "PcmFormat", "AudioChannel", "ReferenceFormat", "SearchEffort", "TimestampGranularity", "TranscriptionFormat"]

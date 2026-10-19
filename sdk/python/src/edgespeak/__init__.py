"""EdgeSpeak's Python SDK for the local CLI runtime."""
from ._input_audio import AudioInput
from ._client import EdgeSpeak, EdgeSpeakError
from ._process import RuntimeStartError
from ._bootstrap import MIN_CLI_VERSION
from ._streaming import EventStream
from ._text import slice_utf8
from ._types import NormalizationMode, NormalizationClass, Device, AudioResponseFormat, PcmFormat, AudioChannel, ReferenceFormat, SearchEffort, TimestampGranularity, TranscriptionFormat

from ._version import __version__ as __version__
__all__ = ["AudioInput", "EdgeSpeak", "EdgeSpeakError", "RuntimeStartError", "MIN_CLI_VERSION", "EventStream",
           "NormalizationMode", "NormalizationClass", "slice_utf8", "Device", "AudioResponseFormat", "PcmFormat", "AudioChannel", "ReferenceFormat", "SearchEffort", "TimestampGranularity", "TranscriptionFormat"]

from ._responses import Transcription, Alignment, Segmentation, Diarization, Embeddings, Similarity, Segment, Word, GatewayEvent, Usage, Models
__all__ += ["Transcription", "Alignment", "Segmentation", "Diarization", "Embeddings", "Similarity", "Segment", "Word", "GatewayEvent", "Usage", "Models"]

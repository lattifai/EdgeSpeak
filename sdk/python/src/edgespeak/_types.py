"""Public option types for editor completion; model IDs remain runtime-defined."""
from typing import Literal

TimestampGranularity = Literal["word", "segment"]
TranscriptionFormat = Literal["json", "verbose_json", "diarized_json", "text"]
ReferenceFormat = Literal["txt", "json", "srt", "ass", "ssa"]
# Empty string is a backwards-compatible gateway alias for standard.
SearchEffort = Literal["standard", "extended", "auto", ""]
# Numeric strings are retained for compatibility with the gateway.
AudioChannel = Literal["mix"] | str | int

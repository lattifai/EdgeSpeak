"""Typed views of stable gateway fields; returned values remain ordinary dicts.

Optional keys depend on response format and runtime version. Timestamps and
all duration fields are seconds. Unknown gateway extension fields are preserved
at runtime; these hints do not parse, coerce, or discard a response.
"""
from typing import Any, TypedDict


class DurationUsage(TypedDict):
    type: str
    seconds: float


class Word(TypedDict, total=False):
    word: str
    start: float
    end: float
    score: float


class Segment(TypedDict, total=False):
    id: int | str
    type: str
    text: str
    start: float
    end: float
    speaker: str | None
    avg_logprob: float
    words: list[Word]
    x_edgespeak: dict[str, Any]


class Transcription(TypedDict, total=False):
    task: str
    text: str
    duration: float
    language: str
    segments: list[Segment]
    usage: DurationUsage
    word_timestamps_unavailable: list[dict[str, Any]]


class Alignment(Transcription, total=False):
    language_candidates: list[str]
    search_effort_used: str
    search_retried: bool
    segmentation_grant: str
    normalization_regions: list[dict[str, Any]]
    optional_spans: list[dict[str, Any]]


class Segmentation(TypedDict, total=False):
    task: str
    text: str
    segments: list[Segment]


class SpeakerTurn(TypedDict):
    start: float
    end: float
    speaker: str


class Diarization(TypedDict):
    duration: float
    speakers: list[str]
    segments: list[SpeakerTurn]


class Embedding(TypedDict):
    index: int
    embedding: list[float]
    effective_speech_seconds: float


class Embeddings(TypedDict):
    object: str
    model: str
    data: list[Embedding]


class Similarity(TypedDict):
    object: str
    model: str
    similarity: float


class GatewayEvent(TypedDict, total=False):
    """Common stream fields; inspect type/task before using protocol payloads."""
    type: str
    task: str
    delta: Any
    text: str
    progress: float
    segments: list[Segment]
    error: dict[str, Any] | None
    response: dict[str, Any]
    choices: list[dict[str, Any]]
    index: int
    content_block: dict[str, Any]
    message: dict[str, Any]
    usage: dict[str, Any]


class UsagePeriod(TypedDict, total=False):
    start: str
    resetsAt: str


class Allowance(TypedDict, total=False):
    period: int | None
    addonBalance: int


class UsageTotals(TypedDict, total=False):
    total: int
    byCategory: dict[str, int]
    bySource: dict[str, int]
    daily: list[dict[str, Any]]


class Remaining(TypedDict, total=False):
    period: int | None
    addon: int
    total: int | None


class Usage(TypedDict, total=False):
    plan: str
    period: UsagePeriod
    allowance: Allowance
    used: UsageTotals
    remaining: Remaining | None
    sync: dict[str, Any]
    state: str


class Model(TypedDict, total=False):
    id: str
    object: str
    created: int
    owned_by: str
    supported_endpoints: list[str]
    execution_location: str
    default_for: list[str]
    installed: bool


class Models(TypedDict):
    object: str
    data: list[Model]

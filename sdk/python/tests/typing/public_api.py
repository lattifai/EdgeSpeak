"""Static-only consumer contract; checked against source and the installed wheel."""
from pathlib import Path
from typing import Any
from typing_extensions import assert_type
from edgespeak import EdgeSpeak, EventStream, TimestampGranularity, TranscriptionFormat


def check_public_api(client: EdgeSpeak, stream: bool, progress: bool,
                     response_format: TranscriptionFormat | None) -> None:
    assert_type(client.transcribe("audio.wav"), dict[str, Any])
    assert_type(client.transcribe("audio.wav", stream=False), dict[str, Any])
    assert_type(client.transcribe("audio.wav", stream=True, response_format="json"), EventStream)
    assert_type(client.align("audio.wav", text="hello", progress=False), dict[str, Any])
    assert_type(client.transcribe(Path("audio.wav"), diarize=True), dict[str, Any])
    assert_type(client.transcribe("audio.wav", response_format="text"), str)
    assert_type(client.transcribe("audio.wav", response_format="verbose_json"), dict[str, Any])
    assert_type(client.transcribe("audio.wav", stream=True), EventStream)
    assert_type(client.transcribe("audio.wav", stream=stream, response_format=response_format),
                dict[str, Any] | str | EventStream)
    assert_type(client.align("audio.wav", text="hello"), dict[str, Any])
    assert_type(client.align("audio.wav", text="hello", progress=True), EventStream)
    assert_type(client.align("audio.wav", text="hello", progress=progress), dict[str, Any] | EventStream)
    assert_type(client.segment("hello"), dict[str, Any])
    assert_type(client.diarize("audio.wav"), dict[str, Any])
    assert_type(client.speaker_embedding(["audio.wav"]), dict[str, Any])
    assert_type(client.speaker_similarity([1.0], [1.0]), dict[str, Any])
    granularities: list[TimestampGranularity] = ["word", "segment"]
    client.transcribe("audio.wav", timestamp_granularities=granularities)
    client.transcribe("audio.wav", timestamp_granularities=(value for value in granularities))
    client.align("audio.wav", text="hello", protected_terms=(word for word in ["EdgeSpeak"]), audio_channel="1")
    client.segment(segments=({"text": "hello"} for _ in range(1)))
    # warn-unused-ignores makes rejection part of the executable type contract.
    client.transcribe("audio.wav", timestamp_granularities=["sentence"])  # type: ignore[list-item]
    client.transcribe("audio.wav", response_format="xml")  # type: ignore[call-overload]
    client.align("audio.wav", text="hello", search_effort="fast")  # type: ignore[call-overload]
    client.align("audio.wav", text="hello", text_format="vtt")  # type: ignore[call-overload]
    with client as opened:
        assert_type(opened, EdgeSpeak)
    with client.transcribe("audio.wav", stream=True) as events:
        assert_type(events, EventStream)
        assert_type(next(events), dict[str, Any])

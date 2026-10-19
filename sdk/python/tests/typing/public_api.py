"""Static-only consumer contract; checked against source and the installed wheel."""
from pathlib import Path
from typing import Any
from typing_extensions import assert_type
from edgespeak import Usage, Models, Transcription, Alignment, Segmentation, Diarization, Embeddings, Similarity, GatewayEvent, Device, EdgeSpeak, EventStream, TimestampGranularity, TranscriptionFormat


def check_public_api(client: EdgeSpeak, stream: bool, progress: bool,
                     response_format: TranscriptionFormat | None) -> None:
    assert_type(client.transcribe("audio.wav"), Transcription)
    assert_type(client.transcribe("audio.wav", stream=False), Transcription)
    assert_type(client.transcribe("audio.wav", stream=True, response_format="json"), EventStream)
    assert_type(client.align("audio.wav", text="hello", progress=False), Alignment)
    assert_type(client.transcribe(Path("audio.wav"), diarize=True), Transcription)
    assert_type(client.transcribe("audio.wav", response_format="text"), str)
    assert_type(client.transcribe("audio.wav", response_format="verbose_json"), Transcription)
    assert_type(client.transcribe("audio.wav", stream=True), EventStream)
    assert_type(client.transcribe("audio.wav", stream=stream, response_format=response_format),
                Transcription | str | EventStream)
    assert_type(client.align("audio.wav", text="hello"), Alignment)
    assert_type(client.align("audio.wav", text="hello", progress=True), EventStream)
    assert_type(client.align("audio.wav", text="hello", progress=progress), Alignment | EventStream)
    assert_type(client.upsample("audio.wav", sample_rate=24_000), bytes)
    assert_type(client.upsample("audio.flac", response_format="mp3", bitrate=192000), bytes)
    assert_type(client.upsample("audio.wav", response_format="flac", pcm_format="s24"), bytes)
    client.upsample("audio.wav", response_format="mp4")  # type: ignore[arg-type]
    client.upsample("audio.wav", pcm_format="float")  # type: ignore[arg-type]
    assert_type(client.segment("hello"), Segmentation)
    assert_type(client.diarize("audio.wav"), Diarization)
    assert_type(client.speaker_embedding(["audio.wav"]), Embeddings)
    assert_type(client.speaker_similarity([1.0], [1.0]), Similarity)
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
        assert_type(next(events), GatewayEvent)


def check_device_constructor() -> None:
    device: Device = "cuda:1"
    assert_type(EdgeSpeak(device=device), EdgeSpeak)
    assert_type(EdgeSpeak(device="cpu"), EdgeSpeak)
    assert_type(EdgeSpeak(device="metal"), EdgeSpeak)
    EdgeSpeak(device=1)  # type: ignore[arg-type]


def check_gateway_api(client: EdgeSpeak) -> None:
    assert_type(client.text_normalizations("$25", language="en", mode="tn", classes=["money"]), dict[str, Any])
    assert_type(client.models(), Models)
    assert_type(client.models_running(), dict[str, Any])
    assert_type(client.models_download("Vendor/Model"), dict[str, Any])
    assert_type(client.usage(refresh=True), Usage)
    client.text_normalizations("25", language="en", mode="other")  # type: ignore[arg-type]
    client.text_normalizations("25", language="en", classes=["other"])  # type: ignore[list-item]


def check_generation_api(client: EdgeSpeak, stream: bool) -> None:
    assert_type(client.chat_completions([{"role": "user", "content": "Hi"}], model="model"), dict[str, Any])
    assert_type(client.chat_completions([{"role": "user", "content": "Hi"}], model="model", stream=True), EventStream)
    assert_type(client.responses("Hi", model="model", stream=stream), dict[str, Any] | EventStream)
    assert_type(client.responses("Hi", model="model", stream=True), EventStream)
    assert_type(client.messages([{"role": "user", "content": "Hi"}], model="model", max_tokens=10, stream=True), EventStream)
    assert_type(client.tokenize("Hi", model="model"), dict[str, Any] | list[int])


def check_memory_audio(client: EdgeSpeak) -> None:
    import numpy as np
    audio = np.zeros((160, 2), dtype=np.float32)
    assert_type(client.transcribe(audio, sample_rate=16000), Transcription)
    assert_type(client.align(audio, sample_rate=16000, text="hello"), Alignment)
    assert_type(client.transcribe(b"encoded"), Transcription)
    assert_type(client.align(b"encoded", text="hello", progress=True), EventStream)

    client.transcribe(123)  # type: ignore[call-overload]
    client.align(bytearray(b"encoded"), text="hello")  # type: ignore[call-overload]


def check_response_fields(client: EdgeSpeak) -> None:
    result = client.transcribe("audio.wav")
    assert_type(result["segments"][0]["start"], float)
    assert_type(result["segments"][0]["words"][0]["word"], str)
    assert_type(client.speaker_embedding("audio.wav")["data"][0]["embedding"], list[float])
    assert_type(client.models()["data"][0]["id"], str)
    client.chat_completions(({"role": "user", "content": word} for word in ["hello"]), model="model")

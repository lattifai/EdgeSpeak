"""Public typing contract for a base installation without NumPy."""
from typing_extensions import assert_type
from edgespeak import Alignment, EdgeSpeak, Transcription


def consume(client: EdgeSpeak) -> None:
    assert_type(client.transcribe('speech.wav'), Transcription)
    assert_type(client.transcribe(b'encoded'), Transcription)
    assert_type(client.align(b'encoded', text='hello'), Alignment)
    assert_type(client.transcribe('speech.wav')['text'], str)
    client.transcribe(123)  # type: ignore[call-overload]


async def async_without_numpy() -> None:
    from edgespeak import AsyncEdgeSpeak, Transcription
    async with AsyncEdgeSpeak(base_url="http://localhost:1118/v1") as client:
        result: Transcription = await client.transcribe(b"encoded")
        print(result)

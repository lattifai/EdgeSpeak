"""Public typing contract for a base installation without NumPy."""
from typing_extensions import assert_type
from edgespeak import Alignment, EdgeSpeak, Transcription


def consume(client: EdgeSpeak) -> None:
    assert_type(client.transcribe('speech.wav'), Transcription)
    assert_type(client.transcribe(b'encoded'), Transcription)
    assert_type(client.align(b'encoded', text='hello'), Alignment)
    assert_type(client.transcribe('speech.wav')['text'], str)
    client.transcribe(123)  # type: ignore[call-overload]

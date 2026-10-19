"""Prepare in-memory samples without importing the optional NumPy dependency."""
from __future__ import annotations

from dataclasses import dataclass
import io
from numbers import Integral
import os
import sys
from typing import Any, TYPE_CHECKING
import wave

if TYPE_CHECKING:
    from numpy.typing import NDArray
    ArrayAudio = NDArray[Any]
else:
    ArrayAudio = Any

AudioInput = str | os.PathLike[str] | bytes | ArrayAudio
MAX_MEMORY_AUDIO_BYTES = 256 * 1024 * 1024
_CHUNK_FRAMES = 65536


@dataclass(frozen=True)
class MemoryAudio:
    payload: bytes
    filename: str
    content_type: str
    channels: int | None = None


def prepare_audio(audio: AudioInput, sample_rate: int | None) -> str | os.PathLike[str] | MemoryAudio:
    if isinstance(audio, (str, os.PathLike, bytes)):
        if sample_rate is not None:
            raise ValueError("sample_rate is only for NumPy arrays; encoded media supplies its own sample rate.")
        if not isinstance(audio, bytes):
            return audio
        if not audio or len(audio) > MAX_MEMORY_AUDIO_BYTES:
            raise ValueError("Encoded audio bytes must be non-empty and at most 256 MiB.")
        return MemoryAudio(audio, "audio.bin", "application/octet-stream")
    np = sys.modules.get("numpy")
    if np is None or not isinstance(audio, np.ndarray):
        raise ValueError("audio must be a local path (str or PathLike), encoded bytes, or a NumPy ndarray; convert array-like values with np.asarray first.")
    # Reject masked arrays and other subclasses whose semantics may discard data.
    if type(audio) is not np.ndarray:
        raise ValueError("audio must be a plain NumPy ndarray; explicitly convert subclasses before uploading.")
    if isinstance(sample_rate, bool) or not isinstance(sample_rate, Integral) or not 1 <= sample_rate <= 384000:
        raise ValueError("NumPy audio requires sample_rate as an integer from 1 to 384000 Hz (not bool).")
    if audio.ndim not in (1, 2) or audio.shape[0] == 0:
        raise ValueError("NumPy audio must have non-empty shape (frames,) or (frames, channels).")
    channels = 1 if audio.ndim == 1 else audio.shape[1]
    if not 1 <= channels <= 8:
        raise ValueError("NumPy audio requires 1..8 channels in (frames, channels) order; transpose channel-first arrays explicitly with .T.")
    if audio.dtype.kind == "i" and audio.dtype.itemsize == 2:
        floating = False
    elif audio.dtype.kind == "f" and audio.dtype.itemsize in (4, 8):
        floating = True
    else:
        raise ValueError("NumPy audio dtype must be int16, float32 or float64; convert explicitly with .astype().")
    if int(audio.shape[0]) * channels * 2 + 44 > MAX_MEMORY_AUDIO_BYTES:
        raise ValueError("Encoded NumPy WAV exceeds the 256 MiB in-memory audio limit.")
    with io.BytesIO() as output:
        with wave.open(output, "wb") as wav:
            wav.setparams((channels, 2, int(sample_rate), 0, "NONE", "not compressed"))
            for offset in range(0, audio.shape[0], _CHUNK_FRAMES):
                chunk = audio[offset:offset + _CHUNK_FRAMES]
                if floating:
                    if not np.isfinite(chunk).all() or (chunk < -1).any() or (chunk > 1).any():
                        raise ValueError("Float audio must be finite and within [-1, 1]; clip or normalize it explicitly first.")
                    chunk = np.rint(chunk.astype(np.float64) * 32767)
                wav.writeframesraw(chunk.astype("<i2").tobytes(order="C"))
        return MemoryAudio(output.getvalue(), "audio.wav", "audio/wav", channels)


def validate_selection(audio: str | os.PathLike[str] | MemoryAudio, track: int | None, channel: str | int | None) -> None:
    if isinstance(audio, MemoryAudio) and audio.channels is not None:
        if track not in (None, 0):
            raise ValueError("NumPy audio has one track; audio_track must be None or 0.")
        if channel is not None and channel != "mix" and int(channel) >= audio.channels:
            raise ValueError(f"audio_channel is out of range for NumPy audio with {audio.channels} channels.")

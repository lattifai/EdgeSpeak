"""Prepare in-memory samples without importing the optional NumPy dependency."""
from __future__ import annotations

from dataclasses import dataclass, field
import io
from numbers import Integral
import os
import re
import sys
from typing import Protocol
from collections.abc import Sequence
import wave
import tempfile
from typing import BinaryIO, Any, cast
from ._audio_budget import positive_limit


class ArrayAudio(Protocol):
    """Structural array type for hints without a NumPy installation.

    Runtime input must still be a plain NumPy ndarray. Shape is (frames,) or
    (frames, channels); dtype must be int16, float32, or float64.
    """
    @property
    def shape(self) -> tuple[int, ...]: ...

    @property
    def dtype(self) -> object: ...


@dataclass(frozen=True, eq=False)
class AudioSamples:
    """NumPy samples with their input rate; does not copy or expose sample data.

    Use (frames,) or (frames, channels), int16 or float32/64 in [-1, 1].
    Do not mutate data until the request has finished preparing its upload.
    """
    data: ArrayAudio = field(repr=False)
    sample_rate: int


AudioInput = str | os.PathLike[str] | bytes | ArrayAudio | AudioSamples
MAX_MEMORY_AUDIO_BYTES = 256 * 1024 * 1024
_CHUNK_FRAMES = 65536


class BytesReader(io.RawIOBase):
    """Seekable read-only bytes view, without a second whole-payload buffer."""
    def __init__(self, data: bytes):
        self._view = memoryview(data)
        self._position = 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        self._checkClosed()
        return self._position

    def seek(self, offset, whence=0):
        self._checkClosed()
        position = offset if whence == 0 else self._position + offset if whence == 1 else len(self._view) + offset if whence == 2 else -1
        if position < 0:
            raise ValueError("Invalid audio seek.")
        self._position = position
        return position

    def read(self, size=-1):
        self._checkClosed()
        if self._position >= len(self._view):
            return b""
        end = len(self._view) if size is None or size < 0 else min(len(self._view), self._position + size)
        value = self._view[self._position:end].tobytes()
        self._position = end
        return value

    def close(self):
        if not self.closed:
            self._view.release()
        super().close()


@dataclass(frozen=True, eq=False)
class AudioPlan:
    source: object = field(repr=False)
    size: int
    sample_rate: int | None = None
    channels: int | None = None
    floating: bool = False

    def open(self, spool_threshold: int | None = None) -> tuple[str, BinaryIO, str]:
        if isinstance(self.source, (str, os.PathLike)):
            path = os.fspath(self.source)
            return os.path.basename(path), open(path, "rb"), "application/octet-stream"
        if isinstance(self.source, bytes):
            return "audio.bin", cast(BinaryIO, BytesReader(self.source)), "application/octet-stream"
        np = sys.modules["numpy"]
        audio = cast(Any, self.source)
        output = tempfile.TemporaryFile("w+b") if spool_threshold is not None and self.size > spool_threshold else io.BytesIO()
        try:
            assert self.channels is not None and self.sample_rate is not None
            with wave.open(output, "wb") as wav:
                wav.setparams((self.channels, 2, self.sample_rate, 0, "NONE", "not compressed"))
                for offset in range(0, audio.shape[0], _CHUNK_FRAMES):
                    chunk = audio[offset:offset + _CHUNK_FRAMES]
                    if self.floating:
                        if not np.isfinite(chunk).all() or (chunk < -1).any() or (chunk > 1).any():
                            raise ValueError("Float audio must be finite and within [-1, 1]; clip or normalize it explicitly first.")
                        chunk = np.rint(chunk.astype(np.float64) * 32767)
                    wav.writeframesraw(chunk.astype("<i2").tobytes(order="C"))
            output.seek(0)
            return "audio.wav", cast(BinaryIO, output), "audio/wav"
        except BaseException:
            output.close()
            raise


def is_single_audio(audio: object) -> bool:
    np = sys.modules.get("numpy")
    return isinstance(audio, (str, os.PathLike, bytes, AudioSamples)) or (np is not None and isinstance(audio, np.ndarray))


def prepare_audio(audio: AudioInput, sample_rate: int | None, *, audio_track: int | None = None,
                  audio_channel: str | int | None = None, max_bytes: int | None = MAX_MEMORY_AUDIO_BYTES) -> AudioPlan:
    positive_limit(max_bytes, "max_memory_audio_bytes")
    if isinstance(audio, AudioSamples):
        if sample_rate is not None:
            raise ValueError("AudioSamples already supplies sample_rate; omit the duplicate input rate.")
        sample_rate, audio = audio.sample_rate, audio.data
        if isinstance(audio, (str, os.PathLike, bytes, AudioSamples)):
            raise ValueError("AudioSamples.data must be a plain NumPy ndarray.")
    if isinstance(audio, (str, os.PathLike, bytes)):
        if sample_rate is not None:
            raise ValueError("sample_rate is only for NumPy arrays; encoded media supplies its own sample rate.")
        if not isinstance(audio, bytes):
            return AudioPlan(audio, 0)
        if not audio:
            raise ValueError("Encoded audio bytes must be non-empty.")
        size = len(audio)
        _check_size(size, max_bytes)
        return AudioPlan(audio, size)
    np = sys.modules.get("numpy")
    if np is None or not isinstance(audio, np.ndarray):
        raise ValueError("audio must be a local path (str or PathLike), encoded bytes, AudioSamples, or a NumPy ndarray; convert array-like values with np.asarray first.")
    if type(audio) is not np.ndarray:
        raise ValueError("audio must be a plain NumPy ndarray; explicitly convert subclasses before uploading.")
    if isinstance(sample_rate, bool) or not isinstance(sample_rate, Integral) or not 1 <= sample_rate <= 384000:
        raise ValueError("NumPy audio requires sample_rate as an integer from 1 to 384000 Hz (not bool).")
    if audio.ndim not in (1, 2) or audio.shape[0] == 0:
        raise ValueError("NumPy audio must have non-empty shape (frames,) or (frames, channels).")
    channels = 1 if audio.ndim == 1 else audio.shape[1]
    if not 1 <= channels <= 8:
        raise ValueError("NumPy audio requires 1..8 channels in (frames, channels) order; transpose channel-first arrays explicitly with .T.")
    validate_selection(channels, audio_track, audio_channel)
    floating = audio.dtype.kind == "f" and audio.dtype.itemsize in (4, 8)
    if not floating and not (audio.dtype.kind == "i" and audio.dtype.itemsize == 2):
        raise ValueError("NumPy audio dtype must be int16, float32 or float64; convert explicitly with .astype().")
    size = int(audio.shape[0]) * channels * 2 + 44
    if size - 8 > 0xffffffff:
        raise ValueError("Encoded NumPy audio exceeds the RIFF/WAV size limit; split the audio.")
    _check_size(size, max_bytes)
    return AudioPlan(audio, size, int(sample_rate), channels, floating)


def _check_size(size: int, max_bytes: int | None) -> None:
    if max_bytes is not None and size > max_bytes:
        raise ValueError(f"Encoded audio uses {size} bytes, exceeding max_memory_audio_bytes={max_bytes} (default 256 MiB); increase this SDK limit or split the audio. Gateway limits still apply.")


def prepare_batch(audio: AudioInput | object, sample_rate: int | None, max_bytes: int | None) -> list[AudioPlan]:
    if is_single_audio(audio):
        return [prepare_audio(cast(AudioInput, audio), sample_rate, max_bytes=max_bytes)]
    if isinstance(audio, (bytearray, memoryview)) or not isinstance(audio, Sequence) or not audio:
        raise ValueError("audio must be a single AudioInput or a non-empty sequence of AudioInput.")
    if any(not is_single_audio(item) for item in audio):
        raise ValueError("audio batch must contain AudioInput values, not nested sequences.")
    naked = [not isinstance(item, (str, os.PathLike, bytes, AudioSamples)) for item in audio]
    if sample_rate is not None and not any(naked):
        raise ValueError("sample_rate is only for bare NumPy arrays in the batch; omit unused/duplicate input rate.")
    return [prepare_audio(item, sample_rate if raw else None, max_bytes=max_bytes) for item, raw in zip(audio, naked)]


def validate_selection(channels: int, track: int | None, channel: str | int | None) -> None:
    if track is not None and (type(track) is not int or track != 0):
        raise ValueError("NumPy audio has one track; audio_track must be None or 0.")
    if channel is None or channel == "mix":
        return
    numeric_string = isinstance(channel, str) and re.fullmatch(r"\+?[0-9]+", channel) is not None
    if not numeric_string and not (type(channel) is int and channel >= 0):
        raise ValueError("audio_channel must be 'mix' or a non-negative integer channel index.")
    if int(channel) >= channels:
        raise ValueError(f"audio_channel is out of range for NumPy audio with {channels} channels.")

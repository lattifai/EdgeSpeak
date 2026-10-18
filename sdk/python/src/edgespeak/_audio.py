"""Validate delivery options and audio containers without native dependencies."""
from __future__ import annotations

import struct

from ._errors import EdgeSpeakError

AUDIO_MIMES = {
    "wav": "audio/wav", "flac": "audio/flac", "mp3": "audio/mpeg",
    "m4a": "audio/mp4", "aac": "audio/aac", "ogg": "audio/ogg", "opus": "audio/ogg",
}


def validate_options(sample_rate: int, response_format: str, bitrate: int | None, pcm_format: str | None) -> None:
    if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or not 1 <= sample_rate <= 48000:
        raise ValueError("sample_rate must be an integer from 1 to 48000 Hz.")
    if not isinstance(response_format, str) or response_format not in AUDIO_MIMES:
        raise ValueError("response_format must be wav, flac, mp3, m4a, aac, ogg or opus.")
    lossless = response_format in ("wav", "flac")
    if bitrate is not None:
        if isinstance(bitrate, bool) or not isinstance(bitrate, int) or not 8000 <= bitrate <= 512000:
            raise ValueError("bitrate must be an integer from 8000 to 512000 bit/s.")
        if lossless:
            raise ValueError("bitrate is only supported for lossy response formats.")
    if pcm_format is not None and (not lossless or pcm_format not in ("s16", "s24", "s32", "f32")
                                   or (response_format == "flac" and pcm_format not in ("s16", "s24"))):
        raise ValueError("pcm_format requires WAV (s16/s24/s32/f32) or FLAC (s16/s24).")
    if response_format == "opus" and sample_rate != 48000:
        raise ValueError("Opus output requires sample_rate=48000.")
    if response_format in ("mp3", "aac", "m4a") and sample_rate not in (8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000):
        raise ValueError("sample_rate is not supported by the selected response_format.")


def _wav(data: bytes, sample_rate: int, pcm_format: str | None) -> bool:
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return False
    end = int.from_bytes(data[4:8], "little") + 8
    if end != len(data):
        return False
    offset, fmt, payload = 12, None, None
    while offset < end:
        if end - offset < 8:
            return False
        size = int.from_bytes(data[offset + 4:offset + 8], "little")
        stop = offset + 8 + size
        if stop > end:
            return False
        tag = data[offset:offset + 4]
        if tag == b"fmt ":
            if fmt is not None:
                return False
            fmt = data[offset + 8:stop]
        elif tag == b"data":
            if payload is not None:
                return False
            payload = data[offset + 8:stop]
        offset = stop + size % 2
    if offset != end or fmt is None or len(fmt) < 16 or not payload:
        return False
    encoding, channels, rate, byte_rate, block, bits = struct.unpack_from("<HHIIHH", fmt)
    if encoding == 0xFFFE:
        if len(fmt) < 40 or int.from_bytes(fmt[16:18], "little") < 22 or fmt[28:40] != bytes.fromhex("00001000800000aa00389b71"):
            return False
        valid_bits = int.from_bytes(fmt[18:20], "little")
        if valid_bits != bits:
            return False
        mask = int.from_bytes(fmt[20:24], "little")
        if mask and (mask.bit_count() != channels or mask & ~0x3FFFF):
            return False
        encoding = int.from_bytes(fmt[24:28], "little")
    if not 1 <= channels <= 8 or rate != sample_rate:
        return False
    if (encoding, bits) not in ((1, 16), (1, 24), (1, 32), (3, 32)):
        return False
    if block != channels * (bits // 8) or byte_rate != rate * block or len(payload) % block:
        return False
    if pcm_format and (encoding, bits) != {"s16": (1, 16), "s24": (1, 24), "s32": (1, 32), "f32": (3, 32)}[pcm_format]:
        return False
    if encoding == 3:
        import math
        if any(not math.isfinite(value[0]) for value in struct.iter_unpack("<f", payload)):
            return False
    return True


def validate_response(data: bytes, media_type: str, response_format: str, sample_rate: int, pcm_format: str | None) -> None:
    valid_mime = media_type.split(";", 1)[0].strip().lower() == AUDIO_MIMES[response_format]
    if response_format == "wav":
        valid = _wav(data, sample_rate, pcm_format)
    elif response_format == "flac":
        valid = len(data) >= 42 and data.startswith(b"fLaC")
    elif response_format == "mp3":
        valid = len(data) >= 4 and (data.startswith(b"ID3") or (data[0] == 0xFF and data[1] & 0xE0 == 0xE0))
    elif response_format == "m4a":
        valid = len(data) >= 24 and data[4:8] == b"ftyp"
    elif response_format == "aac":
        valid = len(data) >= 7 and data[0] == 0xFF and data[1] & 0xF6 == 0xF0
    else:
        marker = b"OpusHead" if response_format == "opus" else b"\x01vorbis"
        valid = len(data) >= 32 and data.startswith(b"OggS") and marker in data[:512]
    if not valid_mime or not valid:
        raise EdgeSpeakError("invalid_response")

"""Bounded local reads; reference parsing stays in the CLI/API runtime."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
from typing import Any, Mapping

_MAX_REFERENCE_BYTES = 64 * 1024 * 1024
_FORMATS = {"txt", "json", "srt", "ass", "ssa"}


def reference_input(text: str | Mapping[str, Any] | None,
                    text_file: str | os.PathLike[str] | None,
                    text_format: str | None) -> tuple[str, str | None]:
    if (text is None) == (text_file is None):
        raise ValueError("Provide exactly one of text or text_file.")
    if text_format is not None:
        text_format = text_format.strip().lower()
        if text_format not in _FORMATS:
            raise ValueError("text_format must be txt, json, srt, ass or ssa.")
    if text_file is not None:
        path = Path(text_file)
        text_format = text_format or path.suffix.lower().lstrip(".") or "txt"
        if text_format not in _FORMATS:
            raise ValueError("text_format must be txt, json, srt, ass or ssa.")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0))
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("Reference input must be a regular file.")
            raw = stream.read(_MAX_REFERENCE_BYTES + 1)
        if len(raw) > _MAX_REFERENCE_BYTES:
            raise ValueError("Reference input exceeds 64 MiB.")
        text = raw.decode("utf-8-sig")
    elif isinstance(text, Mapping):
        if text_format not in (None, "json"):
            raise ValueError("Mapping reference text requires text_format='json'.")
        text_format = "json"
        text = json.dumps(dict(text), ensure_ascii=False, allow_nan=False)
    if text_format is not None and text_format not in _FORMATS:
        raise ValueError("text_format must be txt, json, srt, ass or ssa.")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must not be empty.")
    return text, text_format

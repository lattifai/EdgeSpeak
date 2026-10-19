"""Helpers for the public normalization wire contract."""
from __future__ import annotations

from typing import get_args
from ._types import NormalizationClass


def slice_utf8(text: str, start_byte: int, end_byte: int) -> str:
    """Slice a half-open UTF-8 byte range, rejecting invalid bounds/boundaries.

    Use the original response['text'] with normalization spans, not an
    alternative's rewritten text. Python string indices are not byte offsets.
    """
    if not isinstance(text, str):
        raise ValueError("text must be a string.")
    raw = text.encode("utf-8")
    if type(start_byte) is not int or type(end_byte) is not int or not 0 <= start_byte <= end_byte <= len(raw):
        raise ValueError("UTF-8 byte range is outside the original text.")
    try:
        # Decode both prefix and slice: even an empty range must be on a boundary.
        raw[:start_byte].decode("utf-8")
        return raw[start_byte:end_byte].decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("UTF-8 byte range must end on character boundaries.") from None


def validate_normalization(text, language, mode, top_k, classes):
    if not isinstance(text, str) or not text or len(text.encode("utf-8")) > 256 * 1024:
        raise ValueError("text must be non-empty and at most 256 KiB UTF-8.")
    if not isinstance(language, str) or not language.strip() or len(language.encode("utf-8")) > 256:
        raise ValueError("language is required (for example zh, en, or und), up to 256 UTF-8 bytes.")
    if mode not in ("tn", "itn"):
        raise ValueError("mode must be tn or itn.")
    if top_k is not None and (type(top_k) is not int or not 1 <= top_k <= 16):
        raise ValueError("top_k must be an integer from 1 to 16.")
    if classes is not None:
        if isinstance(classes, (str, bytes, dict)):
            raise ValueError("classes must be a non-empty sequence of normalization classes.")
        try:
            classes = list(classes)
        except TypeError:
            raise ValueError("classes must be a non-empty sequence of normalization classes.") from None
        if not classes or any(not isinstance(item, str) or item not in get_args(NormalizationClass) for item in classes):
            raise ValueError("classes must contain supported normalization classes, e.g. cardinal, money, date.")
    return classes

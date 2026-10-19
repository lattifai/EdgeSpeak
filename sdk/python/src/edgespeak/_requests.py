"""Shared request validation and wire descriptions; no HTTP or process ownership."""
from __future__ import annotations
import json
import math
import re
from dataclasses import dataclass
from numbers import Real, Integral
from itertools import islice
from typing import Any, Iterable, Mapping, Sequence, TypeVar
from ._input_audio import AudioInput, AudioPlan, prepare_audio, prepare_batch, MAX_MEMORY_AUDIO_BYTES
from ._reference import reference_input

_T = TypeVar("_T")

def _materialize(value: Iterable[_T], name: str, *, limit: int | None = None) -> list[_T]:
    """Consume an iterable exactly once and never split a string into characters."""
    if isinstance(value, (str, bytes, Mapping)):
        raise ValueError(f"{name} must be a sequence of items, not a string or mapping.")
    try:
        iterator = iter(value)
    except TypeError:
        raise ValueError(f"{name} must be a sequence of items.") from None
    # Errors raised by user iterator code must retain their original traceback.
    return list(iterator if limit is None else islice(iterator, limit))


def _finite_number(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, Real):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _sentence_options(*, threshold=None, paragraph_threshold=None,
                      semantic_sentence_enabled=None, min_chars=None, max_chars=None,
                      start_margin=None, end_margin=None):
    if semantic_sentence_enabled is not None and type(semantic_sentence_enabled) is not bool:
        raise ValueError("semantic_sentence_enabled must be a boolean.")
    for name, value in (("threshold", threshold), ("paragraph_threshold", paragraph_threshold)):
        if value is not None and (not _finite_number(value) or not 0 <= value <= 1):
            raise ValueError(f"{name} must be a finite number from 0 to 1.")
    for name, value in (("min_chars", min_chars), ("max_chars", max_chars)):
        if value is not None and (type(value) is not int or not 0 <= value <= 65535):
            raise ValueError(f"{name} must be an integer from 0 to 65535.")
    for name, value in (("start_margin", start_margin), ("end_margin", end_margin)):
        if value is not None and (not _finite_number(value) or value < 0):
            raise ValueError(f"{name} must be finite non-negative seconds.")


def _json_numbers(value):
    if isinstance(value, Mapping):
        return {key: _json_numbers(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_numbers(item) for item in value]
    if isinstance(value, Integral) and not isinstance(value, (int, bool)):
        return int(value)
    if isinstance(value, Real) and not isinstance(value, (int, float, bool)):
        return float(value)
    return value


def _json_body(values: Mapping[str, Any], options: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if options is not None and not isinstance(options, Mapping):
        raise ValueError("options must be a mapping of protocol extension fields.")
    if options and any(key in values for key in options):
        raise ValueError("options cannot override explicitly named parameters.")
    body = {key: value for key, value in values.items() if value is not None}
    if options:
        body.update(options)
    if any(not isinstance(key, str) for key in body):
        raise ValueError("JSON field names must be strings.")
    try:
        body = _json_numbers(body)
        json.dumps(body, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise ValueError("Request fields must be finite JSON values.") from None
    return body


def _message_list(messages: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    values = _materialize(messages, "messages")
    if not values or any(not isinstance(value, Mapping) for value in values):
        raise ValueError("messages must be a non-empty sequence of message mappings.")
    return [dict(value) for value in values]


def _model_id(model: str) -> None:
    if not isinstance(model, str) or not model.strip() or len(model.encode("utf-8")) > 512:
        raise ValueError("model must be a non-empty ID up to 512 UTF-8 bytes.")


def _generation_scalars(temperature, top_p, token_limit):
    if temperature is not None and (not _finite_number(temperature) or temperature < 0):
        raise ValueError("temperature must be a finite non-negative number.")
    if top_p is not None and (not _finite_number(top_p) or not 0 <= top_p <= 1):
        raise ValueError("top_p must be a finite number from 0 to 1.")
    if token_limit is not None and (type(token_limit) is not int or token_limit <= 0):
        raise ValueError("output-token limits must be positive integers.")



@dataclass
class AudioRequest:
    route: str
    audio: AudioPlan | list[AudioPlan]
    fields: dict[str, Any]
    response_text: bool = False
    stream_format: str | None = None
    capability: str | None = None

def prepare_transcribe(audio: AudioInput, *, sample_rate=None, model=None, language=None,
                       diarize=False, response_format=None, stream=False, prompt=None,
                       timestamp_granularities=None, word_timestamp_enabled=None, candidates=None,
                       semantic_sentence_enabled=None, min_chars=None, max_chars=None,
                       start_margin=None, end_margin=None, max_bytes=MAX_MEMORY_AUDIO_BYTES) -> AudioRequest:
    _sentence_options(semantic_sentence_enabled=semantic_sentence_enabled,
                      min_chars=min_chars, max_chars=max_chars,
                      start_margin=start_margin, end_margin=end_margin)
    if semantic_sentence_enabled is False and any(value is not None for value in (min_chars, max_chars, start_margin, end_margin)):
        raise ValueError("Sentence length/margin options conflict with semantic_sentence_enabled=False.")
    for name, value in (("stream", stream), ("diarize", diarize), ("word_timestamp_enabled", word_timestamp_enabled)):
        if value is not None and type(value) is not bool:
            raise ValueError(f"{name} must be a boolean.")
    if response_format is None:
        response_format = "diarized_json" if diarize else ("json" if stream else "verbose_json")
    if response_format not in ("json", "verbose_json", "diarized_json", "text"):
        raise ValueError("response_format must be json, verbose_json, diarized_json or text.")
    if diarize and response_format != "diarized_json":
        raise ValueError("diarize requires response_format='diarized_json'.")
    if timestamp_granularities is not None:
        timestamp_granularities = _materialize(timestamp_granularities, "timestamp_granularities", limit=9)
        if len(timestamp_granularities) > 8 or any(value not in ("word", "segment") for value in timestamp_granularities):
            raise ValueError("timestamp_granularities accepts only 'word' and 'segment' (at most 8 entries).")
    if stream and timestamp_granularities:
        raise ValueError("stream=True cannot be combined with timestamp_granularities; omit granularities or disable streaming.")
    if timestamp_granularities and response_format not in ("verbose_json", "diarized_json"):
        raise ValueError("timestamp_granularities requires response_format='verbose_json' or 'diarized_json'.")
    if stream and response_format != "json":
        raise ValueError("stream=True requires response_format='json' and diarize=False.")
    if candidates is not None:
        if type(candidates) is not int or not 0 <= candidates <= 8:
            raise ValueError("candidates must be an integer from 0 to 8; 0 and 1 disable alternatives.")
        if candidates >= 2 and (response_format != "verbose_json" or "word" in (timestamp_granularities or ()) or word_timestamp_enabled is True):
            raise ValueError("candidates >= 2 requires verbose_json without word timestamps (granularity or word_timestamp_enabled=True).")
    if word_timestamp_enabled is False and "word" in (timestamp_granularities or ()):
        raise ValueError("word_timestamp_enabled=False conflicts with timestamp_granularities=['word'].")
    if word_timestamp_enabled is True and response_format not in ("verbose_json", "diarized_json"):
        raise ValueError("word_timestamp_enabled=True requires response_format='verbose_json' or 'diarized_json'.")
    prepared_audio = prepare_audio(audio, sample_rate, max_bytes=max_bytes)
    return AudioRequest("audio/transcriptions", prepared_audio, {
        "model": model, "language": language, "response_format": response_format,
        "stream": True if stream else None, "prompt": prompt,
        "timestamp_granularities[]": timestamp_granularities,
        "word_timestamp_enabled": word_timestamp_enabled, "candidates": candidates,
        "semantic_sentence_enabled": semantic_sentence_enabled,
        "min_chars": min_chars, "max_chars": max_chars,
        "start_margin": start_margin, "end_margin": end_margin,
    }, response_text=response_format == "text", stream_format="sse" if stream else None)

def prepare_align(audio: AudioInput, *, sample_rate=None, text=None, text_file=None,
                  text_format=None, model=None, language=None, search_effort="standard", progress=False,
                  threshold=None, start=None, end=None, protected_terms=None, text_normalization=None,
                  audio_track=None, audio_channel=None, semantic_sentence_enabled=None,
                  min_chars=None, max_chars=None, start_margin=None, end_margin=None,
                  max_bytes=MAX_MEMORY_AUDIO_BYTES) -> AudioRequest:
    if type(progress) is not bool:
        raise ValueError("progress must be a boolean.")
    _sentence_options(threshold=threshold)
    if search_effort not in ("standard", "extended", "auto", ""):
        raise ValueError("search_effort must be standard, extended or auto (empty string means standard).")
    if (start is None) != (end is None):
        raise ValueError("start and end must be supplied together.")
    if start is not None and (not _finite_number(start) or not _finite_number(end) or start < 0 or end is None or end <= start):
        raise ValueError("start and end must be finite seconds with 0 <= start < end.")
    if audio_track is not None and (type(audio_track) is not int or audio_track < 0):
        raise ValueError("audio_track must be a non-negative, zero-based integer.")
    if audio_channel is not None and audio_channel != "mix":
        numeric_string = isinstance(audio_channel, str) and re.fullmatch(r"\+?[0-9]+", audio_channel) is not None
        if not numeric_string and not (type(audio_channel) is int and audio_channel >= 0):
            raise ValueError("audio_channel must be 'mix', a non-negative integer, or its numeric string (e.g. '1').")
    if protected_terms is not None:
        protected_terms = _materialize(protected_terms, "protected_terms")
        if any(not isinstance(term, str) for term in protected_terms):
            raise ValueError("protected_terms must be a sequence of strings, e.g. ['EdgeSpeak'].")
    _sentence_options(semantic_sentence_enabled=semantic_sentence_enabled,
                      min_chars=min_chars, max_chars=max_chars,
                      start_margin=start_margin, end_margin=end_margin)
    if semantic_sentence_enabled is False and any(value is not None for value in (min_chars, max_chars, start_margin, end_margin)):
        raise ValueError("Sentence length/margin options conflict with semantic_sentence_enabled=False.")
    prepared_audio = prepare_audio(audio, sample_rate, audio_track=audio_track, audio_channel=audio_channel, max_bytes=max_bytes)
    text, parsed_format = reference_input(text, text_file, text_format)
    return AudioRequest("audio/alignments", prepared_audio, {
        "text": text, "text_format": parsed_format, "model": model, "language": language, "search_effort": search_effort,
        "threshold": threshold,
        "start": start, "end": end, "protected_terms[]": protected_terms,
        "text_normalization": dict(text_normalization) if text_normalization is not None else None,
        "audio_track": audio_track, "audio_channel": audio_channel,
        "semantic_sentence_enabled": semantic_sentence_enabled,
        "min_chars": min_chars, "max_chars": max_chars,
        "start_margin": start_margin, "end_margin": end_margin,
    }, stream_format="ndjson" if progress else None,
       capability="alignment_reference_formats" if parsed_format not in (None, "txt") else None)

def prepare_diff_align(audio: AudioInput, *, sample_rate=None, reference_segments,
                       transcript_segments, model=None, language=None, offset=0.0,
                       max_bytes=MAX_MEMORY_AUDIO_BYTES) -> AudioRequest:
    if type(offset) not in (int, float) or not math.isfinite(offset) or offset < 0:
        raise ValueError("offset must be finite non-negative seconds.")
    fields = {}
    for name, segments in (("reference_segments", reference_segments),
                           ("transcript_segments", transcript_segments)):
        if not isinstance(segments, Sequence) or isinstance(segments, (str, bytes)) or not segments:
            raise ValueError(f"{name} must be a nonempty sequence of text/speaker mappings.")
        values = []
        for segment in segments:
            if not isinstance(segment, Mapping) or set(segment) - {"text", "speaker"}:
                raise ValueError(f"{name} accepts only text and optional speaker fields.")
            text = segment.get("text")
            speaker = segment.get("speaker")
            if not isinstance(text, str) or not text.strip() or "\0" in text:
                raise ValueError(f"{name} requires nonempty text without NUL.")
            if speaker is not None and (not isinstance(speaker, str) or not speaker.strip() or "\0" in speaker):
                raise ValueError(f"{name} speaker must be a nonempty string or None.")
            values.append(dict(segment))
        fields[name] = values
    return AudioRequest("audio/diff-alignments", prepare_audio(audio, sample_rate, max_bytes=max_bytes),
                       {**fields, "model": model, "language": language, "offset": offset}, capability="diff_alignment")


def prepare_segment(text=None, *, segments=None, threshold=None, paragraph_threshold=None,
                    min_chars=None, max_chars=None, start_margin=None, end_margin=None, options=None):
    _sentence_options(threshold=threshold, paragraph_threshold=paragraph_threshold,
                      min_chars=min_chars, max_chars=max_chars,
                      start_margin=start_margin, end_margin=end_margin)
    if options is not None:
        if not isinstance(options, Mapping):
            raise ValueError("options must be a mapping of segmentation settings.")
        _sentence_options(**{key: value for key, value in options.items()
                             if key in ("threshold", "paragraph_threshold", "min_chars", "max_chars", "start_margin", "end_margin")})
    if (text is None) == (segments is None):
        raise ValueError("Provide exactly one of text or segments.")
    if segments is not None:
        segments = _materialize(segments, "segments")
        if any(not isinstance(segment, Mapping) for segment in segments):
            raise ValueError("segments must be a sequence of mappings, e.g. transcript['segments'].")
        segments = [dict(segment) for segment in segments]
    effective = dict(options or {})
    effective.update({key: value for key, value in {
        "paragraph_threshold": paragraph_threshold, "min_chars": min_chars,
        "max_chars": max_chars, "start_margin": start_margin,
        "end_margin": end_margin}.items() if value is not None})
    paragraph = effective.get("paragraph_threshold")
    if paragraph is not None and threshold is not None and paragraph < threshold:
        raise ValueError("paragraph_threshold must be greater than or equal to threshold.")
    if paragraph is not None and (segments is not None or any(effective.get(key) is not None for key in ("min_chars", "max_chars", "start_margin", "end_margin"))):
        raise ValueError("paragraph_threshold requires plain text without length limits or margins.")
    body = {"text": text, "segments": list(segments) if segments is not None else None,
            "threshold": threshold, "paragraph_threshold": paragraph_threshold,
            "min_chars": min_chars, "max_chars": max_chars,
            "start_margin": start_margin, "end_margin": end_margin,
            "options": dict(options) if options is not None else None}
    return _json_body(body)

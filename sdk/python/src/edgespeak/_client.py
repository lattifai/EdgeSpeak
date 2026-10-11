"""Thin client for the existing EdgeSpeak public gateway protocol."""
from __future__ import annotations

import os
import json
from contextlib import ExitStack
import re
from pathlib import Path
import weakref
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

import httpx

from ._process import start_process, stop_process
from ._reference import reference_input
from ._errors import EdgeSpeakError, check_response
from ._streaming import EventStream


def _dispose(http, process, owner_pid):
    if os.getpid() != owner_pid:
        return
    try:
        http.close()
    finally:
        if process is not None:
            stop_process(process, owner_pid)


class EdgeSpeak:
    """Own a CLI service, or attach to an explicitly supplied gateway.

    Use ``with EdgeSpeak() as client`` or call ``close()``. Attached services
    are never stopped. ``gateway_key`` is a local gateway token, not an account key.
    """

    def __init__(self, *, base_url: str | None = None, gateway_key: str | None = None,
                 api_key: str | None = None,
                 timeout: float = 600, startup_timeout: float = 30):
        if api_key is None and base_url is None:
            api_key = os.environ.get("EDGESPEAK_API_KEY")
        if timeout <= 0 or startup_timeout <= 0:
            raise ValueError("Timeouts must be positive.")
        if api_key is not None and (not isinstance(api_key, str) or not re.fullmatch(r"esak_[A-Za-z0-9_-]{43}", api_key)):
            raise ValueError("api_key must be an account API key starting with esak_.")
        if api_key is not None and base_url is not None:
            raise ValueError("api_key is only used when the SDK starts its own CLI service.")
        self._owner_pid = os.getpid()
        self._closed = False
        self._streams = weakref.WeakSet()
        self._attached = base_url is not None
        process = None
        if base_url is None:
            if gateway_key is not None:
                raise ValueError("gateway_key is only used with an explicit base_url.")
            process, _, base_url, gateway_key = start_process(startup_timeout, api_key)
        else:
            parsed = urlsplit(base_url)
            if (parsed.scheme not in ("http", "https") or not parsed.hostname
                    or parsed.username or parsed.password or parsed.query or parsed.fragment
                    or parsed.path.rstrip("/") != "/v1"):
                raise ValueError("base_url must be an HTTP(S) gateway URL ending in /v1.")
            if parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
                raise ValueError("Remote gateways require HTTPS.")
        try:
            http = httpx.Client(
                base_url=base_url.rstrip("/") + "/", timeout=timeout,
                trust_env=False, follow_redirects=False,
                headers={"User-Agent": "edgespeak-python/0.1.0a1", **(
                    {"Authorization": f"Bearer {gateway_key}"} if gateway_key else {})},
            )
        except BaseException:
            if process is not None:
                stop_process(process, self._owner_pid)
            raise
        self._http = http
        self._finalizer = weakref.finalize(self, _dispose, http, process, self._owner_pid)

    def __enter__(self):
        self._check_open()
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        if os.getpid() != self._owner_pid:
            raise RuntimeError("Create a new EdgeSpeak client after fork.")
        if not self._closed:
            self._closed = True
            # ExitStack attempts every cleanup even when one transport fails.
            with ExitStack() as cleanup:
                cleanup.callback(self._finalizer)
                for stream in list(self._streams):
                    cleanup.callback(stream._close_from_client)

    def _check_open(self):
        if self._closed:
            raise RuntimeError("EdgeSpeak client is closed.")
        if os.getpid() != self._owner_pid:
            raise RuntimeError("Create a new EdgeSpeak client after fork.")

    def _request(self, method: str, path: str, *, response_text: bool = False, **kwargs) -> dict[str, Any] | str:
        self._check_open()
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.TimeoutException:
            raise EdgeSpeakError("request_timeout") from None
        except httpx.HTTPError:
            raise EdgeSpeakError("connection_failed") from None
        check_response(response)
        if response_text:
            return response.text
        try:
            result = response.json()
        except ValueError:
            raise EdgeSpeakError("invalid_response") from None
        if not isinstance(result, dict):
            raise EdgeSpeakError("invalid_response")
        return result

    def _request_stream(self, route, data, files, resources, wire_format):
        try:
            request = self._http.build_request("POST", route, data=data, files=files,
                headers={"progress": "1"} if wire_format == "ndjson" else None)
            response = self._http.send(request, stream=True)
            try:
                if not response.is_success:
                    response.read()
                    check_response(response)
                stream = EventStream(self, response, resources, wire_format)
                self._streams.add(stream)
                return stream
            except BaseException:
                response.close()
                raise
        except BaseException as error:
            resources.close()
            if isinstance(error, httpx.TimeoutException):
                raise EdgeSpeakError("request_timeout") from None
            if isinstance(error, httpx.HTTPError):
                raise EdgeSpeakError("connection_failed") from None
            raise

    def _audio(self, route: str, audio: str | os.PathLike[str] | Sequence[str | os.PathLike[str]],
               fields: dict, *, response_text: bool = False, stream_format: str | None = None) -> dict[str, Any] | str | EventStream:
        self._check_open()
        paths = [audio] if isinstance(audio, (str, os.PathLike)) else list(audio)
        if not paths:
            raise ValueError("At least one audio file is required.")
        data = {}
        for key, value in fields.items():
            if value is None:
                continue
            if key.endswith("[]"):
                if isinstance(value, str):
                    raise ValueError(f"{key} must be a sequence of strings.")
                data[key] = list(value)
            elif isinstance(value, (dict, list, tuple, bool)):
                data[key] = json.dumps(value, ensure_ascii=False, allow_nan=False)
            else:
                data[key] = str(value)
        with ExitStack() as stack:
            files = []
            for audio_path in paths:
                path = Path(audio_path)
                stream = stack.enter_context(path.open("rb"))
                files.append(("file", (path.name, stream, "application/octet-stream")))
            if stream_format:
                return self._request_stream(route, data, files, stack.pop_all(), stream_format)
            return self._request("POST", route, response_text=response_text, data=data, files=files)

    def transcribe(self, audio: str | os.PathLike[str], *, model: str | None = None,
                   language: str | None = None, diarize: bool = False,
                   response_format: str | None = None, stream: bool = False, prompt: str | None = None,
                   timestamp_granularities: Sequence[str] | None = None,
                   word_timestamp_enabled: bool | None = None, candidates: int | None = None,
                   semantic_sentence_enabled: bool | None = None,
                   min_chars: int | None = None, max_chars: int | None = None,
                   start_margin: float | None = None, end_margin: float | None = None) -> dict[str, Any] | str | EventStream:
        """Transcribe media, optionally including speaker labels and semantic sentences.

        Options use the HTTP API's names and semantics. Omitted options inherit
        runtime preferences; timestamps are in seconds. ``text`` output is a str.
        """
        if response_format is None:
            response_format = "diarized_json" if diarize else ("json" if stream else "verbose_json")
        if response_format not in ("json", "verbose_json", "diarized_json", "text"):
            raise ValueError("Invalid response_format.")
        if diarize and response_format != "diarized_json":
            raise ValueError("diarize requires response_format='diarized_json'.")
        return self._audio("audio/transcriptions", audio, {
            "model": model, "language": language, "response_format": response_format,
            "stream": True if stream else None, "prompt": prompt,
            "timestamp_granularities[]": timestamp_granularities,
            "word_timestamp_enabled": word_timestamp_enabled, "candidates": candidates,
            "semantic_sentence_enabled": semantic_sentence_enabled,
            "min_chars": min_chars, "max_chars": max_chars,
            "start_margin": start_margin, "end_margin": end_margin,
        }, response_text=response_format == "text", stream_format="sse" if stream else None)

    def align(self, audio: str | os.PathLike[str], *, text: str | Mapping[str, Any] | None = None,
              text_file: str | os.PathLike[str] | None = None, text_format: str | None = None,
              model: str | None = None,
              language: str | None = None, search_effort: str = "standard", progress: bool = False,
              threshold: float | None = None,
              start: float | None = None, end: float | None = None,
              protected_terms: Sequence[str] | None = None,
              text_normalization: Mapping[str, Any] | None = None,
              audio_track: int | None = None, audio_channel: str | int | None = None,
              semantic_sentence_enabled: bool | None = None,
              min_chars: int | None = None, max_chars: int | None = None,
              start_margin: float | None = None, end_margin: float | None = None) -> dict[str, Any] | EventStream:
        """Align reference text, preserving the HTTP API's normalization and timing options."""
        self._check_open()
        text, text_format = reference_input(text, text_file, text_format)
        if self._attached and text_format not in (None, "txt"):
            health = self._request("GET", "health")
            capabilities = health.get("capabilities")
            if not isinstance(capabilities, list) or "alignment_reference_formats" not in capabilities:
                raise EdgeSpeakError("unsupported_gateway_capability")
        if search_effort not in ("standard", "extended", "auto", ""):
            raise ValueError("Invalid search_effort.")
        if (start is None) != (end is None):
            raise ValueError("start and end must be supplied together.")
        return self._audio("audio/alignments", audio, {
            "text": text, "text_format": text_format, "model": model, "language": language, "search_effort": search_effort,
            "threshold": threshold,
            "start": start, "end": end, "protected_terms[]": protected_terms,
            "text_normalization": dict(text_normalization) if text_normalization is not None else None,
            "audio_track": audio_track, "audio_channel": audio_channel,
            "semantic_sentence_enabled": semantic_sentence_enabled,
            "min_chars": min_chars, "max_chars": max_chars,
            "start_margin": start_margin, "end_margin": end_margin,
        }, stream_format="ndjson" if progress else None)

    def segment(self, text: str | None = None, *, segments: Sequence[Mapping[str, Any]] | None = None,
                threshold: float | None = None, paragraph_threshold: float | None = None,
                min_chars: int | None = None, max_chars: int | None = None,
                start_margin: float | None = None, end_margin: float | None = None,
                options: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Split text into sentences/paragraphs, or resegment timed caption segments.

        Pass ``segments=transcript['segments']`` to retain timing and speakers.
        Paragraph mode accepts plain text only, as in the HTTP API.
        """
        if (text is None) == (segments is None):
            raise ValueError("Provide exactly one of text or segments.")
        body = {"text": text, "segments": list(segments) if segments is not None else None,
                "threshold": threshold, "paragraph_threshold": paragraph_threshold,
                "min_chars": min_chars, "max_chars": max_chars,
                "start_margin": start_margin, "end_margin": end_margin,
                "options": dict(options) if options is not None else None}
        return self._request("POST", "text/segmentations", json={k: v for k, v in body.items() if v is not None})

    def diarize(self, audio: str | os.PathLike[str], *, num_speakers: int | None = None) -> dict[str, Any]:
        """Find speaker turns without transcribing speech."""
        if num_speakers is not None and (type(num_speakers) is not int or not 1 <= num_speakers <= 32):
            raise ValueError("num_speakers must be an integer from 1 to 32.")
        return self._audio("speaker/diarizations", audio, {"num_speakers": num_speakers})

    def speaker_embedding(self, audio: str | os.PathLike[str] | Sequence[str | os.PathLike[str]], *,
                          model: str | None = None) -> dict[str, Any]:
        """Extract one or a batch of embeddings; the API retains input order."""
        return self._audio("speaker/embeddings", audio, {"model": model})

    def speaker_similarity(self, embedding_a: Sequence[float], embedding_b: Sequence[float], *,
                           model: str | None = None) -> dict[str, Any]:
        body = {"embedding_a": list(embedding_a), "embedding_b": list(embedding_b)}
        if model is not None:
            body["model"] = model
        return self._request("POST", "speaker/similarity", json=body)

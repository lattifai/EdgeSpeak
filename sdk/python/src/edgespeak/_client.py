"""Thin client for the existing EdgeSpeak public gateway protocol."""
from __future__ import annotations

import os
import re
from pathlib import Path
import weakref
from typing import Any, Sequence
from urllib.parse import urlsplit

import httpx

from ._process import start_process, stop_process


class EdgeSpeakError(RuntimeError):
    """A gateway failure, with a stable code and optional HTTP status."""

    def __init__(self, code: str, status_code: int | None = None):
        self.code = code
        self.status_code = status_code
        super().__init__(f"EdgeSpeak request failed: {code}" + (f" (HTTP {status_code})" if status_code else ""))


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

    def __init__(self, *, cli_path: str | os.PathLike[str] = "edgespeak-cli",
                 base_url: str | None = None, gateway_key: str | None = None,
                 api_key: str | None = None,
                 timeout: float = 600, startup_timeout: float = 30):
        if timeout <= 0 or startup_timeout <= 0:
            raise ValueError("Timeouts must be positive.")
        if api_key is not None and (not isinstance(api_key, str) or not re.fullmatch(r"esak_[A-Za-z0-9_-]{43}", api_key)):
            raise ValueError("api_key must be an account API key starting with esak_.")
        if api_key is not None and base_url is not None:
            raise ValueError("api_key is only used when the SDK starts its own CLI service.")
        self._owner_pid = os.getpid()
        self._closed = False
        process = None
        if base_url is None:
            if gateway_key is not None:
                raise ValueError("gateway_key is only used with an explicit base_url.")
            process, _, base_url, gateway_key = start_process(cli_path, startup_timeout, api_key)
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
            self._finalizer()

    def _check_open(self):
        if self._closed:
            raise RuntimeError("EdgeSpeak client is closed.")
        if os.getpid() != self._owner_pid:
            raise RuntimeError("Create a new EdgeSpeak client after fork.")

    def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        self._check_open()
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.TimeoutException:
            raise EdgeSpeakError("request_timeout") from None
        except httpx.HTTPError:
            raise EdgeSpeakError("connection_failed") from None
        if not response.is_success:
            # Do not echo server text, headers, URLs or request content (may contain secrets).
            code = "http_error"
            try:
                candidate = response.json().get("error", {})
                candidate = candidate.get("code") if isinstance(candidate, dict) else None
                if isinstance(candidate, str) and len(candidate) <= 100 and all(c.isalnum() or c in "_.-" for c in candidate):
                    code = candidate
            except (ValueError, AttributeError):
                pass
            raise EdgeSpeakError(code, response.status_code)
        try:
            result = response.json()
        except ValueError:
            raise EdgeSpeakError("invalid_response") from None
        if not isinstance(result, dict):
            raise EdgeSpeakError("invalid_response")
        return result

    def _audio(self, route: str, audio: str | os.PathLike[str], fields: dict) -> dict[str, Any]:
        self._check_open()
        path = Path(audio)
        with path.open("rb") as stream:
            return self._request("POST", route, data={k: str(v) for k, v in fields.items() if v is not None},
                                 files={"file": (path.name, stream, "application/octet-stream")})

    def transcribe(self, audio: str | os.PathLike[str], *, model: str | None = None,
                   language: str | None = None, diarize: bool = False) -> dict[str, Any]:
        """Transcribe local media; return the gateway JSON with timestamps in seconds."""
        return self._audio("audio/transcriptions", audio, {
            "model": model, "language": language,
            "response_format": "diarized_json" if diarize else "verbose_json",
        })

    def align(self, audio: str | os.PathLike[str], *, text: str, model: str | None = None,
              language: str | None = None, search_effort: str = "standard") -> dict[str, Any]:
        """Align verbatim reference text against local media."""
        if not text.strip():
            raise ValueError("text must not be empty.")
        if search_effort not in ("standard", "extended", "auto"):
            raise ValueError("Invalid search_effort.")
        return self._audio("audio/alignments", audio, {
            "text": text, "model": model, "language": language, "search_effort": search_effort,
        })

    def diarize(self, audio: str | os.PathLike[str], *, num_speakers: int | None = None) -> dict[str, Any]:
        """Find speaker turns without transcribing speech."""
        if num_speakers is not None and (type(num_speakers) is not int or not 1 <= num_speakers <= 32):
            raise ValueError("num_speakers must be an integer from 1 to 32.")
        return self._audio("speaker/diarizations", audio, {"num_speakers": num_speakers})

    def speaker_embedding(self, audio: str | os.PathLike[str], *, model: str | None = None) -> dict[str, Any]:
        return self._audio("speaker/embeddings", audio, {"model": model})

    def speaker_similarity(self, embedding_a: Sequence[float], embedding_b: Sequence[float], *,
                           model: str | None = None) -> dict[str, Any]:
        body = {"embedding_a": list(embedding_a), "embedding_b": list(embedding_b)}
        if model is not None:
            body["model"] = model
        return self._request("POST", "speaker/similarity", json=body)

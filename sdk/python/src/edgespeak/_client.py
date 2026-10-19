"""Thin client for the existing EdgeSpeak public gateway protocol."""
from __future__ import annotations

import os
from numbers import Real
import json
from contextlib import ExitStack, closing
import weakref
from typing import BinaryIO, Any, Callable, Iterable, Literal, Mapping, Sequence, cast, overload
from urllib.parse import urlsplit

import httpx

from ._input_audio import AudioInput, AudioPlan, prepare_audio, prepare_batch
from ._audio_budget import AudioBudget, DEFAULT_IN_FLIGHT_AUDIO_BYTES, positive_limit, UploadStream
from ._input_audio import MAX_MEMORY_AUDIO_BYTES
from ._responses import Transcription, Alignment, Segmentation, Diarization, Embeddings, Similarity, Usage, Models
from ._concurrency import validate_concurrency, execution_request
from ._version import __version__
from ._process import start_process, stop_process
from ._requests import AudioRequest, prepare_segment, prepare_transcribe, prepare_align, prepare_diff_align, _materialize, _finite_number, _json_body, _message_list, _model_id, _generation_scalars
from ._device import normalize_device
from ._text import validate_normalization
from ._errors import API_KEYS_URL, EdgeSpeakError, check_response, protocol_error, valid_account_key
from ._streaming import EventStream
from ._audio import validate_options as validate_audio_options, validate_response as validate_audio_response
from ._types import NormalizationMode, NormalizationClass, Device, AudioResponseFormat, PcmFormat, AudioChannel, ReferenceFormat, SearchEffort, TimestampGranularity, TranscriptionFormat


def _dispose(http, process, owner_pid):
    if os.getpid() != owner_pid:
        return
    try:
        http.close()
    finally:
        if process is not None:
            stop_process(process, owner_pid)


class _SyncUpload(httpx.SyncByteStream):
    def __init__(self, stream, resources):
        self._upload = UploadStream(stream, resources)

    def __iter__(self):
        return self._upload.chunks()

    def close(self):
        self._upload.resources.close()


def validate_upsample_input(plan: AudioPlan) -> None:
    if plan.size > 32 * 1024 * 1024:
        raise ValueError("audio must not exceed 32 MiB; SDK memory limits cannot override this endpoint limit.")
    if plan.sample_rate is not None and len(cast(Any, plan.source)) / plan.sample_rate > 120:
        raise ValueError("upsample audio must not exceed 120 seconds.")


class EdgeSpeak:
    """Own a CLI service, or attach to an explicitly supplied gateway.

    Use ``with EdgeSpeak() as client`` or call ``close()``. Attached services
    are never stopped. ``gateway_key`` is a local gateway token, not an account key.

    base_url=None discovers/installs a compatible CLI and starts an owned service.
    An explicit URL must end in /v1; non-loopback gateways require HTTPS.
    api_key is an account API KEY for owned mode only; None reads EDGESPEAK_API_KEY.
    Create one at https://edgespeak.com/account/api-keys (sign in first).
    An API KEY is different from a product activation key or gateway token.
    Attached mode uses gateway_key and does not read the account-key environment.
    device selects the owned runtime: cpu, cuda, cuda:N, metal (mps), or auto.
    None/auto preserve the CLI default/environment policy. Metal requires macOS;
    CUDA requires Linux/Windows with a compatible runtime and GPU. Explicit
    device is rejected with base_url, even auto; gateways control their own devices.
    timeout is a positive finite per-I/O timeout in seconds (default 600), not a
    whole-job deadline. startup_timeout is readiness seconds (default 30); CLI
    installation has its own timeout. RuntimeStartError reports startup failure.
    transport and limits customize HTTPX networking; the SDK owns and closes the
    supplied transport. event_hooks accepts synchronous HTTPX request/response
    hooks, including for streams. Hooks see credentials and audio: do not log
    secrets or consume streaming bodies. No requests are automatically retried.
    max_memory_audio_bytes limits each bytes/array encoded payload (default 256 MiB).
    max_in_flight_audio_bytes limits admitted payloads per client (default 512 MiB);
    concurrent callers wait until uploads finish. None disables the corresponding
    SDK cap, not gateway limits. Paths and response/model memory are not counted.
    audio_spool_threshold_bytes opts arrays into private temporary files above
    that size; None (default) keeps encoding in memory. This is not an RSS cap.
    max_concurrency=None preserves defaults (async HTTP 4, sync HTTPX pool).
    Explicit 1..64 caps HTTP work and the owned serve batch execution ceiling;
    attached mode only caps this client. Model/route capacity can be lower.
    GET and model lifecycle requests bypass client slots. Streams hold slots
    until closed. Hooks making nested work requests need a spare slot.
    """

    def __init__(self, *, base_url: str | None = None, gateway_key: str | None = None,
                 api_key: str | None = None, device: Device | None = None,
                 timeout: float = 600, startup_timeout: float = 30,
                 transport: httpx.BaseTransport | None = None,
                 limits: httpx.Limits | None = None,
                 event_hooks: Mapping[str, list[Callable[..., None]]] | None = None,
                 max_memory_audio_bytes: int | None = MAX_MEMORY_AUDIO_BYTES,
                 max_in_flight_audio_bytes: int | None = DEFAULT_IN_FLIGHT_AUDIO_BYTES,
                 audio_spool_threshold_bytes: int | None = None,
                 max_concurrency: int | None = None):
        validate_concurrency(max_concurrency)
        self._request_budget = AudioBudget(max_concurrency)
        positive_limit(max_memory_audio_bytes, "max_memory_audio_bytes")
        positive_limit(audio_spool_threshold_bytes, "audio_spool_threshold_bytes")
        self._audio_budget = AudioBudget(max_in_flight_audio_bytes)
        self._max_memory_audio_bytes = max_memory_audio_bytes
        self._audio_spool_threshold_bytes = audio_spool_threshold_bytes
        if device is not None and base_url is not None:
            raise ValueError("device cannot be used with base_url: the existing gateway controls its compute devices. Omit device or let the SDK start its own service.")
        device = normalize_device(device)
        if api_key is None and base_url is None:
            api_key = os.environ.get("EDGESPEAK_API_KEY")
        if not all(_finite_number(value) and value > 0 for value in (timeout, startup_timeout)):
            raise ValueError("timeout and startup_timeout must be finite positive seconds.")
        if api_key is not None and not valid_account_key(api_key):
            raise ValueError(f"api_key must be an account API KEY starting with esak_. Create one at {API_KEYS_URL}; set EDGESPEAK_API_KEY or pass api_key.")
        if api_key is not None and base_url is not None:
            raise ValueError("api_key is only used when the SDK starts its own CLI service.")
        self._owner_pid = os.getpid()
        self._closed = False
        self._streams: weakref.WeakSet[EventStream] = weakref.WeakSet()
        self._attached = base_url is not None
        process = None
        if base_url is None:
            if gateway_key is not None:
                raise ValueError("gateway_key is only used with an explicit base_url.")
            process, _, base_url, gateway_key = start_process(startup_timeout, api_key, device, max_concurrency) if max_concurrency is not None else start_process(startup_timeout, api_key, device)
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
                transport=transport, limits=limits if limits is not None else httpx.Limits(),
                event_hooks=dict(event_hooks) if event_hooks is not None else None,
                headers={"User-Agent": f"edgespeak-python/{__version__}", **(
                    {"Authorization": f"Bearer {gateway_key}"} if gateway_key else {})},
            )
        except BaseException:
            if process is not None:
                stop_process(process, self._owner_pid)
            raise
        self._http = http
        self._finalizer = weakref.finalize(self, _dispose, http, process, self._owner_pid)

    def __enter__(self) -> EdgeSpeak:
        self._check_open()
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def close(self) -> None:
        """Close open streams and stop only the CLI owned by this client; repeatable."""
        if os.getpid() != self._owner_pid:
            raise RuntimeError("Create a new EdgeSpeak client after fork.")
        if not self._closed:
            self._closed = True
            self._audio_budget.close()
            self._request_budget.close()
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

    @overload
    def _request(self, method: str, path: str, *, response_text: Literal[False] = False, gateway_api: bool = False, missing_route: bool = False, **kwargs) -> dict[str, Any]: ...

    @overload
    def _request(self, method: str, path: str, *, response_text: Literal[True], gateway_api: bool = False, missing_route: bool = False, **kwargs) -> str: ...

    @overload
    def _request(self, method: str, path: str, *, response_text: bool = False, gateway_api: bool = False, missing_route: bool = False, **kwargs) -> dict[str, Any] | str: ...

    def _request(self, method: str, path: str, *, response_text: bool = False, gateway_api: bool = False, missing_route: bool = False, **kwargs) -> dict[str, Any] | str:
        self._check_open()
        request_lease = self._request_budget.acquire(1) if execution_request(method, path) else None
        try:
            upload_resources = kwargs.pop("_upload_resources", None)
            if upload_resources is None:
                response = self._http.request(method, path, **kwargs)
            else:
                request = self._http.build_request(method, path, **kwargs)
                request.stream = _SyncUpload(request.stream, upload_resources)
                response = self._http.send(request)
        except httpx.TimeoutException:
            raise EdgeSpeakError("request_timeout") from None
        except httpx.HTTPError:
            raise EdgeSpeakError("connection_failed") from None
        finally:
            if request_lease is not None:
                request_lease.close()
        check_response(response, gateway_api=gateway_api, missing_route=missing_route)
        if response_text:
            return response.text
        try:
            result = response.json()
        except ValueError:
            raise EdgeSpeakError("invalid_response") from None
        if not isinstance(result, dict):
            raise EdgeSpeakError("invalid_response")
        return result

    def text_normalizations(self, text: str, *, language: str,
                            mode: NormalizationMode = "tn", model: str | None = None,
                            top_k: int | None = None,
                            classes: Sequence[NormalizationClass] | None = None) -> dict[str, Any]:
        """POST /v1/text/normalizations: written→spoken (tn), or spoken→written (itn).

        text: non-empty, <=256 KiB UTF-8. language is required; use und for
        context-based routing. top_k: 1..16; None inherits the gateway default.
        classes: a non-empty allow-list such as ["money", "date"].
        Returns original text and alternatives containing converted text/spans.
        Span offsets are UTF-8 bytes in the original text; use slice_utf8().
        Uses the gateway account's text allowance, not audio-duration allowance.
        """
        self._check_open()
        values = validate_normalization(text, language, mode, top_k, classes)
        if model is not None:
            _model_id(model)
        body = {"text": text, "language": language, "mode": mode,
                "model": model, "top_k": top_k, "classes": values}
        return self._request("POST", "text/normalizations", gateway_api=True, json={k: v for k, v in body.items() if v is not None})

    def health(self) -> dict[str, Any]:
        """GET /v1/health. Read runtime status/capabilities; no inference or usage."""
        return self._request("GET", "health", gateway_api=True)

    def usage(self, *, refresh: bool = False) -> Usage:
        """GET /v1/usage. Account billing-period totals; null remaining can mean unlimited.

        refresh=True asks the gateway to refresh its authorization first. Refresh
        failure may return the local summary. This query consumes no usage.
        """
        if type(refresh) is not bool:
            raise ValueError("refresh must be a boolean.")
        return cast(Usage, self._request("GET", "usage", gateway_api=True, params={"refresh": str(refresh).lower()}))

    def models(self) -> Models:
        """GET /v1/models. Inspect IDs/capabilities; does not load/download models."""
        return cast(Models, self._request("GET", "models", gateway_api=True))

    def models_running(self) -> dict[str, Any]:
        """GET /v1/models/running. Loaded model and runtime queue state."""
        return self._request("GET", "models/running", gateway_api=True)

    def models_downloads(self) -> dict[str, Any]:
        """GET /v1/models/downloads. Observe downloads without starting one."""
        return self._request("GET", "models/downloads", gateway_api=True)

    def _model_operation(self, path: str, model: str) -> dict[str, Any]:
        _model_id(model)
        return self._request("POST", path, gateway_api=True, json={"model": model})

    def models_load(self, model: str) -> dict[str, Any]:
        """POST /v1/models/load. Explicitly load a supported installed model."""
        return self._model_operation("models/load", model)

    def models_unload(self, model: str) -> dict[str, Any]:
        """POST /v1/models/unload. Explicitly unload the selected runtime model."""
        return self._model_operation("models/unload", model)

    def models_download(self, model: str) -> dict[str, Any]:
        """POST /v1/models/download. Start a download; returns job JSON (HTTP 202).

        Does not wait for completion; poll models_downloads(). This can download
        large files. Built-in normalization rules reject lifecycle operations.
        """
        return self._model_operation("models/download", model)

    def models_download_cancel(self, model: str) -> dict[str, Any]:
        """POST /v1/models/download/cancel. Request cancellation; poll for completion."""
        return self._model_operation("models/download/cancel", model)

    @overload
    def _json_result(self, path: str, body: dict[str, Any], stream: Literal[False], protocol: str, headers: Mapping[str, str] | None = None) -> dict[str, Any]: ...

    @overload
    def _json_result(self, path: str, body: dict[str, Any], stream: Literal[True], protocol: str, headers: Mapping[str, str] | None = None) -> EventStream: ...

    @overload
    def _json_result(self, path: str, body: dict[str, Any], stream: bool, protocol: str, headers: Mapping[str, str] | None = None) -> dict[str, Any] | EventStream: ...

    def _json_result(self, path: str, body: dict[str, Any], stream: bool, protocol: str, headers: Mapping[str, str] | None = None) -> dict[str, Any] | EventStream:
        self._check_open()
        if type(stream) is not bool:
            raise ValueError("stream must be a boolean.")
        if not stream:
            result = self._request("POST", path, gateway_api=True, json=body, headers=headers)
            if protocol == "responses" and result.get("status") == "failed":
                raise protocol_error(result)
            if protocol == "responses" and result.get("status") == "incomplete":
                raise EdgeSpeakError("incomplete_response")
            return result
        resources = ExitStack()
        try:
            resources.callback(self._request_budget.acquire(1).close)
            request = self._http.build_request("POST", path, json=body, headers={"Accept": "text/event-stream", **(headers or {})})
            response = self._http.send(request, stream=True)
            try:
                if not response.is_success:
                    response.read()
                    check_response(response, gateway_api=True)
                if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "text/event-stream":
                    raise EdgeSpeakError("invalid_response")
                events = EventStream(self, response, resources, protocol)
                self._streams.add(events)
                return events
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

    @overload
    def chat_completions(self, messages: Iterable[Mapping[str, Any]], *, model: str,
                         stream: Literal[False] = False, temperature: float | None = None, top_p: float | None = None, max_tokens: int | None = None, options: Mapping[str, Any] | None = None) -> dict[str, Any]: ...

    @overload
    def chat_completions(self, messages: Iterable[Mapping[str, Any]], *, model: str,
                         stream: Literal[True], temperature: float | None = None, top_p: float | None = None, max_tokens: int | None = None, options: Mapping[str, Any] | None = None) -> EventStream: ...

    @overload
    def chat_completions(self, messages: Iterable[Mapping[str, Any]], *, model: str,
                         stream: bool = False, temperature: float | None = None, top_p: float | None = None, max_tokens: int | None = None, options: Mapping[str, Any] | None = None) -> dict[str, Any] | EventStream: ...

    def chat_completions(self, messages: Iterable[Mapping[str, Any]], *, model: str,
                         stream: bool = False, temperature: float | None = None, top_p: float | None = None, max_tokens: int | None = None, options: Mapping[str, Any] | None = None) -> dict[str, Any] | EventStream:
        """POST /v1/chat/completions. Text generation, optionally with image inputs.

        messages follows the selected model's OpenAI content schema. stream=True
        yields EventStream chunks until [DONE], including trailing usage chunks.
        options forwards protocol extensions (tools, response_format, etc.) but
        cannot override named parameters. Model capabilities and limits are
        gateway-defined; this method does not generate images.
        """
        _model_id(model)
        _generation_scalars(temperature, top_p, max_tokens)
        body = _json_body({"model": model, "messages": _message_list(messages), "stream": stream,
                          "temperature": temperature, "top_p": top_p, "max_tokens": max_tokens}, options)
        return self._json_result("chat/completions", body, stream, "chat")

    @overload
    def responses(self, input: str | Sequence[Mapping[str, Any]], *, model: str,
                         stream: Literal[False] = False, instructions: str | None = None, max_output_tokens: int | None = None, temperature: float | None = None, top_p: float | None = None, options: Mapping[str, Any] | None = None) -> dict[str, Any]: ...

    @overload
    def responses(self, input: str | Sequence[Mapping[str, Any]], *, model: str,
                         stream: Literal[True], instructions: str | None = None, max_output_tokens: int | None = None, temperature: float | None = None, top_p: float | None = None, options: Mapping[str, Any] | None = None) -> EventStream: ...

    @overload
    def responses(self, input: str | Sequence[Mapping[str, Any]], *, model: str,
                         stream: bool = False, instructions: str | None = None, max_output_tokens: int | None = None, temperature: float | None = None, top_p: float | None = None, options: Mapping[str, Any] | None = None) -> dict[str, Any] | EventStream: ...

    def responses(self, input: str | Sequence[Mapping[str, Any]], *, model: str,
                         stream: bool = False, instructions: str | None = None, max_output_tokens: int | None = None, temperature: float | None = None, top_p: float | None = None, options: Mapping[str, Any] | None = None) -> dict[str, Any] | EventStream:
        """POST /v1/responses. Text generation using string or structured input.

        Structured input may include images where the model supports them.
        stream=True yields EventStream through response.completed. Failed or
        incomplete responses raise EdgeSpeakError. options forwards protocol
        extensions (tools, reasoning, translation, etc.) without overriding named
        parameters. Output is text/protocol JSON, never image generation.
        """
        _model_id(model)
        _generation_scalars(temperature, top_p, max_output_tokens)
        value = input if isinstance(input, str) else _message_list(input)
        body = _json_body({"model": model, "input": value, "stream": stream, "instructions": instructions,
                          "max_output_tokens": max_output_tokens, "temperature": temperature, "top_p": top_p}, options)
        return self._json_result("responses", body, stream, "responses")

    @overload
    def messages(self, messages: Iterable[Mapping[str, Any]], *, model: str, max_tokens: int,
                         stream: Literal[False] = False, anthropic_version: str = "2023-06-01", anthropic_beta: str | None = None, system: str | Sequence[Mapping[str, Any]] | None = None, temperature: float | None = None, top_p: float | None = None, options: Mapping[str, Any] | None = None) -> dict[str, Any]: ...

    @overload
    def messages(self, messages: Iterable[Mapping[str, Any]], *, model: str, max_tokens: int,
                         stream: Literal[True], anthropic_version: str = "2023-06-01", anthropic_beta: str | None = None, system: str | Sequence[Mapping[str, Any]] | None = None, temperature: float | None = None, top_p: float | None = None, options: Mapping[str, Any] | None = None) -> EventStream: ...

    @overload
    def messages(self, messages: Iterable[Mapping[str, Any]], *, model: str, max_tokens: int,
                         stream: bool = False, anthropic_version: str = "2023-06-01", anthropic_beta: str | None = None, system: str | Sequence[Mapping[str, Any]] | None = None, temperature: float | None = None, top_p: float | None = None, options: Mapping[str, Any] | None = None) -> dict[str, Any] | EventStream: ...

    def messages(self, messages: Iterable[Mapping[str, Any]], *, model: str, max_tokens: int,
                         stream: bool = False, anthropic_version: str = "2023-06-01", anthropic_beta: str | None = None, system: str | Sequence[Mapping[str, Any]] | None = None, temperature: float | None = None, top_p: float | None = None, options: Mapping[str, Any] | None = None) -> dict[str, Any] | EventStream:
        """POST /v1/messages. Anthropic message schema, including supported image input.

        max_tokens is a positive output-token limit. stream=True yields all
        content blocks and usage events through message_stop; a block stop alone
        is not completion. options forwards extensions (tools, thinking, etc.)
        but cannot override named parameters. anthropic_version/anthropic_beta are
        forwarded protocol headers, never authentication credentials. No image generation.
        """
        _model_id(model)
        headers = {"anthropic-version": anthropic_version}
        if anthropic_beta is not None:
            headers["anthropic-beta"] = anthropic_beta
        if any(not isinstance(value, str) or not value or not value.isascii() or any(ord(c) < 32 or ord(c) == 127 for c in value) for value in headers.values()):
            raise ValueError("Anthropic protocol headers must be non-empty printable ASCII strings.")
        if options and any(key in options for key in ("anthropic_version", "anthropic_beta")):
            raise ValueError("options cannot override named Anthropic header parameters.")
        _generation_scalars(temperature, top_p, max_tokens)
        if type(max_tokens) is not int or max_tokens <= 0:
            raise ValueError("max_tokens must be a positive integer.")
        body = _json_body({"model": model, "messages": _message_list(messages), "stream": stream,
                          "max_tokens": max_tokens, "system": system, "temperature": temperature, "top_p": top_p}, options)
        return self._json_result("messages", body, stream, "messages", headers)

    def tokenize(self, content: str | None = None, *, model: str,
                 options: Mapping[str, Any] | None = None) -> dict[str, Any] | list[int]:
        """POST /v1/tokenize. Raw text token IDs; not chat-template token accounting.

        Local models use content. For a different provider schema, omit content
        and pass its JSON fields in options. model/content cannot be overridden.
        IDs depend on the tokenizer; no account usage is charged for this query.
        """
        _model_id(model)
        if content is not None and not isinstance(content, str):
            raise ValueError("content must be a string or None.")
        body = _json_body({"model": model, "content": content}, options)
        if content is None and not options:
            raise ValueError("Provide content or the provider's tokenization fields in options.")
        raw = self._request("POST", "tokenize", gateway_api=True, json=body, response_text=True)
        try:
            result = json.loads(raw)
        except ValueError:
            raise EdgeSpeakError("invalid_response") from None
        if isinstance(result, dict):
            return result
        if isinstance(result, list) and all(type(token) is int and token >= 0 for token in result):
            return result
        raise EdgeSpeakError("invalid_response")

    def upsample(self, audio: AudioInput, *, input_sample_rate: int | None = None, sample_rate: int = 48_000,
                 response_format: AudioResponseFormat = "wav", bitrate: int | None = None,
                 pcm_format: PcmFormat | None = None) -> bytes:
        """Return encoded audio bytes, preserving channel count and speaker layout.

        Input: path, encoded bytes, or NumPy/AudioSamples; WAV/FLAC/MP3/M4A/AAC/
        OGG/Opus, 1–8 channels, <=32 MiB/120 s. Bare arrays require
        input_sample_rate; AudioSamples carries its own rate. sample_rate is
        always the output rate. Neither argument resamples before uploading.
        response_format: wav (default), flac, mp3, m4a, aac, ogg (Vorbis), opus.
        bitrate: total lossy target bit/s, e.g. 192000; not valid for WAV/FLAC.
        pcm_format: WAV s16/s24/s32/f32; FLAC s16/s24. Opus requires 48000 Hz.
        Codec/rate/layout combinations must be supported by the gateway.
        Raising the rate uses AudioVAE; lowering it only resamples. No account
        usage is charged. Returns bytes (no output file). Array input may use
        temporary files only when spooling is explicitly configured. Remote gateway
        audio-upload and authentication rules apply.
        """
        self._check_open()
        validate_audio_options(sample_rate, response_format, bitrate, pcm_format)
        fields = {"sample_rate": str(sample_rate)}
        if response_format != "wav":
            fields["response_format"] = response_format
        if bitrate is not None:
            fields["bitrate"] = str(bitrate)
        if pcm_format is not None:
            fields["pcm_format"] = pcm_format
        plan = prepare_audio(audio, input_sample_rate, max_bytes=self._max_memory_audio_bytes)
        validate_upsample_input(plan)
        with ExitStack() as stack:
            stack.callback(self._audio_budget.acquire(plan.size).close)
            filename, source, content_type = plan.open(self._audio_spool_threshold_bytes)
            stack.callback(source.close)
            if plan.size == 0 and os.fstat(source.fileno()).st_size > 32 * 1024 * 1024:
                raise ValueError("audio must not exceed 32 MiB.")
            try:
                request = self._http.build_request("POST", "audio/upsamplings", data=fields,
                    files={"file": (filename, source, content_type)})
                request.stream = _SyncUpload(request.stream, stack)
                with closing(self._request_budget.acquire(1)):
                    response = self._http.send(request)
            except httpx.TimeoutException:
                raise EdgeSpeakError("request_timeout") from None
            except httpx.HTTPError:
                raise EdgeSpeakError("connection_failed") from None
        if response.status_code == 404:
            raise EdgeSpeakError("audio_upsampling_unavailable", 404)
        check_response(response)
        audio_bytes = response.content
        validate_audio_response(audio_bytes, response.headers.get("content-type", ""), response_format, sample_rate, pcm_format)
        return audio_bytes

    def _request_stream(self, route, data, files, resources, wire_format):
        stream_resources = ExitStack()
        stream_resources.callback(resources.close)
        try:
            stream_resources.callback(self._request_budget.acquire(1).close)
            request = self._http.build_request("POST", route, data=data, files=files,
                headers={"progress": "1"} if wire_format == "ndjson" else None)
            request.stream = _SyncUpload(request.stream, resources)
            response = self._http.send(request, stream=True)
            try:
                if not response.is_success:
                    response.read()
                    check_response(response, missing_route=True)
                stream = EventStream(self, response, stream_resources, wire_format)
                self._streams.add(stream)
                return stream
            except BaseException:
                response.close()
                raise
        except BaseException as error:
            stream_resources.close()
            if isinstance(error, httpx.TimeoutException):
                raise EdgeSpeakError("request_timeout") from None
            if isinstance(error, httpx.HTTPError):
                raise EdgeSpeakError("connection_failed") from None
            raise

    @overload
    def _audio(self, route: str, audio: AudioPlan | Sequence[AudioPlan],
               fields: dict, *, response_text: bool = False, stream_format: str) -> EventStream: ...

    @overload
    def _audio(self, route: str, audio: AudioPlan | Sequence[AudioPlan],
               fields: dict, *, response_text: Literal[True], stream_format: None = None) -> str: ...

    @overload
    def _audio(self, route: str, audio: AudioPlan | Sequence[AudioPlan],
               fields: dict, *, response_text: Literal[False] = False, stream_format: None = None) -> dict[str, Any]: ...

    @overload
    def _audio(self, route: str, audio: AudioPlan | Sequence[AudioPlan],
               fields: dict, *, response_text: Literal[False] = False, stream_format: str | None = None) -> dict[str, Any] | EventStream: ...

    @overload
    def _audio(self, route: str, audio: AudioPlan | Sequence[AudioPlan],
               fields: dict, *, response_text: bool = False, stream_format: str | None = None) -> dict[str, Any] | str | EventStream: ...

    def _audio(self, route: str, audio: AudioPlan | Sequence[AudioPlan],
               fields: dict, *, response_text: bool = False, stream_format: str | None = None) -> dict[str, Any] | str | EventStream:
        self._check_open()
        paths = [audio] if isinstance(audio, AudioPlan) else list(audio)
        if not paths or any(not isinstance(item, AudioPlan) for item in paths):
            raise ValueError("Internal audio preparation requires a non-empty list of AudioPlan.")
        data: dict[str, Any] = {}
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
                if isinstance(value, Real):
                    if not _finite_number(value):
                        raise ValueError(f"{key} must be finite.")
                data[key] = str(value)
        with ExitStack() as stack:
            lease = self._audio_budget.acquire(sum(item.size for item in paths))
            stack.callback(lease.close)
            files: list[tuple[str, tuple[str, BinaryIO, str]]] = []
            for item in paths:
                filename, source, content_type = item.open(self._audio_spool_threshold_bytes)
                stack.callback(source.close)
                files.append(("file", (filename, source, content_type)))
            if stream_format:
                return self._request_stream(route, data, files, stack.pop_all(), stream_format)
            return self._request("POST", route, missing_route=True, response_text=response_text,
                                 data=data, files=files, _upload_resources=stack)

    def _execute_audio(self, request: AudioRequest):
        if request.capability and (self._attached or request.capability == "diff_alignment"):
            capabilities = self._request("GET", "health").get("capabilities")
            if not isinstance(capabilities, list) or request.capability not in capabilities:
                raise EdgeSpeakError("unsupported_gateway_capability")
        return self._audio(request.route, request.audio, request.fields,
                           response_text=request.response_text, stream_format=request.stream_format)

    @overload
    def transcribe(self, audio: AudioInput, *, sample_rate: int | None = None, model: str | None = None,
                   language: str | None = None, diarize: bool = False,
                   response_format: TranscriptionFormat | None = None, stream: Literal[True], prompt: str | None = None,
                   timestamp_granularities: Iterable[TimestampGranularity] | None = None,
                   word_timestamp_enabled: bool | None = None, candidates: int | None = None,
                   semantic_sentence_enabled: bool | None = None,
                   min_chars: int | None = None, max_chars: int | None = None,
                   start_margin: float | None = None, end_margin: float | None = None) -> EventStream: ...

    @overload
    def transcribe(self, audio: AudioInput, *, sample_rate: int | None = None, model: str | None = None,
                   language: str | None = None, diarize: bool = False,
                   response_format: Literal["text"], stream: Literal[False] = False, prompt: str | None = None,
                   timestamp_granularities: Iterable[TimestampGranularity] | None = None,
                   word_timestamp_enabled: bool | None = None, candidates: int | None = None,
                   semantic_sentence_enabled: bool | None = None,
                   min_chars: int | None = None, max_chars: int | None = None,
                   start_margin: float | None = None, end_margin: float | None = None) -> str: ...

    @overload
    def transcribe(self, audio: AudioInput, *, sample_rate: int | None = None, model: str | None = None,
                   language: str | None = None, diarize: bool = False,
                   response_format: Literal["json", "verbose_json", "diarized_json"] | None = None, stream: Literal[False] = False, prompt: str | None = None,
                   timestamp_granularities: Iterable[TimestampGranularity] | None = None,
                   word_timestamp_enabled: bool | None = None, candidates: int | None = None,
                   semantic_sentence_enabled: bool | None = None,
                   min_chars: int | None = None, max_chars: int | None = None,
                   start_margin: float | None = None, end_margin: float | None = None) -> Transcription: ...

    @overload
    def transcribe(self, audio: AudioInput, *, sample_rate: int | None = None, model: str | None = None,
                   language: str | None = None, diarize: bool = False,
                   response_format: TranscriptionFormat | None = None, stream: bool = False, prompt: str | None = None,
                   timestamp_granularities: Iterable[TimestampGranularity] | None = None,
                   word_timestamp_enabled: bool | None = None, candidates: int | None = None,
                   semantic_sentence_enabled: bool | None = None,
                   min_chars: int | None = None, max_chars: int | None = None,
                   start_margin: float | None = None, end_margin: float | None = None) -> Transcription | str | EventStream: ...

    def transcribe(self, audio: AudioInput, *, sample_rate: int | None = None, model: str | None = None,
                   language: str | None = None, diarize: bool = False,
                   response_format: TranscriptionFormat | None = None, stream: bool = False, prompt: str | None = None,
                   timestamp_granularities: Iterable[TimestampGranularity] | None = None,
                   word_timestamp_enabled: bool | None = None, candidates: int | None = None,
                   semantic_sentence_enabled: bool | None = None,
                   min_chars: int | None = None, max_chars: int | None = None,
                   start_margin: float | None = None, end_margin: float | None = None) -> Transcription | str | EventStream:
        """Transcribe media, optionally including speaker labels and semantic sentences.

        Args:
            audio: Local media path, complete encoded bytes, or NumPy ndarray.
            sample_rate: Required only for arrays: true input rate in Hz, 1..384000.
                Arrays use (frames,) or (frames, channels), 1..8 channels; int16
                or finite float32/64 in [-1, 1]. Converted to PCM16 WAV without
                resampling. Never pass sample_rate with paths or encoded bytes.
            model: Runtime model ID; None uses the default.
            language: Language code such as "en" or "zh"; None uses detection.
            diarize: Include speaker labels; requires diarized_json output.
            response_format: "json", "verbose_json", "diarized_json", or "text".
                None selects diarized_json when diarize=True, json when streaming,
                otherwise verbose_json.
            stream: Return SSE EventStream; requires json, no diarization or
                granularities, and an attached gateway supporting streaming.
                The headless CLI does not support streaming transcription.
            prompt: Recognition context passed to the runtime.
            timestamp_granularities: ["word"], ["segment"], or ["word", "segment"].
                None/[] sends no explicit request, not a promise to disable timing.
                Requires verbose_json or diarized_json.
            word_timestamp_enabled: None inherits runtime preferences; False
                conflicts with timestamp granularity "word". True requires
                verbose_json/diarized_json and cannot accompany candidates >= 2.
            candidates: 2..8 hypotheses; None/0/1 disables alternatives.
                Requires verbose_json without word granularity or explicit word timing.
            semantic_sentence_enabled: None inherits runtime preferences.
                False cannot accompany sentence length/margin overrides.
            min_chars: Optional minimum sentence length in characters.
            max_chars: Optional maximum sentence length in characters.
            start_margin: Optional sentence start margin in seconds.
            end_margin: Optional sentence end margin in seconds.

        Returns:
            Gateway JSON dict, str for text output, or a closeable EventStream
            when stream=True. All audio timestamps use seconds.

        Raises:
            ValueError: Invalid options or incompatible combinations.
            OSError: Local media cannot be read.
            EdgeSpeakError: Transport, gateway, or stream failure.

        Example:
            client.transcribe("meeting.wav", timestamp_granularities=["word"])

        """
        self._check_open()
        request = prepare_transcribe(audio, sample_rate=sample_rate, model=model, language=language, diarize=diarize, response_format=response_format, stream=stream, prompt=prompt, timestamp_granularities=timestamp_granularities, word_timestamp_enabled=word_timestamp_enabled, candidates=candidates, semantic_sentence_enabled=semantic_sentence_enabled, min_chars=min_chars, max_chars=max_chars, start_margin=start_margin, end_margin=end_margin, max_bytes=self._max_memory_audio_bytes)
        return cast(Transcription | str | EventStream, self._execute_audio(request))

    @overload
    def align(self, audio: AudioInput, *, sample_rate: int | None = None, text: str | Mapping[str, Any] | None = None,
              text_file: str | os.PathLike[str] | None = None, text_format: ReferenceFormat | None = None,
              model: str | None = None,
              language: str | None = None, search_effort: SearchEffort = "standard", progress: Literal[True],
              threshold: float | None = None,
              start: float | None = None, end: float | None = None,
              protected_terms: Iterable[str] | None = None,
              text_normalization: Mapping[str, Any] | None = None,
              audio_track: int | None = None, audio_channel: AudioChannel | None = None,
              semantic_sentence_enabled: bool | None = None,
              min_chars: int | None = None, max_chars: int | None = None,
              start_margin: float | None = None, end_margin: float | None = None) -> EventStream: ...

    @overload
    def align(self, audio: AudioInput, *, sample_rate: int | None = None, text: str | Mapping[str, Any] | None = None,
              text_file: str | os.PathLike[str] | None = None, text_format: ReferenceFormat | None = None,
              model: str | None = None,
              language: str | None = None, search_effort: SearchEffort = "standard", progress: Literal[False] = False,
              threshold: float | None = None,
              start: float | None = None, end: float | None = None,
              protected_terms: Iterable[str] | None = None,
              text_normalization: Mapping[str, Any] | None = None,
              audio_track: int | None = None, audio_channel: AudioChannel | None = None,
              semantic_sentence_enabled: bool | None = None,
              min_chars: int | None = None, max_chars: int | None = None,
              start_margin: float | None = None, end_margin: float | None = None) -> Alignment: ...

    @overload
    def align(self, audio: AudioInput, *, sample_rate: int | None = None, text: str | Mapping[str, Any] | None = None,
              text_file: str | os.PathLike[str] | None = None, text_format: ReferenceFormat | None = None,
              model: str | None = None,
              language: str | None = None, search_effort: SearchEffort = "standard", progress: bool = False,
              threshold: float | None = None,
              start: float | None = None, end: float | None = None,
              protected_terms: Iterable[str] | None = None,
              text_normalization: Mapping[str, Any] | None = None,
              audio_track: int | None = None, audio_channel: AudioChannel | None = None,
              semantic_sentence_enabled: bool | None = None,
              min_chars: int | None = None, max_chars: int | None = None,
              start_margin: float | None = None, end_margin: float | None = None) -> Alignment | EventStream: ...

    def align(self, audio: AudioInput, *, sample_rate: int | None = None, text: str | Mapping[str, Any] | None = None,
              text_file: str | os.PathLike[str] | None = None, text_format: ReferenceFormat | None = None,
              model: str | None = None,
              language: str | None = None, search_effort: SearchEffort = "standard", progress: bool = False,
              threshold: float | None = None,
              start: float | None = None, end: float | None = None,
              protected_terms: Iterable[str] | None = None,
              text_normalization: Mapping[str, Any] | None = None,
              audio_track: int | None = None, audio_channel: AudioChannel | None = None,
              semantic_sentence_enabled: bool | None = None,
              min_chars: int | None = None, max_chars: int | None = None,
              start_margin: float | None = None, end_margin: float | None = None) -> Alignment | EventStream:
        """Align exact spoken words to audio; return JSON or NDJSON progress.

        Args:
            audio: Local media path, encoded bytes, or NumPy ndarray (same as transcribe).
            sample_rate: Required only for arrays; input rate in Hz, 1..384000.
                Shape (frames,) or (frames, channels), 1..8 channels; int16 or
                finite float32/64 in [-1, 1]. No resampling or automatic transpose.
            text: String or mapping, e.g. {"segments": [{"text": "Hello"}]}.
                Supply exactly one of text or text_file.
            text_file: Local UTF-8 file, up to 64 MiB, not a server-side path.
            text_format: "txt", "json", "srt", "ass", or "ssa". None infers the
                file extension or JSON mapping; strings use runtime detection.
                Existing subtitle timing is discarded and recomputed.
            model: Runtime model ID; None uses the default.
            language: Spoken language code; do not translate the reference.
            search_effort: "standard" (default), "extended" (wider search), or
                "auto" (retry eligible standard failures with extended search).
            progress: Return EventStream with progress and a final result object.
                A progress value of 1 alone does not mean completion.
            threshold: Optional semantic sentence boundary threshold.
            start: Crop start in seconds; supply with end, with 0 <= start < end.
            end: Finite crop end in seconds, greater than start.
            protected_terms: Strings, e.g. ["EdgeSpeak", "New York"].
            text_normalization: Runtime settings, e.g. {"enabled": True, "top_k": 2}.
            audio_track: Zero-based track index; None uses runtime selection.
            audio_channel: "mix", a zero-based integer, or numeric string (e.g. "1").
            semantic_sentence_enabled: None inherits runtime preferences.
            min_chars: Optional minimum sentence length in characters.
            max_chars: Optional maximum sentence length in characters.
            start_margin: Optional sentence start margin in seconds.
            end_margin: Optional sentence end margin in seconds.

        Returns:
            Gateway JSON dict, or EventStream when progress=True. Timestamps are
            seconds. This method does not perform speaker diarization.
        """
        self._check_open()
        request = prepare_align(audio, sample_rate=sample_rate, text=text, text_file=text_file, text_format=text_format, model=model, language=language, search_effort=search_effort, progress=progress, threshold=threshold, start=start, end=end, protected_terms=protected_terms, text_normalization=text_normalization, audio_track=audio_track, audio_channel=audio_channel, semantic_sentence_enabled=semantic_sentence_enabled, min_chars=min_chars, max_chars=max_chars, start_margin=start_margin, end_margin=end_margin, max_bytes=self._max_memory_audio_bytes)
        return cast(Alignment | EventStream, self._execute_audio(request))

    def diff_align(self, audio: AudioInput, *, sample_rate: int | None = None,
                   reference_segments: Sequence[Mapping[str, Any]],
                   transcript_segments: Sequence[Mapping[str, Any]],
                   model: str | None = None, language: str | None = None,
                   offset: float = 0.0) -> dict[str, Any]:
        """Acoustically reconcile reference text with ASR text (candidate API).

        Both inputs are nonempty arrays of {"text": str, "speaker": str | None}.
        Do not include caption timestamps: crop the audio before calling. The
        uploaded audio must be at most 300 seconds including context padding.
        offset shifts returned timestamps into the original media timeline.
        Returned original_index values refer to this call's reference array;
        speaker labels come from input text, not verified voice identities.
        Requires a gateway advertising diff_alignment. No single-input fallback.
        """
        self._check_open()
        request = prepare_diff_align(audio, sample_rate=sample_rate, reference_segments=reference_segments, transcript_segments=transcript_segments, model=model, language=language, offset=offset, max_bytes=self._max_memory_audio_bytes)
        return cast(dict[str, Any], self._execute_audio(request))

    def segment(self, text: str | None = None, *, segments: Iterable[Mapping[str, Any]] | None = None,
                threshold: float | None = None, paragraph_threshold: float | None = None,
                min_chars: int | None = None, max_chars: int | None = None,
                start_margin: float | None = None, end_margin: float | None = None,
                options: Mapping[str, Any] | None = None) -> Segmentation:
        """Split text into sentences/paragraphs, or resegment timed caption segments.

        Pass ``segments=transcript['segments']`` to retain timing and speakers.
        Supply exactly one of text or segments. Timed entries contain text,
        start/end in seconds, and optional speaker labels. threshold controls
        sentence boundaries; paragraph_threshold enables paragraph mode, which
        accepts plain text only and cannot accompany length limits or margins.
        min_chars/max_chars are character counts; start_margin/end_margin are
        seconds. None inherits runtime settings. options is a runtime settings
        mapping; its keys are validated by the gateway. Returns gateway JSON.
        """
        self._check_open()
        body = prepare_segment(text, segments=segments, threshold=threshold, paragraph_threshold=paragraph_threshold,
                               min_chars=min_chars, max_chars=max_chars, start_margin=start_margin,
                               end_margin=end_margin, options=options)
        return cast(Segmentation, self._request("POST", "text/segmentations", missing_route=True, json=body))

    def diarize(self, audio: AudioInput, *, sample_rate: int | None = None, num_speakers: int | None = None) -> Diarization:
        """Return speaker turns as gateway JSON without transcribing speech.

        audio accepts a local path, encoded bytes, or NumPy/AudioSamples.
        Bare arrays require sample_rate (input Hz). num_speakers is in 1..32;
        None infers the count. Turn timestamps use seconds.
        """
        self._check_open()
        if num_speakers is not None and (type(num_speakers) is not int or not 1 <= num_speakers <= 32):
            raise ValueError("num_speakers must be an integer from 1 to 32.")
        return cast(Diarization, self._audio("speaker/diarizations", prepare_audio(audio, sample_rate, max_bytes=self._max_memory_audio_bytes), {"num_speakers": num_speakers}))

    def speaker_embedding(self, audio: AudioInput | Sequence[AudioInput], *,
                          sample_rate: int | None = None, model: str | None = None) -> Embeddings:
        """Extract embeddings from one AudioInput or a non-empty batch.

        Bare arrays share sample_rate; AudioSamples carries each item's input
        rate, allowing mixed-rate batches. Encoded inputs use their headers.
        Do not pass a rate when there are no bare arrays. Input order is retained.

        model is a runtime model ID; None uses the default. Returns gateway JSON
        with data entries in input order, each containing an embedding array.
        """
        self._check_open()
        return cast(Embeddings, self._audio("speaker/embeddings", prepare_batch(audio, sample_rate, self._max_memory_audio_bytes), {"model": model}))

    def speaker_similarity(self, embedding_a: Iterable[float], embedding_b: Iterable[float], *,
                           model: str | None = None) -> Similarity:
        """Compare two embedding vectors and return the gateway JSON cosine score.

        Pass the numeric ``data[i]["embedding"]`` arrays from speaker_embedding,
        using the same model for both. The score is in [-1, 1], not a probability;
        the application chooses its match threshold. Model IDs are runtime-defined.
        """
        self._check_open()
        a = _materialize(embedding_a, "embedding_a")
        b = _materialize(embedding_b, "embedding_b")
        for name, values in (("embedding_a", a), ("embedding_b", b)):
            if not values or any(not _finite_number(value) for value in values):
                raise ValueError(f"{name} must contain finite numeric values (not booleans) and must not be empty.")
        body: dict[str, Any] = {"embedding_a": [float(value) for value in a], "embedding_b": [float(value) for value in b]}
        if model is not None:
            body["model"] = model
        return cast(Similarity, self._request("POST", "speaker/similarity", json=body))

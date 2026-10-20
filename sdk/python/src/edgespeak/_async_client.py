"""Async gateway transport and owned CLI lifecycle, without blocking the loop."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from functools import partial
import json
import os
import threading
from typing import Any, Awaitable, Callable, Coroutine, Iterable, Literal, Mapping, Sequence, overload
from urllib.parse import urlsplit
import weakref

import httpx

from ._audio import validate_options, validate_response
from ._audio_budget import AudioBudget, DEFAULT_IN_FLIGHT_AUDIO_BYTES, positive_limit
from ._input_audio import AudioInput, AudioPlan, MAX_MEMORY_AUDIO_BYTES, prepare_audio, prepare_batch
from ._async_utils import settle as _settle, finish_cleanup
from ._async_streaming import AsyncEventStream, AsyncStreamRequest
from ._device import normalize_device
from ._errors import API_KEYS_URL, EdgeSpeakError, check_response, protocol_error, valid_account_key
from contextlib import nullcontext
from ._concurrency import validate_concurrency, execution_request
from ._process import start_process, stop_process
from ._requests import AudioRequest, prepare_segment, prepare_transcribe, prepare_align, prepare_diff_align, _finite_number, _json_body, _message_list, _model_id, _generation_scalars, _materialize
from ._responses import Transcription, Alignment, Diarization, Embeddings, Segmentation, Similarity, Usage, Models
from ._model_catalog import group_models
from ._text import validate_normalization
from ._types import Device, AudioResponseFormat, PcmFormat, AudioChannel, ReferenceFormat, SearchEffort, TimestampGranularity, TranscriptionFormat, NormalizationMode, NormalizationClass
from ._version import __version__



def _abandon_in_background(lease):
    if os.getpid() == lease.pid:
        # GC may run on an event-loop thread. Never wait for a CLI there.
        threading.Thread(target=lease.abandon, name="edgespeak-cli-cleanup", daemon=True).start()


class _StartupLease:
    """Thread-owned abandonment state also cleans up after loop destruction."""
    def __init__(self, timeout, key, device, pid, max_concurrency=None):
        self.args = (timeout, key, device) if max_concurrency is None else (timeout, key, device, max_concurrency)
        self.pid = pid
        self.lock = threading.Lock()
        self.abandoned = False
        self.result = None

    def start(self):
        result = start_process(*self.args)
        with self.lock:
            abandon = self.abandoned
            if not abandon:
                self.result = result
        if abandon:
            stop_process(result[0], self.pid)
            return None
        return result

    def abandon(self):
        with self.lock:
            self.abandoned = True
            result, self.result = self.result, None
        if result is not None:
            stop_process(result[0], self.pid)


class _AsyncUpload(httpx.AsyncByteStream):
    def __init__(self, stream, resources, client, blocking):
        self._iterator = iter(stream)
        self._resources = resources
        self._client = client
        self._blocking = blocking
        self._ended = False

    async def __aiter__(self):
        try:
            while True:
                chunk = await self._client._work(next, self._iterator, None) if self._blocking else next(self._iterator, None)
                if chunk is None:
                    return
                yield chunk
        finally:
            await self.aclose()

    async def aclose(self):
        if not self._ended:
            self._ended = True
            await self._client._cleanup(self._resources.close)


class AsyncEdgeSpeak:
    """Native async client. Prefer async with; otherwise await aclose().

    Construction performs no CLI installation/startup. First awaited use binds
    the instance to one event loop and process. Create clients after fork.
    Owned mode starts/stops its CLI; base_url attaches without stopping a gateway.
    Account API KEY, gateway_key, device and HTTPS rules match EdgeSpeak.
    transport and hooks must be async; supplied transport is owned by the client.
    Input budgets count encoded memory-origin uploads, not RSS. None disables
    each SDK cap; server limits still apply. Spooling is explicitly opt-in.
    Streaming holds an HTTP slot until terminal/aclose; nested requests need a
    spare max_concurrency slot. Cancellation may wait for local workers to stop.
    max_concurrency=None preserves defaults (async HTTP 4, sync HTTPX pool).
    Explicit 1..64 caps HTTP work and the owned serve batch execution ceiling;
    attached mode only caps this client. Model/route capacity can be lower.
    GET and model lifecycle requests bypass client slots. Streams hold slots
    until closed. Hooks making nested work requests need a spare slot.
    """
    def __init__(self, *, base_url: str | None = None, gateway_key: str | None = None,
                 api_key: str | None = None, device: Device | None = None,
                 timeout: float = 600, startup_timeout: float = 30,
                 transport: httpx.AsyncBaseTransport | None = None,
                 limits: httpx.Limits | None = None,
                 event_hooks: Mapping[str, list[Callable[..., Awaitable[None]]]] | None = None,
                 max_memory_audio_bytes: int | None = MAX_MEMORY_AUDIO_BYTES,
                 max_in_flight_audio_bytes: int | None = DEFAULT_IN_FLIGHT_AUDIO_BYTES,
                 audio_spool_threshold_bytes: int | None = None,
                 max_concurrency: int | None = None):
        if base_url is not None and device is not None:
            raise ValueError("device cannot be used with base_url: the existing gateway controls its compute devices.")
        device = normalize_device(device)
        if api_key is None and base_url is None:
            api_key = os.environ.get("EDGESPEAK_API_KEY")
        if not all(_finite_number(v) and v > 0 for v in (timeout, startup_timeout)):
            raise ValueError("timeout and startup_timeout must be finite positive seconds.")
        if api_key is not None and not valid_account_key(api_key):
            raise ValueError(f"api_key must be an account API KEY starting with esak_. Create one at {API_KEYS_URL}; set EDGESPEAK_API_KEY or pass api_key.")
        if base_url is not None and api_key is not None:
            raise ValueError("api_key is only used when the SDK starts its own CLI service.")
        if base_url is None and gateway_key is not None:
            raise ValueError("gateway_key is only used with an explicit base_url.")
        if base_url is not None:
            parsed = urlsplit(base_url)
            if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password
                    or parsed.query or parsed.fragment or parsed.path.rstrip('/') != '/v1'):
                raise ValueError("base_url must be an HTTP(S) gateway URL ending in /v1.")
            if parsed.scheme == 'http' and parsed.hostname not in ('127.0.0.1', 'localhost', '::1'):
                raise ValueError("Remote gateways require HTTPS.")
        positive_limit(max_memory_audio_bytes, "max_memory_audio_bytes")
        positive_limit(audio_spool_threshold_bytes, "audio_spool_threshold_bytes")
        validate_concurrency(max_concurrency)
        self._audio_budget = AudioBudget(max_in_flight_audio_bytes)
        self._max_memory_audio_bytes = max_memory_audio_bytes
        self._audio_spool_threshold_bytes = audio_spool_threshold_bytes
        self._max_concurrency = max_concurrency
        self._owner_pid = os.getpid()
        self._loop = None
        self._closed = False
        self._closing: asyncio.Task[None] | None = None
        self._attached = base_url is not None
        self._base_url = base_url
        self._gateway_key = gateway_key
        self._api_key = api_key
        self._device = device
        self._timeout = timeout
        self._startup_timeout = startup_timeout
        self._transport = transport
        self._limits = limits
        self._hooks = event_hooks
        self._http: httpx.AsyncClient | None = None
        self._pool = None
        self._workers = None
        self._slots: asyncio.Semaphore | None = None
        self._startup = None
        self._startup_lease = None
        self._startup_waiters = 0
        self._startup_finalizer = None
        self._operations: dict[asyncio.Task, int] = {}
        self._streams: weakref.WeakSet[AsyncEventStream] = weakref.WeakSet()

    def _check_identity(self):
        if os.getpid() != self._owner_pid:
            raise RuntimeError("Create a new AsyncEdgeSpeak client after fork.")
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
            self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='edgespeak-io')
            self._workers = asyncio.Semaphore(4)
            self._slots = asyncio.Semaphore(self._max_concurrency if self._max_concurrency is not None else 4)
        elif self._loop is not loop:
            raise RuntimeError("AsyncEdgeSpeak belongs to a different event loop; create a new client.")

    def _check_open(self):
        self._check_identity()
        if self._closed:
            raise RuntimeError("AsyncEdgeSpeak client is closed.")

    def _enter_operation(self):
        self._check_open()
        task = asyncio.current_task()
        self._operations[task] = self._operations.get(task, 0) + 1
        return task

    def _leave_operation(self, task):
        count = self._operations.get(task, 1) - 1
        if count:
            self._operations[task] = count
        else:
            self._operations.pop(task, None)

    async def _work(self, function, *args, on_cancel=None, **kwargs):
        async with self._workers:
            future = self._loop.run_in_executor(self._pool, partial(function, *args, **kwargs))
            try:
                return await asyncio.shield(future)
            except asyncio.CancelledError:
                try:
                    result = await _settle(future)
                    if on_cancel is not None:
                        cleanup = self._loop.run_in_executor(self._pool, on_cancel, result)
                        await _settle(cleanup)
                except BaseException:
                    pass
                raise

    async def _cleanup(self, function, *args):
        return await finish_cleanup(self._work(function, *args))

    async def _ready(self):
        self._check_open()
        if self._http is not None:
            return
        if not self._attached:
            while self._startup is not None and self._startup_lease.abandoned:
                abandoned = self._startup
                try:
                    await asyncio.shield(abandoned)
                except asyncio.CancelledError:
                    raise
                except BaseException:
                    pass
                if self._startup is abandoned:
                    self._startup_finalizer.detach()
                    self._startup = None
            if self._startup is None:
                lease = _StartupLease(self._startup_timeout, self._api_key, self._device, self._owner_pid, self._max_concurrency)
                self._startup_lease = lease
                self._startup_finalizer = weakref.finalize(self, _abandon_in_background, lease)
                # OS shutdown closes the CLI stdin lease; do not start threads at exit.
                self._startup_finalizer.atexit = False
                self._startup = self._loop.run_in_executor(self._pool, lease.start)
            startup, lease = self._startup, self._startup_lease
            self._startup_waiters += 1
            try:
                result = await asyncio.shield(startup)
                if result is None:
                    raise RuntimeError("CLI startup was abandoned.")
                self._check_open()
                _, _, self._base_url, self._gateway_key = result
            except BaseException:
                if self._startup_waiters == 1 and self._http is None:
                    await self._cleanup(lease.abandon)
                    if startup.done() and self._startup is startup:
                        self._startup_finalizer.detach()
                        self._startup = None
                raise
            finally:
                self._startup_waiters -= 1
        self._check_open()
        if self._http is None:
            try:
                self._http = httpx.AsyncClient(base_url=self._base_url.rstrip('/')+'/', timeout=self._timeout,
                    transport=self._transport, limits=self._limits if self._limits is not None else httpx.Limits(),
                    event_hooks=dict(self._hooks) if self._hooks is not None else None,
                    trust_env=False, follow_redirects=False,
                    headers={'User-Agent': f'edgespeak-python/{__version__}', **({'Authorization': f'Bearer {self._gateway_key}'} if self._gateway_key else {})})
            except BaseException:
                if self._startup_lease is not None:
                    await self._work(self._startup_lease.abandon)
                raise

    async def __aenter__(self) -> AsyncEdgeSpeak:
        task = self._enter_operation()
        try:
            await self._ready()
            return self
        finally:
            self._leave_operation(task)

    async def __aexit__(self, *_) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        self._check_identity()
        if asyncio.current_task() in self._operations:
            raise RuntimeError("Cannot await client.aclose() inside an active client request/hook; close it after the request returns.")
        if self._closing is None:
            self._closed = True
            self._audio_budget.close()
            self._closing = asyncio.create_task(self._close())
        try:
            await asyncio.shield(self._closing)
        except asyncio.CancelledError:
            try:
                await _settle(self._closing)
            finally:
                raise

    async def _close(self):
        error = None
        try:
            if self._startup_lease is not None:
                # No process wait on the event loop. The worker sees abandonment.
                with self._startup_lease.lock:
                    self._startup_lease.abandoned = True
            tasks = list(self._operations)
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            if self._startup is not None:
                try:
                    await asyncio.shield(self._startup)
                except BaseException:
                    pass
            for stream in list(self._streams):
                stream._closed_by_client = not stream._closed
                try:
                    await stream.aclose()
                except BaseException as failure:
                    error = error or failure
            try:
                if self._http is not None:
                    await self._http.aclose()
                elif self._transport is not None:
                    await self._transport.aclose()
            except BaseException as failure:
                error = error or failure
        finally:
            try:
                if self._startup_lease is not None:
                    await self._work(self._startup_lease.abandon)
            finally:
                if self._startup_finalizer is not None:
                    self._startup_finalizer.detach()
                self._pool.shutdown(wait=False)
        if error is not None:
            raise error

    async def _request(self, method, path, *, response_text=False, gateway_api=False, missing_route=False, **kwargs):
        task = self._enter_operation()
        try:
            await self._ready()
            async with self._slots if execution_request(method, path) else nullcontext():
                response = await self._http.request(method, path, **kwargs)
            check_response(response, gateway_api=gateway_api, missing_route=missing_route)
            if response_text:
                return response.text
            try:
                value = response.json()
            except ValueError:
                raise EdgeSpeakError('invalid_response') from None
            if not isinstance(value, dict):
                raise EdgeSpeakError('invalid_response')
            return value
        except httpx.TimeoutException:
            raise EdgeSpeakError('request_timeout') from None
        except httpx.HTTPError:
            raise EdgeSpeakError('connection_failed') from None
        finally:
            self._leave_operation(task)

    async def _audio(self, prepared: AudioRequest, *, binary=None):
        task = self._enter_operation()
        resources = ExitStack()
        acquired_slot = False
        response = None
        try:
            if prepared.capability and (self._attached or prepared.capability in ('diff_alignment', 'diarization_model_selection', 'transcription_diarization_model_selection')):
                capabilities = (await self._request('GET', 'health')).get('capabilities')
                if not isinstance(capabilities, list) or prepared.capability not in capabilities:
                    raise EdgeSpeakError('unsupported_gateway_capability')
            plans = [prepared.audio] if isinstance(prepared.audio, AudioPlan) else prepared.audio
            lease = await self._audio_budget.acquire_async(sum(plan.size for plan in plans))
            resources.callback(lease.close)
            await self._ready()
            assert self._slots is not None and self._http is not None
            await self._slots.acquire()
            acquired_slot = True
            files = []
            for plan in plans:
                opened = await self._work(plan.open, self._audio_spool_threshold_bytes, on_cancel=lambda item: item[1].close())
                name, source, content_type = opened
                resources.callback(source.close)
                if binary is not None:
                    if plan.size == 0 and (await self._work(os.fstat, source.fileno())).st_size > 32*1024*1024:
                        raise ValueError('audio must not exceed 32 MiB.')
                files.append(('file', (name, source, content_type)))
            data = audio_fields(prepared.fields)
            request = self._http.build_request('POST', prepared.route, data=data, files=files,
                headers={'progress': '1'} if prepared.stream_format == 'ndjson' else None)
            upload = _AsyncUpload(request.stream, resources, self, any(plan.size == 0 for plan in plans) or self._audio_spool_threshold_bytes is not None)
            request.stream = upload
            response = await self._http.send(request, stream=True)
            # Also handle transports/servers that return before consuming the body.
            await upload.aclose()
            if not response.is_success:
                await response.aread()
                if binary is not None and response.status_code == 404:
                    raise EdgeSpeakError('audio_upsampling_unavailable', 404)
                check_response(response, missing_route=True)
            if prepared.stream_format:
                events = AsyncEventStream(self, response, prepared.stream_format, self._slots.release)
                self._streams.add(events)
                acquired_slot = False
                response = None
                return events
            await response.aread()
            if binary is not None:
                validate_response(response.content, response.headers.get('content-type', ''), *binary)
                return response.content
            if prepared.response_text:
                return response.text
            try:
                result = response.json()
            except ValueError:
                raise EdgeSpeakError('invalid_response') from None
            if not isinstance(result, dict):
                raise EdgeSpeakError('invalid_response')
            return result
        except httpx.TimeoutException:
            raise EdgeSpeakError('request_timeout') from None
        except httpx.HTTPError:
            raise EdgeSpeakError('connection_failed') from None
        finally:
            try:
                if response is not None:
                    await finish_cleanup(response.aclose())
            finally:
                await self._cleanup(resources.close)
                if acquired_slot:
                    assert self._slots is not None
                    self._slots.release()
                self._leave_operation(task)

    async def _prepared_audio(self, prepare, audio, options):
        task = self._enter_operation()
        try:
            prepared = await self._work(prepare, audio, max_bytes=self._max_memory_audio_bytes, **options)
            return await self._audio(prepared)
        finally:
            self._leave_operation(task)

    @overload
    def transcribe(self, audio: AudioInput, *, sample_rate: int | None = None, model: str | None = None,
                   language: str | None = None, diarize: bool = False, diarization_model: str | None = None,
                   response_format: TranscriptionFormat | None = None, stream: Literal[True], prompt: str | None = None,
                   timestamp_granularities: Iterable[TimestampGranularity] | None = None,
                   word_timestamp_enabled: bool | None = None, candidates: int | None = None,
                   semantic_sentence_enabled: bool | None = None, min_chars: int | None = None,
                   max_chars: int | None = None, start_margin: float | None = None,
                   end_margin: float | None = None) -> AsyncStreamRequest: ...

    @overload
    def transcribe(self, audio: AudioInput, *, sample_rate: int | None = None, model: str | None = None,
                   language: str | None = None, diarize: bool = False, diarization_model: str | None = None,
                   response_format: Literal["text"], stream: Literal[False] = False, prompt: str | None = None,
                   timestamp_granularities: Iterable[TimestampGranularity] | None = None,
                   word_timestamp_enabled: bool | None = None, candidates: int | None = None,
                   semantic_sentence_enabled: bool | None = None, min_chars: int | None = None,
                   max_chars: int | None = None, start_margin: float | None = None,
                   end_margin: float | None = None) -> Coroutine[Any, Any, str]: ...

    @overload
    def transcribe(self, audio: AudioInput, *, sample_rate: int | None = None, model: str | None = None,
                   language: str | None = None, diarize: bool = False, diarization_model: str | None = None,
                   response_format: Literal["json", "verbose_json", "diarized_json"] | None = None, stream: Literal[False] = False, prompt: str | None = None,
                   timestamp_granularities: Iterable[TimestampGranularity] | None = None,
                   word_timestamp_enabled: bool | None = None, candidates: int | None = None,
                   semantic_sentence_enabled: bool | None = None, min_chars: int | None = None,
                   max_chars: int | None = None, start_margin: float | None = None,
                   end_margin: float | None = None) -> Coroutine[Any, Any, Transcription]: ...

    @overload
    def transcribe(self, audio: AudioInput, *, sample_rate: int | None = None, model: str | None = None,
                   language: str | None = None, diarize: bool = False, diarization_model: str | None = None,
                   response_format: TranscriptionFormat | None = None, stream: bool = False, prompt: str | None = None,
                   timestamp_granularities: Iterable[TimestampGranularity] | None = None,
                   word_timestamp_enabled: bool | None = None, candidates: int | None = None,
                   semantic_sentence_enabled: bool | None = None, min_chars: int | None = None,
                   max_chars: int | None = None, start_margin: float | None = None,
                   end_margin: float | None = None) -> Coroutine[Any, Any, Transcription | str] | AsyncStreamRequest: ...

    def transcribe(self, audio: AudioInput, *, sample_rate: int | None = None, model: str | None = None,
                   language: str | None = None, diarize: bool = False, diarization_model: str | None = None,
                   response_format: TranscriptionFormat | None = None, stream: bool = False, prompt: str | None = None,
                   timestamp_granularities: Iterable[TimestampGranularity] | None = None,
                   word_timestamp_enabled: bool | None = None, candidates: int | None = None,
                   semantic_sentence_enabled: bool | None = None, min_chars: int | None = None,
                   max_chars: int | None = None, start_margin: float | None = None,
                   end_margin: float | None = None) -> Coroutine[Any, Any, Transcription | str] | AsyncStreamRequest:
        """Same input/options as EdgeSpeak.transcribe; stream=True uses async with."""
        options = dict(sample_rate=sample_rate, model=model, language=language, diarize=diarize, diarization_model=diarization_model,
            response_format=response_format, stream=stream, prompt=prompt, timestamp_granularities=timestamp_granularities,
            word_timestamp_enabled=word_timestamp_enabled, candidates=candidates, semantic_sentence_enabled=semantic_sentence_enabled,
            min_chars=min_chars, max_chars=max_chars, start_margin=start_margin, end_margin=end_margin)
        if stream is True:
            return AsyncStreamRequest(lambda: self._prepared_audio(prepare_transcribe, audio, options))
        return self._prepared_audio(prepare_transcribe, audio, options)

    @overload
    def align(self, audio: AudioInput, *, sample_rate: int | None = None, text: str | Mapping[str, Any] | None = None,
              text_file: str | os.PathLike[str] | None = None, text_format: ReferenceFormat | None = None,
              model: str | None = None, language: str | None = None, search_effort: SearchEffort = 'standard',
              progress: Literal[True], threshold: float | None = None, start: float | None = None, end: float | None = None,
              protected_terms: Iterable[str] | None = None, text_normalization: Mapping[str, Any] | None = None,
              audio_track: int | None = None, audio_channel: AudioChannel | None = None,
              semantic_sentence_enabled: bool | None = None, min_chars: int | None = None, max_chars: int | None = None,
              start_margin: float | None = None, end_margin: float | None = None) -> AsyncStreamRequest: ...

    @overload
    def align(self, audio: AudioInput, *, sample_rate: int | None = None, text: str | Mapping[str, Any] | None = None,
              text_file: str | os.PathLike[str] | None = None, text_format: ReferenceFormat | None = None,
              model: str | None = None, language: str | None = None, search_effort: SearchEffort = 'standard',
              progress: Literal[False] = False, threshold: float | None = None, start: float | None = None, end: float | None = None,
              protected_terms: Iterable[str] | None = None, text_normalization: Mapping[str, Any] | None = None,
              audio_track: int | None = None, audio_channel: AudioChannel | None = None,
              semantic_sentence_enabled: bool | None = None, min_chars: int | None = None, max_chars: int | None = None,
              start_margin: float | None = None, end_margin: float | None = None) -> Coroutine[Any, Any, Alignment]: ...

    @overload
    def align(self, audio: AudioInput, *, sample_rate: int | None = None, text: str | Mapping[str, Any] | None = None,
              text_file: str | os.PathLike[str] | None = None, text_format: ReferenceFormat | None = None,
              model: str | None = None, language: str | None = None, search_effort: SearchEffort = 'standard',
              progress: bool = False, threshold: float | None = None, start: float | None = None, end: float | None = None,
              protected_terms: Iterable[str] | None = None, text_normalization: Mapping[str, Any] | None = None,
              audio_track: int | None = None, audio_channel: AudioChannel | None = None,
              semantic_sentence_enabled: bool | None = None, min_chars: int | None = None, max_chars: int | None = None,
              start_margin: float | None = None, end_margin: float | None = None) -> Coroutine[Any, Any, Alignment] | AsyncStreamRequest: ...

    def align(self, audio: AudioInput, *, sample_rate: int | None = None, text: str | Mapping[str, Any] | None = None,
              text_file: str | os.PathLike[str] | None = None, text_format: ReferenceFormat | None = None,
              model: str | None = None, language: str | None = None, search_effort: SearchEffort = 'standard',
              progress: bool = False, threshold: float | None = None, start: float | None = None, end: float | None = None,
              protected_terms: Iterable[str] | None = None, text_normalization: Mapping[str, Any] | None = None,
              audio_track: int | None = None, audio_channel: AudioChannel | None = None,
              semantic_sentence_enabled: bool | None = None, min_chars: int | None = None, max_chars: int | None = None,
              start_margin: float | None = None, end_margin: float | None = None) -> Coroutine[Any, Any, Alignment] | AsyncStreamRequest:
        """Same input/options as EdgeSpeak.align; progress=True uses async with."""
        options = dict(sample_rate=sample_rate, text=text, text_file=text_file, text_format=text_format, model=model,
            language=language, search_effort=search_effort, progress=progress, threshold=threshold, start=start, end=end,
            protected_terms=protected_terms, text_normalization=text_normalization, audio_track=audio_track,
            audio_channel=audio_channel, semantic_sentence_enabled=semantic_sentence_enabled, min_chars=min_chars,
            max_chars=max_chars, start_margin=start_margin, end_margin=end_margin)
        if progress is True:
            return AsyncStreamRequest(lambda: self._prepared_audio(prepare_align, audio, options))
        return self._prepared_audio(prepare_align, audio, options)

    async def diff_align(self, audio: AudioInput, *, sample_rate: int | None = None,
                         reference_segments: Sequence[Mapping[str, Any]], transcript_segments: Sequence[Mapping[str, Any]],
                         model: str | None = None, language: str | None = None, offset: float = 0.0) -> dict[str, Any]:
        return await self._prepared_audio(prepare_diff_align, audio, dict(sample_rate=sample_rate,
            reference_segments=reference_segments, transcript_segments=transcript_segments, model=model, language=language, offset=offset))

    async def diarize(self, audio: AudioInput, *, sample_rate: int | None = None, num_speakers: int | None = None, model: str | None = None) -> Diarization:
        self._check_open()
        if num_speakers is not None and (type(num_speakers) is not int or not 1 <= num_speakers <= 32):
            raise ValueError('num_speakers must be an integer from 1 to 32.')
        plan = prepare_audio(audio, sample_rate, max_bytes=self._max_memory_audio_bytes)
        if model is not None and (not isinstance(model, str) or not model.strip()):
            raise ValueError('model must be a nonempty string.')
        return await self._audio(AudioRequest('speaker/diarizations', plan,
            {'num_speakers': num_speakers, 'model': model},
            capability='diarization_model_selection' if model is not None else None))

    async def speaker_embedding(self, audio: AudioInput | Sequence[AudioInput], *, sample_rate: int | None = None,
                                model: str | None = None) -> Embeddings:
        self._check_open()
        plans = prepare_batch(audio, sample_rate, self._max_memory_audio_bytes)
        return await self._audio(AudioRequest('speaker/embeddings', plans, {'model': model}))

    async def upsample(self, audio: AudioInput, *, input_sample_rate: int | None = None, sample_rate: int = 48000,
                       response_format: AudioResponseFormat = 'wav', bitrate: int | None = None,
                       pcm_format: PcmFormat | None = None) -> bytes:
        from ._client import validate_upsample_input
        self._check_open()
        validate_options(sample_rate, response_format, bitrate, pcm_format)
        plan = prepare_audio(audio, input_sample_rate, max_bytes=self._max_memory_audio_bytes)
        validate_upsample_input(plan)
        fields = {'sample_rate': sample_rate, 'response_format': response_format, 'bitrate': bitrate, 'pcm_format': pcm_format}
        return await self._audio(AudioRequest('audio/upsamplings', plan, fields), binary=(response_format, sample_rate, pcm_format))

    async def health(self) -> dict[str, Any]:
        return await self._request('GET', 'health', gateway_api=True)

    async def usage(self, *, refresh: bool = False) -> Usage:
        if type(refresh) is not bool:
            raise ValueError('refresh must be a boolean.')
        return await self._request('GET', 'usage', gateway_api=True, params={'refresh': str(refresh).lower()})

    async def models(self) -> Models:
        """Live gateway model data plus capability groups; no model load/download."""
        catalog = await self._request('GET', 'models', gateway_api=True)
        catalog['groups'] = group_models(catalog)
        return catalog

    async def models_running(self) -> dict[str, Any]:
        return await self._request('GET', 'models/running', gateway_api=True)

    async def models_downloads(self) -> dict[str, Any]:
        return await self._request('GET', 'models/downloads', gateway_api=True)

    async def _model_operation(self, path, model):
        _model_id(model)
        return await self._request('POST', path, gateway_api=True, json={'model': model})

    async def models_load(self, model: str) -> dict[str, Any]:
        return await self._model_operation('models/load', model)

    async def models_unload(self, model: str) -> dict[str, Any]:
        return await self._model_operation('models/unload', model)

    async def models_download(self, model: str) -> dict[str, Any]:
        return await self._model_operation('models/download', model)

    async def models_download_cancel(self, model: str) -> dict[str, Any]:
        return await self._model_operation('models/download/cancel', model)

    async def text_normalizations(self, text: str, *, language: str,
                                  mode: NormalizationMode = 'tn', model: str | None = None,
                                  top_k: int | None = None,
                                  classes: Sequence[NormalizationClass] | None = None) -> dict[str, Any]:
        self._check_open()
        values = validate_normalization(text, language, mode, top_k, classes)
        if model is not None:
            _model_id(model)
        return await self._request('POST', 'text/normalizations', gateway_api=True,
            json=_json_body({'text': text, 'language': language, 'mode': mode, 'model': model, 'top_k': top_k, 'classes': values}))

    async def segment(self, text: str | None = None, *, segments: Iterable[Mapping[str, Any]] | None = None,
                      threshold: float | None = None, paragraph_threshold: float | None = None,
                      min_chars: int | None = None, max_chars: int | None = None,
                      start_margin: float | None = None, end_margin: float | None = None,
                      options: Mapping[str, Any] | None = None) -> Segmentation:
        self._check_open()
        body = prepare_segment(text, segments=segments, threshold=threshold, paragraph_threshold=paragraph_threshold,
                               min_chars=min_chars, max_chars=max_chars, start_margin=start_margin,
                               end_margin=end_margin, options=options)
        return await self._request('POST', 'text/segmentations', missing_route=True, json=body)

    async def speaker_similarity(self, embedding_a: Iterable[float], embedding_b: Iterable[float], *,
                                 model: str | None = None) -> Similarity:
        self._check_open()
        a = _materialize(embedding_a, 'embedding_a')
        b = _materialize(embedding_b, 'embedding_b')
        for name, values in (('embedding_a', a), ('embedding_b', b)):
            if not values or any(not _finite_number(value) for value in values):
                raise ValueError(f'{name} must contain finite numeric values (not booleans) and must not be empty.')
        body: dict[str, Any] = {'embedding_a': [float(x) for x in a], 'embedding_b': [float(x) for x in b]}
        if model is not None:
            body['model'] = model
        return await self._request('POST', 'speaker/similarity', json=body)

    async def tokenize(self, content: str | None = None, *, model: str,
                       options: Mapping[str, Any] | None = None) -> dict[str, Any] | list[int]:
        self._check_open()
        _model_id(model)
        if content is not None and not isinstance(content, str):
            raise ValueError('content must be a string or None.')
        body = _json_body({'model': model, 'content': content}, options)
        if content is None and not options:
            raise ValueError("Provide content or the provider's tokenization fields in options.")
        raw = await self._request('POST', 'tokenize', gateway_api=True, json=body, response_text=True)
        try:
            value = json.loads(raw)
        except ValueError:
            raise EdgeSpeakError('invalid_response') from None
        if isinstance(value, dict) or isinstance(value, list) and all(type(t) is int and t >= 0 for t in value):
            return value
        raise EdgeSpeakError('invalid_response')

    async def _json_result(self, path, body, stream, protocol, headers=None):
        self._check_open()
        if type(stream) is not bool:
            raise ValueError('stream must be a boolean.')
        if not stream:
            result = await self._request('POST', path, gateway_api=True, json=body, headers=headers)
            if protocol == 'responses' and result.get('status') == 'failed':
                raise protocol_error(result)
            if protocol == 'responses' and result.get('status') == 'incomplete':
                raise EdgeSpeakError('incomplete_response')
            return result
        task = self._enter_operation()
        acquired = False
        response = None
        try:
            await self._ready()
            assert self._slots is not None and self._http is not None
            await self._slots.acquire()
            acquired = True
            request = self._http.build_request('POST', path, json=body,
                headers={'Accept': 'text/event-stream', **(headers or {})})
            response = await self._http.send(request, stream=True)
            if not response.is_success:
                await response.aread()
                check_response(response, gateway_api=True)
            if response.headers.get('content-type', '').split(';',1)[0].strip().lower() != 'text/event-stream':
                raise EdgeSpeakError('invalid_response')
            result = AsyncEventStream(self, response, protocol, self._slots.release)
            self._streams.add(result)
            acquired = False
            response = None
            return result
        except httpx.TimeoutException:
            raise EdgeSpeakError('request_timeout') from None
        except httpx.HTTPError:
            raise EdgeSpeakError('connection_failed') from None
        finally:
            try:
                if response is not None:
                    await finish_cleanup(response.aclose())
            finally:
                if acquired:
                    self._slots.release()
                self._leave_operation(task)

    @overload
    def chat_completions(self, messages: Iterable[Mapping[str, Any]], *, model: str,
                         stream: Literal[True], temperature: float | None = None, top_p: float | None = None,
                         max_tokens: int | None = None, options: Mapping[str, Any] | None = None) -> AsyncStreamRequest: ...

    @overload
    def chat_completions(self, messages: Iterable[Mapping[str, Any]], *, model: str,
                         stream: Literal[False] = False, temperature: float | None = None, top_p: float | None = None,
                         max_tokens: int | None = None, options: Mapping[str, Any] | None = None) -> Coroutine[Any, Any, dict[str, Any]]: ...

    @overload
    def chat_completions(self, messages: Iterable[Mapping[str, Any]], *, model: str,
                         stream: bool = False, temperature: float | None = None, top_p: float | None = None,
                         max_tokens: int | None = None, options: Mapping[str, Any] | None = None) -> Coroutine[Any, Any, dict[str, Any]] | AsyncStreamRequest: ...

    def chat_completions(self, messages: Iterable[Mapping[str, Any]], *, model: str,
                         stream: bool = False, temperature: float | None = None, top_p: float | None = None,
                         max_tokens: int | None = None, options: Mapping[str, Any] | None = None) -> Coroutine[Any, Any, dict[str, Any]] | AsyncStreamRequest:
        async def call():
            self._check_open()
            _model_id(model)
            _generation_scalars(temperature, top_p, max_tokens)
            body = _json_body({'model': model, 'messages': _message_list(messages), 'stream': stream,
                'temperature': temperature, 'top_p': top_p, 'max_tokens': max_tokens}, options)
            return await self._json_result('chat/completions', body, stream, 'chat')
        return AsyncStreamRequest(call) if stream is True else call()

    @overload
    def responses(self, input: str | Sequence[Mapping[str, Any]], *, model: str,
                  stream: Literal[True], instructions: str | None = None, max_output_tokens: int | None = None,
                  temperature: float | None = None, top_p: float | None = None,
                  options: Mapping[str, Any] | None = None) -> AsyncStreamRequest: ...

    @overload
    def responses(self, input: str | Sequence[Mapping[str, Any]], *, model: str,
                  stream: Literal[False] = False, instructions: str | None = None, max_output_tokens: int | None = None,
                  temperature: float | None = None, top_p: float | None = None,
                  options: Mapping[str, Any] | None = None) -> Coroutine[Any, Any, dict[str, Any]]: ...

    @overload
    def responses(self, input: str | Sequence[Mapping[str, Any]], *, model: str,
                  stream: bool = False, instructions: str | None = None, max_output_tokens: int | None = None,
                  temperature: float | None = None, top_p: float | None = None,
                  options: Mapping[str, Any] | None = None) -> Coroutine[Any, Any, dict[str, Any]] | AsyncStreamRequest: ...

    def responses(self, input: str | Sequence[Mapping[str, Any]], *, model: str,
                  stream: bool = False, instructions: str | None = None, max_output_tokens: int | None = None,
                  temperature: float | None = None, top_p: float | None = None,
                  options: Mapping[str, Any] | None = None) -> Coroutine[Any, Any, dict[str, Any]] | AsyncStreamRequest:
        async def call():
            self._check_open()
            _model_id(model)
            _generation_scalars(temperature, top_p, max_output_tokens)
            value = input if isinstance(input, str) else _message_list(input)
            body = _json_body({'model': model, 'input': value, 'stream': stream, 'instructions': instructions,
                'max_output_tokens': max_output_tokens, 'temperature': temperature, 'top_p': top_p}, options)
            return await self._json_result('responses', body, stream, 'responses')
        return AsyncStreamRequest(call) if stream is True else call()

    @overload
    def messages(self, messages: Iterable[Mapping[str, Any]], *, model: str, max_tokens: int,
                 stream: Literal[True], anthropic_version: str = '2023-06-01', anthropic_beta: str | None = None,
                 system: str | Sequence[Mapping[str, Any]] | None = None, temperature: float | None = None,
                 top_p: float | None = None, options: Mapping[str, Any] | None = None) -> AsyncStreamRequest: ...

    @overload
    def messages(self, messages: Iterable[Mapping[str, Any]], *, model: str, max_tokens: int,
                 stream: Literal[False] = False, anthropic_version: str = '2023-06-01', anthropic_beta: str | None = None,
                 system: str | Sequence[Mapping[str, Any]] | None = None, temperature: float | None = None,
                 top_p: float | None = None, options: Mapping[str, Any] | None = None) -> Coroutine[Any, Any, dict[str, Any]]: ...

    @overload
    def messages(self, messages: Iterable[Mapping[str, Any]], *, model: str, max_tokens: int,
                 stream: bool = False, anthropic_version: str = '2023-06-01', anthropic_beta: str | None = None,
                 system: str | Sequence[Mapping[str, Any]] | None = None, temperature: float | None = None,
                 top_p: float | None = None, options: Mapping[str, Any] | None = None) -> Coroutine[Any, Any, dict[str, Any]] | AsyncStreamRequest: ...

    def messages(self, messages: Iterable[Mapping[str, Any]], *, model: str, max_tokens: int,
                 stream: bool = False, anthropic_version: str = '2023-06-01', anthropic_beta: str | None = None,
                 system: str | Sequence[Mapping[str, Any]] | None = None, temperature: float | None = None,
                 top_p: float | None = None, options: Mapping[str, Any] | None = None) -> Coroutine[Any, Any, dict[str, Any]] | AsyncStreamRequest:
        async def call():
            self._check_open()
            _model_id(model)
            headers = {'anthropic-version': anthropic_version}
            if anthropic_beta is not None:
                headers['anthropic-beta'] = anthropic_beta
            if any(not isinstance(v,str) or not v or not v.isascii() or any(ord(c)<32 or ord(c)==127 for c in v) for v in headers.values()):
                raise ValueError('Anthropic protocol headers must be non-empty printable ASCII strings.')
            if options and any(k in options for k in ('anthropic_version', 'anthropic_beta')):
                raise ValueError('options cannot override named Anthropic header parameters.')
            _generation_scalars(temperature, top_p, max_tokens)
            if type(max_tokens) is not int or max_tokens <= 0:
                raise ValueError('max_tokens must be a positive integer.')
            body = _json_body({'model':model,'messages':_message_list(messages),'stream':stream,'max_tokens':max_tokens,
                'system':system,'temperature':temperature,'top_p':top_p},options)
            return await self._json_result('messages',body,stream,'messages',headers)
        return AsyncStreamRequest(call) if stream is True else call()


def audio_fields(fields):
    result = {}
    for key, value in fields.items():
        if value is None:
            continue
        if key.endswith('[]'):
            if isinstance(value, str):
                raise ValueError(f'{key} must be a sequence of strings.')
            result[key] = list(value)
        elif isinstance(value, (dict, list, tuple, bool)):
            result[key] = json.dumps(value, ensure_ascii=False, allow_nan=False)
        else:
            if isinstance(value, (int, float)) and not _finite_number(value):
                raise ValueError(f'{key} must be finite.')
            result[key] = str(value)
    return result

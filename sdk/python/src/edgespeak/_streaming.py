"""Closeable iterators for the API's SSE transcription and NDJSON alignment."""
from __future__ import annotations

import json
import os
import weakref
from typing import Any, Iterator

import httpx

from ._errors import EdgeSpeakError, payload_error


def _dispose(response, files, owner_pid):
    if os.getpid() != owner_pid:
        return
    try:
        response.close()
    finally:
        files.close()


def _event(raw):
    try:
        value = json.loads(raw)
    except ValueError:
        raise EdgeSpeakError("invalid_response") from None
    if not isinstance(value, dict):
        raise EdgeSpeakError("invalid_response")
    if "error" in value:
        raise payload_error(value)
    return value


def _events(response, wire_format):
    data = []
    for line in response.iter_lines():
        if wire_format == "ndjson":
            if line.strip():
                value = _event(line)
                yield value
        elif not line:
            if data:
                raw = "\n".join(data)
                data.clear()
                if raw.strip() == "[DONE]":
                    return
                value = _event(raw)
                yield value
        elif line.startswith("data:"):
            data.append(line[6:] if line.startswith("data: ") else line[5:])
    if data:
        raw = "\n".join(data)
        if raw.strip() == "[DONE]":
            return
        value = _event(raw)
        yield value
    raise EdgeSpeakError("incomplete_stream")


class EventStream(Iterator[dict[str, Any]]):
    """Iterate API events; use a with block when stopping before exhaustion.

    Closing a stream releases its HTTP connection and upload file descriptors.
    It does not guarantee that already-started server inference is cancelled.
    """

    def __init__(self, client, response, files, wire_format):
        self._client = client
        self._wire_format = wire_format
        self._closed_by_client = False
        self._events = _events(response, wire_format)
        self._finalizer = weakref.finalize(self, _dispose, response, files, client._owner_pid)

    def __iter__(self):
        return self

    def __next__(self):
        if self._closed_by_client:
            raise EdgeSpeakError("stream_closed")
        if not self._finalizer.alive:
            raise StopIteration
        try:
            self._client._check_open()
            value = next(self._events)
            terminal = ((self._wire_format == "ndjson" and value.get("task") == "align"
                         and isinstance(value.get("segments"), list))
                        or (self._wire_format == "sse" and value.get("type") == "transcript.text.done"))
            if terminal:
                self.close()
            return value
        except httpx.TimeoutException:
            self.close()
            raise EdgeSpeakError("request_timeout") from None
        except httpx.HTTPError:
            self.close()
            raise EdgeSpeakError("connection_failed") from None
        except BaseException:
            self.close()
            raise

    def _close_from_client(self):
        self._closed_by_client = self._finalizer.alive
        self.close()

    def close(self):
        self._finalizer()

    def __enter__(self):
        if not self._finalizer.alive:
            raise RuntimeError("Event stream is closed.")
        return self

    def __exit__(self, *_):
        self.close()

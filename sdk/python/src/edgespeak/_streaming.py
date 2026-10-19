"""Closeable iterators for gateway SSE protocols and NDJSON alignment."""
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
    event_name = None
    def frame(raw, name):
        if raw.strip() == "[DONE]":
            if wire_format not in ("sse", "chat"):
                raise EdgeSpeakError("incomplete_stream")
            return None
        value = _event(raw)
        if name == "error" or value.get("type") == "error":
            raise payload_error(value)
        if name and "type" not in value and wire_format not in ("chat", "sse"):
            value["type"] = name
        if wire_format == "responses":
            if value.get("type") == "response.failed":
                result = value.get("response")
                error = result.get("error") if isinstance(result, dict) else None
                raise payload_error({"error": error})
            if value.get("type") == "response.incomplete":
                raise EdgeSpeakError("incomplete_response")
        return value

    for line in response.iter_lines():
        if wire_format == "ndjson":
            if line.strip():
                yield _event(line)
        elif not line:
            if data:
                raw = "\n".join(data)
                data.clear()
                value = frame(raw, event_name)
                event_name = None
                if value is None:
                    return
                yield value
            else:
                event_name = None
        elif line.startswith("event:"):
            event_name = line[6:].lstrip(" ")
        elif line.startswith("data:"):
            data.append(line[6:] if line.startswith("data: ") else line[5:])
    if data:
        value = frame("\n".join(data), event_name)
        if value is None:
            return
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

    def __iter__(self) -> EventStream:
        return self

    def __next__(self) -> dict[str, Any]:
        if self._closed_by_client:
            raise EdgeSpeakError("stream_closed")
        if not self._finalizer.alive:
            raise StopIteration
        try:
            self._client._check_open()
            value = next(self._events)
            terminal = ((self._wire_format == "ndjson" and value.get("task") == "align"
                         and isinstance(value.get("segments"), list))
                        or (self._wire_format == "sse" and value.get("type") == "transcript.text.done")
                        or (self._wire_format == "responses" and value.get("type") == "response.completed")
                        or (self._wire_format == "messages" and value.get("type") == "message_stop"))
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

    def close(self) -> None:
        self._finalizer()

    def __enter__(self) -> EventStream:
        if not self._finalizer.alive:
            raise RuntimeError("Event stream is closed.")
        return self

    def __exit__(self, *_) -> None:
        self.close()

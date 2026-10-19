"""Closeable iterators for gateway SSE protocols and NDJSON alignment."""
from __future__ import annotations

import json
import os
import re
import weakref
from typing import Any, Iterator

import httpx

from ._errors import EdgeSpeakError, payload_error, protocol_error


def _dispose(response, files, owner_pid):
    if os.getpid() != owner_pid:
        return
    try:
        response.close()
    finally:
        files.close()


def _event(raw, *, protocol_errors=False):
    try:
        value = json.loads(raw)
    except ValueError:
        raise EdgeSpeakError("invalid_response") from None
    if not isinstance(value, dict):
        raise EdgeSpeakError("invalid_response")
    if "error" in value and (not protocol_errors or value["error"] is not None):
        raise (protocol_error(value) if protocol_errors else payload_error(value))
    return value


def _sse_lines(response):
    """SSE line endings are CR/LF only; Unicode separators remain JSON text."""
    pending = []
    skip_lf = False
    for chunk in response.iter_text():
        if skip_lf and chunk.startswith("\n"):
            chunk = chunk[1:]
        skip_lf = False
        start = 0
        for separator in re.finditer(r"\r\n|\r|\n", chunk):
            pending.append(chunk[start:separator.start()])
            yield "".join(pending)
            pending.clear()
            start = separator.end()
            skip_lf = separator.group() == "\r" and start == len(chunk)
        pending.append(chunk[start:])
    if any(pending):
        yield "".join(pending)


def _events(response, wire_format):
    data = []
    event_name = None
    def frame(raw, name):
        if raw.strip() == "[DONE]":
            if wire_format not in ("sse", "chat"):
                raise EdgeSpeakError("incomplete_stream")
            return None
        value = _event(raw, protocol_errors=wire_format in ("chat", "responses", "messages"))
        if wire_format in ("chat", "responses", "messages") and (name == "error" or value.get("type") == "error"):
            raise (protocol_error(value) if wire_format in ("chat", "responses", "messages") else payload_error(value))
        if name and "type" not in value and wire_format not in ("chat", "sse"):
            value["type"] = name
        if wire_format == "responses":
            if value.get("type") == "response.failed":
                result = value.get("response")
                error = result.get("error") if isinstance(result, dict) else None
                raise protocol_error({"error": error})
            if value.get("type") == "response.incomplete":
                raise EdgeSpeakError("incomplete_response")
        return value

    lines = _sse_lines(response) if wire_format in ("chat", "responses", "messages") else response.iter_lines()
    for line in lines:
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

"""Closeable iterators for gateway SSE protocols and NDJSON alignment."""
from __future__ import annotations

import json
import os
import re
import weakref
from typing import Iterator
from ._responses import GatewayEvent

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
    if value.get("error") is not None:
        raise (protocol_error(value) if protocol_errors else payload_error(value))
    return value


class LineDecoder:
    """Incremental CR/LF-only splitting; Unicode separators remain data."""
    def __init__(self):
        self.pending = []
        self.skip_lf = False

    def feed(self, chunk):
        if self.skip_lf and chunk.startswith("\n"):
            chunk = chunk[1:]
        self.skip_lf = False
        start = 0
        for separator in re.finditer(r"\r\n|\r|\n", chunk):
            self.pending.append(chunk[start:separator.start()])
            yield "".join(self.pending)
            self.pending.clear()
            start = separator.end()
            self.skip_lf = separator.group() == "\r" and start == len(chunk)
        self.pending.append(chunk[start:])

    def finish(self):
        if any(self.pending):
            yield "".join(self.pending)
        self.pending.clear()


class EventDecoder:
    def __init__(self, wire_format):
        self.wire_format = wire_format
        self.data = []
        self.name = None
        self.done = False

    def _frame(self, raw, name):
        wire_format = self.wire_format
        if raw.strip() == "[DONE]":
            if wire_format not in ("sse", "chat"):
                raise EdgeSpeakError("incomplete_stream")
            self.done = True
            return None
        value = _event(raw, protocol_errors=wire_format in ("chat", "responses", "messages"))
        if wire_format in ("chat", "responses", "messages") and (name == "error" or value.get("type") == "error"):
            raise protocol_error(value)
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

    def feed(self, line):
        if self.wire_format == "ndjson":
            return _event(line) if line.strip() else None
        if not line:
            value = self._frame("\n".join(self.data), self.name) if self.data else None
            self.data.clear()
            self.name = None
            return value
        if line.startswith("event:"):
            self.name = line[6:].lstrip(" ")
        elif line.startswith("data:"):
            self.data.append(line[6:] if line.startswith("data: ") else line[5:])
        return None

    def finish(self):
        if self.data:
            value = self._frame("\n".join(self.data), self.name)
            self.data.clear()
            return value
        return None


def terminal_event(value, wire_format):
    return ((wire_format == "ndjson" and value.get("task") == "align" and isinstance(value.get("segments"), list))
            or (wire_format == "sse" and value.get("type") == "transcript.text.done")
            or (wire_format == "responses" and value.get("type") == "response.completed")
            or (wire_format == "messages" and value.get("type") == "message_stop"))


def _events(response, wire_format):
    lines = LineDecoder()
    decoder = EventDecoder(wire_format)
    for chunk in response.iter_text():
        for line in lines.feed(chunk):
            value = decoder.feed(line)
            if decoder.done:
                return
            if value is not None:
                yield value
    for line in lines.finish():
        value = decoder.feed(line)
        if decoder.done:
            return
        if value is not None:
            yield value
    value = decoder.finish()
    if value is not None:
        yield value
    if not decoder.done:
        raise EdgeSpeakError("incomplete_stream")


class EventStream(Iterator[GatewayEvent]):
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

    def __next__(self) -> GatewayEvent:
        if self._closed_by_client:
            raise EdgeSpeakError("stream_closed")
        if not self._finalizer.alive:
            raise StopIteration
        try:
            self._client._check_open()
            value = next(self._events)
            terminal = terminal_event(value, self._wire_format)
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

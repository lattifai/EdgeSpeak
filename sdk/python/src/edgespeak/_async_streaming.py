"""Native async event streams with the shared gateway protocol decoder."""
from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, Generator
import httpx

from ._errors import EdgeSpeakError
from ._responses import GatewayEvent
from ._streaming import LineDecoder, EventDecoder, terminal_event


class AsyncEventStream(AsyncIterator[GatewayEvent]):
    """Use async with, especially when stopping before a terminal event.

    Closing releases the HTTP slot. It does not promise remote cancellation
    or refund of account usage. Upload resources are released before events.
    """
    def __init__(self, client, response, wire_format, release):
        self._client = client
        self._response = response
        self._wire_format = wire_format
        self._release = release
        self._closed = False
        self._closed_by_client = False
        self._iterator = self._events()

    async def _events(self):
        lines = LineDecoder()
        decoder = EventDecoder(self._wire_format)
        async for chunk in self._response.aiter_text():
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

    def __aiter__(self) -> AsyncEventStream:
        return self

    async def __anext__(self) -> GatewayEvent:
        self._client._check_identity()
        if self._closed_by_client:
            raise EdgeSpeakError("stream_closed")
        if self._closed:
            raise StopAsyncIteration
        self._client._check_open()
        task = self._client._enter_operation()
        try:
            value = await self._iterator.__anext__()
            if terminal_event(value, self._wire_format):
                await self.aclose()
            return value
        except httpx.TimeoutException:
            await self.aclose()
            raise EdgeSpeakError("request_timeout") from None
        except httpx.HTTPError:
            await self.aclose()
            raise EdgeSpeakError("connection_failed") from None
        except BaseException:
            await self.aclose()
            raise
        finally:
            self._client._leave_operation(task)

    async def aclose(self) -> None:
        self._client._check_identity()
        if not self._closed:
            self._closed = True
            try:
                await self._response.aclose()
            finally:
                self._release()

    async def __aenter__(self) -> AsyncEventStream:
        self._client._check_open()
        if self._closed:
            raise RuntimeError("Event stream is closed.")
        return self

    async def __aexit__(self, *_) -> None:
        await self.aclose()


class AsyncStreamRequest(Awaitable[AsyncEventStream]):
    """Lazy single-use stream opener: await it or use async with directly."""
    def __init__(self, open_stream: Callable[[], Awaitable[AsyncEventStream]]):
        self._open_stream = open_stream
        self._used = False
        self._stream: AsyncEventStream | None = None

    async def _open(self) -> AsyncEventStream:
        if self._used:
            raise RuntimeError("AsyncStreamRequest can only be opened once; create a new request.")
        self._used = True
        self._stream = await self._open_stream()
        return self._stream

    def __await__(self) -> Generator[Any, None, AsyncEventStream]:
        return self._open().__await__()

    async def __aenter__(self) -> AsyncEventStream:
        return await self._open()

    async def __aexit__(self, *_) -> None:
        if self._stream is not None:
            await self._stream.aclose()

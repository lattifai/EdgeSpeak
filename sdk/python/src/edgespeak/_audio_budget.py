"""Per-client upload admission. This accounts for payloads, not process RSS."""
from __future__ import annotations

import asyncio
import threading

DEFAULT_IN_FLIGHT_AUDIO_BYTES = 512 * 1024 * 1024


def positive_limit(value: int | None, name: str, *, optional: bool = True) -> None:
    if value is None and optional:
        return
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer" + (" or None." if optional else "."))


class AudioBudget:
    def __init__(self, limit: int | None):
        positive_limit(limit, "max_in_flight_audio_bytes")
        self.limit = limit
        self.used = 0
        self._closed = False
        self._condition = threading.Condition()
        self._waiters: set[tuple[asyncio.AbstractEventLoop, asyncio.Future]] = set()

    def _check(self, size: int) -> None:
        if self._closed:
            raise RuntimeError("EdgeSpeak client is closed.")
        if self.limit is not None and size > self.limit:
            raise ValueError(f"Audio batch uses {size} bytes, exceeding max_in_flight_audio_bytes={self.limit}; reduce the batch or increase this SDK budget. Gateway limits still apply.")

    def acquire(self, size: int) -> AudioLease:
        with self._condition:
            while True:
                self._check(size)
                if self.limit is None or self.used + size <= self.limit:
                    self.used += size
                    return AudioLease(self, size)
                self._condition.wait()

    async def acquire_async(self, size: int) -> AudioLease:
        loop = asyncio.get_running_loop()
        while True:
            with self._condition:
                self._check(size)
                if self.limit is None or self.used + size <= self.limit:
                    self.used += size
                    return AudioLease(self, size)
                future = loop.create_future()
                entry = (loop, future)
                self._waiters.add(entry)
            try:
                await future
            finally:
                with self._condition:
                    self._waiters.discard(entry)

    @staticmethod
    def _wake(future: asyncio.Future) -> None:
        if not future.done():
            future.set_result(None)

    def _notify(self) -> None:
        self._condition.notify_all()
        for loop, future in self._waiters:
            if not loop.is_closed():
                loop.call_soon_threadsafe(self._wake, future)

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._notify()


class AudioLease:
    def __init__(self, budget: AudioBudget, size: int):
        self._budget = budget
        self._size = size
        self._closed = False

    def close(self) -> None:
        with self._budget._condition:
            if not self._closed:
                self._closed = True
                self._budget.used -= self._size
                self._budget._notify()


class UploadStream:
    """Mixin-free helper used by sync and async body adapters."""
    def __init__(self, stream, resources):
        self.stream = stream
        self.resources = resources

    def chunks(self):
        try:
            yield from self.stream
        finally:
            self.resources.close()

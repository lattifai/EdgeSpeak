"""Cancellation-safe draining of local cleanup tasks (Python 3.10 compatible)."""
import asyncio


async def settle(future):
    while not future.done():
        try:
            await asyncio.shield(future)
        except asyncio.CancelledError:
            continue
        except BaseException:
            break
    return future.result()


async def finish_cleanup(awaitable):
    task = asyncio.ensure_future(awaitable)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await settle(task)
        finally:
            raise

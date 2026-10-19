"""Shared client/owned-serve concurrency contract."""
from __future__ import annotations

MAX_CONCURRENCY = 64  # Mirrors runtime-contract HEADLESS_MAX_CONCURRENCY; parity tested.


def validate_concurrency(value: int | None) -> None:
    if value is not None and (type(value) is not int or not 1 <= value <= MAX_CONCURRENCY):
        raise ValueError(f"max_concurrency must be an integer within [1, {MAX_CONCURRENCY}] or None.")


def execution_request(method: str, path: str) -> bool:
    # Model lifecycle/control must remain reachable while generation streams run.
    return method.upper() not in ("GET", "HEAD", "OPTIONS") and not path.lstrip("/").startswith("models/")

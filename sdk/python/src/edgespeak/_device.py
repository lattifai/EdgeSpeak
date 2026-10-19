"""Validate SDK-owned runtime selection without probing or mutating the host."""
from __future__ import annotations

import platform
import re


def normalize_device(device: str | None) -> str | None:
    if device is None:
        return None
    if not isinstance(device, str) or len(device) > 32:
        raise ValueError("device must be cpu, cuda, cuda:<N>, metal (mps), or auto.")
    value = device.lower()
    if value == "mps":
        value = "metal"
    if value not in ("auto", "cpu", "cuda", "metal"):
        match = re.fullmatch(r"cuda:([0-9]+)", value)
        if match is None or int(match[1]) > 0xffffffff:
            raise ValueError("device must be cpu, cuda, cuda:<N>, metal (mps), or auto; N is a non-negative 32-bit integer.")
        value = f"cuda:{int(match[1])}"
    system = platform.system()
    if value.startswith("cuda") and system == "Darwin":
        raise ValueError("CUDA is unavailable on macOS; use device='metal', 'cpu', or 'auto'.")
    if value == "metal" and system != "Darwin":
        raise ValueError("Metal (mps) is only available on macOS; use device='cpu', 'cuda', or 'auto'.")
    return value

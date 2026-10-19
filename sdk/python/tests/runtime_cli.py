"""Resolve the real runtime for integration tests; never skip missing prerequisites."""
from functools import lru_cache
from pathlib import Path
import os

from edgespeak._bootstrap import _compatible, ensure_cli


@lru_cache(maxsize=1)
def resolve_cli():
    """Prefer this workspace's compatible build, else normal SDK discovery/install."""
    executable = "edgespeak-cli.exe" if os.name == "nt" else "edgespeak-cli"
    candidate = Path(__file__).resolve().parents[4] / "code/desktop/target/debug" / executable
    if candidate.is_file():
        if not _compatible(candidate):
            raise RuntimeError("The workspace CLI is incompatible; rebuild it before integration testing.")
        return str(candidate)
    return str(ensure_cli())

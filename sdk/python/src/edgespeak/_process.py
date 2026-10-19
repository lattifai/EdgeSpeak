"""Lifecycle of a CLI service owned exclusively by this client."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import re
import secrets
import subprocess
import threading
import weakref
from urllib.parse import urlsplit

from ._concurrency import validate_concurrency
from ._errors import API_KEYS_URL, valid_account_key


_owned_processes = weakref.WeakSet()
_process_lock = threading.Lock()


def _after_fork_child():
    # Child workers must not retain the write end of the parent's lifetime lease.
    # Popen stdin is unbuffered, so close does not take a inherited buffer lock.
    for process in list(_owned_processes):
        if process.stdin is not None:
            process.stdin.close()
    _owned_processes.clear()
    _process_lock.release()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(before=_process_lock.acquire,
                        after_in_parent=_process_lock.release,
                        after_in_child=_after_fork_child)


class RuntimeStartError(RuntimeError):
    """The installed CLI could not start the SDK protocol."""


def _read_ready(stream, messages):
    try:
        line = stream.readline(65537)
        if len(line) > 65536:
            raise ValueError("oversized ready event")
        messages.put(json.loads(line))
        # Keep stdout open and drained; native libraries may emit later output.
        while stream.read(8192):
            pass
    except (ValueError, OSError):
        if messages.empty():
            messages.put(None)
    finally:
        stream.close()


def stop_process(process: subprocess.Popen, owner_pid: int) -> None:
    # A forked Python child must never shut down its parent's service.
    if os.getpid() != owner_pid:
        return
    with _process_lock:
        if process.stdin is not None:
            process.stdin.close()
        _owned_processes.discard(process)
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


def start_process(startup_timeout: float, api_key: str | None = None,
                  device: str | None = None, max_concurrency: int | None = None):
    validate_concurrency(max_concurrency)
    token = secrets.token_urlsafe(32)
    env = dict(os.environ)
    # SDK always owns its runtime; inherited gateway routing must not redirect it.
    env.pop("EDGESPEAK_BASE_URL", None)
    env.pop("EDGESPEAK_MCP_BIN", None)
    env["EDGESPEAK_API_KEY"] = token
    if api_key is not None:
        env["EDGESPEAK_ACCESS_TOKEN"] = api_key
    if "EDGESPEAK_ACCESS_TOKEN" in env:
        if not valid_account_key(env["EDGESPEAK_ACCESS_TOKEN"]):
            raise ValueError(f"The CLI account credential must be an API KEY starting with esak_. Create one at {API_KEYS_URL}; set EDGESPEAK_API_KEY or pass api_key.")
        env.pop("EDGESPEAK_LICENSE_KEY", None)
    from ._bootstrap import ensure_cli, compatible_version
    cli = ensure_cli()
    command = [str(Path(cli)) if os.path.dirname(str(cli)) else str(cli), "serve", "--sdk"]
    if max_concurrency is not None:
        try:
            probe = subprocess.run([command[0], "serve", "--help"], env=env,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=min(startup_timeout, 10), check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise RuntimeStartError("Cannot verify CLI max_concurrency support; install a compatible CLI.") from None
        if probe.returncode != 0 or b"--max-concurrency" not in probe.stdout + probe.stderr:
            raise RuntimeStartError("CLI does not support max_concurrency; update to a CLI with serve --max-concurrency support.")
        command.extend(["--max-concurrency", str(max_concurrency)])
    if device is not None:
        command.extend(["--device", device])
    process_options = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
                       if os.name == "nt" else {"start_new_session": True})
    try:
        # Serialize fork with both pipe creation/registration and lease closure.
        # Popen's exec-only child path does not run Python at-fork callbacks.
        with _process_lock:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, env=env, shell=False,
                close_fds=True, bufsize=0, **process_options,
            )
            _owned_processes.add(process)
    except OSError:
        raise RuntimeStartError("Cannot launch the detected EdgeSpeak CLI. Check local execution permissions.") from None
    owner_pid = os.getpid()
    messages = queue.Queue(maxsize=1)
    threading.Thread(target=_read_ready, args=(process.stdout, messages), daemon=True).start()
    try:
        event = messages.get(timeout=startup_timeout)
        if event is None and process.poll() is not None:
            raise RuntimeStartError(f"CLI exited before ready (exit code {process.returncode})."
                                    + (f" Check runtime support for device={device!r}." if device is not None else ""))
        if not isinstance(event, dict) or event.get("protocol") != "edgespeak-sdk-v2" or event.get("event") != "ready":
            raise RuntimeStartError("CLI does not support the SDK ready protocol; update the CLI.")
        if not compatible_version(str(event.get("version", ""))):
            raise RuntimeStartError("The running CLI version does not meet SDK requirements.")
        url = event.get("base_url")
        if not isinstance(url, str):
            raise RuntimeStartError("Invalid CLI ready address.")
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError:
            raise RuntimeStartError("Invalid CLI ready address.") from None
        if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
                or not port or parsed.path != "/v1"
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise RuntimeStartError("Invalid CLI ready address.")
        if process.poll() is not None:
            raise RuntimeStartError("CLI exited during startup.")
        return process, owner_pid, url, token
    except BaseException as error:
        stop_process(process, owner_pid)
        if isinstance(error, queue.Empty):
            raise RuntimeStartError("CLI startup timed out.") from None
        raise

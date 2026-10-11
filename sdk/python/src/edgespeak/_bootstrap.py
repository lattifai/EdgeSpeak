"""Discover a compatible CLI, installing the official standalone runtime if needed."""
from __future__ import annotations

from contextlib import contextmanager
import logging
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import tempfile
import time
import threading

import httpx

from ._process import RuntimeStartError

# This floor and the SDK protocol check are both required: early 0.6.3 builds
# predate serve --sdk. Raise the floor when the SDK relies on newer CLI features.
MIN_CLI_VERSION = "0.6.3"
SDK_PROTOCOL = "edgespeak-sdk-v1"
_LOG = logging.getLogger("edgespeak")
_lock_streams = set()
_stream_guard = threading.Lock()


def _release_inherited_locks():
    # Raw FileIO has no buffered-I/O mutex inherited from another thread.
    for stream in _lock_streams:
        stream.close()
    _lock_streams.clear()
    _stream_guard.release()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(before=_stream_guard.acquire,
                        after_in_parent=_stream_guard.release,
                        after_in_child=_release_inherited_locks)


@contextmanager
def _lock_file(path):
    with _stream_guard:
        stream = path.open("a+b", buffering=0)
        _lock_streams.add(stream)
    try:
        yield stream
    finally:
        with _stream_guard:
            _lock_streams.discard(stream)
            stream.close()


def _environment():
    # Neither discovery nor installation needs account/gateway credentials or
    # inherited runtime/download overrides. In particular, probe the sibling host.
    return {k: v for k, v in os.environ.items() if not k.upper().startswith("EDGESPEAK_")}


def _candidates():
    home = Path.home()
    executable = "edgespeak-cli.exe" if os.name == "nt" else "edgespeak-cli"
    found = shutil.which(executable)
    paths = [Path(found)] if found else []
    # Only parse the exact launcher format emitted by the official Windows
    # installer, never execute arbitrary shell text from a .cmd file.
    if os.name == "nt":
        shim = shutil.which("edgespeak-cli.cmd")
        if shim:
            try:
                match = re.fullmatch(r'@echo off\s+"([^"\r\n]+)" %\*\s*', Path(shim).read_text(encoding="ascii"))
                if match and Path(match[1]).is_absolute():
                    paths.append(Path(match[1]))
            except (OSError, UnicodeError):
                pass
    try:
        generation = json.loads((home / ".edgespeak/sdk/current.json").read_text())["generation"]
        if isinstance(generation, str) and re.fullmatch(r"runtime-[a-zA-Z0-9_-]+", generation):
            paths.insert(0, home / ".edgespeak/sdk" / generation / "runtime/Resources" / executable)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    paths += [home / ".edgespeak/runtime/Resources" / executable,
              home / ".local/bin" / executable]
    if platform.system() == "Darwin":
        paths += [base / "EdgeSpeak.app/Contents/Resources/edgespeak-cli"
                  for base in (Path("/Applications"), home / "Applications")]
    if os.name == "nt":
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData/Local"))
        paths += [local / "EdgeSpeak/bin" / executable]
    return dict.fromkeys(path.resolve() for path in paths if path.is_file())


def compatible_version(version: str) -> bool:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    return bool(match and tuple(map(int, match.groups())) >= tuple(map(int, MIN_CLI_VERSION.split("."))))


def _compatible(cli: Path) -> bool:
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    try:
        version = subprocess.run([str(cli), "--version"], stdin=subprocess.DEVNULL,
                                 capture_output=True, timeout=10, env=_environment(), **options)
        match = re.fullmatch(rb"edgespeak(?:-cli)?\s+(\d+)\.(\d+)\.(\d+)\s*", version.stdout.strip())
        if version.returncode or not match:
            return False
        if tuple(map(int, match.groups())) < tuple(map(int, MIN_CLI_VERSION.split("."))):
            return False
        help_result = subprocess.run([str(cli), "serve", "--help"], stdin=subprocess.DEVNULL,
                                     capture_output=True, timeout=10, env=_environment(), **options)
        return help_result.returncode == 0 and re.search(rb"(?<!\S)\[?--sdk(?:\]|\s|$)", help_result.stdout) is not None
    except (OSError, subprocess.TimeoutExpired):
        return False


def _find():
    return next((cli for cli in _candidates() if _compatible(cli)), None)


@contextmanager
def _installation_lock():
    # OS locks survive stale lock files and are released even if Python is killed.
    directory = Path.home() / ".edgespeak/sdk"
    directory.mkdir(parents=True, exist_ok=True)
    with _lock_file(directory / "install.lock") as stream:
        if stream.seek(0, 2) == 0:
            stream.write(b"\0")
        deadline = time.monotonic() + 1800
        while True:
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeStartError("Timed out waiting for CLI installation.") from None
                time.sleep(.1)
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def _install():
    system, machine = platform.system(), platform.machine().lower()
    # The official installer distinguishes Intel Macs from Rosetta on Apple Silicon.
    if (system, machine) not in {("Darwin", "arm64"), ("Darwin", "x86_64"), ("Linux", "x86_64"),
                               ("Windows", "amd64"), ("Windows", "x86_64")}:
        raise RuntimeStartError("Automatic CLI installation is unavailable on this platform.")
    windows = system == "Windows"
    shell = shutil.which("powershell.exe" if windows else "sh")
    if not shell:
        raise RuntimeStartError("The system shell required by the CLI installer is unavailable.")
    suffix = ".ps1" if windows else ".sh"
    _LOG.warning("Installing a compatible EdgeSpeak CLI (requires >= %s and %s).",
                 MIN_CLI_VERSION, SDK_PROTOCOL)
    root = Path.home() / ".edgespeak/sdk"
    root.mkdir(parents=True, exist_ok=True)
    # Never replace a running runtime. Each attempt has its own directory/lock;
    # failed or interrupted attempts cannot block a later generation.
    directory = Path(tempfile.mkdtemp(prefix="runtime-", dir=root))
    script = directory / ("install" + suffix)
    try:
        with httpx.Client(timeout=60, follow_redirects=False) as http:
            response = http.get("https://edgespeak.com/install" + suffix)
            response.raise_for_status()
            if (not response.content or len(response.content) > 1024 * 1024
                    or b"EDGESPEAK_SDK_INSTALL_V1" not in response.content):
                raise RuntimeStartError("The official installer does not yet support SDK-managed installation. A matching installer release is required.")
            script.write_bytes(response.content)
    except httpx.HTTPError:
        raise RuntimeStartError("Cannot download the official CLI installer. Check your network and retry.") from None
    env = _environment()
    env["EDGESPEAK_DATA_DIR"] = str(directory / "data")
    env["EDGESPEAK_RUNTIME_DIR"] = str(directory / "runtime")
    env["EDGESPEAK_INSTALL_DIR"] = str(directory / "bin")
    env["EDGESPEAK_INSTALL_CONTEXT"] = "sdk"
    env["EDGESPEAK_LEGACY_INSTALL_PATH"] = str(directory / "unused-legacy-entry")
    command = ([shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)]
               if windows else [shell, str(script)])
    options = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
               if windows else {"start_new_session": True})
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, env=env, **options)
    try:
        code = process.wait(timeout=1200)
    except BaseException:
        # Bounded cleanup, with no Popen context manager (its exit waits forever).
        try:
            if windows:
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            else:
                os.killpg(process.pid, signal.SIGKILL)
        except (OSError, subprocess.TimeoutExpired):
            pass
        try:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
        raise
    if code:
        raise RuntimeStartError("Official CLI installation failed. Check network, disk space and installation permissions, then retry.")
    cli = directory / "runtime/Resources" / ("edgespeak-cli.exe" if windows else "edgespeak-cli")
    if not _compatible(cli):
        raise RuntimeStartError(f"The available CLI does not meet SDK requirements: CLI >= {MIN_CLI_VERSION} with {SDK_PROTOCOL}. A compatible official CLI release is required.")
    # Publish only after validation. Existing generations remain valid for live
    # clients and other SDK versions; never delete them during an update.
    pointer = directory / "current.json"
    pointer.write_text(json.dumps({"generation": directory.name}))
    os.replace(pointer, root / "current.json")
    return cli


def ensure_cli() -> Path:
    """Reuse compatible installations without network access; bootstrap once otherwise."""
    cli = _find()
    if cli:
        return cli
    try:
        with _installation_lock():
            cli = _find()  # Another Python process may have just finished installing.
            return cli if cli else _install()
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeStartError("CLI installation could not finish. Check network and local installation permissions, then retry.") from None

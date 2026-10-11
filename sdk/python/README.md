# EdgeSpeak Python SDK

Development candidate **0.1.0a1**. Not yet published to PyPI. Requires a CLI build
that supports `edgespeak-cli serve --sdk`; released older CLIs do not implement
this handshake. Python 3.10 or later is required.

The SDK automatically discovers the CLI in PATH and standard installation locations.
It requires **CLI >= 0.6.3 with the `edgespeak-sdk-v1` protocol**; the version floor
is exported as `edgespeak.MIN_CLI_VERSION`. Compatible installations work without
a network check. Missing or incompatible installations trigger the official stable
installer, which installs a new runtime generation under `~/.edgespeak/sdk/`.
The installer uses the same download verification and platform selection as the
[CLI installation guide](https://edgespeak.com/docs/cli). It preserves system CLI entries, PATH, and running runtime generations.
SDK processes serialize installation; afterward the version and SDK capability are
checked again. If the official CLI or installer release still lacks SDK support, startup fails with
a clear `RuntimeStartError` rather than repeatedly reinstalling. There is no
`cli_path` parameter. No installation occurs at import time or in attached gateway mode.

Automatic installation supports macOS Apple Silicon, Linux x86_64 and Windows x64.
It requires network access, writable user installation directories and the platform
installer prerequisites (POSIX shell/curl/tar or Windows PowerShell). Installation
has a separate 20-minute timeout; `startup_timeout` applies to service readiness.
Account keys are not sent to the installer, and bootstrap does not update models
or access the account vault. Supply an account API key before inference, or reuse
a device already activated by the desktop app or an existing CLI installation. This package contains no CLI, native engine, or models.

For local development:

```sh
python -m pip install -e ./sdk/python
```

```python
from edgespeak import EdgeSpeak

with EdgeSpeak() as client:
    transcript = client.transcribe("meeting.wav", language="en", diarize=True)
    aligned = client.align("meeting.wav", text="The verbatim spoken words.")
    speakers = client.diarize("meeting.wav", num_speakers=2)
    voice = client.speaker_embedding("speaker.wav")
    similarity = client.speaker_similarity(
        voice["data"][0]["embedding"], voice["data"][0]["embedding"]
    )
```

Responses preserve the gateway JSON, including nested timestamps in **seconds**.
Language codes are validated by the runtime. Omit `language` for runtime detection;
do not translate the reference transcript before forced alignment. File errors
raise Python `OSError`; gateway errors raise `EdgeSpeakError` with `code` and
`status_code`. Server message text is not copied into exceptions.

## Lifetime and ownership

Create one client and reuse it. By default the SDK launches its own authenticated
loopback service through the CLI on an OS-assigned port. Models load on demand;
first inference can include a model download. No service is created at import time.

Use a `with` block or call `close()`. Closing is idempotent. Garbage collection and
normal interpreter exit also trigger cleanup, but their timing is not a substitute
for explicit ownership. Cleanup can block while the child exits: 15 seconds before
terminate, then two 3-second fallback waits. The CLI's stdin lifetime lease also
handles a killed Python parent; a 10-second watchdog bounds a stuck HTTP drain.
Native Host and worker shutdown remains the CLI runtime's responsibility and can
finish after the HTTP listener closes.

The SDK starts the owned CLI in a separate process group so a caught Ctrl+C in an
interactive Python session does not silently destroy it. Forked children cannot
use the inherited client; create a new client in each worker. Prefer multiprocessing
`spawn`, as for other threaded Python libraries.

To attach to a separately managed gateway:

```python
with EdgeSpeak(
    base_url="http://127.0.0.1:1118/v1",
    gateway_key="your-local-gateway-token",
) as client:
    result = client.transcribe("meeting.wav")
```

Closing an attached client never stops the external service. Remote URLs require
HTTPS. Redirects and environment proxies are disabled; environment CA overrides
are also ignored. `gateway_key` is a **gateway token**, not an account API Key.
For an SDK-owned service, pass an account key explicitly:

```python
import os
with EdgeSpeak(api_key=os.environ["EDGESPEAK_ACCESS_TOKEN"]) as client:
    result = client.transcribe("meeting.wav")
```

The CLI receives this key through its environment, never its arguments. The key
and session credential remain in process memory; existing desktop credentials
are preserved. Usage remains in the shared machine ledger. An inherited
`EDGESPEAK_ACCESS_TOKEN` is also supported by the CLI. Account keys cannot be
used as gateway tokens or with an attached service. This integration requires
the matching, unreleased account backend and CLI changes; production deployment
and end-to-end account authentication validation are still pending.

Account keys require online authorization and cannot enable offline mode. New
server requests reject revoked keys; a previously issued credential lasts at
most five minutes. Revocation does not stop inference already in progress.

SDK and desktop sessions on the same machine share a device slot. Closing the SDK
or revoking a key does not remove that device; remove an unused machine in the
account page’s device management to free its slot. Account keys remain valid until
expiry or explicit revocation, including after a password reset.

`timeout` defaults to 600 seconds per HTTP I/O phase, not a total job deadline.
A timeout is not proof that server-side inference has stopped. `startup_timeout`
defaults to 30 seconds after CLI discovery/installation.

## CLI requirement for each SDK release

Each SDK release ships its own `MIN_CLI_VERSION` in `src/edgespeak/_bootstrap.py`.
Raise that constant when a new SDK release needs a newer CLI. At startup,
`ensure_cli()` compares installed versions against this SDK's requirement and
calls the encapsulated `_install()` function if no compatible installation exists.
That function installs the **latest official stable CLI**, not the minimum version,
and validates it before use. An installed version at or above the minimum is reused
when it supports the required SDK protocol. Future-version numbers used in tests
are examples, not release announcements.

## Validation

```sh
python -m unittest discover -s sdk/python/tests -v
EDGESPEAK_TEST_CLI=/absolute/path/edgespeak-cli \
  python -m unittest discover -s sdk/python/tests -v
```

The opt-in CLI suite checks service readiness, authentication, independent client
lifetimes, attachment, and Python death/interrupt behavior. It does not run model
inference. macOS model acceptance has separately covered transcription, alignment,
diarization, embeddings, similarity, and owned process-tree cleanup. Windows
lifecycle acceptance has separately verified isolation, authentication, attachment,
close/GC cleanup, and service exit after forcibly terminating Python. Windows
model inference and Linux acceptance have not been verified for this candidate.

Automatic installation has local fixture coverage; the new installer mode and
matching CLI still require publication and end-to-end download acceptance. Windows
and Linux automatic installation have not yet been validated on those platforms.

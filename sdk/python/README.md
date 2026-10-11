# EdgeSpeak Python SDK

Development candidate **0.1.0a1**. Not yet published to PyPI. Requires a CLI build
that supports `edgespeak-cli serve --sdk`; released older CLIs do not implement
this handshake. Python 3.10 or later is required.

Install the CLI using the [EdgeSpeak installation guide](https://edgespeak.com/docs/cli)
and activate this device with `edgespeak-cli login` before inference. This package
does not contain the CLI, native engine, or models.

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

`timeout` defaults to 600 seconds per HTTP I/O phase, not a total job deadline.
A timeout is not proof that server-side inference has stopped. `startup_timeout`
defaults to 30 seconds. Configure `cli_path` when the CLI is not on `PATH`.

## Validation

```sh
python -m unittest discover -s sdk/python/tests -v
EDGESPEAK_TEST_CLI=/absolute/path/edgespeak-cli \
  python -m unittest discover -s sdk/python/tests -v
```

The opt-in CLI suite checks service readiness, authentication, independent client
lifetimes, attachment, and Python death/interrupt behavior. It does not run model
inference. Windows lifecycle and real-model acceptance remain separate checks.

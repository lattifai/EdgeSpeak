# EdgeSpeak Python SDK

Development candidate **0.1.0a1**. Not yet published to PyPI. Requires a CLI build
that supports `edgespeak-cli serve --sdk`; released older CLIs do not implement
this handshake. Python 3.10 or later is required.

The SDK automatically discovers the CLI in PATH and standard installation locations.
It requires **CLI >= 0.6.3 with the `edgespeak-sdk-v2` protocol**; the version floor
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
with EdgeSpeak(api_key=os.environ["EDGESPEAK_API_KEY"]) as client:
    result = client.transcribe("meeting.wav")
```

The CLI receives this key through its environment, never its arguments. The key
and session credential remain in process memory; existing desktop credentials
are preserved. Usage remains in the shared machine ledger. An inherited
`EdgeSpeak()` reads `EDGESPEAK_API_KEY` automatically when `api_key` is omitted.
The SDK translates it to the CLI account credential internally. For attached
services, pass `gateway_key`; the examples read `EDGESPEAK_GATEWAY_KEY`. Account keys cannot be
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

## Speech methods

All methods return the API JSON unchanged, except `transcribe(response_format="text")`, which returns a string. Times are in seconds. See the [audio API](https://edgespeak.com/docs/api-audio), [alignment API](https://edgespeak.com/docs/api-align), and [text API](https://edgespeak.com/docs/api-text) for model requirements and parameter constraints.

| Method | Options and behavior |
| --- | --- |
| `transcribe(audio, ...)` | `model`, `language`, `diarize`, `response_format`, `prompt`, `timestamp_granularities`, `word_timestamp_enabled`, `candidates`, `semantic_sentence_enabled`, `min_chars`, `max_chars`, `start_margin`, `end_margin`, `stream` |
| `align(audio, ...)` | `text` or `text_file`, `text_format`, `model`, `language`, `search_effort`, `threshold`, `start` + `end`, `protected_terms`, `text_normalization`, `audio_track`, `audio_channel`, `semantic_sentence_enabled`, `min_chars`, `max_chars`, `start_margin`, `end_margin`, `progress` |
| `segment(text, ...)` | Plain text or `segments`, `threshold`, `paragraph_threshold`, `min_chars`, `max_chars`, `start_margin`, `end_margin`, `options` |
| `diarize(audio, ...)` | Independent speaker turns; optional `num_speakers` from 1 to 32 |
| `speaker_embedding(audio, ...)` | One path or a list of paths; optional `model`; batch results retain input order |
| `speaker_similarity(a, b, ...)` | Two embeddings produced by the same model; optional `model` |

`diarize=True` selects `diarized_json` in transcription. It cannot be combined with another response format. Speaker-count selection belongs to `diarize()`: the transcription and alignment APIs do not accept `num_speakers`. The alignment API does not currently perform speaker diarization.

## Reference files and alignment

```python
with EdgeSpeak() as client:
    aligned = client.align(
        "speech.wav", text_file="captions.ass", language="en",
        search_effort="auto", semantic_sentence_enabled=True,
        min_chars=10, max_chars=80,
    )
    from_json = client.align(
        "speech.wav", text={"segments": [{"text": "The exact words spoken."}]}
    )
```

`text_file` reads a local UTF-8 file (optional BOM, up to 64 MiB). Supported extensions are `.txt`, `.json`, `.srt`, `.ass`, and `.ssa`; `text_format` can override the extension. JSON accepts the API caption structure with `segments[].text` (or a top-level `text` fallback). To pass subtitle contents directly, use `text=contents, text_format="srt"` (or `json`, `ass`, `ssa`). Supply exactly one of `text` and `text_file`.

The SDK uploads file contents, never a local `text_path`. The CLI's shared parser extracts spoken text, discards existing subtitle timing, and ignores ASS styles, comments, and drawing commands. Alignment computes new timing from the audio. This requires the matching unreleased CLI/API `text_format` support.


Attached gateways must advertise `alignment_reference_formats` in `/v1/health.capabilities` before the SDK sends JSON/SRT/ASS/SSA. Older gateways raise `unsupported_gateway_capability`; upgrade the gateway. `text_format` cannot be combined with server-side `text_path`.

## Semantic sentences and paragraphs

```python
with EdgeSpeak() as client:
    sentences = client.segment("First sentence. A second sentence.", max_chars=80)
    paragraphs = client.segment("A longer passage.", paragraph_threshold=0.6)
    transcript = client.transcribe("meeting.wav", diarize=True)
    captions = client.segment(segments=transcript["segments"], min_chars=10, max_chars=80)
```

Plain-text mode produces sentences. Timed-segment mode retains timing and speaker information through the API's resegmentation behavior. Paragraph mode accepts plain text only and cannot be combined with timed segments, length limits, or margins. `semantic_sentence_enabled=True` also enables sentence segmentation directly during transcription or alignment; omitted settings inherit runtime defaults.

## Progress and streaming

```python
with EdgeSpeak() as client:
    with client.align("speech.wav", text="The exact words spoken.", progress=True) as events:
        for event in events:
            print(event)
```

Alignment yields progress/stage events followed by the final alignment object. A progress value of 1 is not the final result. `transcribe(stream=True)` yields SSE events and currently requires an attached desktop gateway; the headless CLI does not support streaming transcription. Streaming transcription requires `response_format="json"` and does not support diarization or timestamp granularities. The API rejects incompatible combinations.

Use a stream context manager when stopping early. Closing the client also closes its streams; further iteration on an unfinished stream raises `stream_closed`. A final result releases resources immediately. A connection that ends without a terminal event raises `EdgeSpeakError` with code `incomplete_stream`. Closing a stream releases the connection and upload files, but does not guarantee cancellation of inference already running.

## Runnable examples

The [Python SDK examples](https://github.com/lattifai/EdgeSpeak/tree/main/sdk/python/examples) cover transcription, alignment, semantic sentences/paragraphs, timed captions, speaker turns, batch embeddings, and similarity. Run each file with `--help` for its options. Use `--base-url` to attach to a gateway; otherwise the example starts and closes its own CLI service.

```bash
python sdk/python/examples/transcribe.py meeting.wav --diarize --semantic
python sdk/python/examples/align.py speech.wav --text-file captions.srt --progress
python sdk/python/examples/segment.py --text "First sentence. Another sentence." --max-chars 80
python sdk/python/examples/segment.py --segments-file transcript.json --max-chars 80
python sdk/python/examples/speakers.py meeting.wav alice.wav bob.wav --num-speakers 2
```

## Account key expiry and allowance

A key may be set to **Never expires**. This removes the key expiry date only; account entitlement, subscription usage limits, online authorization, and revocation still apply. Temporary authorization credentials remain limited to five minutes.

The SDK preserves the gateway's `error.code` as `exception.code`. Use `exception.reason` to distinguish `api_key_expired`, `api_key_revoked`, and `usage_exhausted`. Quota errors expose a validated `exception.resets_at` when the server supplies the next reset time; the existing gateway code remains `license_required` for that response. No arbitrary server message is echoed.

API keys share the account subscription allowance and its billing period with desktop usage. Creating or switching keys does not reset usage. The next subscription period restores its allowance according to the account plan.

For an SSH tunnel to a GPU server, see [remote GPU attachment](examples/remote-gpu.md). Audio is uploaded to that server; closing the SDK does not stop the remote service.

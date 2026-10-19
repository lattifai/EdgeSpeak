# EdgeSpeak Python SDK

Transcribe, align, segment text, identify speaker turns, and compare voice embeddings
through the local EdgeSpeak CLI. Audio is processed by the connected runtime;
the SDK does not bundle engines or models.

[简体中文](https://github.com/lattifai/EdgeSpeak/blob/main/sdk/python/README.zh-CN.md) · [Documentation](https://edgespeak.com/docs/python-sdk) · [Examples](https://github.com/lattifai/EdgeSpeak/tree/main/sdk/python/examples)

## Installation

Requires Python 3.10+. One pure-Python wheel serves all supported Python versions
and platforms. Install from PyPI:

```bash
python -m pip install edgespeak
```

The SDK discovers an installed CLI and automatically
installs the latest official stable CLI if none meets its requirements.
Automatic installation supports macOS Apple Silicon, Linux x86_64, and Windows x64
and requires network access. Models load on demand; first use may download a model.

## Create and configure an API KEY

1. Sign in to [EdgeSpeak → API KEY](https://edgespeak.com/account/api-keys).
2. Create an API KEY, choose an expiry (including never expires) and usage limit,
   and copy the full key shown at creation.
3. Set `EDGESPEAK_API_KEY` in the environment running Python:

```bash
export EDGESPEAK_API_KEY="your API KEY"
```

In Windows PowerShell, use `$env:EDGESPEAK_API_KEY="your API KEY"`.
`EdgeSpeak()` reads this variable automatically; you can also pass `EdgeSpeak(api_key=...)`.
An API KEY authorizes programmatic access and is different from a product activation
key. Keep it out of source control. An already activated local device can also
reuse its existing authorization.

API KEY access requires online authorization and shares the account subscription
allowance and billing period with desktop usage. Creating a key does not reset usage.
Never expires only removes the expiry date; entitlement, usage limits, and revocation
still apply.

## Quick start

```python
from edgespeak import EdgeSpeak

with EdgeSpeak() as client:
    transcript = client.transcribe("meeting.wav", language="en", diarize=True)
    print(transcript["text"])
    aligned = client.align("speech.wav", text="The exact words spoken.")
    speakers = client.diarize("meeting.wav", num_speakers=2)
```

Reuse a client and use `with` or `close()` to release its owned service.
Results are usually dictionaries with timestamps in seconds;
`response_format="text"` returns a string. Alignment needs the spoken words in
the original language. It also accepts `text_file="captions.srt"`, supporting
TXT, JSON, SRT, ASS, and SSA; existing subtitle timing is recomputed from the audio.

| Method | Purpose |
| --- | --- |
| `transcribe(audio, ...)` | Transcription, optional speaker labels and word timestamps |
| `align(audio, text=... / text_file=..., ...)` | Align a transcript or subtitles to audio |
| `segment(text, ...)` / `segment(segments=..., ...)` | Segment text or resegment timed captions |
| `diarize(audio, ...)` | Independent speaker diarization |
| `speaker_embedding(audio, ...)` | Single or batch voice embeddings |
| `speaker_similarity(a, b, ...)` | Compare two embeddings from the same model |

Typed options include `timestamp_granularities=["word", "segment"]` and
`search_effort="auto"`. Use `help(EdgeSpeak.transcribe)` or `help(EdgeSpeak.align)`
for parameter details. Alignment does not perform diarization; choose a speaker
count with the independent `diarize()` method.

## Progress

```python
with EdgeSpeak() as client:
    with client.align("speech.wav", text="The exact words spoken.", progress=True) as events:
        for event in events:
            print(event)
```

Progress events precede the final result. Close the stream when stopping early;
closing does not guarantee cancellation of inference already running.
`transcribe(stream=True)` currently requires an attached desktop gateway and
does not support diarization or timestamp granularities.

## Compute device

Set the device when the SDK starts its own CLI service:

```python
with EdgeSpeak(device="cpu") as client:
    transcript = client.transcribe("meeting.wav")
# Linux/Windows: device="cuda" or "cuda:1" to select a GPU index.
# macOS: device="metal" (alias "mps").
```

Names are case-insensitive. Omit `device` or use `"auto"` to preserve the CLI's
default/environment policy. CUDA requires a compatible CLI/runtime and GPU;
Metal requires macOS. Hardware availability and model backend support are checked
by the runtime. CUDA indices follow CUDA device enumeration, not necessarily
system monitor numbering. This is a service-wide preference; each capability
retains its supported backends (CPU-only processing remains CPU-only).

An explicit `device`, including `"auto"`, cannot be combined with `base_url`:
the SDK raises `ValueError` before connecting. Existing gateways manage their
own devices; configure the gateway itself instead.

## Connect to an existing gateway

Set `base_url` to use an already running EdgeSpeak desktop or CLI gateway instead
of starting another CLI service:

```python
import os
from edgespeak import EdgeSpeak

with EdgeSpeak(
    base_url="http://127.0.0.1:1118/v1",
    gateway_key=os.environ["EDGESPEAK_GATEWAY_KEY"],
) as client:
    result = client.transcribe("meeting.wav")
```

`EDGESPEAK_GATEWAY_KEY` is an example variable for storing the gateway token; the
SDK does not read it automatically. Obtain the token from the gateway administrator.
Omit `gateway_key` if the local gateway has token authentication disabled.

- **The client does not need an account API KEY.** Do not pass `api_key` together
  with `base_url`; the SDK rejects that combination. Attached mode ignores the
  client's `EDGESPEAK_API_KEY`, does not send or modify it, and does not change
  the existing gateway's authorization.
- **The gateway still needs its own valid authorization.** Requests use the
  account or device authorization configured in that runtime. Metered usage is
  accounted for under its plan and usage rules. A gateway token controls access;
  it does not select a billing account. The SDK adds no separate charge and does
  not bypass quotas. For a gateway operated by someone else, confirm any fees
  with its operator.
- **Connections to remote gateways require HTTPS.** HTTP is allowed for loopback
  hosts (`localhost`, `127.0.0.1`, `::1`); LAN IPs and other non-loopback gateways
  also require HTTPS. Audio is uploaded to the remote gateway server.
- Closing the client does not stop an existing gateway. Environment proxies are
  ignored; create a separate client in each process.

When starting a CLI gateway directly, the CLI's `EDGESPEAK_API_KEY` means a
**gateway token**. In SDK-owned mode, the same variable means an **account API KEY**.
Do not interchange them. Changing the client's environment does not reconfigure
an already running gateway, but a CLI started later from that environment inherits it.

## Errors

`EdgeSpeakError` exposes `code`, `status_code`, `reason`, and `resets_at`.
Its `reason` distinguishes `api_key_expired`, `api_key_revoked`, and `usage_exhausted`.
Changing keys does not restore account allowance. Invalid arguments raise `ValueError`,
file errors raise `OSError`, and CLI startup failures raise `RuntimeStartError`.

`timeout` defaults to 600 seconds per HTTP I/O phase, not a total task deadline.
`startup_timeout` defaults to 30 seconds and excludes CLI installation time.

### Audio upsampling

```python
from pathlib import Path

with EdgeSpeak() as client:
    Path("output.wav").write_bytes(client.upsample("input.wav", sample_rate=24_000))
```

`sample_rate` defaults to 48,000 Hz and accepts positive integer rates up to
48,000 Hz. Higher-than-source rates use AudioVAE at 48 kHz, followed by
band-limited downsampling when needed. Lower-than-source rates only downsample;
equal rates preserve the WAV bytes. Independent calls consume no account usage.
Each channel is processed independently; channel count, order and valid WAV layout are preserved.
Input must be 1–8 channel PCM16 or float32 WAV, at most 32 MiB and 120 seconds. First
upsampling may download the AudioVAE model. The result is WAV bytes; the caller
chooses whether and where to save them. Requires a CLI/gateway build containing
`POST /v1/audio/upsamplings`; this capability is not in older released builds.

CLI equivalent: `edgespeak-cli upsample input.wav --output output.wav --sample-rate 24000`.

## Dual-input alignment (candidate gateway)

The candidate SDK exposes `diff_align(audio, reference_segments=[{"text": "Official words"}], transcript_segments=[{"text": "ASR words"}], offset=0.0)`. Both arrays accept nonempty `text` and optional `speaker`; native acoustic diff chooses the output. This requires `/v1/health.capabilities` to include `diff_alignment`; it is not available in older released gateways and never falls back to `align()`.

Each request is limited to 300 seconds including padding (413 on excess). Long recordings must be windowed by the consumer while preserving both texts. Result times include `offset`; `original_index` is local to the request reference array, or -1. Speaker labels come from input text, not voice identification. Normalization, extended search and streaming options are not supported here.

### Audio formats and encoding options (unreleased)

`upsample` accepts WAV (PCM16/24/32, Float32), FLAC, MP3, M4A/AAC, ADTS AAC, Ogg/Vorbis and Ogg/Opus files, detected by content. It returns WAV bytes by default. `response_format` selects `wav`, `flac`, `mp3`, `m4a`, `aac`, `ogg` (Vorbis), or `opus` (Ogg/Opus).

```python
Path("output.mp3").write_bytes(client.upsample("input.m4a",
    sample_rate=48_000, response_format="mp3", bitrate=192_000))
Path("output.wav").write_bytes(client.upsample("input.flac",
    sample_rate=24_000, pcm_format="s24"))
```

`bitrate` is the total target bit/s for lossy output only; WAV/FLAC reject it. `pcm_format` accepts WAV `s16/s24/s32/f32` or FLAC `s16/s24`; lossy formats reject it. Opus output requires 48000 Hz; MP3 supports mono/stereo. Unsupported rate, layout or encoding combinations fail explicitly. Codec availability depends on the gateway machine; missing codecs cause an error. The SDK installs no extra audio libraries and never silently downmixes.

Limits remain 32 MiB, 120 seconds and 1–8 channels. Speaker-position semantics and synchronization are preserved; storage order may change according to the target container standard. Lossy codecs may add delay/padding; prefer WAV/FLAC for sample-accurate timelines. Results are bytes in the requested format, never automatically saved, and consume no account usage.

## Text, catalog and usage

The following additions require a matching SDK build and gateway capabilities.
New method names follow HTTP paths; existing methods keep their names.

```python
from edgespeak import slice_utf8

with EdgeSpeak() as client:
    result = client.text_normalizations("The fee is $25.", language="en", top_k=1)
    print(result["alternatives"][0]["text"])  # converted text; result["text"] is original
    for span in result["alternatives"][0]["spans"]:
        print(slice_utf8(result["text"], span["start_byte"], span["end_byte"]))
    sentences = client.segment("First sentence. Second sentence.")
    catalog = client.models()
    totals = client.usage(refresh=True)
```

Use `mode="itn"` for spoken → written text. Normalization and segmentation use
text allowance; they do not consume audio-duration allowance. UTF-8 byte offsets
must not be used as Python string indices. `slice_utf8` validates byte boundaries.
`usage()` preserves `null` values for unlimited allowances.

`health()`, `models()`, `models_running()` and `models_downloads()` return gateway
JSON without starting inference. `models_load(model)`, `models_unload(model)`,
`models_download(model)` and `models_download_cancel(model)` are explicit actions;
a download call starts a job and does not wait for completion. Poll `models_downloads()`.

## Text generation

```python
with EdgeSpeak() as client:
    with client.responses("Explain this sentence.", model="your-text-model", stream=True) as events:
        for event in events:
            print(event)
```

`chat_completions(messages, model=...)`, `responses(input, model=...)` and
`messages(messages, model=..., max_tokens=...)` follow their respective API schemas.
They return JSON by default or `EventStream` with `stream=True`. Structured inputs
can include images when the selected model supports them; these APIs generate
text, not images. `options` forwards protocol extensions without overriding named
parameters, including omitted ones. `messages()` sends `anthropic-version` (default
`2023-06-01`); use `anthropic_version`/`anthropic_beta` for protocol headers.
`tokenize(content, model=...)` returns a JSON object or a raw integer token array;
for another provider schema, omit content and pass its fields in `options`.

Streams use their own protocol terminators: Chat `[DONE]`, Responses
`response.completed`, Messages `message_stop`.
Failures, incomplete Responses and EOF without a terminator raise `EdgeSpeakError`.
Keep already-yielded events if partial output matters; non-stream incomplete Responses
raise without returning their partial result.
Use a `with` block or `close()` when exiting early. Closing a stream does not
promise to cancel started inference or erase already consumed usage.

Local generation uses the gateway account's allowance. Calls forwarded to a
configured external provider follow that provider's billing; the SDK adds no
second charge. Model/download/health queries and tokenization consume no
EdgeSpeak inference allowance; external providers may charge separately. Realtime and MCP remain separate gateway protocols; use
their documented clients rather than synchronous SDK methods.

# EdgeSpeak Python SDK

Transcribe, align, segment text, identify speaker turns, and compare voice embeddings
through the local EdgeSpeak CLI. Audio is processed by the connected runtime;
the SDK does not bundle engines or models.

[简体中文](https://github.com/lattifai/EdgeSpeak/blob/main/sdk/python/README.zh-CN.md) · [Documentation](https://edgespeak.com/docs/python-sdk) · [Examples](https://github.com/lattifai/EdgeSpeak/tree/main/sdk/python/examples)

## Installation

Requires Python 3.10+. One pure-Python wheel serves all supported Python versions
and platforms. Once published to PyPI, install with:

```bash
python -m pip install edgespeak
```

The first PyPI release is pending. Until then, run `python -m pip install ./sdk/python`
from the repository root. The SDK discovers an installed CLI and automatically
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

## Progress and existing gateways

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

Attach with `EdgeSpeak(base_url="http://127.0.0.1:1118/v1", gateway_key=...)`.
`gateway_key` is a gateway token, not an account API KEY. Closing an attached client
does not stop the gateway. Remote URLs require HTTPS and audio is uploaded to that
server. Environment proxies are ignored. Create a separate client in each process;
do not reuse a client inherited across fork.

## Errors

`EdgeSpeakError` exposes `code`, `status_code`, `reason`, and `resets_at`.
Its `reason` distinguishes `api_key_expired`, `api_key_revoked`, and `usage_exhausted`.
Changing keys does not restore account allowance. Invalid arguments raise `ValueError`,
file errors raise `OSError`, and CLI startup failures raise `RuntimeStartError`.

`timeout` defaults to 600 seconds per HTTP I/O phase, not a total task deadline.
`startup_timeout` defaults to 30 seconds and excludes CLI installation time.

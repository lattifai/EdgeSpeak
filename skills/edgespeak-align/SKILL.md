---
name: edgespeak-align
version: 0.4.0
minCliVersion: 0.7.6
description: Force-align audio/video against a known transcript on-device via EdgeSpeak to produce word-level timestamps (start, end, score) for karaoke captions, word-accurate SRT, voice-over sync, and clip extraction. The default model covers 346 languages and mixed-language text; the transcript can be plain text, SRT, or caption JSON, and lyrics with section headers follow the sung order. Use when the user already has the transcript/script/lyrics/subtitles and wants to know exactly when each word is spoken.
---

# EdgeSpeak Align

Force-align an audio/video file against a **reference transcript you already have**, producing **word-level timestamps** — when each word starts and ends. Runs **entirely on-device**; the audio never leaves the machine. Under the hood it calls `edgespeak-cli align`. When the EdgeSpeak desktop app is running, the CLI talks to its local gateway (OpenAI-compatible, `127.0.0.1:1117`) and reuses the warm model (proxy mode); when the app is not running, the CLI launches the bundled on-device engine itself (standalone mode). **Standalone is a normal mode, not an error.**

**Version compatibility.** The frontmatter pins this skill's `version` and the oldest CLI it is written against (`minCliVersion`). If `edgespeak-cli --version` reports something older, run `edgespeak-cli update` (or re-run the installer) before relying on the flags documented here. Same-numbered builds can still differ, so `--help` is the tiebreaker: a command or flag documented here but missing from the installed `--help` also means update — don't route around it.

Alignment ≠ transcription. Transcription guesses the words; alignment is given the words and only finds the timing. If the user does **not** have the text yet, use `edgespeak-transcribe` instead.

## Explicit remote GPU deployment

The local instructions below are the default. If the user explicitly requests
an existing remote EdgeSpeak gateway (including a configured
`EDGESPEAK_BASE_URL`), use that gateway instead of starting a local model.
Audio/text is then uploaded to the chosen server; do not describe this mode as
keeping data on the client machine. Do not silently fall back to local inference
when the remote request fails.

Use the matching public Python SDK and the
[SSH attachment guide](https://github.com/lattifai/EdgeSpeak/blob/main/sdk/python/examples/remote-gpu.md). An SSH tunnel
can expose the remote loopback listener at `http://127.0.0.1:18118/v1`; direct
remote URLs require HTTPS. Pass any gateway token via an environment variable.
The account API key is not a gateway token.

```python
import os
from edgespeak import EdgeSpeak

with EdgeSpeak(base_url=os.environ["EDGESPEAK_BASE_URL"],
               gateway_key=os.environ.get("EDGESPEAK_GATEWAY_KEY"),
               timeout=1800) as client:
    result = client.align("speech.wav", text="The exact words spoken.")
```

Closing this attached client does not stop the remote service. A timeout does
not cancel inference: check the server before retrying a long job. Keep the API
response unchanged; convert consumer-specific schemas in the consumer.

## Dual-input acoustic alignment (Python SDK / HTTP only)

When both an edited official transcript and ASR captions exist, use the Python SDK
(0.6.8 or newer) `client.diff_align(audio, reference_segments=[{"text": "..."}],
transcript_segments=[{"text": "..."}], offset=0.0)`. The attached gateway must
advertise `diff_alignment` in `/v1/health.capabilities` (gateway 0.6.8 or newer;
older gateways are rejected). The HTTP endpoint is `POST /v1/audio/diff-alignments`.
There is no `edgespeak-cli` command or MCP tool for it.
Both arrays reach the native acoustic diff engine. Never replace this call with
single-input alignment or choose one transcript silently.

Each segment accepts only nonempty `text` and optional `speaker`. Send at most
300 seconds of audio per request, including any context padding; excess audio
returns 413. `offset` shifts result times into the source media timeline. Long
recordings need consumer-side windows that preserve both input texts; ambiguous
unbounded windows must fail, not drop text. Do not use the single-input long-audio
advice below for this endpoint.

The response contains native `segments[].words`, `original_index` (index in this
request's reference array, or -1), and optional input speaker labels.
`speaker_source="input_text"` is provenance, not verified voice identity. Native
output may differ from either input. Keep the response intact and do downstream
schema conversion and speaker verification in the consumer. Text normalization,
extended search, progress streams, and single-input byte mappings are unsupported.

## Inputs to confirm

- Media path to align.
- Reference transcript/script/lyrics/subtitle text (inline, or a `.txt`, `.srt`, or caption `.json` file).
- Spoken language, if the user knows it.
- For lyrics with `[Verse]` / `[Chorus]` style headers: whether to follow the sung order (default) or align the text exactly as written.
- Desired output: stdout text, `.txt`, `.json`, or `.srt`.
- Optional protected terms for brand names, jargon, names, or tokens that must stay verbatim.

## How to do it

1. Confirm two inputs: the **media file** and the **reference text** (a string, or a text file to read).
2. Check the runtime first:

   ```bash
   edgespeak-cli status
   ```

   - **Command not found** → the CLI isn't installed. Tell the user and point them to the install steps at https://edgespeak.com/docs/cli#install (a self-contained one-line installer on macOS Apple Silicon and Linux x86_64, with CUDA auto-detected on Linux; a PowerShell installer on Windows x64; the EdgeSpeak desktop app also ships the CLI). The user runs the installer; do not run it yourself.
   - **License not activated / locked** → run `edgespeak-cli login`, sign in on the official website, and approve this device to sync the account’s Free or subscription plan, or its historical buyout entitlement. Free does not require a purchase. Use `edgespeak-cli activate <KEY>` only with an existing key. Non-interactive runs (agents, pipes, CI) fail fast with `license_required`; activate first, then rerun.
   - **Gateway not running (standalone)** → this is fine; `align` is local-only and runs against the bundled on-device engine. When the app is running it reuses the warm gateway (proxy) instead.
3. Run `edgespeak-cli align`:

   ```bash
   edgespeak-cli align <audio-or-video-file> --text-file script.txt [-o out.json] [--format txt|json|srt]
   ```

   - Prefer `--text-file` / `-T` for reference text files. It reads `.txt`, `.srt`, or caption `.json` (`segments[].text`, or a top-level `text`) without pushing long text through argv. Only the spoken text is used: any timing already in the subtitles is discarded and recomputed from the audio.
   - For short snippets, inline text is also supported: `--text "<reference transcript>"`.
   - Without `-o`: result prints to **stdout**.
   - `-o out.srt` / `out.json` / `out.txt`: the **extension decides the format**. Use `--format` only when the path's extension is ambiguous.
   - **Do not silently overwrite an existing output file.** The CLI clobbers an existing `-o` target without warning. If the requested path already exists and the user did not explicitly ask to overwrite or regenerate that exact file, confirm with the user first (or agree on a different path); if you cannot ask, write to a new non-conflicting path and say so in your answer.
   - `json` is the gateway alignment response shape — `{ task: "align", duration, text, segments[].words[], usage }`, words in seconds with a `[0,1]` `score`; `srt` gives one cue per word; `txt` is human-readable.
   - `--protected-terms "<term>"` (repeatable) keeps brand names / jargon verbatim through normalization, so they don't get split or rewritten before matching.
   - `--language <tag>` is optional. The default model (Lattice-2) covers 346 languages, so any well-formed language code works (`zh`, `en-US`, `ja`, `yue`, …), including codes outside the 82-language catalog on https://edgespeak.com/docs/languages. Omit it to let the runtime infer the language from the reference text. **If the user tells you the language, pass it**: text alone can confuse languages that share a script (Cantonese written in Chinese characters can be read as Mandarin). Pass `und` for mixed-language text such as Chinese with English words, for romanized text, or for a language that has no code: each word is then matched against every language's pronunciations.
   - `--pronunciation-mode default|mandarin_cantonese`: by default, Chinese or Cantonese alignment already considers both Mandarin and Cantonese readings. `mandarin_cantonese` only makes that explicit; there is no need to pass it.
   - **Lyrics follow the sung order by default.** When the text is lyrics — at least two lines that are only a `[Section]` header, such as `[Verse 1]` / `[Chorus]` — the CLI first transcribes the audio, repeats the lines that are sung again, removes lines that are not sung, and aligns that expanded text. The result's `text` is the text actually aligned, and its `follow_audio` object records the changes (see "Output shape"). This extra transcription counts toward usage. Pass `--no-follow-audio` to align the text exactly as given, for example when the user wants the lyric sheet's own line order or has already expanded the repeats.
   - `--search-effort standard|extended|auto` sets how widely alignment searches (default `standard`). `extended` searches wider: slower, and it needs extra memory. `auto` runs `standard` first and reruns with `extended` only when the failure says a retry is recommended. Keep the default for normal runs; see "When alignment fails" for when to use the other two.
   - `--device cpu|cuda|cuda:<N>|metal|auto` picks the compute backend (case-insensitive; `cuda:<N>` selects GPU N, `metal` (alias `mps`) is macOS, `gpu` means Metal on macOS / CUDA elsewhere). **Standalone mode only** — with the app gateway reachable the flag errors explicitly; an unavailable backend also errors rather than silently falling back.
   - `--license-key <KEY>` (alias `--key`) only to pass a license key explicitly for this run; normally activation already covers it.
4. Use the word timings to build captions, cut clips, or sync a voice-over.

## Output shape (json)

CLI `json` output is **identical to the gateway's `POST /v1/audio/alignments` response** — proxy mode passes the API response through verbatim, standalone constructs the same shape:

```json
{
  "task": "align",
  "duration": 19.6855,
  "text": "as you can see it's easy ...",
  "segments": [
    { "id": 0, "start": 0.02, "end": 19.52, "text": "as you can see it's easy ...",
      "words": [ { "word": "as", "start": 0.02, "end": 0.18, "score": 0.92 } ] }
  ],
  "usage": { "type": "duration", "seconds": 19.6855 }
}
```

- The aligned words live under `segments[].words[]` (usually a single segment spanning the aligned content; collect words across all segments to get the full word list). There is no flat top-level `words[]`.
- `score` is a `[0, 1]` confidence (higher = more confident). Use it to flag low-score words, but do not treat it as a calibrated percentage. **The distribution depends on the alignment model**, so do not hard-code a threshold or expect the same numbers across models — compare words within one run instead.
- `language` is the resolved language code when the runtime knows it (for example `ja` or `yue`); it can be absent, so don't require it. JSON key order is not guaranteed (may be alphabetical); parse by key, not position.
- `follow_audio` appears only when the text was recognized as lyrics and lyric expansion was on. `applied: true` means the text was expanded: `lines[].source_line` maps each aligned line back to a 0-based line of the original text (section headers count as lines), with `repeat: true` on lines sung again, `missing` lists original lines removed as not sung, and `uncertain[]` (`kind`: `extra` or `missing`, `line`, optional `start` / `end`) marks spots that were left unchanged for the user to check by ear. `applied: false` means the sung order could not be determined and the original text was aligned as given. Mention `missing` and `uncertain` lines to the user instead of hiding them.

## When alignment fails

A failed alignment is an **error**, never a result: `edgespeak-cli align` exits non-zero, prints nothing on stdout, and writes no `-o` file. Older runtimes could report success with an empty or whole-clip result; current ones fail instead, so a script that used to "succeed" on a bad pairing can now stop with an error. That is the intended behavior.

On stderr, the line that starts with `error: alignment_failed:` or `error: alignment_search_budget_exceeded:` is stable and meant for parsing — a code followed by a JSON object. Lines before it are progress output:

```text
aligning talk.wav against reference text via http://127.0.0.1:1117/v1 ...
error: alignment_failed: {"reason":"search_incomplete","search_effort_used":"standard","search_path":"whole_audio","retry_recommended":true,"estimated_extra_bytes":3221225472}
Alignment stopped before the end of the reference text, possibly because of music or long silence.
Hint: rerun with --search-effort extended for a wider search (slower; expected to use about 3.0 GiB more memory).
```

The lines after the `error:` line are localized explanations for people; read the code and the JSON, not the prose.

| Code | Meaning |
|---|---|
| `alignment_failed` | Alignment ran but could not place the reference text on the audio. `reason` says how: `search_incomplete` (the search stopped before the end of the text, often because of music or long silence), `no_path` / `no_words` (nothing matched), `collapsed` (the words piled up into an implausibly short span). |
| `alignment_search_budget_exceeded` | A wider search was requested but would need more memory than this machine can spare, so it did not run. |

Fields in the JSON object (each may be absent when the runtime did not report it):

- `retry_recommended` — `true` only when a wider search is expected to help **and** fits in this machine's memory. This is the only signal to decide on a retry; don't infer it from `reason` or the message.
- `estimated_extra_bytes` — the extra memory a wider search is expected to use. It is an estimate for the search itself, not a ceiling for the whole process.
- `search_effort_used` — `standard` or `extended`, the search that actually ran.
- `search_path` — `whole_audio` or `streaming` (long files are aligned in chunks).
- `search_limit` — why a wider search is not available, when it isn't.

What to do:

1. **`retry_recommended: true`** → rerun the same command once with `--search-effort extended`. Tell the user it is slower and quote `estimated_extra_bytes` as the expected extra memory. For unattended batch runs you can pass `--search-effort auto` from the start, which makes that one retry automatically.
2. **`retry_recommended: false` or missing** → do not rerun the same command, with or without `extended`. Check that the reference text really is what is spoken in this file (right file, right language, no missing or extra passages), fix the pairing, and align again.
3. **`alignment_search_budget_exceeded`** → the wider search does not fit in memory. Trim the media to a shorter clip, align it against the matching part of the text, and offset the timings yourself. Don't retry the same command.
4. An `extended` run that still fails with `search_incomplete` comes back with `retry_recommended: false`; there is no wider setting to try. Report the failure.

**Never fabricate timestamps.** Do not fill a failed range with evenly spaced words, fall back to segment timing, or reuse timings from an earlier run on different text. Show the error, say which reason it gave, and stop there if no retry applies.

The same failure reaches every surface in the same shape:

- **MCP `edgespeak_align`** takes an optional `search_effort` argument (`standard` default, `extended`, `auto`), plus `language`, `protected_terms`, `pronunciation_mode`, `text_normalization`, and `follow_audio` (default `true`; pass `false` to align lyrics exactly as given). A failure is a tool error (`isError: true`) whose text is JSON: `{"code": "alignment_failed", "message": "alignment_failed", "alignment": { … }}`, with the same `alignment` fields as above. It never returns words on failure.
- **HTTP `POST /v1/audio/alignments`** takes a `search_effort` form field. A failure is HTTP 422 with `error.code` set to one of the codes above and `error.alignment` holding the fields. A successful response carries `search_effort_used` when the runtime reports it, and `search_retried: true` only when `auto` actually ran the wider search.

## Sentence-level timing (combine with segment)

`align` returns **words**, not sentences. To get sentence/caption-level timing, save the alignment as JSON and re-split it:

1. `edgespeak-cli align <media> --text-file script.txt -o words.json`
2. `edgespeak-cli segment --transcript words.json` — re-splits the text into sentences and re-maps every word timing into them (each sentence's `start` / `end` come from its first/last word; see `edgespeak-segment`). Add `--max-chars` / `--min-chars` for caption-length cues, `-o out.srt` for subtitles directly.

This pairing is the reliable way to get sentence timestamps; `segment` alone on plain text does **not** produce real timings, and manual sentence-onto-words mapping is no longer needed.

## Boundaries / gotchas (read this)

- **Requires `edgespeak-cli`.** If the command isn't found, point the user to https://edgespeak.com/docs/cli#install (a self-contained installer on macOS Apple Silicon, Linux x86_64, and Windows x64; the EdgeSpeak desktop app also ships the CLI) and let them run the installer. If it's found but errors, show the error — **do not fabricate timings under any circumstances**. Alignment failures have their own codes and retry rules; see "When alignment fails".
- **`--search-effort` needs a current runtime.** If `edgespeak-cli align --help` does not list it, run `edgespeak-cli update` before relying on it.
- **First use needs activation.** Run `edgespeak-cli login`, sign in on the official website, and approve this device to sync your Free or subscription plan, or historical buyout entitlement. A purchase is not required for Free. If this machine already has a buyout license, sign in with its purchasing account; a different Key is rejected rather than silently replacing that entitlement. Use `edgespeak-cli activate <KEY>` with an existing key, or pass `--license-key <KEY>` (alias `--key`) for one run. Surface license errors; do not work around them. Interactive standalone commands can offer browser sign-in; non-interactive runs (agents, pipes, CI) fail fast instead of prompting.
- **Pre-download the alignment model for headless machines**: `edgespeak-cli models download EdgeSpeak/Lattice-2` (or `--all`) fetches it ahead of time — standalone only, quit the EdgeSpeak app first.
- **The default alignment model is Lattice-2.** It covers 346 languages, mixed-language text, and `und`. Earlier runtimes defaulted to Lattice-1, which could only align Chinese, English, and German and failed outright on Japanese, Korean, or Cantonese. `align` has **no** `--model` flag, so the CLI always uses the default — a caller that needs Lattice-1 specifically has to send `model` to `POST /v1/audio/alignments` itself. A script written against the old default now gets a different model's timings and a different `score` distribution; say so rather than treating the numbers as comparable.
- **Local-only**: alignment uses the local EdgeSpeak alignment runtime; audio stays on device.
- **The text must roughly match the audio.** Alignment assumes the words are actually spoken; large mismatches (wrong language, missing/extra paragraphs) degrade timing or fail with `alignment_failed`. Lyric repeats and skipped lines are the exception the default lyric expansion handles, and only when the text has section headers. It is robust to minor disfluencies and punctuation, not to substituting a different transcript.
- **No speaker diarization** — alignment times the words; it does not say who spoke them. For speaker-labeled transcription use `edgespeak-transcribe` with `--diarize`.

### Long audio: expect long runtimes, not manual chunking

The engine streams long audio automatically: files longer than ~3 minutes are aligned in fixed-length chunks with bounded peak memory — a few GB (roughly 5 GB measured on an 85-minute file), instead of the 30+ GB an unbounded whole-file lattice would need. Short files are aligned in one globally optimal pass. You do **not** need to pre-split media or do offset arithmetic for memory reasons — align the whole file and let the engine chunk.

The one thing that still scales with duration is **runtime**: a long file takes correspondingly long. That's normal, not a hang — see the timeout section below.

`--search-effort extended` on a long file aligns it in one pass only when that fits in memory; otherwise it fails with `alignment_search_budget_exceeded` instead of running.

### Timeouts and a busy gateway

A real alignment of more than a minute or two of audio can run **longer than a 2-minute command timeout**. Give the command a generous timeout or run it in the background — don't assume a slow run failed. The local gateway is **single-instance and serializes** requests: don't fire many `align`/`segment`/`transcribe` calls at it concurrently, and if a request is killed mid-flight the gateway can be briefly busy/unreachable afterward — re-check `edgespeak-cli status` and retry rather than fabricating timings.

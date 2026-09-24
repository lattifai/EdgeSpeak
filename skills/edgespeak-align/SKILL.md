---
name: edgespeak-align
version: 0.3.0
minCliVersion: 0.5.6
description: Force-align audio/video against a known transcript on-device via EdgeSpeak to produce word-level timestamps (start, end, score) for karaoke captions, word-accurate SRT, dubbing, and clip extraction. Use when the user already has the transcript/script/lyrics and wants to know exactly when each word is spoken.
---

# EdgeSpeak Align

Force-align an audio/video file against a **reference transcript you already have**, producing **word-level timestamps** — when each word starts and ends. Runs **entirely on-device**; the audio never leaves the machine. Under the hood it calls `edgespeak-cli align`. When the EdgeSpeak desktop app is running, the CLI talks to its local gateway (OpenAI-compatible, `127.0.0.1:1117`) and reuses the warm model (proxy mode); when the app is not running, the CLI launches the bundled on-device engine itself (standalone mode). **Standalone is a normal mode, not an error.**

**Version compatibility.** The frontmatter pins this skill's `version` and the oldest CLI it is written against (`minCliVersion`). If `edgespeak-cli --version` reports something older, run `edgespeak-cli update` (or re-run the installer) before relying on the flags documented here. Same-numbered builds can still differ, so `--help` is the tiebreaker: a command or flag documented here but missing from the installed `--help` also means update — don't route around it.

Alignment ≠ transcription. Transcription guesses the words; alignment is given the words and only finds the timing. If the user does **not** have the text yet, use `edgespeak-transcribe` instead.

## Inputs to confirm

- Media path to align.
- Reference transcript/script/lyrics text.
- Desired output: stdout text, `.txt`, `.json`, or `.srt`.
- Optional protected terms for brand names, jargon, names, or tokens that must stay verbatim.

## How to do it

1. Confirm two inputs: the **media file** and the **reference text** (a string, or a text file to read).
2. Check the runtime first:

   ```bash
   edgespeak-cli status
   ```

   - **Command not found** → the CLI isn't installed. On Windows x64, tell the user to install the EdgeSpeak desktop app, which ships the CLI. On macOS Apple Silicon or Linux x86_64, use `curl -fsSL https://edgespeak.com/install.sh | sh` (self-contained, no desktop app needed; on Linux the installer auto-detects NVIDIA GPUs and installs a CUDA-enabled runtime).
   - **License not activated / locked** → run `edgespeak-cli login` to sign in via the browser (purchased accounts activate this machine directly, new accounts start a free 7-day trial; signing in also replaces an anonymous trial with your account credentials), or `edgespeak-cli activate <KEY>` with an existing key. No account and no browser at hand? `edgespeak-cli trial` starts an instant anonymous 7-day trial (device-bound, one per device). Non-interactive runs (agents, pipes, CI) fail fast with `license_required` instead of prompting.
   - **Gateway not running (standalone)** → this is fine; `align` is local-only and runs against the bundled on-device engine. When the app is running it reuses the warm gateway (proxy) instead.
3. Run `edgespeak-cli align`:

   ```bash
   edgespeak-cli align <audio-or-video-file> --text-file script.txt [-o out.json] [--format txt|json|srt]
   ```

   - Prefer `--text-file` / `-T` for reference text files. It reads `.txt`, `.srt`, or caption JSON without pushing long text through argv.
   - For short snippets, inline text is also supported: `--text "<reference transcript>"`.
   - Without `-o`: result prints to **stdout**.
   - `-o out.srt` / `out.json` / `out.txt`: the **extension decides the format**. Use `--format` only when the path's extension is ambiguous.
   - **Do not silently overwrite an existing output file.** The CLI clobbers an existing `-o` target without warning. If the requested path already exists and the user did not explicitly ask to overwrite or regenerate that exact file, confirm with the user first (or agree on a different path); if you cannot ask, write to a new non-conflicting path and say so in your answer.
   - `json` is the gateway alignment response shape — `{ task: "align", duration, text, segments[].words[], usage }`, words in seconds with a `[0,1]` `score`; `srt` gives one cue per word; `txt` is human-readable.
   - `--protected-terms "<term>"` (repeatable) keeps brand names / jargon verbatim through normalization, so they don't get split or rewritten before matching.
   - `--language <tag>` is optional: a BCP-47 tag (`zh`, `en-US`, …) or `und` to state that no language information is available. Omitting it lets the runtime decide, which is the normal path — pass it only when the user states the spoken language and the runtime picked wrong.
   - `--search-effort standard|extended|auto` sets how widely alignment searches (default `standard`). `extended` searches wider: slower, and it needs extra memory. `auto` runs `standard` first and reruns with `extended` only when the failure says a retry is recommended. Keep the default for normal runs; see "When alignment fails" for when to use the other two.
   - `--device cpu|cuda|cuda:<N>|metal|auto` picks the compute backend (case-insensitive; `cuda:<N>` selects GPU N, `metal` is macOS, `gpu` means Metal on macOS / CUDA elsewhere). **Standalone mode only** — with the app gateway reachable the flag errors explicitly; an unavailable backend also errors rather than silently falling back.
   - `--license-key <KEY>` (alias `--key`) only to pass a license key explicitly for this run; normally activation already covers it.
4. Use the word timings to build captions, cut clips, or sync dubbing.

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
- The alignment response carries no `language` key. JSON key order is not guaranteed (may be alphabetical); parse by key, not position.

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

- **MCP `edgespeak_align`** takes an optional `search_effort` argument (`standard` default, `extended`, `auto`). A failure is a tool error (`isError: true`) whose text is JSON: `{"code": "alignment_failed", "message": "alignment_failed", "alignment": { … }}`, with the same `alignment` fields as above. It never returns words on failure.
- **HTTP `POST /v1/audio/alignments`** takes a `search_effort` form field. A failure is HTTP 422 with `error.code` set to one of the codes above and `error.alignment` holding the fields. A successful response carries `search_effort_used` when the runtime reports it, and `search_retried: true` only when `auto` actually ran the wider search.

## Sentence-level timing (combine with segment)

`align` returns **words**, not sentences. To get sentence/caption-level timing, save the alignment as JSON and re-split it:

1. `edgespeak-cli align <media> --text-file script.txt -o words.json`
2. `edgespeak-cli segment --transcript words.json` — re-splits the text into sentences and re-maps every word timing into them (each sentence's `start` / `end` come from its first/last word; see `edgespeak-segment`). Add `--max-chars` / `--min-chars` for caption-length cues, `-o out.srt` for subtitles directly.

This pairing is the reliable way to get sentence timestamps; `segment` alone on plain text does **not** produce real timings, and manual sentence-onto-words mapping is no longer needed.

## Boundaries / gotchas (read this)

- **Requires `edgespeak-cli`.** If the command isn't found, install the EdgeSpeak desktop app on Windows x64, or use `curl -fsSL https://edgespeak.com/install.sh | sh` on macOS Apple Silicon and Linux x86_64 (self-contained, no desktop app needed; CUDA auto-detected on Linux). If it's found but errors, show the error — **do not fabricate timings under any circumstances**. Alignment failures have their own codes and retry rules; see "When alignment fails".
- **`--search-effort` needs a current runtime.** If `edgespeak-cli align --help` does not list it, run `edgespeak-cli update` before relying on it.
- **First use needs activation.** A fresh install activates once via `edgespeak-cli login` (browser sign-in; also upgrades an anonymous trial to your account), `edgespeak-cli activate <KEY>`, or `edgespeak-cli trial` (instant anonymous 7-day trial, no browser or account; one per device). Without it the on-device engine fails with `license_required`; the error carries self-serve guidance plus a purchase link — surface it, don't work around it. In an interactive terminal, standalone commands offer to sign in and continue automatically; non-interactive runs (agents, pipes, CI) fail fast instead of prompting. To pass the key on a single run, use `--license-key <KEY>` (alias `--key`).
- **Pre-download the alignment model for headless machines**: `edgespeak-cli models download lattice-2-aligner` (or `--all`) fetches it ahead of time — standalone only, quit the EdgeSpeak app first.
- **The default alignment model is Lattice-2.** Earlier runtimes defaulted to Lattice-1, which could only align Chinese, English, and German and failed outright on Japanese, Korean, or Cantonese; Lattice-2 covers more languages. `align` has **no** `--model` flag, so the CLI always uses the default — a caller that needs Lattice-1 specifically has to send `model` to `POST /v1/audio/alignments` itself. A script written against the old default now gets a different model's timings and a different `score` distribution; say so rather than treating the numbers as comparable.
- **Local-only**: alignment uses the local EdgeSpeak alignment runtime; audio stays on device.
- **The text must roughly match the audio.** Alignment assumes the words are actually spoken; large mismatches (wrong language, missing/extra paragraphs) degrade timing or fail with `alignment_failed`. It is robust to minor disfluencies and punctuation, not to substituting a different transcript.
- **No speaker diarization** — alignment times the words; it does not say who spoke them. For speaker-labeled transcription use `edgespeak-transcribe` with `--diarize`.

### Long audio: expect long runtimes, not manual chunking

The engine streams long audio automatically: files longer than ~3 minutes are aligned in fixed-length chunks with bounded peak memory — a few GB (roughly 5 GB measured on an 85-minute file), instead of the 30+ GB an unbounded whole-file lattice would need. Short files are aligned in one globally optimal pass. You do **not** need to pre-split media or do offset arithmetic for memory reasons — align the whole file and let the engine chunk.

The one thing that still scales with duration is **runtime**: a long file takes correspondingly long. That's normal, not a hang — see the timeout section below.

`--search-effort extended` on a long file aligns it in one pass only when that fits in memory; otherwise it fails with `alignment_search_budget_exceeded` instead of running.

### Timeouts and a busy gateway

A real alignment of more than a minute or two of audio can run **longer than a 2-minute command timeout**. Give the command a generous timeout or run it in the background — don't assume a slow run failed. The local gateway is **single-instance and serializes** requests: don't fire many `align`/`segment`/`transcribe` calls at it concurrently, and if a request is killed mid-flight the gateway can be briefly busy/unreachable afterward — re-check `edgespeak-cli status` and retry rather than fabricating timings.

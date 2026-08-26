---
name: edgespeak-align
version: 0.1.0
minCliVersion: 0.4.0
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
- `score` is a `[0, 1]` confidence (higher = more confident). Use it to flag low-score words, but do not treat it as a calibrated percentage.
- The alignment response carries no `language` key. JSON key order is not guaranteed (may be alphabetical); parse by key, not position.

## Sentence-level timing (combine with segment)

`align` returns **words**, not sentences. To get sentence/caption-level timing, save the alignment as JSON and re-split it:

1. `edgespeak-cli align <media> --text-file script.txt -o words.json`
2. `edgespeak-cli segment --transcript words.json` — re-splits the text into sentences and re-maps every word timing into them (each sentence's `start` / `end` come from its first/last word; see `edgespeak-segment`). Add `--max-chars` / `--min-chars` for caption-length cues, `-o out.srt` for subtitles directly.

This pairing is the reliable way to get sentence timestamps; `segment` alone on plain text does **not** produce real timings, and manual sentence-onto-words mapping is no longer needed.

## Boundaries / gotchas (read this)

- **Requires `edgespeak-cli`.** If the command isn't found, install the EdgeSpeak desktop app on Windows x64, or use `curl -fsSL https://edgespeak.com/install.sh | sh` on macOS Apple Silicon and Linux x86_64 (self-contained, no desktop app needed; CUDA auto-detected on Linux). If it's found but errors, show the error — **do not fabricate timings under any circumstances**.
- **First use needs activation.** A fresh install activates once via `edgespeak-cli login` (browser sign-in; also upgrades an anonymous trial to your account), `edgespeak-cli activate <KEY>`, or `edgespeak-cli trial` (instant anonymous 7-day trial, no browser or account; one per device). Without it the on-device engine fails with `license_required`; the error carries self-serve guidance plus a purchase link — surface it, don't work around it. In an interactive terminal, standalone commands offer to sign in and continue automatically; non-interactive runs (agents, pipes, CI) fail fast instead of prompting. To pass the key on a single run, use `--license-key <KEY>` (alias `--key`).
- **Pre-download the alignment model for headless machines**: `edgespeak-cli models download lattice-1-aligner` (or `--all`) fetches it ahead of time — standalone only, quit the EdgeSpeak app first.
- **Local-only**: alignment uses the local EdgeSpeak alignment runtime; audio stays on device.
- **The text must roughly match the audio.** Alignment assumes the words are actually spoken; large mismatches (wrong language, missing/extra paragraphs) degrade timing. It is robust to minor disfluencies and punctuation, not to substituting a different transcript.
- **No speaker diarization** — alignment times the words; it does not say who spoke them. For speaker-labeled transcription use `edgespeak-transcribe` with `--diarize`.

### Long audio: expect long runtimes, not manual chunking

The engine streams long audio automatically: files longer than ~3 minutes are aligned in fixed-length chunks with bounded peak memory — a few GB (roughly 5 GB measured on an 85-minute file), instead of the 30+ GB an unbounded whole-file lattice would need. Short files are aligned in one globally optimal pass. You do **not** need to pre-split media or do offset arithmetic for memory reasons — align the whole file and let the engine chunk.

The one thing that still scales with duration is **runtime**: a long file takes correspondingly long. That's normal, not a hang — see the timeout section below.

### Timeouts and a busy gateway

A real alignment of more than a minute or two of audio can run **longer than a 2-minute command timeout**. Give the command a generous timeout or run it in the background — don't assume a slow run failed. The local gateway is **single-instance and serializes** requests: don't fire many `align`/`segment`/`transcribe` calls at it concurrently, and if a request is killed mid-flight the gateway can be briefly busy/unreachable afterward — re-check `edgespeak-cli status` and retry rather than fabricating timings.

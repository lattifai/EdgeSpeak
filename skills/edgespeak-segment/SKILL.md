---
name: edgespeak-segment
version: 0.1.1
minCliVersion: 0.4.0
description: Split a long run of text into natural sentences on-device via EdgeSpeak using a semantic sentence splitter that works on unpunctuated ASR output, or re-segment a word-timed transcript JSON (from transcribe/align) into new sentence boundaries while re-mapping every word timing. Use when the user has raw transcript text, captions, or dictation and wants clean sentence boundaries for subtitles, reading, translation chunks, or further processing — or wants existing timed captions re-split at a different cue length without re-transcribing.
---

# EdgeSpeak Segment

Turn an undifferentiated block of text into **natural sentences**, on-device. This is a **semantic** sentence splitter (a small local model), so it works on **ASR output that has no punctuation or broken punctuation** — where naïve "split on period" fails completely. Under the hood it calls `edgespeak-cli segment`. When the EdgeSpeak desktop app is running, the CLI talks to its local gateway (OpenAI-compatible, `127.0.0.1:1117`) and reuses the warm model (proxy mode); when the app is not running, the CLI launches the bundled on-device engine itself (standalone mode). **Standalone is a normal mode, not an error.**

**Version compatibility.** The frontmatter pins this skill's `version` and the oldest CLI it is written against (`minCliVersion`). If `edgespeak-cli --version` reports something older, run `edgespeak-cli update` (or re-run the installer) before relying on the flags documented here. Same-numbered builds can still differ, so `--help` is the tiebreaker: a command or flag documented here but missing from the installed `--help` also means update — don't route around it.

## Inputs to confirm

- Text to segment, preferably as a file path for large input.
- Desired output: stdout text, `.txt`, `.json`, or `.srt`.
- Optional sentence-boundary sensitivity threshold.
- Optional sentence length constraints.

## How to do it

1. Get the text — inline, or (better for long text) a file path.
2. Check the runtime first:

   ```bash
   edgespeak-cli status
   ```

   - **Command not found** → the CLI isn't installed. On Windows x64, tell the user to install the EdgeSpeak desktop app, which ships the CLI. On macOS Apple Silicon or Linux x86_64, use `curl -fsSL https://edgespeak.com/install.sh | sh` (self-contained, no desktop app needed; on Linux the installer auto-detects NVIDIA GPUs and installs a CUDA-enabled runtime).
   - **License not activated / locked** → run `edgespeak-cli login` to sign in via the browser (purchased accounts activate this machine directly, new accounts start a free 7-day trial; signing in also replaces an anonymous trial with your account credentials), or `edgespeak-cli activate <KEY>` with an existing key. No account and no browser at hand? `edgespeak-cli trial` starts an instant anonymous 7-day trial (device-bound, one per device). Non-interactive runs (agents, pipes, CI) fail fast with `license_required` instead of prompting.
   - **Gateway not running (standalone)** → this is fine; `segment` runs against the bundled on-device engine. When the app is running it reuses the warm gateway (proxy) instead.
3. Run `edgespeak-cli segment`:

   ```bash
   # from a file
   edgespeak-cli segment --file transcript.txt [-o out.txt] [--format txt|json|srt]

   # or inline
   edgespeak-cli segment --text "<text to split>"

   # length-constrained split
   edgespeak-cli segment --file transcript.txt --min-chars 40 --max-chars 120

   # re-split a word-timed transcript (transcribe/align JSON), keeping real timings
   edgespeak-cli segment --transcript words.json -o resplit.json --max-chars 80
   ```

   - `--file`, `--text`, and `--transcript` are mutually exclusive.
   - `--transcript <json>` consumes a word-timed transcribe/align JSON (`segments[].words[]` required — input without word timing errors out): it re-splits the text into new sentences and re-maps each word into them, so every new sentence carries real `start` / `end` from its first/last word. Output is transcribe-shaped verbose JSON (default format in this mode is `json`; `srt` / `txt` also work). `--start-margin` / `--end-margin` then pad the sentence windows outward, but only into the silence between sentences — adjacent cues never overlap. `--min-chars` / `--max-chars` are **soft** limits here: a sentence boundary is never allowed to land inside a word, so when the only way to respect the limit would be to cut a word in half, the boundary moves to the end of that word instead and the cue runs a few characters over (the following cue is correspondingly shorter, possibly under `--min-chars`). Words stay intact and every cue's `text` matches its `words[]`. If the text genuinely can't be matched back onto the words at all, the command errors instead of emitting mis-timed output. A diarized transcript (from `transcribe --diarize`) is accepted as input, but the re-split output carries **no** `speaker` fields — new sentence boundaries invalidate the old attribution (by design). If the user needs speaker labels at a different cue length, re-run `transcribe --diarize` with shaping flags instead.
   - Default output (`txt` / stdout): one sentence per line.
   - **Do not silently overwrite an existing output file.** The CLI clobbers an existing `-o` target without warning. If the requested path already exists and the user did not explicitly ask to overwrite or regenerate that exact file, confirm with the user first (or agree on a different path); if you cannot ask, write to a new non-conflicting path and say so in your answer.
   - `--format json`: an envelope object — the sentence array lives under the top-level `segments` key, it is **not** a bare array. The shape depends on the input mode: plain text (`--file` / `--text`) gives `{ "task": "segment", "text": "<all sentences joined>", "segments": [{ "text": ... }] }` with **no** `start` / `end` keys at all, while `--transcript` gives the transcribe shape `{ "task": "transcribe", "duration", "text", "segments": [{ "id", "start", "end", "text", "words" }], "usage" }` (see "Timestamps: read this").
   - `--threshold <0..1>` tunes boundary sensitivity (default `0.35`). **Lower → more, shorter sentences; higher → fewer, longer sentences.** Adjust only if the default over/under-splits.
   - `--min-chars <N>` / `--max-chars <N>` tune length-constrained splitting.
   - `--device cpu|cuda|cuda:<N>|metal|auto` picks the compute backend (case-insensitive; `metal` is macOS, `gpu` means Metal on macOS / CUDA elsewhere). **Standalone mode only** — with the app gateway reachable the flag errors explicitly; an unavailable backend also errors rather than silently falling back.
   - `--license-key <KEY>` (alias `--key`) only to pass a license key explicitly for this run; normally activation already covers it.

## Timestamps: read this

When the input is **plain text**, there is no timing to report, and the JSON says so by **omitting** `start` and `end` from every segment — a plain-text segment is `{ "text": ... }` and nothing more. Do not read those keys with a `0.0` default and pass the result downstream as timing, and never fabricate replacements: a missing `start` / `end` means "this run had no audio", not "this sentence happens at second zero". `--format srt` on plain text still emits one cue per sentence, but every cue is `00:00:00,000 --> 00:00:00,000`, so the SRT is not usable as a subtitle file.

To get **real per-sentence timing**:

- **Already have a word-timed JSON** (from `edgespeak-transcribe` or `edgespeak-align`)? Run `segment --transcript <json>` — it re-splits and re-maps the word timings in one command; no manual mapping needed.
- **Only have media + plain text?** Run `edgespeak-cli align <media> --text-file <text> -o words.json` first to get the word-timed JSON (see `edgespeak-align`), then `segment --transcript words.json`.

Use `--file` / `--text` when you only need **clean sentence text**; use `--transcript` when you also need **timing**.

## Output shape (json)

```json
{
  "task": "segment",
  "text": "As you can see it's easy it's simple. And it works.",
  "segments": [
    { "text": "As you can see it's easy it's simple." },
    { "text": "And it works." }
  ]
}
```

That is the **plain-text** shape (`--file` / `--text`): `task` is `"segment"`, `text` is all sentences
joined, and `segments[]` holds one `{ "text": ... }` entry per sentence with no timing keys at all
(see "Timestamps: read this").

`--transcript` returns the transcribe shape instead — `task` is `"transcribe"`, the top level gains
`duration` and `usage`, and each segment carries `id`, `start`, `end`, `text`, and `words[]`:

```json
{
  "task": "transcribe",
  "duration": 19.691,
  "text": "Lattice AI is a high-performance engine designed for the structuring of audio and video content assets.\nIt runs entirely on local compute, ensuring your data security.",
  "segments": [
    { "id": 0, "start": 0.22, "end": 3.48,
      "text": "Lattice AI is a high-performance engine designed for the",
      "words": [ { "word": "Lattice", "start": 0.22, "end": 0.64, "score": 0.991 } ] }
  ],
  "usage": { "type": "duration", "seconds": 19.691 }
}
```

No `speaker` field is emitted in either mode; a diarized input loses its labels on re-split (see the
`--transcript` note above). JSON key order is not guaranteed — parse by key, not position.

## Boundaries / gotchas (read this)

- **Requires `edgespeak-cli`.** If the command isn't found, install the EdgeSpeak desktop app on Windows x64, or use `curl -fsSL https://edgespeak.com/install.sh | sh` on macOS Apple Silicon and Linux x86_64 (self-contained, no desktop app needed; CUDA auto-detected on Linux). If it's found but errors, show the error — **do not hand-split the text yourself and pass it off as the model's output**.
- **First use needs activation.** A fresh install activates once via `edgespeak-cli login` (browser sign-in; also upgrades an anonymous trial to your account), `edgespeak-cli activate <KEY>`, or `edgespeak-cli trial` (instant anonymous 7-day trial, no browser or account; one per device). Without it the on-device engine fails with `license_required`; the error carries self-serve guidance plus a purchase link — surface it, don't work around it. In an interactive terminal, standalone commands offer to sign in and continue automatically; non-interactive runs (agents, pipes, CI) fail fast instead of prompting. To pass the key on a single run, use `--license-key <KEY>` (alias `--key`).
- **Pre-download the segmenter model for headless machines**: `edgespeak-cli models download lattice-1-text-segmenter` (or `--all`) fetches it ahead of time — standalone only, quit the EdgeSpeak app first.
- **It does not add punctuation or capitalization** — it finds boundaries. Output sentences carry the input's casing/spelling (ASR typos stay).
- **If length constraints don't take effect**, or a run fails while parsing the result, open the EdgeSpeak app and rerun (proxy mode), and capture the command, mode, and CLI version as a bug report — don't hand-split to fake the constraint.
- **First standalone segment after a model-key rename can need a credential refresh.** If a fresh standalone run fails with `model_key_unavailable` / `device-bound-model-key` / `model_not_found (HTTP 404)`, tell the user to open EdgeSpeak once or refresh their license credentials, then retry. Do not treat it as permanent segmentation failure.
- **Long text is slow**: it's a real model pass. ~96K characters takes around 3 minutes. It is not hung — be patient.
- For very large inputs prefer `--file` over a huge inline `--text` to avoid shell-length limits.

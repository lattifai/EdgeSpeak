---
name: edgespeak-video-voice
version: 0.1.0
minCliVersion: 0.6.1
description: Give code-rendered video (HyperFrames, Remotion, Canvas, Manim, plain web animation) an on-device voice-over with word-synced captions — write the narration, synthesize it locally with EdgeSpeak, force-align it for word timestamps, and convert those into a cues.json / timing.js / frame-number table that drives the animation. Use when the user wants an animated or programmatic video to narrate itself, captions that pop word by word in sync with the voice, or scene cuts timed to narration sentences.
---

# EdgeSpeak Video Voice

Make a video that Claude builds in code **speak**, and make every caption word land exactly when it is
said. The whole chain runs **on-device**: the narration text and the audio never leave the machine.

```text
narration script ──speech──▶ narration.wav ──align──▶ words.json ──video_cues.py──▶ cues.json / timing.js
                                                                                        │
                                            HyperFrames · Remotion · Canvas · Manim ◀───┘
```

This skill composes two others: `edgespeak-broadcast` (speech synthesis) and `edgespeak-align`
(word timestamps). It links to them for the full model / voice / error tables instead of repeating
them; read the relevant section there whenever a step below fails.

**Version compatibility.** The frontmatter pins this skill's `version` and the oldest CLI it is
written against (`minCliVersion`). If `edgespeak-cli --version` reports something older, run
`edgespeak-cli update` (or re-run the installer) first. `--help` is the tiebreaker for flags; for
model ids the live list is the gateway's `/v1/models` plus `edgespeak-cli speech --help`, not this
file.

## Inputs to confirm

- What the video is about, its target length, and the narration language (the recommended speech
  model below covers Chinese and English).
- The video framework and, for frame-based tools such as Remotion, the frame rate.
- Lead-in before the first word (for example a 0.5 s title card), if any.
- Voice preference: a described voice ("warm, low, unhurried female narrator"), one of the local
  preset voices, or the user's own cloned voice (`user:<uuid>`).
- Output paths. Do not silently overwrite an existing WAV or JSON: `edgespeak-cli` clobbers `-o`
  targets without warning, so confirm first or pick a new path. The bundled script refuses to
  overwrite unless you pass `--overwrite`.

## 1. Check the runtime

```bash
edgespeak-cli status
edgespeak-cli --version
```

- **Command not found** → the CLI isn't installed. Point the user to https://edgespeak.com/docs/cli#install
  (a self-contained one-line installer on macOS Apple Silicon and Linux x86_64; on Windows x64 the
  EdgeSpeak desktop app ships the CLI). The user runs the installer; do not run it yourself.
- **License not activated / locked** → `edgespeak-cli login` (browser sign-in; new accounts start a
  free 7-day trial), `edgespeak-cli activate <KEY>`, or `edgespeak-cli trial` for an instant anonymous
  trial. Non-interactive runs fail fast with `license_required`; surface it, don't work around it.
- **Gateway not running (standalone)** → fine. `speech` and `align` launch the on-device engine
  themselves when the desktop app is closed.

The bundled script needs **Python 3.9+** (standard library only). The optional chunked-alignment path
in step 7 also needs `ffmpeg`.

## 2. Write the narration

Write the script as plain text. Sentence cues — the points that drive scene cuts — are cut at
sentence-ending punctuation (`。！？!?.…`), so end the narration for each shot with one of those marks
wherever the picture should change. Alignment may return the whole script as a single segment or as
several; the converter in step 5 splits at those marks either way.

- Write for the ear: short sentences, numbers and symbols spelled the way they should be spoken
  ("EdgeSpeak dot com", "三百四十六种"), no Markdown.
- Budget about 4 Chinese characters or 2.5 English words per second, then check the real duration
  after synthesis instead of trusting the estimate.
- Keep the exact file you synthesize from — the alignment in step 4 must use the same words.

## 3. Synthesize the voice-over

Recommended models for narration (both verified against `/v1/models` on CLI 0.6.1; confirm they are
installed on this machine before using them):

| Goal | Model | Voice | `--instructions` |
| --- | --- | --- | --- |
| Narration in Chinese or English with a preset or cloned voice, plus a short delivery direction | `BreezeBlue/Breeze-TTS-2` | a cloneable preset (`builtin:warm-neighbor`, `builtin:clear-male-guide`, …) or `user:<uuid>` | optional delivery direction, **≤ 60 characters** ("calm, confident product narrator") |
| A brand-new voice invented from a description, no reference audio | `Qwen/Qwen3-TTS-1.7B-VoiceDesign` (alias `qwen3-tts-1.7b-voice-design`) | `builtin:auto` only | **required** voice description, **≤ 120 characters** |

Pick the voice from live data, never from memory:

```bash
curl -s http://127.0.0.1:1117/v1/models   # only while the desktop app is running
edgespeak-cli voices list                 # voice ids and per-model compatibility
```

- In `/v1/models`, a speech model's `features`, `supported_languages`, and `instruction.maxChars`
  are authoritative. `BreezeBlue/Breeze-TTS-2` currently publishes `instruct` + `voice_clone` and
  languages `zh` / `en`; it has no short alias — pass the full id.
- In `voices list`, choose an `id` whose `compatibility` entry for the chosen model has
  `"status": "ready"`. The nine official named voices (`builtin:Vivian`, `builtin:Serena`, …) are
  **not** usable with Breeze-TTS-2 or VoiceDesign; they belong to the CustomVoice models described
  in `edgespeak-broadcast`.
- If the desktop gateway has local authentication turned on, ask the user for the key and add
  `-H "Authorization: Bearer <key>"`; do not read the key from their environment or files.
- Omit `--language` and let the model decide unless it picks wrong.

```bash
# Preset voice + a short delivery direction
edgespeak-cli speech "$(cat narration.txt)" -o narration.wav \
  -m BreezeBlue/Breeze-TTS-2 --voice builtin:warm-neighbor \
  --instructions "calm, confident product narrator" --seed 7

# A voice designed from a description
edgespeak-cli speech "$(cat narration.txt)" -o narration.wav \
  -m Qwen/Qwen3-TTS-1.7B-VoiceDesign --voice builtin:auto \
  --instructions "a warm young female narrator, clear and unhurried, slight smile" --seed 7
```

- The result JSON is on **stdout** (`duration_seconds`, `sample_rate`, `seed_used`, `warnings`);
  engine logs are on stderr. Keep `seed_used` so the take can be reproduced.
- Input is capped at 4096 characters per call. Longer scripts: synthesize per paragraph with the same
  voice and seed, then either concatenate the WAVs before aligning or align each part and stitch the
  timings with `video_cues.py merge` (step 7).
- To audition voices, synthesize the same one or two sentences with 2–3 candidates and let the user
  listen before rendering the full script.
- Pairing errors (`voice_not_ready`, `custom_voice_requires_official_named_voice`,
  `model_not_found`, `language_unsupported`) are verdicts, not transient failures: re-pair per
  `edgespeak-broadcast` → "Pairing errors", don't retry the same call.

## 4. Align for word timestamps

```bash
edgespeak-cli align narration.wav -t "$(cat narration.txt)" -o words.json
```

- **Use `-t` / `--text` with the script inline.** `-T` / `--text-file` sends a local file path, and a
  standalone `edgespeak-cli serve` process rejects it (`field 'text_path' (local path) is not
  supported on this listener; send 'text'`), even on loopback. Inline text works in every mode, so
  `-t` is the portable default.
- Align against the **exact** text you synthesized, not an ASR transcript of the audio.
- Output is `{task, duration, text, segments[].words[]}` with times in seconds. Words keep attached
  punctuation (`EdgeSpeak，`), and Chinese is timed per character.
- A failed alignment exits non-zero and writes nothing. Follow `edgespeak-align` → "When alignment
  fails": rerun once with `--search-effort extended` only when the error JSON says
  `"retry_recommended": true`. **Never fabricate or evenly space timestamps.**

## 5. Convert to a cue table

```bash
python3 <skill-dir>/scripts/video_cues.py build words.json -o cues.json \
  --lead 0.5 --fps 30 --timing-js timing.js
```

| Flag | Effect |
| --- | --- |
| `-o cues.json` | Required. The cue table (below). |
| `--timing-js timing.js` | Also write `window["CUES"] = {...};` for HyperFrames / web pages (`--var NAME` changes the property name; it is written as a quoted string, so any name is safe). |
| `--lead S` | Shift every time by `S` seconds of lead-in (finite, ≥ 0). `duration` includes it. |
| `--fps N` | Add `startFrame` / `endFrame` to every word and sentence, and `durationInFrames` (finite, > 0). |
| `--sentences punct\|segments` | `punct` (default): a sentence ends at every word ending in `。！？!?.…` (closing quotes/brackets after the mark are allowed) and at every segment boundary — correct whether alignment returned one segment for the whole script or one per sentence. A word ending in `.` counts, so abbreviations like `Dr.` also split. `segments`: one alignment segment = one sentence, no further splitting. |
| `--strip-punct` | Drop punctuation attached to word text (sentence text keeps it). |
| `--overwrite` | Replace existing outputs; without it the script refuses. `-o` and `--timing-js` must be different files, and neither may be the input. |

`cues.json` shape (times rounded to milliseconds, key order fixed so the file diffs cleanly):

```json
{
  "generator": "video_cues.py", "source": "words.json",
  "lead": 0.5, "audioDuration": 49.52, "duration": 50.02, "fps": 30.0, "durationInFrames": 1501,
  "sentences": [
    { "text": "EdgeSpeak，把语音理解、…完全离线运行。", "start": 0.64, "end": 11.52,
      "firstWord": 0, "lastWord": 45, "startFrame": 19, "endFrame": 346 }
  ],
  "words": [
    { "text": "EdgeSpeak，", "start": 0.64, "end": 1.02, "sentence": 0, "score": 0.3474,
      "startFrame": 19, "endFrame": 31 }
  ]
}
```

- Sentence `text` is sliced from the alignment segment's own text, so spacing and punctuation are
  exactly what was written (CJK is not re-spaced). If the words cannot be located in that text the
  script rebuilds it from the words and reports a warning on stdout.
- Frame rule: `startFrame = floor(start × fps)`, `endFrame = max(startFrame + 1, ceil(end × fps))`,
  computed from the unrounded times (lead included) before the seconds are rounded for output.
  `endFrame` is exclusive — every word is on screen for at least one frame.
- `score` is the aligner's confidence, useful to spot a mistimed word; its scale depends on the model,
  so compare within one file instead of applying a fixed threshold. A score that is not a finite number
  is written as `null` and reported in `warnings`.
- The script exits non-zero and writes nothing when a segment has no words, a time is missing,
  negative, NaN or infinite, a word ends before it starts, times go backwards, or the input's
  `duration` ends before its last word (a sign the alignment belongs to different audio). Fix the
  input; don't patch times by hand.
- Outputs are written to an exclusively created temporary file in the same directory and then renamed
  into place, so an interrupted run never leaves a half-written file and never touches other files.

## 6. Drive the animation

Rules that keep picture and voice locked:

- **Apply the lead-in exactly once.** If you passed `--lead 0.5`, the cue times already include it:
  place the narration audio at `0.5` s in the composition and use cue times as-is. Do not add the lead
  again in animation code.
- A word **appears at its `start`** (and may dim or stay after `end`); never schedule it by its index.
- **Cut scenes on sentence boundaries**: scene *k* spans `sentences[k].start` to
  `sentences[k+1].start` (the last one runs to `duration`). The gap between sentences is the natural
  place for transitions.
- Use `duration` / `durationInFrames` as the composition length.
- Re-run steps 3–5 whenever the narration changes; never keep old cues for new audio.

**HyperFrames / GSAP** — load `timing.js` before the composition script, keep exactly one paused
timeline, and let the framework own audio playback (see the `hyperframes-core` skill for the full
contract):

```html
<div id="root" data-composition-id="main" data-start="0" data-width="1920" data-height="1080"
     data-duration="50.02">
  <audio id="vo" src="voice/narration.wav" data-start="0.5" data-track-index="10" data-volume="1"></audio>
  <div id="caption" class="caption"></div>
</div>
<script src="timing.js"></script>
<script>
  const C = window.CUES;
  const tl = gsap.timeline({ paused: true });
  const cap = document.getElementById("caption");
  const spans = C.words.map((w) => {
    const s = document.createElement("span");
    s.textContent = w.text;
    s.style.display = "inline-block"; // HyperFrames only transforms block-level boxes
    s.style.opacity = "0";
    cap.appendChild(s);
    return s;
  });
  C.words.forEach((w, i) => {
    tl.fromTo(spans[i], { opacity: 0, y: 12 }, { opacity: 1, y: 0, duration: 0.12, ease: "power2.out" }, w.start);
  });
  C.sentences.forEach((s) => {
    // Clear the previous sentence at each sentence start (scene cut point).
    const prev = spans.slice(0, s.firstWord);
    if (prev.length) tl.set(prev, { opacity: 0 }, s.start);
  });
  window.__timelines = window.__timelines || {};
  window.__timelines["main"] = tl;
</script>
```

Set the root `data-duration` from `C.duration`; the audio `data-start` equals `C.lead`. The word
spans are `inline-block` because HyperFrames does not allow transforms (`y`) on inline elements.

**Remotion** — import the JSON and compare against the current frame (build with `--fps` equal to the
composition's `fps`):

```tsx
import cues from "./cues.json";
import { Audio, Sequence, staticFile, useCurrentFrame } from "remotion";

export const Narrated = () => {
  const frame = useCurrentFrame();
  const leadFrames = Math.round(cues.lead * cues.fps);
  const sentence = cues.sentences.find((s) => frame >= s.startFrame && frame < s.endFrame);
  return (
    <>
      <Sequence from={leadFrames}><Audio src={staticFile("narration.wav")} /></Sequence>
      <div className="caption">
        {sentence && cues.words.slice(sentence.firstWord, sentence.lastWord + 1).map((w, i) => (
          <span key={i} style={{ opacity: frame >= w.startFrame ? 1 : 0.25 }}>{w.text}</span>
        ))}
      </div>
    </>
  );
};
// Composition: durationInFrames={cues.durationInFrames} fps={cues.fps}
```

**Canvas / Manim / anything else** — read `cues.json`, compute the current time `t`, and draw the
words with `start <= t`. In Manim, add the narration with `self.add_sound("narration.wav",
time_offset=cues["lead"])` and schedule each reveal with `self.wait()` for the gap up to the next
word's `start`.

Verify before delivering: render or snapshot frames at two or three word `start` times and confirm
the word is visible exactly there, and play the final render to check that captions and voice agree.

## 7. When alignment is unstable (singing, music beds, long takes)

For long audio the engine already chunks alignment automatically — memory is **not** a reason to
split. Split only when alignment keeps failing: `alignment_failed` after the recommended
`--search-effort extended` retry, or a failure with `"retry_recommended": false` even though the text
really is what is sung or spoken. Typical causes are singing, a loud music bed, or long silences.

1. Get sentence windows from a transcription of the same audio:

   ```bash
   edgespeak-cli transcribe song.wav --timestamps segment -o windows.json
   ```

2. Match each window to the **script lines** it contains (use the script text, not the ASR text —
   the ASR words are only for locating the windows). Pad each window by about 0.2–0.3 s on both
   sides without overlapping its neighbour.
3. Cut each window and align it with its script lines:

   ```bash
   ffmpeg -ss 12.30 -t 8.40 -i song.wav -ac 1 -ar 16000 chunk-01.wav
   edgespeak-cli align chunk-01.wav -t "<script lines for this window>" -o chunk-01.json
   ```

4. Stitch the chunks back onto the song's timeline (offset = the `-ss` value of each cut), then
   convert as usual:

   ```bash
   python3 <skill-dir>/scripts/video_cues.py merge chunk-01.json@12.30 chunk-02.json@21.00 -o words.json
   python3 <skill-dir>/scripts/video_cues.py build words.json -o cues.json --fps 30
   ```

   `merge` refuses chunks that overlap or are out of order: a word that starts more than 1 ms before
   the last word of an earlier chunk ends is an error. Offsets must be finite and ≥ 0. If one chunk still fails to align, report
   which lines failed; do not interpolate their timing.

## Boundaries / gotchas

- **Requires `edgespeak-cli` 0.6.1 or newer** for the models named above; older runtimes may lack
  `BreezeBlue/Breeze-TTS-2`. `speech --help` lists model ids but not voices — use `voices list`.
- **Synthesis is slower than real time** on most machines and the first run may load or download a
  model. Give `speech` and `align` generous timeouts; a silent run is not a hang. The local gateway
  serializes requests, so run them one at a time.
- **Output is WAV.** Convert with `ffmpeg` afterwards if the framework wants another format.
- **Voice consent.** Only clone a voice the user has the right to use; see `edgespeak-broadcast` →
  "Voice management".
- If any step errors, show the error. Do not fabricate audio, timestamps, or claim a render is synced
  without checking frames.

## Bundled script

- `scripts/video_cues.py build`: alignment or word-timestamp transcription JSON → `cues.json`
  (words + sentences, optional lead-in and frame numbers) and optional `timing.js`.
- `scripts/video_cues.py merge`: stitch clip-level alignments (`chunk.json@offset`) into one
  alignment JSON on the original timeline.
- `scripts/test_video_cues.py`: standard-library `unittest` suite for both subcommands
  (`python3 -m unittest test_video_cues` from the `scripts/` directory).

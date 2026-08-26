---
name: edgespeak-broadcast
version: 0.2.0
minCliVersion: 0.4.4
description: Turn text into natural speech fully on-device via EdgeSpeak (Broadcast) — synthesize WAV audio with official named voices, cloned voices, style instructions, speed and reproducible seeds, design a brand-new voice from a text description, and manage a local voice library including cloning a voice from consented reference audio. Use when the user wants local private text-to-speech, an audio version of some text, or wants to list/add/delete EdgeSpeak voices.
---

# EdgeSpeak Broadcast

Turn text into speech, **entirely on-device — the text never leaves the machine**. Broadcast is EdgeSpeak's speech feature; under the hood this skill calls `edgespeak-cli speech` (alias: `synthesize`). When the EdgeSpeak desktop app is running, the CLI talks to its local gateway (OpenAI-compatible, `127.0.0.1:1117`) and reuses the warm model (proxy mode); when the app is not running, the CLI launches the bundled on-device engine itself (standalone mode). **Standalone is a normal mode, not an error.**

**Version compatibility.** The frontmatter pins this skill's `version` and the oldest CLI it is written against (`minCliVersion`). If `edgespeak-cli --version` reports something older, run `edgespeak-cli update` (or re-run the installer) before relying on the flags documented here. Same-numbered builds can still differ, so `--help` is the tiebreaker **for flags** — a flag documented here but missing from the installed `--help` means update, don't route around it.

`--help` is **not** the tiebreaker for model ids: `speech --help` names only a subset of the installed TTS models. The live, authoritative list is the gateway's `/v1/models` — see "Pick a model and a voice".

## Inputs to confirm

- The text to speak (or the file it comes from).
- Output WAV path.
- Any requested voice, style instructions, speed, language, or reproducibility (seed) preferences.
- Whether the user wants a **named voice** (a specific, reusable EdgeSpeak voice identity), a **cloned voice** (their own `user:` voice), or a **designed voice** (invented from a text description) — the answer decides the model, not just the `--voice` value.

## How to do it

1. Check the runtime first:

   ```bash
   edgespeak-cli status
   ```

   - **Command not found** → the CLI isn't installed. On Windows x64, tell the user to install the EdgeSpeak desktop app, which ships the CLI. On macOS Apple Silicon or Linux x86_64, use `curl -fsSL https://edgespeak.com/install.sh | sh` (self-contained, no desktop app needed; on Linux the installer auto-detects NVIDIA GPUs and installs a CUDA-enabled runtime).
   - **License not activated / locked** → run `edgespeak-cli login` to sign in via the browser (purchased accounts activate this machine directly, new accounts start a free 7-day trial; signing in also replaces an anonymous trial with your account credentials), or `edgespeak-cli activate <KEY>` with an existing key. No account and no browser at hand? `edgespeak-cli trial` starts an instant anonymous 7-day trial (device-bound, one per device). Non-interactive runs (agents, pipes, CI) fail fast with `license_required` instead of prompting.
   - **Gateway not running (standalone)** → this is fine; `speech` will launch the bundled on-device engine itself.
2. Pick a model and a voice **together**. They are not independent choices — every TTS model accepts
   one family of voices and rejects the others (see "Pick a model and a voice" below).
3. Synthesize:

   ```bash
   edgespeak-cli speech "<text>" -o out.wav [options]

   # Default: the general-purpose clone-capable model with a preset voice
   edgespeak-cli speech "<text>" -o out.wav --voice builtin:warm-neighbor

   # A specific official named voice (needs a CustomVoice model)
   edgespeak-cli speech "<text>" -o out.wav \
     -m Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice --voice builtin:Serena

   # Named voice plus a speaking style (only the 1.7B CustomVoice model honors --instructions)
   edgespeak-cli speech "<text>" -o out.wav \
     -m Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice --voice builtin:Aiden \
     --instructions "a calm news anchor, measured and clear"

   # Voice design: invent a voice from a text description (no reference audio needed)
   edgespeak-cli speech "<text>" -o out.wav \
     -m Qwen/Qwen3-TTS-1.7B-VoiceDesign --voice builtin:auto \
     --instructions "a warm, calm narrator with a low voice"
   ```

   The WAV is written to `-o` and a JSON result is printed to **stdout**. Engine logs go to **stderr** — when scripting, parse stdout only.

   **Do not silently overwrite an existing output file.** `speech` clobbers an existing `-o` WAV without warning. If the requested path already exists and the user did not explicitly ask to overwrite or regenerate that exact file, confirm with the user first (or agree on a different path); if you cannot ask, write to a new non-conflicting path and say so in your answer.

## Pick a model and a voice

Ask the gateway what the installed TTS models can do (the app must be running):

```bash
curl -s http://127.0.0.1:1117/v1/models \
  -H "Authorization: Bearer $EDGESPEAK_API_KEY"
```

Every model whose `supported_endpoints` include `/v1/audio/speech` declares a `features` array:

| Feature | Meaning |
| --- | --- |
| `named_voice` | Accepts EdgeSpeak's official named voices — and **only** those |
| `voice_clone` | Accepts the cloneable preset voices, your own `user:<uuid>` voices, and `builtin:auto` |
| `instruct` | Actually honors `--instructions` style text |
| `live_audio_streaming` | The engine can emit audio while still synthesizing (this is what the app's Broadcast player uses to start speaking early; `speech` still writes one finished WAV, so it changes nothing for this skill) |

Those features resolve to six local models. **Pass the id verbatim:**

| Model id | Voices it accepts | `instruct` | Streaming |
| --- | --- | --- | --- |
| `k2-fsa/OmniVoice` *(CLI default)* | presets, `user:` clones, `builtin:auto` | no | no |
| `Qwen/Qwen3-TTS-0.6B-Base` | presets, `user:` clones, `builtin:auto` | no | yes |
| `Qwen/Qwen3-TTS-12Hz-1.7B-Base` | presets, `user:` clones, `builtin:auto` | no | yes |
| `Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice` | official named voices only | no | yes |
| `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice` | official named voices only | **yes** | yes |
| `Qwen/Qwen3-TTS-1.7B-VoiceDesign` | `builtin:auto` only | **yes** (required) | no |

Three of them also answer to a short alias: `k2-fsa/OmniVoice` → `omnivoice`,
`Qwen/Qwen3-TTS-0.6B-Base` → `qwen3-tts-0.6b-base`, `Qwen/Qwen3-TTS-1.7B-VoiceDesign` →
`qwen3-tts-1.7b-voice-design`. The three `12Hz` models have **no** short alias — a guessed one
(`qwen3-tts-12hz-1.7b-customvoice`, …) returns HTTP 404 `model_not_found`.

Then list the local voice library (JSON to stdout):

```bash
edgespeak-cli voices list
```

Each entry has an `id`, `supported_languages`, and a `compatibility` array naming the models that can
use it. **Pick an id whose `compatibility` entry for your chosen model is `"ready"`** — that array,
not the voice's name, is the reliable pairing check. The library splits in two:

- **Official named voices** — `builtin:Vivian`, `builtin:Serena`, `builtin:Uncle_Fu`, `builtin:Dylan`,
  `builtin:Eric`, `builtin:Ryan`, `builtin:Aiden`, `builtin:Ono_Anna`, `builtin:Sohee`. Nine stable
  identities across ten languages, usable **only** with the two `CustomVoice` models. Their `names` /
  `descriptions` objects are **empty**, so refer to them by id when presenting choices to the user.
- **Cloneable voices** — the presets (`builtin:bright-girl`, `builtin:energetic-boy`,
  `builtin:warm-neighbor`, …) plus every `user:<uuid>` the user added. These carry localized `names` /
  `descriptions` (`en-US`, `zh-CN`) and work **only** with the `voice_clone` models.

### Pairing errors

| What you sent | Response |
| --- | --- |
| A `CustomVoice` model with `builtin:auto`, a preset, or a `user:` clone | HTTP 400 `custom_voice_requires_official_named_voice` |
| A `voice_clone` model with an official named voice | HTTP 409 `voice_not_ready` |
| A model id absent from `/v1/models` (including an invented short alias) | HTTP 404 `model_not_found` |

Recover by re-reading `/v1/models` and `voices list` and re-pairing. Never retry the same combination,
and if you have to change the user's requested voice or model to make the pair valid, say so.

**`--instructions` is silently ignored by models without `instruct`.** Only
`Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice` and `Qwen/Qwen3-TTS-1.7B-VoiceDesign` honor it. Everywhere else
the call still returns success with an empty `warnings` array and byte-identical audio — same seed in,
same WAV out. If the user asked for a speaking style, move them to one of those two models rather than
reporting a style that was never applied.

## Option map

| User asks for | Use with `speech` | Notes |
| --- | --- | --- |
| A specific voice | `--voice builtin:<id>` or `--voice user:<uuid>` | Must be compatible with `-m` — see "Pick a model and a voice". Default `builtin:auto` lets the engine pick and is **rejected** by the two `CustomVoice` models. OpenAI voice aliases (e.g. `alloy`) are also accepted on the clone-capable models. |
| Speaking style ("cheerful", "slow news anchor tone", …) | `--instructions "<style>"` | Free-form style text, honored **only** by models with the `instruct` feature (`Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice`, `Qwen/Qwen3-TTS-1.7B-VoiceDesign`); silently ignored on every other model. Conflicts with `--disable-style`. |
| Ignore the style saved with the voice | `--disable-style` | Explicitly disables the voice's default style. |
| Faster / slower speech | `--speed <N>` | Default 1.0. The local model may support a narrower range than OpenAI's 0.25–4.0. |
| Language hint | `--language zh-CN` or `--language en-US` | Selects the internal reference for the voice. |
| Reproducible output | `--seed <N>` | Non-negative. Same seed + same inputs → same audio. The seed actually used is reported in the result JSON (`seed_used`). |
| A different local model | `-m <model-id>` | Six local TTS models — see the table in "Pick a model and a voice". Default is `k2-fsa/OmniVoice`. `speech --help` lists only three of the six, so read `/v1/models`, not `--help`, when choosing. |
| A specific named voice identity | `-m Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice` (or the `1.7B` one) `--voice builtin:<Name>` | The only way to reach the nine official named voices. The `1.7B` variant additionally honors `--instructions`; the `0.6B` variant is faster. |
| Design a new voice from a description | `-m Qwen/Qwen3-TTS-1.7B-VoiceDesign --voice builtin:auto --instructions "<voice description>"` | Voice design invents a voice from free-form text. It requires `--voice builtin:auto` and `--instructions`. Short alias `qwen3-tts-1.7b-voice-design` also works. |
| Generation quality knobs | `--guidance-scale <0–5>`, `--inference-steps <1–64>` | Omit either for the model default. |
| Run on a specific compute backend | `--device cpu\|cuda\|cuda:<N>\|metal\|auto` | Case-insensitive; `metal` is macOS, `gpu` means Metal on macOS / CUDA elsewhere. **Standalone mode only** — with the app gateway reachable the flag errors explicitly; an unavailable backend also errors rather than silently falling back. |

Input is limited to **4096 characters** per call (OpenAI `input` limit). For longer text, split it into ≤4096-character parts at natural boundaries (paragraphs/sentences), synthesize each part, and concatenate the WAVs afterwards (`ffmpeg -f concat`). Keep the same `--voice` and `--seed` across parts for a consistent result.

## Result JSON (stdout)

Real output shape — long input is synthesized in chunks automatically and reported per chunk:

```json
{
  "output_path": "/abs/path/out.wav",
  "format": "wav",
  "size_bytes": 90284,
  "sample_rate": 24000,
  "duration_seconds": 1.88,
  "seed_used": 3862347868,
  "infer_seconds": 7.49,
  "warnings": [],
  "chunks": [
    { "index": 0, "character_count": 21, "duration_seconds": 1.88,
      "seed_used": 3862347868, "infer_seconds": 7.49, "warnings": [] }
  ]
}
```

Read `sample_rate` from the response rather than assuming a fixed rate — it comes from the model.
Surface non-empty `warnings` to the user, but do **not** treat an empty `warnings` array as proof that
every option took effect: an `--instructions` string dropped by a model without `instruct` produces no
warning at all.

## Voice management

```bash
# List all voices (JSON)
edgespeak-cli voices list

# Clone a voice from reference audio + its exact transcript
edgespeak-cli voices add ref.wav --ref-text "<exact words spoken in ref.wav>" \
  --name "My voice" [--language zh-CN] [--speaker-description "<optional description>"] --consent

# Delete a user-created voice (by id or exact name); built-in voices cannot be deleted
edgespeak-cli voices delete user:<uuid>
edgespeak-cli voices delete "My voice"
```

- `--consent` is **required** for `voices add`: it asserts the user has permission to use the reference recording. Never add a voice without the user explicitly confirming they have the right to use that recording; refuse to clone third-party voices without consent.
- `--ref-text` must be the exact transcript of the reference audio — a mismatch degrades cloning quality.
- `voices delete` with a name requires an exact, unique match; ambiguous or unknown names fail with a clear error.
- After adding, use the returned/listed `user:<uuid>` id with `speech --voice`.

## MCP and API equivalents

- Through the EdgeSpeak MCP server (`edgespeak-cli mcp` or the app's MCP endpoint), the same capabilities are exposed as tools: `edgespeak_create_speech`, `edgespeak_list_voices`, `edgespeak_add_voice`, `edgespeak_delete_voice`. Prefer MCP tools when an EdgeSpeak MCP server is already configured. `edgespeak_create_speech` accepts the same model ids as the CLI and returns `{artifact_path, sample_rate, duration, seed_used, chunks[], warnings[]}`.
- **Do not take model ids from the MCP schemas.** `edgespeak_create_speech`'s own `model` description lists an outdated set, and `edgespeak_list_models` returns only `{id, capabilities, locality, owned_by}` — no `features`. For which model supports named voices, cloning, or `instruct`, read HTTP `/v1/models`.
- With the app running, the local gateway also serves OpenAI-compatible `POST /v1/audio/speech` (JSON body `{model, input, voice, response_format}`, WAV bytes back). Stay with the CLI unless the user specifically needs raw API access.

## Boundaries / gotchas (read this)

- **Requires `edgespeak-cli` 0.4.4 or newer** (see the version compatibility note up top). Older runtimes ship neither the `CustomVoice` models nor the official named voices. If a flag documented here is missing from `--help`, run `edgespeak-cli update` first.
- **First use needs activation** (`edgespeak-cli login` for browser sign-in — it also upgrades an anonymous trial to your account, `activate <KEY>` with an existing key, or `edgespeak-cli trial` for an instant anonymous 7-day trial), same as the other EdgeSpeak skills. Surface license errors; don't work around them. Non-interactive runs fail fast instead of prompting.
- **Six model ids work here**, and `speech --help` only names three of them — see "Pick a model and a voice". Do not conclude a model is unavailable because `--help` omits it, and do not invent short aliases for the `12Hz` models. The app's Broadcast workspace offers the same models with richer UI workflows.
- **Model and voice must match.** A mismatch fails fast with `custom_voice_requires_official_named_voice` (400), `voice_not_ready` (409), or `model_not_found` (404) — recover per "Pairing errors", don't retry unchanged. Some gateway builds additionally reject the CLI's default `--voice builtin:auto` with HTTP 400 `unsupported_auto_voice`; the same recovery applies, so prefer choosing an explicit voice upfront over relying on the default.
- **Synthesis is slower than real time on most machines** (a short sentence can take ~10–20 s in standalone mode; the first run may also decrypt/load or download the model). **Don't assume it hung.**
- **Output is WAV only.** If the user wants MP3/M4A/OGG, synthesize WAV first and convert with `ffmpeg` afterwards.
- **stdout vs stderr**: the result JSON is on stdout; engine progress/logs are on stderr. Never parse stderr.
- If `speech` errors, show the error — **do not fabricate audio or claim success without the output file existing.**

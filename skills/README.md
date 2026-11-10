# EdgeSpeak Skills

**English** · [简体中文](README.zh-CN.md)

This directory is the canonical source for EdgeSpeak Agent Skills. Active
development and future updates are managed in the main EdgeSpeak repository.

Agent Skills that let any Skills-capable agent acquire authorized media, transcribe audio/video **on-device** through [EdgeSpeak](https://edgespeak.com), and turn anonymous speaker labels into evidence-backed names. EdgeSpeak transcription audio never leaves your machine.

## Install

```bash
# auto-detect your agent
npx skills add lattifai/EdgeSpeak

# or target a specific agent
npx skills add lattifai/EdgeSpeak --agent claude-code
npx skills add lattifai/EdgeSpeak --agent cursor
npx skills add lattifai/EdgeSpeak --agent codex
```

### Claude Code plugin

This repository is also a Claude Code plugin marketplace with two plugins. In a Claude Code session:

```
/plugin marketplace add lattifai/EdgeSpeak
/plugin install edgespeak@edgespeak
/plugin install edgespeak-extras@edgespeak
```

- `edgespeak` bundles transcription, alignment, segmentation, karaoke captions, translation, and speaker naming.
- `edgespeak-extras` adds speech synthesis (Broadcast), voice-overs with word-synced captions for code-rendered video, and YouTube acquisition. Install it on top of `edgespeak`. If you added EdgeSpeak from the Claude directory, you already have the core skills: install only `edgespeak-extras` from this marketplace, not `edgespeak` as well, or the same six skills load twice. Until September 2026 the `edgespeak` plugin carried all eight skills; if you installed it then, install `edgespeak-extras` too to keep them.

Claude uses the skills automatically when a request fits, and you can also call one directly as `/<plugin>:<skill-name>` (for example `/edgespeak:edgespeak-transcribe`). Both plugins track this repository's commits: turn on auto-update for the `edgespeak` marketplace under **Marketplaces** in `/plugin`, or update by hand with `/plugin marketplace update edgespeak` followed by `/plugin update edgespeak@edgespeak` (and `/plugin update edgespeak-extras@edgespeak`).

## Requirements

Most skills shell out to `edgespeak-cli`, a self-contained on-device transcription and speech runtime for **macOS Apple Silicon**, **Linux x86_64**, and **Windows x64**. The karaoke skill uses configured EdgeSpeak MCP tools when available and falls back to the same CLI. You can get the runtime in any of these ways:

- **Self-contained CLI for macOS and Linux — no app required:**

  ```bash
  curl -fsSL https://edgespeak.com/install.sh | sh
  ```

  This installs a self-contained runtime (CLI + on-device engine + dependencies) under `~/.edgespeak/runtime` and symlinks `edgespeak-cli` into `~/.local/bin` (PATH is set up for you). On Linux the installer detects NVIDIA GPUs (via `nvidia-smi`) and automatically installs a CUDA-enabled runtime matched to your GPU generation, falling back to the CPU build otherwise; set `EDGESPEAK_LINUX_PROFILE=cpu|cuda-legacy|cuda-modern|cuda-blackwell` to override the detection. At run time, `--device cpu|cuda|cuda:<N>|metal|auto` on `transcribe` / `align` / `segment` / `speech` selects the compute backend (standalone mode only).

- **Self-contained CLI for Windows x64 — no app required.** In PowerShell:

  ```powershell
  irm https://edgespeak.com/install.ps1 | iex
  ```

  It installs the CPU build by default and adds `edgespeak-cli` to your user PATH without administrator access. To install the CUDA build on a supported NVIDIA GPU, run `$env:EDGESPEAK_WINDOWS_ACCELERATOR = "cuda"` in the same window first. See [CLI install](https://edgespeak.com/docs/cli#install-windows) for driver requirements.

- **Desktop app:** install [EdgeSpeak](https://edgespeak.com) from the website — it ships the same `edgespeak-cli`.

Either way, verify the install:

```bash
edgespeak-cli --version
edgespeak-cli status
```

Update the runtime later with `edgespeak-cli update` (re-fetches the latest self-contained package).

### Versioning

Each skill's frontmatter carries its own `version`. Skills that invoke EdgeSpeak also carry `minCliVersion` — the oldest `edgespeak-cli` they are written against. Skills without a CLI dependency (`edgespeak-translate`, `edgespeak-name-speakers`, and `edgespeak-yt-download`) omit it. If `edgespeak-cli --version` reports something older, or a flag documented in a skill is missing from the installed `--help`, run `edgespeak-cli update` first.

### Extra requirements for the karaoke skill

`edgespeak-karaoke` runs bundled scripts and renders video, so it also needs:

- **Node.js 18 or newer.**
- **FFmpeg built with `libass`**, and `ffprobe` — a separate executable that must also be on PATH.
  Style previews and hard subtitles both go through FFmpeg's `ass` filter, which libass provides; an
  FFmpeg without it fails with `No such filter: 'ass'`. Burning to MP4/MOV/MKV/TS also needs
  `libx264`; WebM needs `libvpx` and `libopus`.

`brew install ffmpeg` and the ffmpeg packages in the major Linux distributions include all of these.
Verify with:

```bash
node --version                       # v18 or newer
ffprobe -version                     # must exist alongside ffmpeg
ffmpeg -filters   | grep -w ass      # the ASS renderer
ffmpeg -encoders  | grep -w libx264  # H.264 output
```

### Extra requirements for speaker naming, video voice-overs, and YouTube acquisition

- `edgespeak-name-speakers` uses Python 3.9 or newer and its standard library; no extra Python packages are needed.
- `edgespeak-video-voice` uses Python 3.9 or newer and its standard library for its cue converter; its optional chunked-alignment path also uses FFmpeg.
- `edgespeak-yt-download` uses a current [yt-dlp](https://github.com/yt-dlp/yt-dlp) plus FFmpeg/ffprobe. YouTube extraction changes frequently, so check `yt-dlp --version` and follow yt-dlp's current official installation/update guidance rather than relying on an old system package.

## Activation

First use needs an account activation. Sign in on the official website and approve this device to sync your Free or subscription plan, or your historical buyout entitlement. Free does not require a purchase.

```bash
# Sign in, then approve this device on the official website
edgespeak-cli login

# Print the sign-in link when this machine has no browser
edgespeak-cli login --no-browser

# Or activate directly if you already have a license key
edgespeak-cli activate <KEY>
```

`login` waits for website approval and saves the resulting account activation on this machine. `--no-browser` prints the sign-in link instead of opening a browser; `--json` emits the resulting license status. If the machine already has a buyout license, sign in with its purchasing account: a different Key is rejected rather than silently replacing the existing entitlement. Historical buyout rights remain in place.

There is no seven-day signup or anonymous device activation. The new CLI removes the old anonymous activation commands; older clients calling the retired endpoint receive HTTP 410. If an old credential still reports a trial, use `login` to sync the real account plan; do not assume the credential identifies your purchasing account.

`<KEY>` is your existing license key (starts with `ES-`) from [edgespeak.com](https://edgespeak.com). Activation connects once to exchange the key for a signed credential stored on your machine. You can pass the key via `--stdin` (avoids shell history) or the `EDGESPEAK_LICENSE_KEY` environment variable. Run `edgespeak-cli status` to see your plan, offline cache window, and any lock reason. Use your account page to manage subscriptions and devices; do not repeatedly try the retired activation route.

For headless or air-gapped machines: `edgespeak-cli models download --all` pre-downloads the default transcription / alignment / segmentation models (standalone only — quit the EdgeSpeak app first), and lifetime licenses can then run `edgespeak-cli offline enable` to keep working fully offline.

## Skills

| Skill | Plugin | What it does |
|-------|--------|--------------|
| [`edgespeak-yt-download`](edgespeak-yt-download/SKILL.md) | `edgespeak-extras` | Download an authorized YouTube video's media, captions, or public metadata with conservative serial requests and safe cookie handling |
| [`edgespeak-transcribe`](edgespeak-transcribe/SKILL.md) | `edgespeak` | Transcribe audio/video to text / SRT / JSON with timing, speaker diarization, and sentence-shaping options, fully on-device |
| [`edgespeak-name-speakers`](edgespeak-name-speakers/SKILL.md) | `edgespeak` | Resolve anonymous `speaker_N` labels to evidence-backed names while preserving the original IDs and leaving uncertain identities unresolved |
| [`edgespeak-align`](edgespeak-align/SKILL.md) | `edgespeak` | Force-align audio against a known transcript, subtitle file, or lyrics → word-level timestamps (karaoke captions, clip cutting, voice-over sync). The default model covers 346 languages and mixed-language text, and lyrics with section headers follow the sung order |
| [`edgespeak-segment`](edgespeak-segment/SKILL.md) | `edgespeak` | Split a wall of (even unpunctuated) text into natural sentences — or re-split a word-timed transcript at a new cue length with every word timing re-mapped |
| [`edgespeak-broadcast`](edgespeak-broadcast/SKILL.md) | `edgespeak-extras` | Turn text into speech fully on-device (Broadcast): WAV synthesis with official named voices, cloned voices, or a voice designed from a text description, plus style instructions and reproducible seeds |
| [`edgespeak-video-voice`](edgespeak-video-voice/SKILL.md) | `edgespeak-extras` | Give code-rendered video (HyperFrames, Remotion, Canvas, Manim) an on-device voice-over: synthesize the narration, align it word by word, and export a cue table (JSON, `window.CUES` script, or frame numbers) that times captions and scene cuts |
| [`edgespeak-karaoke`](edgespeak-karaoke/SKILL.md) | `edgespeak` | Create styled word-highlighted ASS captions, preview presets on real video frames, and optionally burn them into the source container where practical |
| [`edgespeak-translate`](edgespeak-translate/SKILL.md) | `edgespeak` | Translate a timed transcript with the timings and 1:1 segment mapping intact — subtitles, bilingual SRT, or a length-budgeted script to be voiced |

## How it works

The transcription, alignment, segmentation, and broadcast skills shell out to `edgespeak-cli` (`transcribe` / `align` / `segment` / `speech`). The video voice-over skill chains `speech` and `align`, then converts the word timings with a bundled standard-library Python script. The karaoke skill prefers a configured EdgeSpeak MCP server and uses the CLI as its fallback. Speaker naming is a separate evidence-driven enrichment over diarized JSON; it never pretends the transcription engine recognized a person's identity. The YouTube skill uses yt-dlp for an explicitly authorized network acquisition before local processing. The translate skill uses no EdgeSpeak runtime at all — the agent does the translating itself, so the text stays on your machine like the audio does; its bundled checker, which verifies the timings and segment mapping survived, needs only Node.js 18+. EdgeSpeak audio processing stays on-device.

The same local capabilities are also available without a skill: `edgespeak-cli mcp` runs the EdgeSpeak MCP server over stdio (tools such as `edgespeak_transcribe_file` and `edgespeak_align`; see [MCP](https://edgespeak.com/docs/mcp)), and the Python SDK (`python -m pip install edgespeak`) wraps the same API, for example `EdgeSpeak().align("speech.wav", text_file="script.txt")` (see [Python SDK](https://edgespeak.com/docs/python-sdk)).

## License

Apache-2.0 — see [LICENSE](LICENSE).

### Explicit remote GPU use

Alignment, transcription, and segmentation skills also document attaching the public Python SDK to a user-selected remote gateway through HTTPS or an SSH tunnel. See [remote GPU attachment](../sdk/python/examples/remote-gpu.md). In this mode audio/text leaves the client for that server; the local-only privacy statements above apply to the default local deployment. Consumer-specific podcast schemas and publishing remain in the consuming project.

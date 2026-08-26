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

## Requirements

Most skills shell out to `edgespeak-cli`, a self-contained on-device transcription and speech runtime for **macOS Apple Silicon**, **Linux x86_64**, and **Windows x64**. The karaoke skill uses configured EdgeSpeak MCP tools when available and falls back to the same CLI. You can get the runtime in either of two ways:

- **Self-contained CLI for macOS and Linux — no app required:**

  ```bash
  curl -fsSL https://edgespeak.com/install.sh | sh
  ```

  This installs a self-contained runtime (CLI + on-device engine + dependencies) under `~/.edgespeak/runtime` and symlinks `edgespeak-cli` into `~/.local/bin` (PATH is set up for you). On Linux the installer detects NVIDIA GPUs (via `nvidia-smi`) and automatically installs a CUDA-enabled runtime matched to your GPU generation, falling back to the CPU build otherwise; set `EDGESPEAK_LINUX_PROFILE=cpu|cuda-legacy|cuda-modern|cuda-blackwell` to override the detection. At run time, `--device cpu|cuda|cuda:<N>|metal|auto` on `transcribe` / `align` / `segment` / `speech` selects the compute backend (standalone mode only).

- **Desktop app:** install [EdgeSpeak](https://edgespeak.com) from the website — it ships the same `edgespeak-cli`. This is the Windows installation path.

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

### Extra requirements for speaker naming and YouTube acquisition

- `edgespeak-name-speakers` uses Python 3.9 or newer and its standard library; no extra Python packages are needed.
- `edgespeak-yt-download` uses a current [yt-dlp](https://github.com/yt-dlp/yt-dlp) plus FFmpeg/ffprobe. YouTube extraction changes frequently, so check `yt-dlp --version` and follow yt-dlp's current official installation/update guidance rather than relying on an old system package.

## Activation

First use needs a one-time activation — the on-device engine requires a valid license:

```bash
# Sign in via your browser: purchased accounts activate this machine directly,
# new accounts start a free 7-day trial automatically.
edgespeak-cli login

# No account and no browser at hand? Start an instant anonymous 7-day trial
edgespeak-cli trial

# Or activate directly if you already have a license key
edgespeak-cli activate <KEY>
```

`login` opens a browser sign-in and finishes activation automatically — and if the device is already on the anonymous trial, signing in replaces the trial with your account credentials; `--no-browser` prints the sign-in link instead, `--json` emits the resulting license status. `trial` starts an anonymous, device-bound trial with zero friction (one trial per device; trial transcription has a daily time cap) — if `edgespeak-cli trial --help` describes a browser sign-in, the installed CLI predates the instant trial — run `edgespeak-cli update` first. `<KEY>` is your license key (starts with `ES-`) from [edgespeak.com](https://edgespeak.com). Activation goes online once to exchange the key for a signed credential stored on your machine. Buyout licenses show as `lifetime`; unless full offline mode is explicitly enabled, `edgespeak-cli status` will also show how long the cached license can work without internet. You can pass the key via `--stdin` (avoids shell history) or the `EDGESPEAK_LICENSE_KEY` environment variable. Run `edgespeak-cli status` any time to see your plan, trial time left, offline cache window, and any lock reason; expired or invalid licenses surface a purchase link at [edgespeak.com](https://edgespeak.com).

For headless or air-gapped machines: `edgespeak-cli models download --all` pre-downloads the default transcription / alignment / segmentation models (standalone only — quit the EdgeSpeak app first), and lifetime licenses can then run `edgespeak-cli offline enable` to keep working fully offline.

## Skills

| Skill | What it does |
|-------|--------------|
| [`edgespeak-yt-download`](edgespeak-yt-download/SKILL.md) | Download an authorized YouTube video's media, captions, or public metadata with conservative serial requests and safe cookie handling |
| [`edgespeak-transcribe`](edgespeak-transcribe/SKILL.md) | Transcribe audio/video to text / SRT / JSON with timing, speaker diarization, and sentence-shaping options, fully on-device |
| [`edgespeak-name-speakers`](edgespeak-name-speakers/SKILL.md) | Resolve anonymous `speaker_N` labels to evidence-backed names while preserving the original IDs and leaving uncertain identities unresolved |
| [`edgespeak-align`](edgespeak-align/SKILL.md) | Force-align audio against a known transcript → word-level timestamps (karaoke captions, clip cutting, dubbing) |
| [`edgespeak-segment`](edgespeak-segment/SKILL.md) | Split a wall of (even unpunctuated) text into natural sentences — or re-split a word-timed transcript at a new cue length with every word timing re-mapped |
| [`edgespeak-broadcast`](edgespeak-broadcast/SKILL.md) | Turn text into speech fully on-device (Broadcast): WAV synthesis with official named voices, cloned voices, or a voice designed from a text description, plus style instructions and reproducible seeds |
| [`edgespeak-karaoke`](edgespeak-karaoke/SKILL.md) | Create styled word-highlighted ASS captions, preview presets on real video frames, and optionally burn them into the source container where practical |
| [`edgespeak-translate`](edgespeak-translate/SKILL.md) | Translate a timed transcript with the timings and 1:1 segment mapping intact — subtitles, bilingual SRT, or a length-budgeted dub script |

## How it works

The transcription, alignment, segmentation, and broadcast skills shell out to `edgespeak-cli` (`transcribe` / `align` / `segment` / `speech`). The karaoke skill prefers a configured EdgeSpeak MCP server and uses the CLI as its fallback. Speaker naming is a separate evidence-driven enrichment over diarized JSON; it never pretends the transcription engine recognized a person's identity. The YouTube skill uses yt-dlp for an explicitly authorized network acquisition before local processing. The translate skill uses no EdgeSpeak runtime at all — the agent does the translating itself, so the text stays on your machine like the audio does; its bundled checker, which verifies the timings and segment mapping survived, needs only Node.js 18+. EdgeSpeak audio processing stays on-device.

## License

MIT — see [LICENSE](LICENSE).

# EdgeSpeak

**English** · [简体中文](README.zh-CN.md)

Private, on-device speech tools for macOS, the command line, and AI agents.
EdgeSpeak transcribes audio and video locally, force-aligns known text to speech,
segments text, and exposes the same local capabilities to agent workflows.

> **Latest release:** EdgeSpeak 0.4.4. GitHub Releases in this repository is the
> official public release channel.

[Releases](https://github.com/lattifai/EdgeSpeak/releases) ·
[Website](https://edgespeak.com) ·
[Changelog](https://edgespeak.com/changelog) ·
[Agent Skills](https://github.com/lattifai/EdgeSpeak-Skills)

## Downloads

Release packages are attached to the
[GitHub Releases](https://github.com/lattifai/EdgeSpeak/releases) page. They are
not committed to the Git tree.

| Package | Platform | Availability |
| --- | --- | --- |
| EdgeSpeak desktop app | macOS on Apple silicon | Stable — 0.4.4 |
| EdgeSpeak desktop app | Windows 10/11 on x86_64 | Unsigned Preview — 0.4.4 |
| Self-contained `edgespeak-cli` | macOS on Apple silicon | Stable — 0.4.4 |
| Self-contained `edgespeak-cli` | Windows 10/11 on x86_64 | Unsigned Preview — 0.4.4 |
| Self-contained `edgespeak-cli` | Ubuntu Linux on x86_64 | Planned |

Each published package is accompanied by release notes and a SHA-256 checksum.
The macOS app is signed and notarized for distribution. The Windows build is an
unsigned Preview with manual updates; verify its checksum before installation.
Windows 11 x64 was validated on physical NVIDIA hardware across CPU, CUDA, and
Vulkan. Windows 10 x64 is supported at Preview level but was not exercised on a
physical Windows 10 machine for this release; hosted Windows CI covers the
release workflow.

## Install the CLI on macOS

The current one-line installer provides the self-contained macOS arm64 runtime;
the desktop app is optional:

```bash
curl -fsSL https://edgespeak.com/install.sh | sh
```

Activate it once, then confirm the runtime is ready:

```bash
edgespeak-cli trial
edgespeak-cli status
```

If you already have a license key, use `edgespeak-cli activate <KEY>` instead.
The same macOS CLI package is also downloadable directly from this repository's
Releases page.

## Install the CLI on Windows

Run this in PowerShell on Windows 10/11 x64. The default installation supports
CPU and Vulkan without downloading the optional NVIDIA CUDA vendor runtime:

```powershell
irm https://edgespeak.com/install.ps1 | iex
```

To opt into CUDA, set `EDGESPEAK_WINDOWS_ACCELERATOR` before installation:

```powershell
$env:EDGESPEAK_WINDOWS_ACCELERATOR = "cuda"
irm https://edgespeak.com/install.ps1 | iex
```

## CLI examples

```bash
# Transcribe audio or video
edgespeak-cli transcribe meeting.m4a -o meeting.json
edgespeak-cli transcribe interview.mp4 -o interview.srt

# Align a known transcript to speech
edgespeak-cli align meeting.m4a --text-file transcript.txt -o aligned.json

# Split plain text into natural sentences
edgespeak-cli segment --file transcript.txt -o sentences.json

# Inspect the local runtime
edgespeak-cli models
edgespeak-cli status
```

The CLI uses the desktop app's warm local engine when the app is running. When
the app is closed, the self-contained macOS and Windows CLI packages start their
bundled on-device engine instead. Audio and video remain on your machine in both
modes.

## Agent Skills

Install all public EdgeSpeak Skills into any Skills-compatible agent:

```bash
npx skills add lattifai/EdgeSpeak-Skills
```

You can also target a specific agent with `--agent claude-code`, `--agent
cursor`, or `--agent codex`.

| Skill | Capability |
| --- | --- |
| [`edgespeak-transcribe`](https://github.com/lattifai/EdgeSpeak-Skills/blob/main/skills/edgespeak-transcribe/SKILL.md) | Transcribe local audio/video to text, SRT, or JSON |
| [`edgespeak-align`](https://github.com/lattifai/EdgeSpeak-Skills/blob/main/skills/edgespeak-align/SKILL.md) | Produce word-level timing from media and a known transcript |
| [`edgespeak-segment`](https://github.com/lattifai/EdgeSpeak-Skills/blob/main/skills/edgespeak-segment/SKILL.md) | Split long or unpunctuated text into natural sentences |
| `edgespeak-karaoke` *(coming with the next Skills update)* | Create styled word-highlighted ASS subtitles and optional hard-subbed video |

The transcription, alignment, and segmentation Skills call `edgespeak-cli`.
The upcoming karaoke Skill prefers configured EdgeSpeak MCP tools and falls back
to the same CLI. See the
[EdgeSpeak Skills repository](https://github.com/lattifai/EdgeSpeak-Skills) for
full instructions.

## MCP

`edgespeak-cli` also exposes EdgeSpeak tools over stdio for MCP-compatible
clients. For example, after installing and activating the CLI:

```bash
claude mcp add edgespeak -- edgespeak-cli mcp
```

## Repository scope

This repository is the public distribution home for:

- versioned release notes;
- the signed macOS installer;
- the unsigned Windows Preview installer;
- self-contained CLI archives and checksums; and
- future Linux CLI packages.

Release maintainers should follow the
[public release checklist](docs/RELEASING.md). Product source, build outputs, and
large runtime assets are maintained outside this Git tree.

## Languages

English is the default documentation language in `README.md`. Simplified
Chinese is available in `README.zh-CN.md`. Future translations should use
`README.<locale>.md` and be added to the language switch at the top of every
README.

## Support

Report release-package problems in
[GitHub Issues](https://github.com/lattifai/EdgeSpeak/issues). For product and
license information, visit [edgespeak.com](https://edgespeak.com).

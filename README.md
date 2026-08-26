# EdgeSpeak

**English** · [简体中文](README.zh-CN.md)

Private, on-device transcription, alignment, segmentation, and speech tools for
desktop, CLI, MCP, and AI agent workflows.

[Releases](https://github.com/lattifai/EdgeSpeak/releases) ·
[Website](https://edgespeak.com) ·
[Changelog](https://edgespeak.com/changelog) ·
[Agent Skills](skills/README.md)

## Desktop downloads

| Platform | Availability |
| --- | --- |
| macOS on Apple silicon | Stable |
| Windows 10/11 on x86_64 | Unsigned Preview |

Download desktop installers and checksums from
[GitHub Releases](https://github.com/lattifai/EdgeSpeak/releases).

## Install the CLI

macOS on Apple silicon or Linux on x86_64:

```bash
curl -fsSL https://edgespeak.com/install.sh | sh
```

Windows 10/11 on x86_64:

```powershell
irm https://edgespeak.com/install.ps1 | iex
```

Windows uses CPU or Vulkan by default. To enable CUDA:

```powershell
$env:EDGESPEAK_WINDOWS_ACCELERATOR = "cuda"
irm https://edgespeak.com/install.ps1 | iex
```

Activate a trial or license, then verify the runtime:

```bash
edgespeak-cli trial # or: edgespeak-cli activate <KEY>
edgespeak-cli status
```

## CLI and MCP

```bash
edgespeak-cli transcribe meeting.m4a -o meeting.json
edgespeak-cli align meeting.m4a --text-file transcript.txt -o aligned.json
edgespeak-cli segment --file transcript.txt -o sentences.json
claude mcp add edgespeak -- edgespeak-cli mcp
```

## Agent Skills

See [EdgeSpeak Skills](skills/README.md) for the current agent skill catalog and
installation instructions.

## Repository

This repository contains public documentation, Agent Skills, and GitHub
Releases. Product source code and build outputs are maintained elsewhere.

[Release checklist](docs/RELEASING.md) ·
[Support](https://github.com/lattifai/EdgeSpeak/issues)

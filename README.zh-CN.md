# EdgeSpeak

[English](README.md) · **简体中文**

面向 macOS、命令行和 AI Agent 的隐私优先端侧语音工具。EdgeSpeak 在本机转录音视频、
把已有文稿与语音做强制对齐、完成文本分句，并把同一组本地能力提供给 Agent 工作流。

> **最新版本：** EdgeSpeak 0.4.4。本仓库的 GitHub Releases 是官方公开发布渠道。

[版本发布](https://github.com/lattifai/EdgeSpeak/releases) ·
[官方网站](https://edgespeak.com) ·
[更新记录](https://edgespeak.com/zh/changelog) ·
[Agent Skills](https://github.com/lattifai/EdgeSpeak-Skills)

## 下载

安装包统一作为附件发布到
[GitHub Releases](https://github.com/lattifai/EdgeSpeak/releases)，不直接提交到 Git 代码树。

| 软件包 | 平台 | 状态 |
| --- | --- | --- |
| EdgeSpeak 桌面 App | Apple 芯片 Mac | Stable — 0.4.4 |
| EdgeSpeak 桌面 App | Windows 10/11 x86_64 | 未签名 Preview — 0.4.4 |
| 自包含 `edgespeak-cli` | Apple 芯片 Mac | Stable — 0.4.4 |
| 自包含 `edgespeak-cli` | Windows 10/11 x86_64 | 未签名 Preview — 0.4.4 |
| 自包含 `edgespeak-cli` | x86_64 Ubuntu Linux | 规划中 |

每个正式软件包都会同时提供版本说明和 SHA-256 校验值。macOS App 已完成发布签名和公证。
Windows 版本是采用手动更新的未签名 Preview，安装前请核对校验值。
Windows 11 x64 已在 NVIDIA 物理机上完成 CPU、CUDA、Vulkan 验收。Windows 10 x64
属于 Preview 支持范围，但本次没有使用 Windows 10 物理机验收；发布流程由 Hosted
Windows CI 覆盖。

## 在 macOS 上安装 CLI

当前的一键安装脚本会提供自包含的 macOS arm64 运行时，无需安装桌面 App：

```bash
curl -fsSL https://edgespeak.com/install.sh | sh
```

首次激活后，确认本地运行时已经就绪：

```bash
edgespeak-cli trial
edgespeak-cli status
```

如果已经有授权 Key，也可以改用 `edgespeak-cli activate <KEY>`。同一个 macOS CLI
软件包也可以从本仓库的 Releases 页面直接下载。

## 在 Windows 上安装 CLI

在 Windows 10/11 x64 的 PowerShell 中运行。默认安装支持 CPU 和 Vulkan，不会下载可选的
NVIDIA CUDA 厂商运行库：

```powershell
irm https://edgespeak.com/install.ps1 | iex
```

如需启用 CUDA，请在安装前设置 `EDGESPEAK_WINDOWS_ACCELERATOR`：

```powershell
$env:EDGESPEAK_WINDOWS_ACCELERATOR = "cuda"
irm https://edgespeak.com/install.ps1 | iex
```

## CLI 示例

```bash
# 转录音频或视频
edgespeak-cli transcribe meeting.m4a -o meeting.json
edgespeak-cli transcribe interview.mp4 -o interview.srt

# 把已有文稿与语音对齐
edgespeak-cli align meeting.m4a --text-file transcript.txt -o aligned.json

# 把纯文本切分成自然句子
edgespeak-cli segment --file transcript.txt -o sentences.json

# 查看本地运行时
edgespeak-cli models
edgespeak-cli status
```

桌面 App 运行时，CLI 会复用 App 中已经预热的本地引擎；App 关闭时，自包含的 macOS 与
Windows CLI 会启动随附的端侧引擎。两种模式下，音视频都留在本机处理。

## Agent Skills

把全部公开 EdgeSpeak Skills 安装到任意兼容 Skills 的 Agent：

```bash
npx skills add lattifai/EdgeSpeak-Skills
```

也可以通过 `--agent claude-code`、`--agent cursor` 或 `--agent codex` 指定 Agent。

| Skill | 能力 |
| --- | --- |
| [`edgespeak-transcribe`](https://github.com/lattifai/EdgeSpeak-Skills/blob/main/skills/edgespeak-transcribe/SKILL.md) | 把本机音视频转成文本、SRT 或 JSON |
| [`edgespeak-align`](https://github.com/lattifai/EdgeSpeak-Skills/blob/main/skills/edgespeak-align/SKILL.md) | 根据媒体和已有文稿生成词级时间戳 |
| [`edgespeak-segment`](https://github.com/lattifai/EdgeSpeak-Skills/blob/main/skills/edgespeak-segment/SKILL.md) | 把长文本或无标点文本切成自然句子 |
| `edgespeak-karaoke` *(将在下次 Skills 更新中提供)* | 生成带样式的逐词高亮 ASS 字幕，并可选择输出硬字幕视频 |

转录、对齐和分句 Skill 调用 `edgespeak-cli`；即将提供的卡拉 OK Skill 优先使用已经
配置的 EdgeSpeak MCP 工具，并回退到同一个 CLI。完整说明见
[EdgeSpeak Skills 仓库](https://github.com/lattifai/EdgeSpeak-Skills)。

## MCP

`edgespeak-cli` 也可以通过 stdio 向兼容 MCP 的客户端提供 EdgeSpeak 工具。例如，安装并
激活 CLI 后，可在 Claude Code 中执行：

```bash
claude mcp add edgespeak -- edgespeak-cli mcp
```

## 仓库范围

本仓库是以下公开发布内容的统一入口：

- 带版本的发布说明；
- 已签名的 macOS 安装包；
- 未签名的 Windows Preview 安装包；
- 自包含 CLI 压缩包及校验值；
- 未来的 Linux CLI 软件包。

发布维护者应遵循[公开发布清单](docs/RELEASING.zh-CN.md)。产品源码、构建中间产物和
大型运行时资源不放在本 Git 代码树中。

## 语言

`README.md` 是默认英文文档，`README.zh-CN.md` 提供简体中文。未来新增翻译时，使用
`README.<locale>.md` 命名，并在每份 README 顶部的语言切换栏中加入入口。

## 支持

发布包相关问题请提交到
[GitHub Issues](https://github.com/lattifai/EdgeSpeak/issues)。产品和授权信息请访问
[edgespeak.com](https://edgespeak.com)。

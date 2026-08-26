# EdgeSpeak

[English](README.md) · **简体中文**

面向桌面端、CLI、MCP 与 AI Agent 工作流的隐私优先端侧转录、对齐、分句和语音工具。

[版本发布](https://github.com/lattifai/EdgeSpeak/releases) ·
[官方网站](https://edgespeak.com) ·
[更新记录](https://edgespeak.com/zh/changelog) ·
[Agent Skills](skills/README.zh-CN.md)

## 桌面端下载

| 平台 | 状态 |
| --- | --- |
| Apple 芯片 Mac | Stable |
| Windows 10/11 x86_64 | 未签名 Preview |

桌面安装包与校验值请从
[GitHub Releases](https://github.com/lattifai/EdgeSpeak/releases) 下载。

## 安装 CLI

Apple 芯片 Mac 或 x86_64 Linux：

```bash
curl -fsSL https://edgespeak.com/install.sh | sh
```

Windows 10/11 x86_64：

```powershell
irm https://edgespeak.com/install.ps1 | iex
```

Windows 默认使用 CPU 或 Vulkan。如需启用 CUDA：

```powershell
$env:EDGESPEAK_WINDOWS_ACCELERATOR = "cuda"
irm https://edgespeak.com/install.ps1 | iex
```

激活试用或正式授权后，确认运行时状态：

```bash
edgespeak-cli trial # 或：edgespeak-cli activate <KEY>
edgespeak-cli status
```

## CLI 与 MCP

```bash
edgespeak-cli transcribe meeting.m4a -o meeting.json
edgespeak-cli align meeting.m4a --text-file transcript.txt -o aligned.json
edgespeak-cli segment --file transcript.txt -o sentences.json
claude mcp add edgespeak -- edgespeak-cli mcp
```

当前 Agent Skill 清单与安装方式请查看
[EdgeSpeak Skills](skills/README.zh-CN.md)。

## 仓库

本仓库包含公开文档、Agent Skills 和 GitHub Releases；产品源码与构建产物在其他仓库维护。

[发布清单](docs/RELEASING.zh-CN.md) ·
[问题反馈](https://github.com/lattifai/EdgeSpeak/issues)

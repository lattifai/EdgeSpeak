# EdgeSpeak

[English](README.md) · **简体中文**

面向 Claude Code 的本机语音工作流。EdgeSpeak 通过本机的 `edgespeak-cli` 在你自己的电脑上转录、对齐音视频，录音不会被上传。

## 能做什么

| Skill | 能力 |
|-------|------|
| `edgespeak-transcribe` | 把音视频转成文字、SRT 或 JSON，支持词级时间、匿名说话人标签和字幕分句参数 |
| `edgespeak-align` | 把音频与已有文稿做强制对齐，得到词级时间戳 |
| `edgespeak-segment` | 把长段或无标点的文字切成自然句子，也能重切带词级时间的转录 |
| `edgespeak-karaoke` | 生成逐词高亮的 ASS 字幕，用真实画面预览样式，并用 FFmpeg 烧录进视频 |
| `edgespeak-translate` | 翻译带时间轴的文稿，保持每个时间戳和 1:1 段落映射不变 |
| `edgespeak-name-speakers` | 只在名单或来源页面能证实时，把匿名 `speaker_N` 标签换成真实姓名 |

请求合适时 Claude 会自动使用这些 Skill，也可以直接调用，例如 `/edgespeak:edgespeak-transcribe`。

## 前置要求

- **本机的 EdgeSpeak CLI。** 按 [edgespeak.com/docs/cli](https://edgespeak.com/docs/cli#install) 的步骤安装，支持 macOS Apple Silicon、Linux x86_64 和 Windows x64 (EdgeSpeak 桌面 App 也自带它)。
- **同一台电脑上的 Claude Code。** 这些 Skill 调用的是你电脑上的 CLI，所以不能在 claude.ai 对话的云端沙箱里运行。从 Claude 官方目录添加插件后，请在 Claude Code 里使用。
- **EdgeSpeak 授权。** 运行 `edgespeak-cli login` 或 `edgespeak-cli trial`，新设备有 7 天试用。方案见 [edgespeak.com](https://edgespeak.com)。
- 卡拉 OK 字幕另需 Node.js 18+ 和带 libass 的 FFmpeg；说话人命名需要 Python 3.9+。

## 数据与联网

- 音频和视频在你的电脑上转录，这些 Skill 不会上传它们。你让 Claude 处理的转录文字会成为 Claude 对话的一部分。
- `edgespeak-cli` 在激活或刷新授权时会连接 edgespeak.com；首次使用时会从 download.edgespeak.com 以及 EdgeSpeak 在 huggingface.co、modelscope.cn 上的模型仓库下载模型文件。
- `edgespeak-translate` 不联网，翻译由 Claude 在对话中完成。
- `edgespeak-name-speakers` 可能会向你索要来源页面 URL 并读取该页面；发起这次联网时会说明，也不会为了读取元数据而下载媒体。它保留原始说话人 ID，为每个拟定的姓名列出证据，证据有歧义时就不命名。

隐私政策：[edgespeak.com/privacy](https://edgespeak.com/privacy)

## 更多 EdgeSpeak Skill

更多 EdgeSpeak Skill 发布在面向 Claude Code 的 EdgeSpeak 插件市场：

```
/plugin marketplace add lattifai/EdgeSpeak
```

## 支持

问题反馈：[github.com/lattifai/EdgeSpeak/issues](https://github.com/lattifai/EdgeSpeak/issues)

## 许可

Apache-2.0，见 [LICENSE](LICENSE)。

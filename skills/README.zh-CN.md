# EdgeSpeak Skills

[English](README.md) · **简体中文**

这里是 EdgeSpeak Agent Skills 的唯一维护源；后续开发与更新统一在 EdgeSpeak 主仓库中管理。

让任意支持 Agent Skills 的客户端获取已获授权的媒体、经 [EdgeSpeak](https://edgespeak.com) 在**本机**转写音视频，并把匿名说话人标签解析成有证据支持的真实姓名。EdgeSpeak 转写时音频不出设备。

## 安装

```bash
# 自动识别当前 agent
npx skills add lattifai/EdgeSpeak

# 或指定 agent
npx skills add lattifai/EdgeSpeak --agent claude-code
npx skills add lattifai/EdgeSpeak --agent cursor
npx skills add lattifai/EdgeSpeak --agent codex
```

## 前置要求

大部分 Skill 调用 `edgespeak-cli` —— 一个自包含的本机转录与语音合成运行时，支持 **macOS Apple Silicon**、**Linux x86_64** 和 **Windows x64**。卡拉 OK Skill 优先使用已配置的 EdgeSpeak MCP 工具，并回退到同一个 CLI。本地运行时有两种获取方式：

- **macOS 和 Linux 自包含 CLI —— 无需桌面 App：**

  ```bash
  curl -fsSL https://edgespeak.com/install.sh | sh
  ```

  会把自包含运行时 (CLI + 本地引擎 + 依赖) 安装到 `~/.edgespeak/runtime`，并把 `edgespeak-cli` 软链进 `~/.local/bin` (PATH 自动配好)。Linux 上安装脚本会探测 NVIDIA GPU (经 `nvidia-smi`) 并自动安装匹配 GPU 代际的 CUDA 运行时，无 GPU 时回落 CPU 构建；可用 `EDGESPEAK_LINUX_PROFILE=cpu|cuda-legacy|cuda-modern|cuda-blackwell` 覆盖探测结果。运行时可在 `transcribe` / `align` / `segment` / `speech` 上用 `--device cpu|cuda|cuda:<N>|metal|auto` 选择计算后端 (仅 standalone 模式)。

- **桌面 App：** 从官网安装 [EdgeSpeak](https://edgespeak.com)，它自带同一个 `edgespeak-cli`。Windows 请使用此安装方式。

无论哪种方式，装完后验证一下：

```bash
edgespeak-cli --version
edgespeak-cli status
```

之后用 `edgespeak-cli update` 更新运行时 (重新拉取最新的自包含包)。

### 版本约定

每个 Skill 的 frontmatter 都带有自身的 `version`。会调用 EdgeSpeak 的 Skill 还带有 `minCliVersion` —— 它所要求的最低 `edgespeak-cli` 版本；不依赖 CLI 的 `edgespeak-translate`、`edgespeak-name-speakers` 和 `edgespeak-yt-download` 则省略该字段。如果 `edgespeak-cli --version` 低于要求，或 Skill 里写到的参数在本机 `--help` 中不存在，先跑 `edgespeak-cli update` 更新。

### 卡拉 OK Skill 的额外依赖

`edgespeak-karaoke` 会运行内置脚本并渲染视频，因此还需要：

- **Node.js 18 或更高版本。**
- **带 `libass` 编译的 FFmpeg**，以及 `ffprobe` —— 它是独立的可执行文件，同样需要在 PATH 中。
  样式预览和硬字幕都走 FFmpeg 的 `ass` 滤镜，该滤镜由 libass 提供；缺少它的 FFmpeg 会直接报
  `No such filter: 'ass'`。烧录到 MP4/MOV/MKV/TS 还需要 `libx264`；WebM 需要 `libvpx` 和 `libopus`。

`brew install ffmpeg` 以及主流 Linux 发行版的 ffmpeg 包都已包含上述组件。可以这样验证：

```bash
node --version                       # v18 或更高
ffprobe -version                     # 必须与 ffmpeg 一同存在
ffmpeg -filters   | grep -w ass      # ASS 渲染器
ffmpeg -encoders  | grep -w libx264  # H.264 输出
```

### 说话人命名与 YouTube 获取的额外依赖

- `edgespeak-name-speakers` 使用 Python 3.9 或更高版本及其标准库，不需要额外 Python 包。
- `edgespeak-yt-download` 使用较新的 [yt-dlp](https://github.com/yt-dlp/yt-dlp) 以及 FFmpeg/ffprobe。YouTube 提取方式经常变化，请先检查 `yt-dlp --version`，并按 yt-dlp 当前官方说明安装或更新，不要依赖过旧的系统软件包。

## 激活

首次使用需要一次性激活 —— 本地引擎需要有效授权：

```bash
# 浏览器登录：已购账号直接激活本机，新账号自动获得 7 天免费试用
edgespeak-cli login

# 没有账号、也不方便开浏览器？立即开通匿名 7 天试用
edgespeak-cli trial

# 已有授权 Key 时也可直接激活
edgespeak-cli activate <KEY>
```

`login` 打开浏览器登录并自动完成激活——若本机已在匿名试用中，登录会用你的账号凭据替换试用授权；`--no-browser` 只打印登录链接，`--json` 输出激活后的授权状态。`trial` 零摩擦开通匿名设备试用 (一台设备一次；试用转录有每日时长上限)；若 `edgespeak-cli trial --help` 显示的是浏览器登录说明，说明当前安装的 CLI 早于即时试用功能——先跑 `edgespeak-cli update` 更新。`<KEY>` 是你的授权 Key (以 `ES-` 开头，来自 [edgespeak.com](https://edgespeak.com))。激活会联网一次，用 Key 换取签名凭据并落地本机。买断授权会显示为 `lifetime`；除非显式开启 full offline mode，`edgespeak-cli status` 还会显示缓存授权可在无网络下工作的时间窗口。也可以用 `--stdin` 传 Key (避免进 shell 历史) 或环境变量 `EDGESPEAK_LICENSE_KEY`。随时可跑 `edgespeak-cli status` 查看授权方案、试用剩余时间、离线缓存窗口和锁定原因；过期或失效时会给出 [edgespeak.com](https://edgespeak.com) 的购买链接。

无人值守或离线机器：先用 `edgespeak-cli models download --all` 预下载默认的转录 / 对齐 / 分句模型 (仅 standalone —— 需先退出 EdgeSpeak App)，买断授权随后可 `edgespeak-cli offline enable` 完全离线工作。

## 包含的 Skill

| Skill | 能力 |
|-------|------|
| [`edgespeak-yt-download`](edgespeak-yt-download/SKILL.md) | 用保守的串行请求与安全的 Cookie 处理，下载已获授权的 YouTube 视频、音频、字幕或公开元数据 |
| [`edgespeak-transcribe`](edgespeak-transcribe/SKILL.md) | 把音视频转成文字 / SRT / JSON，并支持时间轴、说话人识别与分句参数，全程本地 |
| [`edgespeak-name-speakers`](edgespeak-name-speakers/SKILL.md) | 把匿名 `speaker_N` 标签解析成有证据支持的姓名，同时保留原始 ID，并让不确定身份保持未解析 |
| [`edgespeak-align`](edgespeak-align/SKILL.md) | 把音频与已有文稿做强制对齐 → 词级时间戳 (逐词高亮字幕、按句剪辑、配音对齐) |
| [`edgespeak-segment`](edgespeak-segment/SKILL.md) | 把一大段 (甚至无标点的) 文字切成自然句子，也能按新的字幕长度重切带词级时间的转录 JSON 并同步重排每个词的时间 |
| [`edgespeak-broadcast`](edgespeak-broadcast/SKILL.md) | 把文字变成语音 (播报)，全程本地：官方具名音色、克隆音色或按文字描述设计的音色，支持风格指令与可复现种子，输出 WAV |
| [`edgespeak-karaoke`](edgespeak-karaoke/SKILL.md) | 生成带样式的逐词高亮 ASS 字幕，可用真实视频帧预览预设，并尽量按源容器烧录硬字幕 |
| [`edgespeak-translate`](edgespeak-translate/SKILL.md) | 翻译带时间轴的文稿，保持时间戳与 1:1 段落映射不变——用于字幕、双语 SRT，或有长度预算的配音脚本 |

## 原理

转录、对齐、分句与播报 Skill 经 `edgespeak-cli`（`transcribe` / `align` / `segment` / `speech`）工作；卡拉 OK Skill 优先使用已配置的 EdgeSpeak MCP，CLI 作为回退。说话人命名是在 diarized JSON 上独立进行的证据推断，不会假装转写引擎已经识别出人物身份。YouTube Skill 使用 yt-dlp，在本地处理前执行用户明确授权的联网获取。翻译 Skill 完全不用 EdgeSpeak 运行时——由 Agent 自己翻译，所以文本和音频一样留在本机；它自带的校验脚本 (核对时间轴与段落映射有没有被改坏) 只需要 Node.js 18+。EdgeSpeak 的音频处理始终在设备内完成。

## 许可

MIT —— 见 [LICENSE](LICENSE)。

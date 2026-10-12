# EdgeSpeak Python SDK

当前为 **0.6.4 开发候选**，尚未发布到 PyPI。需要 Python 3.10+，以及支持
`edgespeak-cli serve --sdk` 的 CLI 构建；旧版已发布 CLI 尚不支持这个握手。

SDK 发布版本跟随用户确定的 CLI 版本。所有支持的 Python 版本和平台共用一个
纯 Python `py3-none-any` wheel；native CLI 单独安装。

SDK 自动从 PATH 和标准安装位置发现 CLI，要求 **CLI ≥ 0.6.4 且支持
`edgespeak-sdk-v2` 协议**；最低版本可通过 `edgespeak.MIN_CLI_VERSION` 查看。
兼容的本地安装直接复用，不联网检查。缺失或不兼容时，自动调用官方稳定版安装器，
将新运行时安装到 `~/.edgespeak/sdk/` 下的独立目录，沿用[官网安装器](https://edgespeak.com/zh/docs/cli)
的平台选择与下载校验，保留原 CLI 入口、PATH 和运行中的旧版本。多个 SDK 进程串行安装，安装后再次
检查版本和协议；如果官方 CLI 或安装器版本仍不满足要求，抛出明确的 `RuntimeStartError`，不循环安装。
不提供 `cli_path` 参数；导入包和连接现有网关均不会安装 CLI。

自动安装支持 macOS Apple Silicon、Linux x86_64 和 Windows x64，需要联网、
用户安装目录可写，以及官方安装器依赖（POSIX shell/curl/tar 或 Windows PowerShell）。
安装单独限时 20 分钟，`startup_timeout` 只计算服务启动就绪的等待时间。
安装器不会收到账号 API Key，安装阶段不更新模型、不访问账号凭据库。
推理前向 SDK 提供账号 API Key，或复用桌面 App / 已有 CLI 激活的设备。
Python 包不包含 CLI、引擎或模型。

```python
from edgespeak import EdgeSpeak

with EdgeSpeak() as client:
    transcript = client.transcribe("meeting.wav", language="zh", diarize=True)
    aligned = client.align("meeting.wav", text="与音频对应的逐字稿。")
    turns = client.diarize("meeting.wav", num_speakers=2)
    embedding = client.speaker_embedding("speaker.wav")
```

结果保留网关 JSON，时间戳单位为秒。语言参数由运行时校验，省略时由运行时判断。
对齐必须提供与音频对应的原语言文本。文件错误保留 Python `OSError`；网关错误为
带 `code` 和 `status_code` 的 `EdgeSpeakError`，不回显服务端原始报错文本。

建议创建一个客户端反复使用。默认经 CLI 启动独占本机服务，使用随机端口和临时令牌；
导入模块不启动服务。模型按需加载，首次调用可能下载模型。

使用 `with` 或显式 `close()` 确保释放；GC 和解释器正常退出仅作兜底。关闭最多先等
15 秒，然后 terminate、kill 分别再等 3 秒。CLI 监听父进程管道，在父进程被强杀时也会
退出；卡住的 HTTP 排空由 10 秒 watchdog 兜底。native Host 与 worker 仍由 CLI 管理，
其清理可能晚于 HTTP 端口关闭。不要把端口关闭等同于模型资源已验收释放。

显式 `base_url` 接入现有服务时，SDK 关闭不会终止该服务，`gateway_key` 指本机网关令牌。
SDK 自己启动服务时，可用 `EdgeSpeak(api_key=os.environ["EDGESPEAK_API_KEY"])`。
CLI 只通过环境变量接收账号密钥，不放入命令行参数。密钥和会话凭据仅驻留进程内存，
不覆盖桌面账号；用量账本仍共享持久化。省略 `api_key` 时，`EdgeSpeak()` 自动读取 `EDGESPEAK_API_KEY`，
并在内部转换为 CLI 的账号凭据。接入已有网关使用 `gateway_key`；示例从
`EDGESPEAK_GATEWAY_KEY` 读取网关令牌。
账号密钥不能作为 `gateway_key`，也不能用于显式 `base_url` 的附加模式。
此功能依赖配套的未发布后端与 CLI；生产部署及完整账号鉴权联调尚未完成。

账号密钥要求在线授权，不能开启离线模式。撤销后服务端拒绝新请求，已签发凭据
最多有效五分钟；撤销不会中断已经开始的推理任务。

同一机器上的 SDK 和桌面端共用设备名额。关闭 SDK 或撤销密钥不会移除该设备；
不再使用的机器可在账号页的设备管理中移除，以释放名额。账号密钥在密码重置后
仍然有效，直到到期或手动撤销。

远程地址必须 HTTPS；不跟随重定向，也不读取环境代理或
环境 CA 配置。fork 子进程不可复用父客户端；多进程优先使用 spawn。

`timeout` 默认 600 秒，按 HTTP I/O 阶段计时，不是任务总耗时上限；超时不保证推理停止。
`startup_timeout` 默认 30 秒，从完成 CLI 发现或安装后开始计算。

开发安装、完整接口示例和测试命令见 [English README](README.md)。当前测试包括 HTTP
替身与真实 macOS CLI 生命周期；macOS 已单独通过转录、对齐、说话人分离、声纹、
相似度及所属进程树释放的真实模型验收。Windows 已通过实例隔离、认证、附加模式、关闭/GC 和强杀 Python 后服务退出验收；
本候选尚未验证 Windows 模型推理与 Linux 平台。

自动安装已通过本地替身测试；新安装器模式与配套 CLI 仍待发布及完整下载验收。
Windows 和 Linux 的自动安装尚未在对应平台验证。

## 每个 SDK 版本的 CLI 要求

每次 SDK 发版都携带自己的最低 CLI 版本，统一定义在 `src/edgespeak/_bootstrap.py`
的 `MIN_CLI_VERSION`。新 SDK 依赖更新的 CLI 时，提高这个常量即可。
启动入口 `ensure_cli()` 比较本机版本；未安装或没有满足要求的版本时，调用封装的
`_install()` 函数安装**官方最新稳定版**，而不是安装最低版本号对应的旧包。
安装后再次验证；已有版本达到最低要求且支持 SDK 协议时直接复用。
测试中的未来版本号仅为示例，不代表发布计划。

## 语音方法

各方法保留 API 返回的 JSON；`transcribe(response_format="text")` 返回字符串。时间单位为秒。模型要求和参数约束见[音频 API](https://edgespeak.com/zh/docs/api-audio)、[对齐 API](https://edgespeak.com/zh/docs/api-align)和[文本 API](https://edgespeak.com/zh/docs/api-text)。

| 方法 | 参数与行为 |
| --- | --- |
| `transcribe(audio, ...)` | `model`、`language`、`diarize`、`response_format`、`prompt`、`timestamp_granularities`、`word_timestamp_enabled`、`candidates`、`semantic_sentence_enabled`、`min_chars`、`max_chars`、`start_margin`、`end_margin`、`stream` |
| `align(audio, ...)` | `text` 或 `text_file`、`text_format`、`model`、`language`、`search_effort`、`threshold`、`start` + `end`、`protected_terms`、`text_normalization`、`audio_track`、`audio_channel`、`semantic_sentence_enabled`、`min_chars`、`max_chars`、`start_margin`、`end_margin`、`progress` |
| `segment(text, ...)` | 纯文本或 `segments`，以及 `threshold`、`paragraph_threshold`、`min_chars`、`max_chars`、`start_margin`、`end_margin`、`options` |
| `diarize(audio, ...)` | 独立说话人分离，可用 `num_speakers` 指定 1–32 位说话人 |
| `speaker_embedding(audio, ...)` | 单个路径或路径列表，可指定 `model`；批量结果保持输入顺序 |
| `speaker_similarity(a, b, ...)` | 比较同一模型生成的两个声纹向量，可指定 `model` |

转录中 `diarize=True` 选择 `diarized_json`，不能同时选择其他响应格式。人数设置属于独立的 `diarize()`；转录和对齐 API 不接受 `num_speakers`。对齐 API 目前不执行说话人分离。

## 参考文件与对齐

```python
with EdgeSpeak() as client:
    aligned = client.align(
        "speech.wav", text_file="captions.ass", language="zh",
        search_effort="auto", semantic_sentence_enabled=True,
        min_chars=10, max_chars=40,
    )
    from_json = client.align(
        "speech.wav", text={"segments": [{"text": "音频中实际说出的原文。"}]}
    )
```

`text_file` 读取本地 UTF-8 文件，支持 BOM，上限为 64 MiB。支持 `.txt`、`.json`、`.srt`、`.ass` 和 `.ssa`，也可用 `text_format` 覆盖扩展名。JSON 使用包含 `segments[].text` 的字幕结构，或回退到顶层 `text`。直接传字幕内容时，使用 `text=contents, text_format="srt"`，格式也可为 `json`、`ass` 或 `ssa`。`text` 和 `text_file` 必须且只能提供一个。

SDK 上传文件内容，不发送本地 `text_path`。CLI 共用解析器提取原文，忽略字幕原有时间，以及 ASS 样式、注释和绘图；对齐根据音频重新计算时间。这需要配套的未发布 CLI/API `text_format` 支持。

连接已有网关时，网关必须在 `/v1/health.capabilities` 声明 `alignment_reference_formats`，SDK 才会发送 JSON/SRT/ASS/SSA；旧网关报 `unsupported_gateway_capability`，需要更新网关。`text_format` 不能与服务端路径 `text_path` 同传。

## 语义分句与分段

```python
with EdgeSpeak() as client:
    sentences = client.segment("这是第一句。这是第二句。", max_chars=40)
    paragraphs = client.segment("一段较长的原文。", paragraph_threshold=0.6)
    transcript = client.transcribe("meeting.wav", diarize=True)
    captions = client.segment(segments=transcript["segments"], min_chars=10, max_chars=40)
```

纯文本模式生成句子；带时间的 `segments` 模式通过 API 的重新分句行为保留时间和说话人信息。段落模式仅接受纯文本，不能同时设置时间片段、长度限制或边距。转录、对齐也可设置 `semantic_sentence_enabled=True` 直接分句；未传参数沿用运行时默认设置。

## 进度与流式结果

```python
with EdgeSpeak() as client:
    with client.align("speech.wav", text="音频中实际说出的原文。", progress=True) as events:
        for event in events:
            print(event)
```

对齐依次返回进度、阶段事件和最终对齐对象；进度达到 1 不等于收到最终结果。`transcribe(stream=True)` 返回 SSE 事件，目前需要连接桌面端网关，Headless CLI 不支持流式转录。流式转录要求 `response_format="json"`，不支持说话人分离或时间粒度参数；不兼容组合会由 API 拒绝。

提前停止读取时使用流的上下文管理器。关闭客户端也会关闭其流。连接结束却没有终止事件时，抛出错误码为 `incomplete_stream` 的 `EdgeSpeakError`。关闭流会释放连接和上传文件，但不保证已开始的推理被取消。

## 可运行示例

[Python SDK 示例](https://github.com/lattifai/EdgeSpeak/tree/main/sdk/python/examples)覆盖转录、对齐、语义分句与分段、带时间字幕、说话人分离、批量声纹和相似度。各文件用 `--help` 查看参数。传 `--base-url` 连接已有网关，否则示例自行启动并关闭 CLI 服务。

```bash
python sdk/python/examples/transcribe.py meeting.wav --diarize --semantic
python sdk/python/examples/align.py speech.wav --text-file captions.srt --progress
python sdk/python/examples/segment.py --text "这是第一句。这是第二句。" --max-chars 40
python sdk/python/examples/segment.py --segments-file transcript.json --max-chars 40
python sdk/python/examples/speakers.py meeting.wav alice.wav bob.wav --num-speakers 2
```

## 密钥有效期与账号额度

密钥可选择**永久有效**，仅表示密钥不设到期日；账号授权、订阅额度、在线验证和撤销仍然生效。临时授权凭据仍最多有效五分钟。

SDK 用 `exception.code` 保留网关原始错误码，用 `exception.reason` 区分 `api_key_expired`（密钥过期）、`api_key_revoked`（密钥已撤销）、`usage_exhausted`（本期额度耗尽）。服务器提供下次重置时间时，可读取经过验证的 `exception.resets_at`；额度响应的既有网关错误码仍是 `license_required`。异常不会原样输出任意服务器错误文本。

API Key 与桌面端共享账号订阅额度及其计费周期。创建或切换密钥不重置用量，进入下一个订阅周期才按账号套餐恢复额度。

通过 SSH 隧道连接 GPU 服务器见[远程 GPU 接入](examples/remote-gpu.md)。音频会上传到该服务器；关闭 SDK 不会停止远端服务。

## 参数补全与默认行为

SDK 导出 `TimestampGranularity`、`TranscriptionFormat`、`ReferenceFormat`、
`SearchEffort`、`AudioChannel` 类型，编辑器可以提示合法值。已知的错误参数组合
会在上传音频前抛出带说明的 `ValueError`。模型名称和语言支持仍由运行时决定。

```python
from edgespeak import EdgeSpeak, TimestampGranularity

granularities: list[TimestampGranularity] = ["word", "segment"]
with EdgeSpeak() as client:
    result = client.transcribe("meeting.wav", timestamp_granularities=granularities)
    print(result["text"])
```

| 参数 | 可选值与默认行为 |
| --- | --- |
| `timestamp_granularities` | `["word"]`、`["segment"]` 或两者；`None`/`[]` 表示不显式请求，不等于关闭时间戳 |
| `response_format` | `json`、`verbose_json`、`diarized_json`、`text`；默认 `verbose_json`，`diarize=True` 时为 `diarized_json`，`stream=True` 时为 `json` |
| `text_format` | `txt`、`json`、`srt`、`ass`、`ssa`；省略时推断扩展名或 JSON 映射，字符串交给运行时检测 |
| `search_effort` | `standard`（默认）、`extended`、`auto`；保留空字符串作为 standard 的兼容写法 |
| `audio_channel` / `audio_track` | 声道为 `"mix"`、从 0 开始的整数或 `"1"` 这样的数字字符串，音轨为从 0 开始的整数；`None` 使用运行时选择 |
| `candidates` | 2–8 个候选；`None`、0、1 表示关闭多候选 |
| `num_speakers` | 1–32；`None` 自动推断人数 |
| `start` / `end` | 秒，必须同时传入有限数值，满足 `0 <= start < end` |
| `min_chars` / `max_chars` | 字符数；`None` 沿用运行时设置 |
| `start_margin` / `end_margin` | 秒；`None` 沿用运行时设置 |

时间戳粒度要求 `verbose_json` 或 `diarized_json`。流式要求 `json`，不支持
同时传说话人标注或时间戳粒度。多候选要求 `verbose_json`，不能与 `word` 粒度
同时使用，也不能设置 `word_timestamp_enabled=True`。
`word_timestamp_enabled=False` 与 `word` 粒度冲突。
归一化和分句设置字典保留透传，由运行时验证字段与依赖模型的范围。

JSON 响应保留为字典，纯文本响应为 `str`，流式转录与对齐进度为可关闭的
`EventStream`。可用 `help(EdgeSpeak.transcribe)` 和 `help(EdgeSpeak.align)`
查看逐参数说明。本地参数错误为 `ValueError`，文件错误为 `OSError`，
启动错误为 `RuntimeStartError`，请求错误为 `EdgeSpeakError`，提供
`code`、`status_code`、`reason`、`resets_at` 字段。

`timestamp_granularities`、`protected_terms` 和 `segments` 支持列表、元组及
生成器等一次性迭代输入；校验前只读取一次，避免校验耗尽数据后发送空列表。
不能用字符串、字节串、字典代替外层迭代输入，不可迭代值也会抛出 `ValueError`。
`start`、`end`、`timeout`、`startup_timeout` 拒绝布尔值、非有限数和超出传输范围的数值。
分句边距、阈值等依赖运行时的数值设置仍交给网关验证。
生命周期检查优先：已关闭或 fork 后继承的客户端在参数校验前抛出 `RuntimeError`。

返回类型重载让编辑器将默认调用识别为 JSON 字典，将 `response_format="text"`
识别为 `str`，将 `stream=True` 或 `progress=True` 识别为 `EventStream`。
如果参数是运行时才确定的布尔值或格式，返回类型仍为联合类型。

```sh
python -m pip install -e './sdk/python[dev]'
python -m mypy --strict --follow-imports=silent --warn-unused-ignores sdk/python/tests/typing/public_api.py
python -m mypy --follow-imports=silent sdk/python/src/edgespeak/_client.py sdk/python/src/edgespeak/_types.py sdk/python/src/edgespeak/_streaming.py
```

CI 还会在 Python 3.10～3.15 上针对构建后的 wheel 检查调用方类型契约。
该检查覆盖公开类型接口，不代表全部进程管理和安装内部代码都已通过严格类型检查。

`word_timestamp_enabled=True` 要求 `verbose_json` 或 `diarized_json`，且不能与
`candidates>=2` 同用。非法媒体路径及声纹向量输入也会在本地报错。
用户自己的迭代器若抛出异常，会保留原异常与堆栈，不改写为 SDK 参数错误。
为兼容数字字符串声道，`AudioChannel` 在类型层接受字符串，具体内容由运行时
校验。开发用 mypy 固定为已验证版本，保证负向类型测试的错误码可复现。

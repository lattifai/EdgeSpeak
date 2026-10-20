# EdgeSpeak Python SDK

通过本机 EdgeSpeak CLI 完成转录、强制对齐、语义分句、说话人分离和声纹处理。
音频由所连接的运行时处理，SDK 不内置引擎或模型。

[English](https://github.com/lattifai/EdgeSpeak/blob/main/sdk/python/README.md) · [完整文档](https://edgespeak.com/zh/docs/python-sdk) · [示例](https://github.com/lattifai/EdgeSpeak/tree/main/sdk/python/examples)

## 安装

需要 Python 3.10+。所有支持的 Python 版本和平台共用一个纯 Python wheel。
从 PyPI 安装：

```bash
python -m pip install edgespeak
```

SDK 自动查找本机 CLI；未安装或版本不满足要求时，自动安装官方最新稳定版。
自动安装支持 macOS Apple Silicon、Linux x86_64 和 Windows x64，需要联网。
模型按需加载，首次调用可能下载模型。

## 创建和配置 API KEY

1. 登录 [EdgeSpeak → API KEY](https://edgespeak.com/zh/account/api-keys)。
2. 创建 API KEY，设置有效期（可选永久有效）及用量限制，并复制创建时显示的完整密钥。
3. 在运行 Python 的环境中设置 `EDGESPEAK_API_KEY`：

```bash
export EDGESPEAK_API_KEY="你的 API KEY"
```

Windows PowerShell 使用 `$env:EDGESPEAK_API_KEY="你的 API KEY"`。
`EdgeSpeak()` 会自动读取该变量，也可显式传入 `EdgeSpeak(api_key=...)`。
API KEY 用于程序访问，与产品激活密钥不同；不要将它写入代码仓库。
已激活的本机设备也可沿用现有授权。

API KEY 需要在线授权，与桌面端共享账号订阅额度及计费周期；新建密钥不会重置额度。
永久有效仅表示没有到期日，账号授权、用量限制和撤销仍然生效。

## 快速开始

```python
from edgespeak import EdgeSpeak

with EdgeSpeak() as client:
    transcript = client.transcribe("meeting.wav", language="zh", diarize=True)
    print(transcript["text"])
    aligned = client.align("speech.wav", text="音频中实际说出的原文。")
    speakers = client.diarize("meeting.wav", num_speakers=2)
```

建议复用客户端，使用 `with` 或 `close()` 释放 SDK 启动的服务。
结果通常为字典，时间戳单位为秒；`response_format="text"` 返回字符串。
对齐需要与音频对应的原语言文本，也支持 `text_file="captions.srt"`，可读取 TXT、JSON、SRT、ASS、SSA。
字幕原有时间会根据音频重新对齐。

| 方法 | 用途 |
| --- | --- |
| `transcribe(audio, ...)` | 音频转录，可附带说话人标注、词级时间戳 |
| `align(audio, text=... / text_file=..., ...)` | 将原文或字幕与音频对齐 |
| `segment(text, ...)` / `segment(segments=..., ...)` | 纯文本分句或带时间片段重新分句 |
| `diarize(audio, ...)` | 独立说话人分离 |
| `speaker_embedding(audio, ...)` | 提取单个或批量声纹 |
| `speaker_similarity(a, b, ...)` | 比较同一模型产生的两个声纹向量 |

显式选择说话人模型（SDK 0.6.9）：`client.diarize(audio, model="EdgeSpeak/Lattice-2")` 为本次请求选择 Lattice-2，`EdgeSpeak/Lattice-1` 选择旧模型。不传 `model` 时保留运行时偏好。网关须在 `/health` 声明 `diarization_model_selection`；旧网关会明确报错，不会静默忽略选择。此参数用于独立说话人分离，不是转录模型参数。

完整转录、词级对齐和说话人归属（SDK 0.6.9）：
```python
result = client.transcribe(audio, model="EdgeSpeak/Lattice-2-Flash", diarize=True,
    diarization_model="EdgeSpeak/Lattice-2", word_timestamp_enabled=True,
    timestamp_granularities=["word", "segment"], semantic_sentence_enabled=True)
```
`diarization_model` 要求 `diarized_json` 输出（`diarize=True` 自动选择）以及网关的 `transcription_diarization_model_selection` 能力，不改变转录模型和保存的偏好。同步、异步客户端均支持此参数。



参数有类型提示，例如 `timestamp_granularities=["word", "segment"]`、
`search_effort="auto"`。可用 `help(EdgeSpeak.transcribe)`、`help(EdgeSpeak.align)` 查看参数说明。
对齐不执行说话人分离；指定人数使用独立的 `diarize()`。

## 内存音频

`transcribe`、`align`、`diarize`、`diff_align`、`speaker_embedding`、`upsample` 都支持文件路径、完整编码媒体的 `bytes`、NumPy 数组和 `AudioSamples`。
使用数组先安装 `python -m pip install "edgespeak[numpy]"`。

```python
from pathlib import Path
import numpy as np

with EdgeSpeak() as client:
    client.transcribe(Path("speech.mp3").read_bytes())  # 完整编码文件
    audio = np.zeros((16000, 2), dtype=np.float32)      # (采样帧数, 声道数)
    client.transcribe(audio, sample_rate=16000)
    client.align(audio, sample_rate=16000, text="你好", audio_channel=1)
```

数组必须传真实输入采样率 `sample_rate`（Hz，1..384000），这个参数不执行重采样。
`(frames,)` 表示单声道，`(frames, channels)` 支持 1～8 声道并保留顺序，
声道在前的数组需自行转置。支持 int16，或值有限且在 [-1, 1] 内的 float32/float64。
浮点数按 `rint(x * 32767)` 量化为 PCM16 WAV；int16 保留原始采样值。
转换不会自动混音或推断扬声器位置。转录沿用网关默认混音行为；
对齐可用 `audio_channel` 选择从 0 开始的声道或 `"mix"`，数组的 `audio_track` 只能为 None 或 0。

编码 `bytes` 从媒体内容读取采样率和声道；对 bytes、路径传 `sample_rate` 会报错。
不接受裸 PCM bytes、bytearray、memoryview、文件对象或 URL；裸采样数据先转为 ndarray。
单条内存输入默认限制为编码后 256 MiB，可配置；服务端上传大小及音频时长限制仍然生效。
调用进行期间不要修改数组。
NumPy 子类（例如带掩码的数组）需要显式转换为普通 ndarray。


`AudioSamples(array, sample_rate)` 可为每条数组携带输入采样率，适合混合批量：

```python
from edgespeak import AudioSamples

client.speaker_embedding([AudioSamples(a, 16000), AudioSamples(b, 24000), encoded_wav])
client.diarize(a, sample_rate=16000)
client.upsample(a, input_sample_rate=16000, sample_rate=24000)
```

`upsample` 的 `sample_rate` 始终是**输出采样率**；裸数组用 `input_sample_rate` 传输入率。
其他音频方法的 `sample_rate` 为输入率。使用 `AudioSamples` 时不要重复传输入率。
声纹批量中，顶层输入率只用于裸数组，包装数组各用自己的率，文件和 bytes 从文件头读取。
返回 `data` 的顺序和 `index` 对应输入；SDK 不拆分请求或自动重试，计费规则不变。

### 内存限制

同步和异步客户端均可配置：

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `max_memory_audio_bytes` | 256 MiB | 每条 bytes/数组编码后的大小上限 |
| `max_in_flight_audio_bytes` | 512 MiB | 每客户端正在准备/上传的内存来源输入总预算，整批求和 |
| `audio_spool_threshold_bytes` | `None` | 默认全内存；显式设置后，超过阈值的数组编码写私有临时文件 |

前两项设为 `None` 可关闭相应 SDK 限制；正整数单位均为字节，拒绝 bool/零/负数。
超出总预算的单项或整批立即报错，预算暂时不足则等待；同步多线程调用也可能等待。
请求体上传完毕即关闭输入并归还预算，不随响应流保留。关闭客户端会唤醒预算等待者。
路径输入不计这两项预算；显式落盘的数组仍计入。默认不会强制落盘，异常和取消会清理临时文件。
这不是进程 RSS 上限，不包含调用方原数组、排队输入、响应数据或模型内存；数据生产者仍应使用有界队列。
这些配置不会绕过网关限制，`upsample` 仍独立限制 32 MiB、120 秒和 1～8 声道。

## 异步调用

完整可运行示例：[async_transcribe.py](examples/async_transcribe.py)，包含并发转录、流式对齐与自动释放资源。

```python
from edgespeak import AsyncEdgeSpeak

async with AsyncEdgeSpeak(max_concurrency=4) as client:
    result = await client.transcribe("speech.wav")
    async with client.align("speech.wav", text="音频原文。", progress=True) as events:
        async for event in events:
            print(event)
```

方法名、参数和结果结构与同步客户端一致；用 `await` 获取结果，流式调用推荐直接 `async with`。
也可 `stream = await client.align(..., progress=True)`，但必须用 `async with stream` 或 `await stream.aclose()`。
同一个流请求只能打开一次。提前退出时关闭流；持有的响应流占 HTTP 并发槽，嵌套调用须留足 `max_concurrency`。
等待输入预算的任务不占 HTTP 槽位，上传完成就归还预算。

构造时不安装或启动 CLI，首次 `await`/进入上下文才启动自有服务；使用 `async with` 或 `await client.aclose()` 释放资源。
连接已有网关的鉴权、计费和关闭规则与同步类相同：仍用 `gateway_key`，不读取账号 API KEY 环境变量，关闭不停止网关。
`transport` 使用 HTTPX 异步传输，`event_hooks` 使用异步函数，SDK 拥有并关闭传入的 transport。
网络使用原生异步 I/O；本地编码、文件读写、CLI 安装启动在有界工作线程执行。
取消会等待正在运行的本地工作完成清理，因此不保证瞬时返回，也不保证远端推理取消或退还用量。
客户端绑定首次使用的事件循环和进程，跨 loop/fork 使用会报错；每个进程自行创建客户端。


## 进度

```python
with EdgeSpeak() as client:
    with client.align("speech.wav", text="音频原文。", progress=True) as events:
        for event in events:
            print(event)
```

进度事件后还会返回最终结果；提前退出时应关闭流。关闭流不保证取消已开始的推理。
`transcribe(stream=True)` 目前需要连接桌面端网关，不支持说话人标注或时间粒度参数。

## 选择计算设备

SDK 自己启动 CLI 服务时，可以指定设备：

```python
with EdgeSpeak(device="cpu") as client:
    transcript = client.transcribe("meeting.wav")
# Linux/Windows：device="cuda"，或用 "cuda:1" 指定显卡索引。
# macOS：device="metal"，也支持别名 "mps"。
```

设备名称不区分大小写。不传 `device` 或使用 `"auto"` 时，沿用 CLI 的默认及环境配置。
CUDA 需要兼容的 CLI、运行时和显卡；Metal 仅支持 macOS。硬件可用性和各模型的后端支持由运行时检查。
CUDA 索引遵循 CUDA 设备枚举顺序，不一定与系统监视器编号一致。
这是服务级设备偏好，各能力仍受自身支持的后端限制；仅支持 CPU 的处理仍在 CPU 上执行。

**连接已有网关时不能设置 `device`，包括 `"auto"`。** 与 `base_url` 同时传入会在连接前抛出
`ValueError`。已有网关的设备由网关端配置，SDK 无法覆盖。

## 连接已经运行的网关

已有 EdgeSpeak 桌面端或 CLI 网关时，指定 `base_url`，SDK 就不会另行启动 CLI：

```python
import os
from edgespeak import EdgeSpeak

with EdgeSpeak(
    base_url="http://127.0.0.1:1118/v1",
    gateway_key=os.environ["EDGESPEAK_GATEWAY_KEY"],
) as client:
    result = client.transcribe("meeting.wav")
```

这里的 `EDGESPEAK_GATEWAY_KEY` 只是示例中存放网关令牌的变量，SDK 不会自动读取它。
向网关管理员获取令牌；如果本机网关未启用令牌认证，可省略 `gateway_key`。

- **客户端不需要账号 API KEY。** 指定 `base_url` 后不要传 `api_key`；SDK 会拒绝这两个参数同时使用。
  此模式忽略客户端的 `EDGESPEAK_API_KEY`，不会发送、修改它，也不会改变已有网关的授权。
- **网关端仍需自己的有效授权。** 请求使用网关运行时配置的账号或设备授权；
  需要计量的用量按该授权对应的套餐和规则结算。网关令牌只控制访问，不能切换计费账号。
  SDK 不额外计费，连接网关也不会绕过额度限制；其他人提供的网关，其使用费用需向提供方确认。
- **远程网关连接必须使用 HTTPS。** 本机回环地址（`localhost`、`127.0.0.1`、`::1`）可用 HTTP；
  局域网 IP 或其他非回环网关地址也要求 HTTPS。连接远程网关时，音频会上传至该网关服务器。
- 关闭客户端不会关闭已有网关。SDK 不读取环境代理配置；多进程应各自创建客户端。

注意：直接启动 CLI 网关时，CLI 的 `EDGESPEAK_API_KEY` 表示**网关令牌**；
SDK 自动启动模式中的同名变量表示**账号 API KEY**。不要混用两种凭据。
修改客户端环境变量不会重新配置已经运行的网关；但之后从该环境启动 CLI 时会继承变量。

## 错误处理

`EdgeSpeakError` 提供 `code`、`status_code`、`reason` 和 `resets_at`。
通过 `reason` 区分 `api_key_expired`（已过期）、`api_key_revoked`（已撤销）、
`usage_exhausted`（本期额度耗尽）；更换密钥不会恢复账号额度。
参数错误为 `ValueError`，文件错误为 `OSError`，CLI 启动错误为 `RuntimeStartError`。

`timeout` 默认为 600 秒，针对 HTTP I/O 阶段，不是任务总时限；
`startup_timeout` 默认为 30 秒，不包含 CLI 安装时间。

### 音频上采样

```python
from pathlib import Path

with EdgeSpeak() as client:
    Path("output.wav").write_bytes(client.upsample("input.wav", sample_rate=24_000))
```

`sample_rate` 默认 48,000 Hz，支持不超过 48,000 Hz 的正整数目标采样率。
目标高于源采样率时，使用 AudioVAE 超分至 48 kHz，再按需带限降采样；目标低于源采样率时直接降采样，相同时保留原 WAV 字节。独立调用不计账号用量。
各声道独立处理，保留声道数、顺序和有效 WAV 布局。
输入支持下方所列格式，限制 1～8 声道、32 MiB、120 秒。首次升采样可能下载 AudioVAE 模型。
返回 WAV 字节，由调用方选择是否保存及保存位置。
需要 CLI 0.6.8 或更新版本的 `POST /v1/audio/upsamplings`。

CLI 对应命令：`edgespeak-cli upsample input.wav --output output.wav --sample-rate 24000`。

## 双输入对齐（CLI 0.6.8+）

SDK 提供 `diff_align(audio, reference_segments=[{"text": "官方稿"}], transcript_segments=[{"text": "ASR 字幕"}], offset=0.0)`。两个数组都接收非空 `text` 和可选 `speaker`，由原生声学 diff 决定输出。网关 `/v1/health.capabilities` 必须包含 `diff_alignment`；旧版已发布网关不支持，也不会退回 `align()`。

每次最多 300 秒音频（含上下文 padding），超限返回 413。长录音由消费端保留两份文本后分窗。结果时间已含 `offset`；`original_index` 是本次 reference 数组下标或 -1。说话人标签来自输入文字，不是声纹身份结论。本接口不支持文本归一化、扩展搜索或流式进度。

### 音频格式与编码参数（CLI 0.6.8+）

`upsample` 支持 WAV（PCM16/24/32、Float32）、FLAC、MP3、M4A/AAC、ADTS AAC、OGG/Vorbis、OGG/Opus 文件输入，按实际内容检测。默认仍返回 WAV 字节；可用 `response_format` 选择 `wav`、`flac`、`mp3`、`m4a`、`aac`、`ogg`（Vorbis）、`opus`（Ogg/Opus）。

```python
Path("output.mp3").write_bytes(client.upsample("input.m4a",
    sample_rate=48_000, response_format="mp3", bitrate=192_000))
Path("output.wav").write_bytes(client.upsample("input.flac",
    sample_rate=24_000, pcm_format="s24"))
```

`bitrate` 是整条音频的目标 bit/s，仅用于有损格式；WAV/FLAC 不接受此参数。`pcm_format` 支持 WAV 的 `s16/s24/s32/f32`、FLAC 的 `s16/s24`，有损格式不接受。Opus 输出固定 48000 Hz，MP3 只支持单/双声道；不兼容的采样率、声道布局或编码参数明确拒绝。编码能力由网关机器提供，缺少所需编码器时会报错；SDK 不安装额外音频库或自动混音。

仍限制 32 MiB、120 秒及 1～8 声道；保留声道的扬声器语义与同步，跨容器可能按标准重排存储顺序。有损编码可能有 delay/padding；要求精确样本时间轴优先 WAV/FLAC。结果为所选格式的 bytes，SDK 不自动保存，也不扣账号用量。

## 文本、模型目录和用量

以下新增方法需要匹配的 SDK 构建和网关能力。新方法按 HTTP 路径命名，已有方法名称保持不变。

```python
from edgespeak import slice_utf8

with EdgeSpeak() as client:
    result = client.text_normalizations("收费$25。", language="zh", top_k=1)
    print(result["alternatives"][0]["text"])  # 转换结果；顶层 text 是原文
    for span in result["alternatives"][0]["spans"]:
        print(slice_utf8(result["text"], span["start_byte"], span["end_byte"]))
    sentences = client.segment("第一句话。第二句话。")
    catalog = client.models()
    totals = client.usage(refresh=True)
```

`mode="itn"` 用于口语形式转书面形式。规范化和分句按文本用量计量，不消耗音频时长额度。
偏移是 UTF-8 字节位置，不能直接用于 Python 字符串切片；`slice_utf8` 会检查字节边界。
`usage()` 保留不限量额度中的 `null`，不会把它转换为零。

`health()`、`models()`、`models_running()`、`models_downloads()` 返回网关 JSON（`models()` 另外添加能力分组 `groups`），不启动推理。`models_load(model)`、
`models_unload(model)`、`models_download(model)`、`models_download_cancel(model)` 是显式操作；
下载返回任务状态，不等待完成，可通过 `models_downloads()` 轮询。

## 按能力查看模型

现有 `models()` 在 `Models` 返回值中增加 `groups` 字段（SDK 0.6.9），按能力整理网关实时目录，原有 `object`、`data` 保持不变；`AsyncEdgeSpeak` 同样支持，调用时使用 `await`。

```python
with EdgeSpeak() as client:
    catalog = client.models()
    groups = catalog["groups"]
    for capability, group in groups.items():
        print(capability, group["description"])
        for model in group["models"]:
            print(model["id"], model.get("installed"), model.get("default_for", []))
```

按服务实际声明分为转录、强制对齐、说话人分离、声纹提取/相似度、语音合成、文本生成/分词、分句、文本规范化和音频升采样。每组提供 `title`、`description`、`supported_endpoints`、`sdk_methods` 与 `models`。同一模型支持多种能力时会出现在多个组。模型条目保留服务返回的完整元数据和标准公开 ID，SDK 不维护另一份模型清单；未知或未声明的能力保留在 `other` 中。

- `installed=True`：服务报告已安装，不代表已加载，也不保证当前账号对所有请求都有权限。
- `installed=False`：服务报告未安装；没有此字段代表状态未知，不能当成未安装。
- `default_for`、`supported_endpoints` 属于各个模型，不代表组内所有模型都支持。转录使用返回的标准 ID，例如 `transcribe(model="EdgeSpeak/Lattice-2-Flash")`；说话人模型在配套网关上使用 `diarize(model=...)` 或 `transcribe(diarization_model=...)` 选择。
- 该方法仅调用 `GET /v1/models`，不加载、下载模型；原始网关模型记录保留在 `data` 中，分组与说明是 SDK 添加的视图。托管客户端仍可能按正常流程安装/启动 CLI。已加载情况查看 `models_running()`。服务可能声明语音合成 HTTP 能力，但 SDK 尚无便捷方法，此时 `sdk_methods` 为空。

可运行示例：`python examples/models.py --base-url http://127.0.0.1:1118/v1` 和 `python examples/async_models.py --base-url http://127.0.0.1:1118/v1`；加 `--json` 可打印完整元数据。

## 文本生成

```python
with EdgeSpeak() as client:
    with client.responses("解释这句话。", model="你的文本模型", stream=True) as events:
        for event in events:
            print(event)
```

`chat_completions(messages, model=...)`、`responses(input, model=...)`、
`messages(messages, model=..., max_tokens=...)` 分别沿用对应 API 的内容结构。
默认返回 JSON，`stream=True` 返回 `EventStream`。模型支持时可在结构化内容中输入图像，
输出仍是文本，不提供图像生成。`options` 可发送协议扩展字段，但不能覆盖显式参数。
`messages()` 通过 `anthropic_version`（默认 `2023-06-01`）和 `anthropic_beta` 设置协议头。
`tokenize(content, model=...)` 随提供方返回 JSON 对象或原始整数 token 数组；其他提供方格式可省略 content，
通过 options 提交其字段。

各流按各自协议结束：Chat 的 `[DONE]`、Responses 的 `response.completed`、
Messages 的 `message_stop`。
失败、不完整的 Responses、缺少终止事件的断流均抛出 `EdgeSpeakError`。
需要部分结果时请保留已经产出的事件；非流式不完整 Responses 会抛错而不返回部分结果。
提前退出请使用 `with` 或 `close()`；关闭流不保证取消已开始的推理，也不会撤销已消耗用量。

本机生成按网关账号额度计量；转发到已配置的外部提供方时按提供方规则计费，SDK 不重复扣量。
模型/下载状态/健康查询及 tokenize 不扣 EdgeSpeak 推理用量，外部提供方可能自行收费。Realtime 和 MCP 仍是独立网关协议，
请使用对应协议的客户端，不通过同步 SDK 方法模拟。

## 类型与 HTTP 集成

`Transcription`、`Alignment`、`Segmentation`、`Diarization`、`Embeddings`、
`Similarity`、`Usage`、`Models`、`GatewayEvent` 提供字段提示。返回值仍是普通字典，
保留网关扩展字段；可选字段取决于格式和运行时，时间戳单位为秒。
基础安装不需要 NumPy 就能进行类型检查；数组输入仍需 `edgespeak[numpy]`。

`EdgeSpeak(transport=..., limits=..., event_hooks=...)` 支持同步 HTTPX 传输、连接池限制和
请求／响应钩子。SDK 在 `close()` 时关闭传入的 transport，请勿与其他客户端共享。
钩子也适用于流式请求；不要记录凭据，也不要在响应钩子中读取流式正文。
网关返回有效的 `x-request-id`／`request-id` 响应头时，HTTP 错误通过 `error.request_id` 提供该标识。
请求不会自动重试，避免重复推理或扣量。

分句阈值须为 `[0, 1]` 内的有限数，字符数须为 `0..65535` 的整数，边距须为非负有限秒数，
布尔参数须使用 `True`／`False`；非法值在上传前报错。`Device` 和 `AudioChannel` 提供补全提示，
CUDA 显卡索引和数字字符串声道由运行时校验。

### 统一并发上限

同步与异步客户端均支持 `max_concurrency: int | None = None`，显式值为 1～64。自有服务同时限制客户端请求并给 CLI 下发 `serve --max-concurrency`；连接已有网关只限制当前客户端，不修改网关配置。不支持此参数的 CLI 会明确报能力错误，需要更新到支持该参数的 CLI。

`None` 保留 serve 默认策略：异步客户端默认 4，同步保留 HTTPX 连接池行为。原有路由、模型和设备容量可能更低，上限不承诺实得推理路数，也不改变音频分块并行或 realtime。响应流至结束/关闭才归还客户端槽；GET 查询与模型生命周期控制豁免。服务端在上传完成后申请执行许可，执行/流结束或取消时释放。鉴权与计费规则不变。

## 可运行示例

SDK 要求 CLI **0.6.8 或更新版本**，且支持 SDK 协议。自动启动模式下，CLI 缺失或不兼容时会自动安装最新稳定版；连接已有网关不会安装或升级网关端的 CLI。

先用 `python -m pip install edgespeak` 安装，再下载以下脚本或从仓库运行。
每个脚本都独立展示客户端创建、SDK 调用、输出和资源释放，无需辅助文件。
运行 `python sdk/python/examples/<脚本名>.py --help` 查看参数。

| 功能 | 同步示例 | 异步示例 |
| --- | --- | --- |
| 转录 | [transcribe.py](examples/transcribe.py) | [async_transcribe.py](examples/async_transcribe.py) |
| 对齐及进度流 | [align.py](examples/align.py) | [async_align.py](examples/async_align.py) |
| 文本及带时间戳分句 | [segment.py](examples/segment.py) | [async_segment.py](examples/async_segment.py) |
| 说话人分离、声纹及相似度 | [speakers.py](examples/speakers.py) | [async_speakers.py](examples/async_speakers.py) |

例如：`python sdk/python/examples/async_align.py speech.wav --text "Hello." --progress`。
不传 `--base-url` 时，设置账号 `EDGESPEAK_API_KEY`，SDK 会启动并释放自己的 CLI。
连接已有网关时，增加 `--base-url http://127.0.0.1:1118/v1`，按需设置网关令牌
`EDGESPEAK_GATEWAY_KEY`。此模式忽略客户端的账号 API KEY，关闭客户端不会停止已有网关。
远程网关地址要求 HTTPS，音频会上传至该网关。

# EdgeSpeak Python SDK

通过本机 EdgeSpeak CLI 完成转录、强制对齐、语义分句、说话人分离和声纹处理。
音频由所连接的运行时处理，SDK 不内置引擎或模型。

[English](https://github.com/lattifai/EdgeSpeak/blob/main/sdk/python/README.md) · [完整文档](https://edgespeak.com/zh/docs/python-sdk) · [示例](https://github.com/lattifai/EdgeSpeak/tree/main/sdk/python/examples)

## 安装

需要 Python 3.10+。所有支持的 Python 版本和平台共用一个纯 Python wheel。
正式发布到 PyPI 后，使用：

```bash
python -m pip install edgespeak
```

首次 PyPI 发布尚未完成；当前可在仓库根目录运行 `python -m pip install ./sdk/python`。
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

参数有类型提示，例如 `timestamp_granularities=["word", "segment"]`、
`search_effort="auto"`。可用 `help(EdgeSpeak.transcribe)`、`help(EdgeSpeak.align)` 查看参数说明。
对齐不执行说话人分离；指定人数使用独立的 `diarize()`。

## 进度与现有网关

```python
with EdgeSpeak() as client:
    with client.align("speech.wav", text="音频原文。", progress=True) as events:
        for event in events:
            print(event)
```

进度事件后还会返回最终结果；提前退出时应关闭流。关闭流不保证取消已开始的推理。
`transcribe(stream=True)` 目前需要连接桌面端网关，不支持说话人标注或时间粒度参数。

已有网关使用 `EdgeSpeak(base_url="http://127.0.0.1:1118/v1", gateway_key=...)`。
`gateway_key` 是网关令牌，不是账号 API KEY；关闭客户端不会关闭已有网关。
远程地址要求 HTTPS，音频会上传至该服务器；SDK 不读取环境代理配置。
多进程应各自创建客户端，不复用 fork 继承的客户端。

## 错误处理

`EdgeSpeakError` 提供 `code`、`status_code`、`reason` 和 `resets_at`。
通过 `reason` 区分 `api_key_expired`（已过期）、`api_key_revoked`（已撤销）、
`usage_exhausted`（本期额度耗尽）；更换密钥不会恢复账号额度。
参数错误为 `ValueError`，文件错误为 `OSError`，CLI 启动错误为 `RuntimeStartError`。

`timeout` 默认为 600 秒，针对 HTTP I/O 阶段，不是任务总时限；
`startup_timeout` 默认为 30 秒，不包含 CLI 安装时间。

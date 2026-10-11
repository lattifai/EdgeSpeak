# EdgeSpeak Python SDK

当前为 **0.1.0a1 开发候选**，尚未发布到 PyPI。需要 Python 3.10+，以及支持
`edgespeak-cli serve --sdk` 的 CLI 构建；旧版已发布 CLI 尚不支持这个握手。

按[官网 CLI 指南](https://edgespeak.com/zh/docs/cli)安装 CLI，并先执行
`edgespeak-cli login` 激活设备。Python 包不包含 CLI、引擎或模型。

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
SDK 自己启动服务时，可用 `EdgeSpeak(api_key=os.environ["EDGESPEAK_ACCESS_TOKEN"])`。
CLI 只通过环境变量接收账号密钥，不放入命令行参数。密钥和会话凭据仅驻留进程内存，
不覆盖桌面账号；用量账本仍共享持久化。CLI 也支持继承 `EDGESPEAK_ACCESS_TOKEN`。
账号密钥不能作为 `gateway_key`，也不能用于显式 `base_url` 的附加模式。
此功能依赖配套的未发布后端与 CLI；生产部署及完整账号鉴权联调尚未完成。

账号密钥要求在线授权，不能开启离线模式。撤销后服务端拒绝新请求，已签发凭据
最多有效五分钟；撤销不会中断已经开始的推理任务。

远程地址必须 HTTPS；不跟随重定向，也不读取环境代理或
环境 CA 配置。fork 子进程不可复用父客户端；多进程优先使用 spawn。

`timeout` 默认 600 秒，按 HTTP I/O 阶段计时，不是任务总耗时上限；超时不保证推理停止。
`startup_timeout` 默认 30 秒；CLI 不在 PATH 时传 `cli_path`。

开发安装、完整接口示例和测试命令见 [English README](README.md)。当前测试包括 HTTP
替身与真实 macOS CLI 生命周期；真实模型与 Windows 平台仍需单独验收。

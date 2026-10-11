# EdgeSpeak Python SDK

当前为 **0.1.0a1 开发候选**，尚未发布到 PyPI。需要 Python 3.10+，以及支持
`edgespeak-cli serve --sdk` 的 CLI 构建；旧版已发布 CLI 尚不支持这个握手。

SDK 自动从 PATH 和标准安装位置发现 CLI，要求 **CLI ≥ 0.6.3 且支持
`edgespeak-sdk-v1` 协议**；最低版本可通过 `edgespeak.MIN_CLI_VERSION` 查看。
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
SDK 自己启动服务时，可用 `EdgeSpeak(api_key=os.environ["EDGESPEAK_ACCESS_TOKEN"])`。
CLI 只通过环境变量接收账号密钥，不放入命令行参数。密钥和会话凭据仅驻留进程内存，
不覆盖桌面账号；用量账本仍共享持久化。CLI 也支持继承 `EDGESPEAK_ACCESS_TOKEN`。
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

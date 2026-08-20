# 公开发布清单

[English](RELEASING.md) · **简体中文**

本清单只覆盖向 `lattifai/EdgeSpeak` 发布公开版本的流程。构建、签名、公证和产品级验证
应先在私有开发仓中完成，再进入以下步骤。

## 发布顺序

1. 完成上游构建和发布验证。
2. 首先在本仓库发布 GitHub Release。
3. 再把同一版本发布或推广到 App 自动更新、官网下载和 CLI 安装脚本。
4. 分别验证每个公开渠道。GitHub 上传成功，并不能证明自动更新、官网或安装脚本已经
   提供新版本。

## 准备 GitHub Release

- 使用语义化版本标签：`vMAJOR.MINOR.PATCH`。
- 标题使用 `EdgeSpeak MAJOR.MINOR.PATCH`。
- 先创建草稿；任何必需软件包缺失时都不要正式发布。
- 发布说明面向用户描述可感知的结果，不写内部实现细节。
- 正文先写英文，再增加 `## 简体中文` 章节。
- 只有不面向稳定渠道的版本才标记为预发布版。

## 必需附件

首个 macOS 与 Windows GitHub 版本应同时包含：

| 附件 | 是否必需 |
| --- | --- |
| `EdgeSpeak_<version>_aarch64.dmg` | 是 |
| `EdgeSpeak_<version>_aarch64.dmg.sha256` | 是 |
| `edgespeak-cli-standalone-macos-arm64.tar.gz` | 是 |
| `edgespeak-cli-standalone-macos-arm64.tar.gz.sha256` | 是 |
| `EdgeSpeak_<version>_windows-preview_cpu-cuda-vulkan_x64_setup.exe` | 是 |
| `EdgeSpeak_<version>_windows-preview_cpu-cuda-vulkan_x64_setup.exe.sha256` | 是 |
| `edgespeak-cli-mcp-windows-x86_64.zip` | 是 |
| `edgespeak-cli-mcp-windows-x86_64.zip.sha256` | 是 |
| `edgespeak-cli-mcp-windows-x86_64-cuda-runtime.zip` | 是 |
| `edgespeak-cli-mcp-windows-x86_64-cuda-runtime.zip.sha256` | 是 |

Ubuntu 运行时就绪后，再添加对应的 x86_64 压缩包和 `.sha256` 文件。每个 CLI 附件名都
应保留操作系统和架构。不要上传构建中间目录、调试符号、凭据、日志或私有模型来源。

## 正式发布前验证

- 确认标签、DMG 内的 App 和 `edgespeak-cli` 使用的是同一个版本。
- 对实际上传的每个文件重新验证校验值。
- 验证 macOS App 的签名、公证、安装和首次启动。
- 确认 Windows 版本被明确标记为采用手动更新的未签名 Preview，并披露 Windows 10/11
  的实际验证边界。
- 把 CLI 压缩包解压到干净的临时目录，从该副本运行 `edgespeak-cli --version` 和
  `edgespeak-cli status`。
- 使用发布授权或测试权益，至少运行一个有代表性的端侧命令。
- 从草稿或已发布版本重新下载每个附件，确认与本地已验证产物逐字节一致。
- 确认中英文发布说明描述了同一组用户可见变化。

## 正式发布后

- 同步更新两份 README 中的发布状态和平台表格。
- 确认所有链接的 Skill 已经公开，再移除对应 README 表格中的「即将提供」标记。
- 把同一版本发布或推广到剩余分发渠道。
- 分别验证官网下载、App 自动更新、`install.sh`、`install.ps1` 及其面向用户展示的版本。
- 从公开更新记录链接到对应的 GitHub Release。
- 除非存在安全或法律原因，否则保留旧的稳定版本供用户下载。

## 新增文档语言

英文保持默认语言。新增翻译时，以 `README.<locale>.md` 命名，在每份 README 顶部的
语言切换栏中加入链接；发布说明保持相同顺序：先英文，再写翻译章节。

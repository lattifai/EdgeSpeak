# 公开发布清单

[English](RELEASING.md) · **简体中文**

本清单只覆盖向 `lattifai/EdgeSpeak` 发布公开版本的流程。构建、签名、公证和产品级验证
应先在私有开发仓中完成，再进入以下步骤。

## 发布顺序

1. 完成上游构建和发布验证。
2. 创建 GitHub Release 草稿，上传必需的桌面端附件并核对上传字节，但暂不公开草稿。
3. 把对应的已验证产物发布或提升到 App 自动更新、官网下载和 CLI 安装脚本。
4. 分别验证每个公开渠道。GitHub 上传成功，并不能证明自动更新、官网或安装脚本已经
   提供新版本。
5. 只有全部必需公网渠道都验证通过后，才把 GitHub Release 从草稿正式公开。

## 准备 GitHub Release

- 使用语义化版本标签：`vMAJOR.MINOR.PATCH`。
- 标题使用 `EdgeSpeak MAJOR.MINOR.PATCH`。
- 先创建草稿；任何必需软件包缺失时都不要正式发布。
- 发布说明面向用户描述可感知的结果，不写内部实现细节。
- 正文先写英文，再增加 `## 简体中文` 章节。
- 只有不面向稳定渠道的版本才标记为预发布版。

## 必需附件

每个 GitHub Release 应同时包含：

| 附件 | 是否必需 |
| --- | --- |
| `EdgeSpeak_<version>_aarch64.dmg` | 是 |
| `EdgeSpeak_<version>_aarch64.dmg.sha256` | 是 |
| `EdgeSpeak_<version>_windows-preview_cpu-cuda-vulkan_x64_setup.exe` | 是 |
| `EdgeSpeak_<version>_windows-preview_cpu-cuda-vulkan_x64_setup.exe.sha256` | 是 |

GitHub Releases 只包含桌面安装包。CLI 与 MCP 运行时通过 `install.sh`、`install.ps1` 及其
配置的下载源分发。不要附加 CLI 压缩包、CUDA 厂商运行库、构建中间目录、调试符号、凭据、
日志或私有模型来源。

## 正式发布前验证

- 确认标签、DMG 内的 App 以及 Windows 安装包版本一致。
- 对实际上传的每个文件重新验证校验值。
- 验证 macOS App 的签名、公证、安装和首次启动。
- 确认 Windows 版本被明确标记为采用手动更新的未签名 Preview，并披露 Windows 10/11
  的实际验证边界。
- 通过 `install.sh` 与 `install.ps1` 独立验证 CLI 分发，包括 `edgespeak-cli --version`
  和 `edgespeak-cli status`。
- 从草稿或已发布版本重新下载每个附件，确认与本地已验证产物逐字节一致。
- 确认中英文发布说明描述了同一组用户可见变化。

## 正式发布后

- 核对两份 README 中 Stable / Preview 平台状态和下载入口；精确版本号只放在 Release 与
  changelog 中维护。
- 确认公开 EdgeSpeak Skills 仓库链接有效；当前能力清单只在该仓库维护，不要复制到
  README 中形成容易过期的副本。
- 再次分别核对官网下载、App 自动更新、`install.sh`、`install.ps1` 及其面向用户展示的
  版本。
- 从公开更新记录链接到对应的 GitHub Release。
- 除非存在安全或法律原因，否则保留旧的稳定版本供用户下载。

## 新增文档语言

英文保持默认语言。新增翻译时，以 `README.<locale>.md` 命名，在每份 README 顶部的
语言切换栏中加入链接；发布说明保持相同顺序：先英文，再写翻译章节。

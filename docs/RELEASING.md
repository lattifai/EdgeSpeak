# Public Release Checklist

**English** · [简体中文](RELEASING.zh-CN.md)

This checklist covers publication to `lattifai/EdgeSpeak`. Build, signing,
notarization, and product-level validation happen in the private development
repositories before these steps begin.

## Release order

1. Complete the upstream build and release validation.
2. Create a draft GitHub Release, upload the required desktop attachments, and
   verify the uploaded bytes without publishing the draft.
3. Publish or promote the corresponding validated artifacts through the app
   updater, website download, and CLI installer.
4. Verify every public surface separately. A successful GitHub upload does not
   prove that the updater, website, or install script serves the new version.
5. Publish the GitHub Release from draft only after all required public surfaces
   pass verification.

## Prepare the GitHub Release

- Use a semantic version tag: `vMAJOR.MINOR.PATCH`.
- Use the title `EdgeSpeak MAJOR.MINOR.PATCH`.
- Start as a draft. Do not publish while any required package is still missing.
- Write user-facing outcomes rather than internal implementation details.
- Put English first in the release body, followed by a `## 简体中文` section.
- Mark a release as a prerelease only when it is not intended for the stable
  channel.

## Required assets

Attach all of the following to each GitHub Release:

| Asset | Required |
| --- | --- |
| `EdgeSpeak_<version>_aarch64.dmg` | Yes |
| `EdgeSpeak_<version>_aarch64.dmg.sha256` | Yes |
| `EdgeSpeak_<version>_windows-preview_cpu-cuda-vulkan_x64_setup.exe` | Yes |
| `EdgeSpeak_<version>_windows-preview_cpu-cuda-vulkan_x64_setup.exe.sha256` | Yes |

GitHub Releases contain desktop installers only. CLI and MCP runtimes are
distributed through `install.sh`, `install.ps1`, and their configured download
sources. Do not attach CLI archives, CUDA vendor runtimes, build intermediates,
debug symbols, credentials, logs, or private model sources.

## Verify before publishing

- Confirm the tag, the app inside the DMG, and the Windows installer use the
  same version.
- Verify every checksum against the exact uploaded file.
- Verify the macOS app signature, notarization, installation, and first launch.
- Confirm the Windows release is described as an unsigned Preview with manual
  updates and that its Windows 10/11 validation boundary is disclosed.
- Verify the CLI distribution independently through `install.sh` and
  `install.ps1`, including `edgespeak-cli --version` and `edgespeak-cli status`.
- Download every asset back from the draft or published release and confirm it
  is byte-for-byte identical to the validated local artifact.
- Confirm the English and Chinese notes describe the same user-visible changes.

## After publishing

- Verify the Stable / Preview platform labels and download entry points in both
  READMEs; keep exact version numbers in Releases and the changelog.
- Confirm the public EdgeSpeak Skills repository link is valid; keep the current
  capability catalog in that repository instead of duplicating it in the READMEs.
- Recheck the website download, app updater, `install.sh`, `install.ps1`, and
  their customer-visible version independently.
- Link the GitHub Release from the public changelog.
- Keep old stable releases available unless a security or legal reason requires
  removal.

## Adding another documentation language

English remains the default. Add a translated README as
`README.<locale>.md`, add its link to every README's language switch, and keep
release notes in the same order: English first, then translated sections.

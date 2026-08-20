# Public Release Checklist

**English** · [简体中文](RELEASING.zh-CN.md)

This checklist covers publication to `lattifai/EdgeSpeak`. Build, signing,
notarization, and product-level validation happen in the private development
repositories before these steps begin.

## Release order

1. Complete the upstream build and release validation.
2. Publish the GitHub Release in this repository first.
3. Publish or promote the same version through the app updater, website
   download, and CLI installer.
4. Verify every public surface separately. A successful GitHub upload does not
   prove that the updater, website, or install script serves the new version.

## Prepare the GitHub Release

- Use a semantic version tag: `vMAJOR.MINOR.PATCH`.
- Use the title `EdgeSpeak MAJOR.MINOR.PATCH`.
- Start as a draft. Do not publish while any required package is still missing.
- Write user-facing outcomes rather than internal implementation details.
- Put English first in the release body, followed by a `## 简体中文` section.
- Mark a release as a prerelease only when it is not intended for the stable
  channel.

## Required assets

For the first macOS and Windows GitHub release, attach all of the following:

| Asset | Required |
| --- | --- |
| `EdgeSpeak_<version>_aarch64.dmg` | Yes |
| `EdgeSpeak_<version>_aarch64.dmg.sha256` | Yes |
| `edgespeak-cli-standalone-macos-arm64.tar.gz` | Yes |
| `edgespeak-cli-standalone-macos-arm64.tar.gz.sha256` | Yes |
| `EdgeSpeak_<version>_windows-preview_cpu-cuda-vulkan_x64_setup.exe` | Yes |
| `EdgeSpeak_<version>_windows-preview_cpu-cuda-vulkan_x64_setup.exe.sha256` | Yes |
| `edgespeak-cli-mcp-windows-x86_64.zip` | Yes |
| `edgespeak-cli-mcp-windows-x86_64.zip.sha256` | Yes |
| `edgespeak-cli-mcp-windows-x86_64-cuda-runtime.zip` | Yes |
| `edgespeak-cli-mcp-windows-x86_64-cuda-runtime.zip.sha256` | Yes |

When the Ubuntu runtime is ready, also attach its x86_64 archive and matching
`.sha256` file. Keep the operating system and architecture in every CLI asset
name. Do not upload intermediate build directories, debug symbols, credentials,
logs, or private model sources.

## Verify before publishing

- Confirm the tag, the app inside the DMG, and `edgespeak-cli` use the same
  version.
- Verify every checksum against the exact uploaded file.
- Verify the macOS app signature, notarization, installation, and first launch.
- Confirm the Windows release is described as an unsigned Preview with manual
  updates and that its Windows 10/11 validation boundary is disclosed.
- Extract the CLI archive into a clean temporary directory and run
  `edgespeak-cli --version` and `edgespeak-cli status` from that extracted copy.
- Run at least one representative on-device command with a release license or
  test entitlement.
- Download every asset back from the draft or published release and confirm it
  is byte-for-byte identical to the validated local artifact.
- Confirm the English and Chinese notes describe the same user-visible changes.

## After publishing

- Update the release-status and platform table in both READMEs.
- Confirm every linked Skill is public, then remove any "coming" label from the
  corresponding README row.
- Publish or promote the same version through the remaining distribution
  surfaces.
- Verify the website download, app updater, `install.sh`, `install.ps1`, and
  their customer-visible version independently.
- Link the GitHub Release from the public changelog.
- Keep old stable releases available unless a security or legal reason requires
  removal.

## Adding another documentation language

English remains the default. Add a translated README as
`README.<locale>.md`, add its link to every README's language switch, and keep
release notes in the same order: English first, then translated sections.

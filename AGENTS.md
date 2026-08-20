# Repository Instructions

This repository is the public distribution home for EdgeSpeak. Keep product
source code, build intermediates, credentials, and release binaries out of the
Git tree. Publish versioned binaries as GitHub Release assets.

## Language

- Use English for commit messages.
- Keep `README.md` in English and `README.zh-CN.md` in Simplified Chinese.
- Update both README files together whenever user-visible release, platform,
  installation, or support information changes.
- Keep release notes bilingual, with English first and Simplified Chinese in a
  `## 简体中文` section.

## Release Safety

- Create releases as drafts first.
- Attach a matching SHA-256 file for every downloadable package.
- Verify the uploaded assets byte-for-byte before publishing a draft.
- Follow `docs/RELEASING.md` for the complete public release checklist.

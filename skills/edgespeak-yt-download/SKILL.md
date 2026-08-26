---
name: edgespeak-yt-download
version: 0.1.0
description: Download an authorized YouTube video's media, captions, and public metadata with yt-dlp for local transcription or analysis, using conservative serial requests, stable filenames, no-overwrite defaults, and safe cookie handling. Use when the user supplies a YouTube URL and needs a local audio/video file, subtitles, or title/description/participant metadata before edgespeak-transcribe or edgespeak-name-speakers.
---

# EdgeSpeak YT Download

Acquire a YouTube source deliberately and leave a verifiable local artifact. Use only for content the user is authorized to access and download. Do not bypass DRM, access controls, payment, private-video permissions, geographic restrictions, or account restrictions.

YouTube and `yt-dlp` behavior changes frequently. Check the installed `yt-dlp --help` before using a documented flag, and update `yt-dlp` rather than inventing extractor/client/PO-token workarounds when YouTube changes.

## Inputs to confirm

- The exact video URL.
- What is needed: public metadata only, captions only, best audio, or full video.
- Output directory and any quality/container constraint.
- Caption languages, if captions are requested.
- Single video or playlist. Default to **one video** with `--no-playlist`; never expand a watch URL into a playlist unless the user explicitly asks.
- Whether an existing output may be reused. Default to no overwrite.

If media already exists and the URL is only needed to identify speakers, fetch metadata rather than downloading the media again.

## Preflight

Run:

```bash
yt-dlp --version
yt-dlp --help
ffmpeg -version
ffprobe -version
```

`ffmpeg`/`ffprobe` are needed to merge separate high-quality video/audio streams and verify media. If `yt-dlp` is absent or stale, follow the current official installation instructions. Do not assume an old system package has current YouTube extractor fixes.

Before each command, verify the output directory and proposed targets. Use a stable template containing the video ID:

```text
%(title)s [%(id)s].%(ext)s
```

Do not hard-code the final extension; post-processing or merging may change it.

## Request discipline

Run **one YouTube download at a time**. Do not parallelize videos, languages, download agents, or fragments. These conservative options reduce request bursts:

```text
--concurrent-fragments 1 --sleep-requests 1 --sleep-interval 5 --max-sleep-interval 10
```

Local work such as transcription may run after a download completes, but do not overlap it with another YouTube acquisition unless the user explicitly changes this policy.

## Metadata only

To obtain the title, description, channel, duration, chapters, and public participant clues without media:

```bash
yt-dlp --no-playlist --skip-download --write-info-json --no-overwrites \
  -P /path/to/output \
  -o '%(title)s [%(id)s].%(ext)s' \
  'https://www.youtube.com/watch?v=VIDEO_ID'
```

Read the resulting `.info.json`; do not treat title/description names as proof of a label-to-person mapping. Pass the roster and source URL to `edgespeak-name-speakers` as candidate evidence.

## Download media

For the best available audio without an unnecessary lossy transcode:

```bash
yt-dlp --no-playlist --no-overwrites \
  --concurrent-fragments 1 --sleep-requests 1 \
  --sleep-interval 5 --max-sleep-interval 10 \
  -f 'ba/b' \
  --print 'after_move:filepath' \
  -P /path/to/output \
  -o '%(title)s [%(id)s].%(ext)s' \
  'https://www.youtube.com/watch?v=VIDEO_ID'
```

For full video, omit `-f` and let current `yt-dlp` choose its default best formats; with FFmpeg available it can merge separate streams. Add an explicit format/container rule only when the user requests one and `yt-dlp -F URL` confirms it is available.

To retain public metadata with a media download, add `--write-info-json`. The printed `after_move:filepath` is the actual final media path; use it rather than predicting the extension.

## Download captions

First list the exact manual and automatic subtitle language tags:

```bash
yt-dlp --no-playlist --list-subs \
  'https://www.youtube.com/watch?v=VIDEO_ID'
```

Then request only the languages needed. This example requests matching manual and automatic English variants when available:

```bash
yt-dlp --no-playlist --skip-download --no-overwrites \
  --write-subs --write-auto-subs \
  --sub-langs 'en.*,en' --sub-format 'vtt/best' \
  --sleep-requests 1 \
  -P /path/to/output \
  -o '%(title)s [%(id)s].%(ext)s' \
  'https://www.youtube.com/watch?v=VIDEO_ID'
```

Automatic captions can contain material errors. Label them as automatic and do not substitute them for an EdgeSpeak transcript without telling the user.

## Playlists

Only after explicit confirmation, remove `--no-playlist`, keep downloads serial, and use both an indexed template and an archive file so an interrupted run can resume without redownloading completed items:

```text
-o '%(playlist_title)s/%(playlist_index)03d - %(title)s [%(id)s].%(ext)s'
--download-archive /path/to/output/downloaded.txt
```

Do not share one archive file between concurrent processes.

## Authentication and throttling

Start without cookies. If a video the user can legitimately access requires their signed-in session, ask before reading browser cookies and prefer:

```text
--cookies-from-browser firefox
```

Use the browser the user names. Cookies can grant account access: never display them, export them to the repository, place them in command output, or commit cookie files. Do not ask the user to paste cookies into chat. Avoid combining `--cookies-from-browser` with `--cookies` to create an exported cookie jar.

On `429`, “confirm you're not a bot,” `403`, or extraction failure:

1. Stop repeated/burst retries and preserve the full error.
2. Check `yt-dlp --version`, current official yt-dlp guidance, and update if needed.
3. Let the user complete any legitimate browser/CAPTCHA flow; use their authorized browser session only with consent.
4. Retry later with the serial delay options. Use a proxy only when the user already has a legitimate configured proxy; do not use one to evade restrictions.

Do not hard-code undocumented player clients, visitor data, PO tokens, or copied extractor arguments from an old incident. Those fixes age quickly and may weaken account safety.

## Verify and hand off

- Confirm the command exited successfully and report the actual path printed by `after_move:filepath`.
- Run `ffprobe` on downloaded media and check duration plus audio/video streams.
- For metadata, confirm `id`, `webpage_url`, `title`, `channel`, and `duration` in `.info.json`.
- For captions, report the exact language tag, file format, and whether it is manual or automatic.
- If a target already exists, reuse it only after matching the video ID and verifying it; otherwise choose a new path. Never add `--force-overwrites` silently.

For a named local transcript, hand the verified media to `edgespeak-transcribe --diarize`, then give the diarized JSON plus the source metadata/URL to `edgespeak-name-speakers`.

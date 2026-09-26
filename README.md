# EdgeSpeak

**English** · [简体中文](README.zh-CN.md)

Private, on-device speech workflows for Claude Code. EdgeSpeak transcribes and aligns audio and
video on your own machine through the local `edgespeak-cli`, so your recordings are never uploaded.

## What it does

| Skill | What it does |
|-------|--------------|
| `edgespeak-transcribe` | Transcribe audio or video to text, SRT, or JSON with word timing, anonymous speaker labels, and caption-shaping options |
| `edgespeak-align` | Force-align audio against a transcript you already have to get word-level timestamps |
| `edgespeak-segment` | Split long or unpunctuated text into natural sentences, or re-split a word-timed transcript |
| `edgespeak-karaoke` | Build word-highlighted ASS captions, preview styles on real frames, and burn them into video with FFmpeg |
| `edgespeak-translate` | Translate a timed transcript while keeping every timestamp and the 1:1 segment mapping intact |
| `edgespeak-name-speakers` | Turn anonymous `speaker_N` labels into names only when a roster or source page supports them |

Claude uses these skills when a request fits. You can also call one directly, for example
`/edgespeak:edgespeak-transcribe`.

## Requirements

- **The local EdgeSpeak CLI.** Follow the install steps at
  [edgespeak.com/docs/cli](https://edgespeak.com/docs/cli#install). It runs on macOS Apple Silicon,
  Linux x86_64, and Windows x64 (the EdgeSpeak desktop app also ships it).
- **Claude Code on that same machine.** The skills call the CLI on your computer, so they do not
  run inside the claude.ai chat sandbox. Add the plugin from the Claude directory and use it in
  Claude Code.
- **An EdgeSpeak license.** Run `edgespeak-cli login` or `edgespeak-cli trial`; new devices get a
  7-day trial. See [edgespeak.com](https://edgespeak.com) for plans.
- Karaoke captions also need Node.js 18+ and FFmpeg with libass. Speaker naming needs Python 3.9+.

## Data and network use

- Audio and video are transcribed on your machine and are never uploaded by these skills. Transcript
  text you ask Claude to work with becomes part of your Claude conversation.
- `edgespeak-cli` contacts edgespeak.com to activate or refresh a license, and downloads model
  files on first use from download.edgespeak.com and EdgeSpeak's model repositories on huggingface.co
  and modelscope.cn.
- `edgespeak-translate` uses no network; Claude does the translation in the conversation.
- `edgespeak-name-speakers` may ask for a source page URL and read that page; it says when it makes
  that network request, and it does not download media just to read its metadata. It keeps the
  original speaker IDs, shows the evidence behind each proposed name, and leaves a speaker unnamed
  when the evidence is ambiguous.

Privacy policy: [edgespeak.com/privacy](https://edgespeak.com/privacy)

## More EdgeSpeak skills

Additional EdgeSpeak skills are published in the EdgeSpeak marketplace for Claude Code as the
`edgespeak-extras` plugin:

```
/plugin marketplace add lattifai/EdgeSpeak
/plugin install edgespeak-extras@edgespeak
```

Install only `edgespeak-extras` from that marketplace. Its `edgespeak` plugin carries the same six
skills you already have from the Claude directory, so installing both loads them twice.

## Support

Report problems at [github.com/lattifai/EdgeSpeak/issues](https://github.com/lattifai/EdgeSpeak/issues).

## License

Apache-2.0. See [LICENSE](LICENSE).

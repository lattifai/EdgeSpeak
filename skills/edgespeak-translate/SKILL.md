---
name: edgespeak-translate
version: 0.1.0
description: Translate a timed transcript (EdgeSpeak JSON or SRT) into a target language yourself, keeping a strict 1:1 segment mapping and every timestamp untouched, so the result still lines up with the audio for subtitles and dubbing. Enforces punctuation parity, consistent terminology, localized country/place names, and a per-segment character budget when the translation will be spoken. Use when the user wants a transcript, captions, or subtitles translated, mentions "translate the transcript", "翻译字幕", bilingual subtitles, or wants a dub script for EdgeSpeak Broadcast.
---

# EdgeSpeak Translate

Translate a **timed transcript** into another language. This skill is **agent-driven**: you write the translations. There is no `edgespeak-cli translate`, no translation API, no external MT service — the quality comes from your own language ability plus the rules below. That also keeps the whole pipeline local: the audio was transcribed on-device, and the text should not be shipped to a cloud translator either.

It fits between the other skills: `edgespeak-transcribe` / `edgespeak-align` produce the timed source, this skill adds the target language, and `edgespeak-broadcast` can speak the result as a dub.

## Inputs to confirm

- **Source transcript** — an EdgeSpeak JSON (`segments[]` with `start` / `end` / `text`, optionally `words[]`) or an `.srt`. A plain wall of text has no timing; run `edgespeak-segment` on it first if per-sentence output is wanted.
- **Target language.**
- **Output shape** — translation-only SRT, bilingual SRT (source line + target line), or JSON with a `translation` field per segment (best when anything downstream needs the timings).
- **Will it be spoken?** If the translation feeds `edgespeak-broadcast` for dubbing, the length budget below is a hard constraint, not a preference. Ask this before translating — it changes every line.

## Invariants

These hold for every segment. A violation means the output no longer matches the audio.

| Field | Rule |
| --- | --- |
| segment count / order | Identical to source. **Never merge or split.** |
| `id`, `start`, `end` | Preserved verbatim |
| `text` | Preserved verbatim (the source stays in the file) |
| `words[]` | Preserved verbatim — these are *source*-language timings |
| `translation` | Added, non-empty |

One source segment → one target segment. Everything downstream (SRT cues, karaoke, dub alignment) indexes on that.

Non-speech segments — music, lyrics, applause, noise — still need a non-empty `translation`: copy the source `text` verbatim rather than translating or leaving it blank, so the 1:1 count holds.

## How to do it

1. **Read the source** and count segments. Report the count before starting.
2. **Skim ~5 segments spread across the file** and note, in a few lines you keep in front of you while translating: domain, register (formal/casual, per speaker if known), recurring terms, and the tokens to keep verbatim (brands, products, people, acronyms). This term list is what makes chunk 7 consistent with chunk 1.
3. **Translate in chunks of ~30 segments.** Quality degrades on longer runs. Give each chunk the term list plus the last couple of segments before it and the first couple after it as *context only, not to translate*.
4. **Parallelize when it's long.** ≥5 chunks → dispatch one subagent per chunk in a single message, each returning an `{id: translation}` map. Fewer → do it inline. Never bundle more than ~30 segments into one dispatch.
5. **Merge, then run the checker** (below) instead of eyeballing it. Counting 600 segments by hand is exactly the check that gets skipped.
6. **Write the output** in the requested shape. Do not silently overwrite an existing file at the target path: if it already exists and the user did not explicitly ask to overwrite or regenerate it, confirm first (or agree on a different path); when you cannot ask, write to a new non-conflicting path and say so in your answer.

## Checking the result

One bundled script, zero dependencies, Node 18+. It re-reads both files and proves the mechanical parts of the rules above:

```bash
node <skill-dir>/scripts/check-translation.mjs \
    --translated out.json --source transcript.json --lang zh
```

`--translated` is the only required flag; `--source` unlocks the invariant checks (they need something to compare against), and `--lang` selects the character budget. Exit codes: `0` clean · `1` WARN · `2` FAIL.

| Level | What it catches |
| --- | --- |
| **FAIL** | segment count ≠ source · empty translation · `text` / `start` / `end` / `id` / `words[]` altered · `target_lang` contradicts `--lang` |
| **WARN** | `——` / parens / brackets absent from the source · `A / B` alternatives · translation over the character budget · leftover `TODO` / `???` markers |
| **SKIP** | a check that could not run — no `--source` to compare against, no `--lang`, or a target language with no calibrated speaking rate |

A FAIL means the output no longer lines up with the audio — fix the segment and re-run. A WARN is a judgement call: fix it, or tell the user why it stands. Do not edit the file to silence a check you haven't understood, and do not report success on a non-zero exit.

A SKIP is not a pass. The run ends with `No findings, but not fully checked` instead of `Clean`, and it still exits `0` — relay that distinction to the user rather than calling the output verified. Language codes are normalized before lookup, so `zh-CN`, `zh_CN`, and `ZH` all resolve to `zh`.

The checker reads transcript JSON, not SRT — one more reason to keep JSON as the master artifact and generate SRT from it. Its own tests run with `node --test "<skill-dir>/scripts/*.test.mjs"`.

## Translation rules

The rules that matter most, roughly in order of how often they get broken.

**Rewrite, don't word-substitute.** The line should read like a native speaker wrote it, not like it was mapped token by token.

**Punctuation parity — never inject punctuation the source lacks.** Forbidden when the corresponding source has none: `——` / `—` / `--`, `（…）` / `(…)`, `[…]` / `【…】`. An em-dash forces a hard pause and TTS reads parentheses aloud as asides; both deform delivery even in plain subtitles. Rewrite the connector instead, using what the source already implies:

- `I think it's nextgen because these things go crazy.`
  - ✗ `我觉得那就是下一代打法——这些东西就是会疯传。`
  - ✓ `我觉得那就是下一代打法，因为这些东西就是会疯传。`
- `the demultiplexer or demux.`
  - ✗ `解复用器（也叫 demux）。`
  - ✓ `解复用器，也叫 demux。`

Beyond "don't insert": **mirror the count and order** of interior punctuation, picking the natural target mark from the same class (`. ! ? …` ↔ `。！？…`; `, ; :` ↔ `，、；：`). `Hi, friend.` → `你好，朋友。`, not `朋友你好。` — dropping a comma for style silently breaks bilingual cue splitting.

**One term, one translation.** When a term admits several defensible renderings, decide once and reuse it everywhere. Never ship both side by side — `/` gets read aloud as "斜杠" and the audience hears your indecision:

- ✗ `参差不齐的智能 / 锯齿状智能` ✗ `参差不齐` ✓ `参差不齐的智能`

**Localize countries, places, and nationalities; keep proper nouns.** Default is to *translate* these with the standard exonym — they are ordinary vocabulary, not brand names. Leaving them in English next to translated text reads as half-machine-translated, and TTS pronounces them with the wrong phonemes.

- Countries / regions: China → 中国 · Russia → 俄罗斯 · America → 美国 · Europe → 欧洲 · EU → 欧盟 · Middle East → 中东
- Nationalities and languages, singular and plural: Chinese → 中国人 / 中文 · Americans → 美国人
- Cities and metonyms: Moscow → 莫斯科 · San Francisco → 旧金山 · Silicon Valley → 硅谷 · Wall Street → 华尔街 · Hollywood → 好莱坞

Keep the English **only** when the source uses it as the proper noun of an organization or publication — "China Mobile" the company, "Wall Street Journal" the newspaper. The same principle applies to any target language with established exonyms.

**Add nothing the source didn't say.** No acronyms, no expansions, no parenthetical glosses. Treat the source as a voice script and render only what was spoken:

- `People call it model view controller.` → ✓ `大家叫它模型视图控制器。` ✗ `大家叫它 MVC（模型-视图-控制器）。`

**Never annotate suspected ASR errors.** `Cloud Code（应为 Claude Code）` gets read aloud verbatim. If another segment in the same transcript clearly shows the right name, silently use the canonical form in both. If it isn't obvious, translate as-is and mention it to the user separately.

**Numbers and units: one writing system per token.** `30%` or `百分之三十`, never `三十%`; `50 GB`, never `五十G B`. Mixed forms break text normalizers and get read out character by character. Prefer Arabic digits plus the unit, and use the fully spelled-out form only when the source itself spelled the number out.

**Enumerated reads keep their token count.** `1 2 3 4 5 6 7` → `1、2、3、4、5、6、7`, not `1 到 7` — the duration budget assumes each token was spoken.

**Prune demonstratives for zh / ja / ko.** English leans on `this / that / these / the` as syntactic scaffolding; CJK drops them routinely. Default to deleting, and keep only for real deixis ("look at *this* slide") or explicit contrast:

- `These models are getting wild.` → ✓ `模型越来越离谱了。` ✗ `这些模型变得越来越疯狂。`

Does not apply to European-language targets, which keep their demonstratives.

**Preserve voice and force.** Casual stays casual, precise stays precise, questions stay questions, emphasis stays emphatic. Keep fillers only when they carry meaning.

**Use the target language's own punctuation convention** — full-width `，。？！：；` for zh / ja / ko — and stay consistent across every chunk of the same transcript.

## Length budget (subtitles, and mandatory for dubbing)

Each segment has a fixed duration. A translation that overruns it either scrolls past the viewer or, when synthesized, gets compressed into audible distortion.

**Hard ceiling** — `max_chars = (end - start) × CPS`, never exceeded:

| Target | zh | ja | ko | en | fr | es | pt | de | nl | ru | hi |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CPS ceiling | 9 | 20 | 17 | 22 | 35 | 31 | 34 | 43 | 33 | 37 | 27 |

**Translating into a language not in that table** (Italian, Arabic, Thai, Vietnamese, Polish …) is fine — everything else in this skill applies unchanged, and the checker still verifies segment count, invariants, and punctuation. Only the budget check goes away, and it reports itself as SKIP. **Do not invent a CPS number for the missing language**: a fabricated ceiling silently passes overlong lines or forces pointless compression, which is worse than an honest gap. Instead judge length by eye against the source duration, keeping the same *relative* density the table implies — a syllable-dense language sits nearer zh, a word-length-heavy one nearer de — and tell the user the budget was not machine-checked.

**Ideal length** — aim for `(end - start) × source_cps × ratio`, which preserves the speaker's delivery density: en→zh `0.35` · ja/ko `0.51` · ru `0.93` · hi/es/pt/nl `0.98` · de `1.05` · fr `1.10`.

**Counting characters in a zh / ja / ko line**: brand names and acronyms that stay in Latin script do not cost one budget unit per letter — `Claude` speaks in roughly the time of two Chinese characters, and the spaces around it are not spoken at all. Count a run of Latin letters as `ceil(letters / 3)` units, ignore spaces, and count everything else per character. Latin-script targets count every character as-is. Do not shorten a line that only looks long because it carries an untranslated product name.

The ceiling wins over the ideal. When they conflict, compress the phrasing — drop implied subjects, pick shorter synonyms, collapse subordinate clauses. **Never merge or split segments to solve a budget problem.** Both rules are waived for segments under ~1.5 s or under ~20 source characters. If a segment simply cannot fit, translate it as tightly as you can and flag it to the user rather than silently overrunning.

## Optional refinement pass

When the user asks for higher quality (a flagship video, a first run into a new language), do a second pass over the merged result: re-read each chunk against the source and check four axes — accuracy, naturalness, terminology consistency, voice preservation — and rewrite `translation` in place where one fails. Report what changed and anything you flagged but left alone. Skip this pass for drafts and bulk backfills; it roughly doubles the cost.

## Boundaries / gotchas (read this)

- **There is no CLI for this.** Don't invent `edgespeak-cli translate` and don't shell out to an online translation service — the point is that the text stays on the machine, and a fabricated command fails loudly in front of the user.
- **Word timings are source-language.** Translating does not re-time anything: `words[]` still describes the original audio. For target-language word timing, synthesize the translation with `edgespeak-broadcast`, then run `edgespeak-align` on that audio.
- **Segment count is the contract.** If you find yourself wanting to merge two cues because the translation reads better, don't — fix the phrasing instead.
- **Long transcripts are the normal case.** A 60-minute talk is ~600 segments, ~20 chunks. Chunk and parallelize rather than trying to hold it all in one pass, and never quietly translate only the first N segments — if you have to stop early, say exactly where you stopped.
- **The checker needs Node 18+**, but nothing else — no EdgeSpeak runtime, no license. If Node is missing, say the verification did not run rather than claiming the output is clean.

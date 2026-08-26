---
name: edgespeak-name-speakers
version: 0.4.0
description: Resolve anonymous speaker_N labels in an EdgeSpeak diarized transcript to evidence-backed real names, while preserving the original cluster IDs and leaving uncertain identities unresolved. Use after edgespeak-transcribe --diarize for interviews, meetings, panels, and podcasts when the user wants named speakers, or when the user provides a participant roster, source page, or YouTube URL that can supply identity metadata.
---

# EdgeSpeak Name Speakers

Turn an existing diarized transcript from anonymous labels into a traceable named copy. This is an **identity-enrichment step**, not speaker diarization: `edgespeak-transcribe --diarize` decides which voice spoke each segment, while this skill determines whether there is enough evidence to associate a voice cluster with a person.

Do not imply that EdgeSpeak acoustically recognizes identities. A source title or participant list supplies candidates; it does not prove which anonymous voice is which.

## Inputs to confirm

- The diarized EdgeSpeak JSON. If only media is available, first use `edgespeak-transcribe --diarize -o transcript.json`.
- The best available participant metadata: a user-confirmed roster, official episode/show notes, or the original video/YouTube URL. Ask for the source URL when names matter and the local media does not carry enough metadata.
- A new output path, normally `<stem>.named.json`. Never overwrite the anonymous master transcript.

If the agent cannot access the source page, ask the user to paste its title, description, and participant roster. Do not download the media merely to obtain metadata; for a YouTube source, use the metadata-only flow in `edgespeak-yt-download` when needed.

## Workflow

### 1. Validate the master transcript

The input must have a `segments` array and every segment must contain `speaker` with either an anonymous string such as `speaker_0` or `null`. If no speaker keys exist, stop and request a diarized JSON; naming a plain transcript would be guesswork.

### 2. Build the roster, then extract evidence once

Normalize source metadata before asking the agent to read a long transcript. Use a small JSON roster:

```json
{
  "speakers": [
    {
      "name": "Joon Sung Park",
      "role": "guest",
      "kind": "person",
      "aliases": ["June"]
    },
    {
      "name": "Sonya Huang",
      "role": "host",
      "kind": "person",
      "aliases": []
    }
  ]
}
```

`name` is required. `role`, `affiliation`, `kind`, and `aliases` are optional. Use `kind` to distinguish a person from a synthetic/production voice such as `ChatGPT`, `Intro`, or `Narrator`; do not force every anonymous cluster to be a person. Add an ASR spelling to `aliases` only when it is observed in the transcript or confirmed by source metadata. The canonical `name` remains the authoritative spelling.

Resolve this skill's installed directory as `<skill-dir>`, then create the compact evidence view with the roster in the same pass:

```bash
python3 <skill-dir>/scripts/speaker_names.py inspect /path/to/transcript.json \
  --roster /path/to/participants.json \
  > /path/to/transcript.speaker-evidence.json
```

For a quick roster without roles or aliases, repeat `--candidate 'Full Name'` instead. The report includes:

- per-label speaking/turn/question-like statistics and representative samples;
- the opening dialogue and self-introduction/address candidates;
- full-transcript occurrences of every roster name and alias;
- the nearest different-speaker segment before and after every occurrence;
- strong/medium/weak match counts, shared name parts omitted from matching, and
  same-role ambiguity risks;
- conservative candidate-to-label `speaker_lead` scores derived from
  self-introductions, opening direct addresses, introductions, and repeated
  named-question responses;
- unattributed counts and roster candidates with no textual mention.

This directly exposes patterns such as “host names Ari, then `speaker_1` answers” without requiring a blind scan through hundreds of segments. A mention plus its neighboring speaker is still a lead, not proof: an introduction may name several people before anyone answers. Compare multiple occurrences and the actual response content.

The report does not modify the transcript. Do not overwrite an existing report without the user's approval. If a canonical name has no matches because ASR rendered it differently, add the observed rendering as an alias and rerun **inspect only**; transcription does not need to run again.

Read each candidate's `match_details`, `match_summary`, and `risks` before drawing a conclusion. A full canonical name or confirmed alias is a strong lexical match, a family name is medium, and another name part is weak. A self-introduction promotes the matched occurrence to strong evidence. Shared name parts such as `David` in a roster containing both `David Friedberg` and `David Sacks` are omitted because they cannot distinguish the candidates. The report flags `shared_roster_name_parts`, `same_role_candidates`, `partial_name_only`, `weak_name_parts_only`, and `no_text_matches`; these are decision warnings, not identity predictions. A partial-name-only match can also be an ordinary word, so it must never assign a label by itself.

Use `speaker_lead` to prioritize the next passages to audit. It scores all matching segments even when `--mentions-per-candidate` limits the displayed examples. Self-introductions point to the current label; a name used as an opening direct address, in an introduction, or in a named question points to the next different-speaker turn. A single named question is deliberately below the proposal threshold; it must repeat consistently or agree with stronger evidence. If two candidates lead to the same anonymous label, both leads are blocked with `speaker_lead_collision`. A surviving lead is structured evidence, not permission to skip the surrounding transcript or the confidence rules below.

Start with the top-level `speaker_leads` summary, then open the matching candidate's event list and surrounding turns. The summary also exposes blocked collisions so they cannot disappear inside a long report.

For a short transcript, also read every segment. For a long transcript, inspect additional passages around direct address, introductions, job/company references, and speaker switches only where the report leaves ambiguity.

Rank evidence in this order:

1. The user's explicit identification of a label or voice.
2. A self-introduction or unambiguous direct address in the transcript.
3. Official source metadata, show notes, chapters, or an on-page participant list.
4. Multiple transcript details matching a candidate's role, affiliation, or biography.
5. Conversation-role heuristics such as host/guest turn patterns.

Metadata can establish who participated, but it cannot assign labels by itself when several candidates remain possible. The report's speaking share and question-like rate help test a known `host`/`guest` role, but do not establish identity. Long-form guests often dominate speaking time while panelists may have similar shares; apparent gender, accent, pitch, label order, and “the host usually speaks first” are never sufficient identity evidence.

Apply a strict ambiguity gate when two or more candidates have the same role. Do not distinguish them using topic familiarity, speaking share, conversational style, or expected panel order alone. Unless each inferred mapping has a self-identification, an unambiguous direct response, or another candidate-specific signal, leave those labels unresolved. One-to-one elimination is acceptable only when every other mapping is independently confirmed, the roster is known to be exhaustive, label and participant counts agree, and there are no extra guest, audience, narrator, clip, or production clusters. Otherwise elimination is still a guess. A biographical signal must be distinctive to the candidate and corroborated; generic subject expertise is not enough.

Use the name spelling from an authoritative source. ASR may render a name phonetically (`June` instead of `Joon`); use the rendering only as a search alias, not as the output name.

### 3. Audit every label

Before writing, present a compact table with `speaker ID`, proposed name, confidence, and concrete evidence. Use only these outcomes:

- **Confirmed** — the user confirmed the mapping, or the transcript contains an unambiguous self-identification/direct identification corroborated by the source roster.
- **Strong** — at least two independent signals agree, including a direct-address, role, affiliation, or biographical signal; no evidence conflicts.
- **Unresolved** — evidence is ambiguous, role-only, or contradictory.

Ask the user to confirm any inferred mapping when a wrong attribution would materially affect publication, research, meeting records, or downstream editing. Never force a one-to-one assignment simply because candidate and label counts match. Keep uncertain labels as `speaker_N` (or use a clearly generic role such as `Audience` only when the content establishes that role and a personal identity is unnecessary).

If one anonymous label appears to contain two different people, or one person is split across multiple labels without a defensible merge, report a diarization/clustering problem. Identity naming cannot repair it; rerun diarization with a known speaker-count hint through the supported MCP/API path described in `edgespeak-transcribe` when appropriate.

### 4. Write a named copy

Apply only confirmed or accepted strong mappings:

```bash
python3 <skill-dir>/scripts/speaker_names.py apply /path/to/transcript.json \
  -o /path/to/transcript.named.json \
  --map 'speaker_0=Joon Sung Park' \
  --map 'speaker_1=Sonya Huang'
```

The helper refuses to overwrite files and rejects labels absent from the input. In the named copy it:

- replaces mapped `segments[].speaker` values with the real name;
- adds `segments[].speaker_id` with the original anonymous label for every attributed segment;
- adds a top-level `speaker_mapping` object;
- preserves text, timing, words, usage, `null` speakers, and unresolved labels.

The result is enriched EdgeSpeak JSON, not the original `diarized_json` wire shape. Consumers that require the exact API response should use the anonymous master plus `speaker_mapping` separately.

### 5. Verify the result

- Read the helper's `mapped_segment_counts` and `unresolved_speakers` summary.
- Compare the named copy's text, segment count, timestamps, word arrays, and usage with the master; only identity fields should differ.
- Review at least the first and last occurrence of every mapped speaker and any identity-clue segment.
- Report unresolved labels honestly. Do not silently omit them from the deliverable.

The bundled helper tests run with:

```bash
python3 -m unittest discover -s <skill-dir>/scripts -p 'test_*.py'
```

## Cross-file and privacy boundaries

- `speaker_0` is local to one media file. Never reuse a mapping across episodes based on label number.
- Do not identify someone from voice similarity unless the user explicitly supplies an authorized reference workflow and the tooling produces a verified match. This skill does not provide biometric identification.
- A local transcript can be inspected without uploading it. Fetching a source page or YouTube metadata is a separate network action; say so when it is used.
- Source URLs, titles, and public rosters are metadata. Cookies, private meeting links, access tokens, and private participant details are sensitive: never print, persist in reports, or commit them.

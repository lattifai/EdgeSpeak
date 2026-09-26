#!/usr/bin/env python3
"""Inspect and enrich EdgeSpeak diarized JSON with evidence-backed speaker names."""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional


IDENTITY_CLUE_PATTERNS = (
    re.compile(
        r"\b(my name is|welcome|joined by|speaking with|start with you)\b"
        r"|我是|我叫|欢迎|嘉宾|主持人|请到",
        re.IGNORECASE,
    ),
    # Preserve likely self-introductions without treating every "I am ..." as a name.
    re.compile(r"\b(?:I am|I'm)\s+[A-Z][\w'-]+"),
)

QUESTION_LIKE = re.compile(
    r"(?:[?？]\s*$)|(?:^\s*(?:who|what|when|where|why|how|do|does|did|is|are|"
    r"can|could|would|will|tell me|take me|walk me|give me)\b)",
    re.IGNORECASE,
)

INTRODUCTION_CUE = re.compile(
    r"\b(?:welcome|joined by|speaking with|start with you|over to you|meet)\b",
    re.IGNORECASE,
)

MIN_SPEAKER_LEAD_SCORE = 4
MIN_SPEAKER_LEAD_MARGIN = 2


class TranscriptError(ValueError):
    """Raised when a transcript or mapping is not safe to process."""


def load_transcript(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise TranscriptError(f"input does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise TranscriptError(f"input is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise TranscriptError("top-level JSON must be an object")
    segments = data.get("segments")
    if not isinstance(segments, list):
        raise TranscriptError("input must contain a segments array")
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            raise TranscriptError(f"segments[{index}] must be an object")
        if "speaker" not in segment:
            raise TranscriptError(
                f"segments[{index}] has no speaker key; transcribe with --diarize first"
            )
        speaker = segment["speaker"]
        if speaker is not None and not isinstance(speaker, str):
            raise TranscriptError(f"segments[{index}].speaker must be a string or null")
    return data


def compact_segment(
    segment: dict[str, Any], text_limit: int = 320, index: Optional[int] = None
) -> dict[str, Any]:
    text = " ".join(str(segment.get("text", "")).split())
    if len(text) > text_limit:
        text = f"{text[: text_limit - 1]}…"
    result = {
        "id": segment.get("id"),
        "start": segment.get("start"),
        "end": segment.get("end"),
        "speaker": segment.get("speaker"),
        "text": text,
    }
    if index is not None:
        result["index"] = index
    return result


def duration(segment: dict[str, Any]) -> float:
    start = segment.get("start")
    end = segment.get("end")
    if isinstance(start, (int, float)) and isinstance(end, (int, float)):
        return max(0.0, float(end) - float(start))
    return 0.0


def choose_samples(
    segments: list[dict[str, Any]],
    max_samples: int,
    positions: dict[int, int],
) -> list[dict[str, Any]]:
    if max_samples <= 0:
        return []

    first_count = min(2, max_samples)
    last_count = min(2, max(0, max_samples - first_count))
    longest_count = max_samples - first_count - last_count
    chosen = list(segments[:first_count])
    chosen.extend(
        sorted(segments, key=lambda item: len(str(item.get("text", ""))), reverse=True)[
            :longest_count
        ]
    )
    if last_count:
        chosen.extend(segments[-last_count:])

    unique: dict[int, dict[str, Any]] = {}
    for segment in chosen:
        unique[id(segment)] = segment
    ordered = sorted(unique.values(), key=lambda item: positions[id(item)])
    return [compact_segment(segment, index=positions[id(segment)]) for segment in ordered]


def is_identity_clue(text: str) -> bool:
    return any(pattern.search(text) for pattern in IDENTITY_CLUE_PATTERNS)


def load_roster(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise TranscriptError(f"roster does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise TranscriptError(f"roster is not valid JSON: {exc}") from exc

    if isinstance(data, dict):
        candidates = data.get("speakers")
    else:
        candidates = data
    if not isinstance(candidates, list):
        raise TranscriptError("roster must be an array or an object with a speakers array")

    normalized: list[dict[str, Any]] = []
    names: set[str] = set()
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            raise TranscriptError(f"roster speaker {index} must be an object")
        name = candidate.get("name")
        if not isinstance(name, str) or not name.strip():
            raise TranscriptError(f"roster speaker {index}.name must be a non-empty string")
        name = name.strip()
        name_key = name.casefold()
        if name_key in names:
            raise TranscriptError(f"duplicate roster name: {name}")
        names.add(name_key)

        aliases = candidate.get("aliases", [])
        if not isinstance(aliases, list) or not all(
            isinstance(alias, str) and alias.strip() for alias in aliases
        ):
            raise TranscriptError(f"roster speaker {index}.aliases must be a string array")

        entry: dict[str, Any] = {
            "name": name,
            "aliases": [alias.strip() for alias in aliases],
        }
        for field in ("role", "affiliation", "kind"):
            value = candidate.get(field)
            if value is not None:
                if not isinstance(value, str) or not value.strip():
                    raise TranscriptError(
                        f"roster speaker {index}.{field} must be a non-empty string"
                    )
                entry[field] = value.strip()
        normalized.append(entry)
    return normalized


def candidate_term_details(candidate: dict[str, Any]) -> list[dict[str, str]]:
    name = candidate["name"]
    parts = [part for part in name.split() if len(part) >= 3]
    raw_details = [{"term": name, "kind": "canonical_name", "strength": "strong"}]
    raw_details.extend(
        {"term": alias, "kind": "alias", "strength": "strong"}
        for alias in candidate.get("aliases", [])
    )
    if len(parts) > 1:
        raw_details.extend(
            {
                "term": part,
                "kind": "family_name" if index == len(parts) - 1 else "name_part",
                "strength": "medium" if index == len(parts) - 1 else "weak",
            }
            for index, part in enumerate(parts)
        )

    details: list[dict[str, str]] = []
    seen: set[str] = set()
    for detail in raw_details:
        normalized = detail["term"].strip()
        key = normalized.casefold()
        if key and key not in seen:
            seen.add(key)
            details.append({**detail, "term": normalized})
    return sorted(details, key=lambda detail: len(detail["term"]), reverse=True)


def shared_roster_name_parts(
    candidates: list[dict[str, Any]],
) -> dict[str, list[str]]:
    owners: dict[str, set[str]] = defaultdict(set)
    spellings: dict[str, str] = {}
    for candidate in candidates:
        for detail in candidate_term_details(candidate):
            if detail["kind"] not in {"name_part", "family_name"}:
                continue
            key = detail["term"].casefold()
            owners[key].add(candidate["name"])
            spellings[key] = detail["term"]
    return {
        spellings[key]: sorted(names)
        for key, names in owners.items()
        if len(names) > 1
    }


def candidate_search_terms(
    candidate: dict[str, Any], ignored_terms: Optional[set[str]] = None
) -> list[str]:
    ignored_terms = ignored_terms or set()
    return [
        detail["term"]
        for detail in candidate_term_details(candidate)
        if detail["term"].casefold() not in ignored_terms
    ]


def exact_term_matches(text: str, terms: list[str]) -> list[str]:
    return [
        term
        for term in terms
        if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, re.IGNORECASE)
    ]


def is_self_introduction(text: str, term: str) -> bool:
    return bool(
        re.search(
            rf"\b(?:my name is|I am|I'm)\s+{re.escape(term)}(?!\w)",
            text,
            re.IGNORECASE,
        )
    )


def is_opening_address(text: str, term: str) -> bool:
    return bool(
        re.search(
            rf"^\s*{re.escape(term)}(?!\w)\s*[,!:]",
            text,
            re.IGNORECASE,
        )
    )


def has_introduction_cue(text: str, term: str) -> bool:
    match = re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, re.IGNORECASE)
    if match is None:
        return False
    return bool(INTRODUCTION_CUE.search(text[max(0, match.start() - 80) : match.start()]))


def is_named_question(text: str, term: str) -> bool:
    if "?" not in text and "？" not in text:
        return False
    match = re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, re.IGNORECASE)
    if match is None:
        return False
    before = text[: match.start()]
    after = text[match.end() :]
    if re.search(r"\b(?:like|as)\s*$", before, re.IGNORECASE):
        return False
    if re.match(r"['’]s\b", after, re.IGNORECASE):
        return False
    return True


def nearest_other_speaker(
    segments: list[dict[str, Any]], index: int, direction: int
) -> Optional[dict[str, Any]]:
    current_speaker = segments[index].get("speaker")
    cursor = index + direction
    while 0 <= cursor < len(segments):
        segment = segments[cursor]
        speaker = segment.get("speaker")
        if speaker is not None and speaker != current_speaker:
            return compact_segment(segment, index=cursor)
        cursor += direction
    return None


def evidence_entry(
    segments: list[dict[str, Any]], index: int, matched_terms: Optional[list[str]] = None
) -> dict[str, Any]:
    result = {
        "segment": compact_segment(segments[index], index=index),
        "previous_other_speaker": nearest_other_speaker(segments, index, -1),
        "next_other_speaker": nearest_other_speaker(segments, index, 1),
    }
    if matched_terms is not None:
        result["matched_terms"] = matched_terms
    return result


def label_signal(
    segments: list[dict[str, Any]],
    index: int,
    match_details: list[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    text = str(segments[index].get("text", ""))
    current_speaker = segments[index].get("speaker")

    for detail in match_details:
        if detail["self_introduction"] and current_speaker is not None:
            return {
                "type": "self_introduction",
                "target_speaker": current_speaker,
                "source_speaker": current_speaker,
                "weight": 12,
            }

    next_speaker = nearest_other_speaker(segments, index, 1)
    if next_speaker is None:
        return None
    for detail in match_details:
        if is_opening_address(text, detail["term"]):
            return {
                "type": "opening_address_response",
                "target_speaker": next_speaker["speaker"],
                "source_speaker": current_speaker,
                "weight": 4,
            }
    for detail in match_details:
        if has_introduction_cue(text, detail["term"]):
            return {
                "type": "introduction_response",
                "target_speaker": next_speaker["speaker"],
                "source_speaker": current_speaker,
                "weight": 3,
            }
    for detail in match_details:
        if is_named_question(text, detail["term"]):
            return {
                "type": "named_question_response",
                "target_speaker": next_speaker["speaker"],
                "source_speaker": current_speaker,
                "weight": 3,
            }
    return None


def speaker_lead(
    scores: dict[str, int], events: list[dict[str, Any]]
) -> dict[str, Any]:
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    positive = [
        {"speaker": speaker, "score": score}
        for speaker, score in ranked
        if score > 0
    ]
    top_score = ranked[0][1] if ranked else 0
    runner_up_score = max(0, ranked[1][1]) if len(ranked) > 1 else 0
    margin = top_score - runner_up_score
    proposed = (
        ranked[0][0]
        if ranked
        and top_score >= MIN_SPEAKER_LEAD_SCORE
        and margin >= MIN_SPEAKER_LEAD_MARGIN
        else None
    )
    return {
        "speaker": proposed,
        "score": top_score if proposed is not None else None,
        "margin": margin if proposed is not None else None,
        "ranked_scores": positive,
        "event_count": len(events),
        "events": events[:20],
    }


def build_candidate_evidence(
    segments: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    mentions_per_candidate: int,
) -> list[dict[str, Any]]:
    result = []
    shared_parts = shared_roster_name_parts(candidates)
    shared_keys = {term.casefold() for term in shared_parts}
    role_groups: dict[str, list[str]] = defaultdict(list)
    for candidate in candidates:
        role = candidate.get("role")
        if isinstance(role, str) and role:
            role_groups[role.casefold()].append(candidate["name"])

    for candidate in candidates:
        details = candidate_term_details(candidate)
        ignored = [
            detail["term"]
            for detail in details
            if detail["term"].casefold() in shared_keys
        ]
        terms = candidate_search_terms(candidate, shared_keys)
        details_by_term = {detail["term"].casefold(): detail for detail in details}
        mentions = []
        scores: dict[str, int] = defaultdict(int)
        signal_events = []
        matched_mention_count = 0
        strong_mentions = 0
        medium_mentions = 0
        weak_mentions = 0
        for index, segment in enumerate(segments):
            text = str(segment.get("text", ""))
            matches = exact_term_matches(text, terms)
            if matches:
                matched_mention_count += 1
                match_details = [
                    {
                        **details_by_term[term.casefold()],
                        "self_introduction": is_self_introduction(text, term),
                    }
                    for term in matches
                ]
                if any(
                    detail["strength"] == "strong"
                    or detail["self_introduction"]
                    for detail in match_details
                ):
                    strong_mentions += 1
                elif any(
                    detail["strength"] == "medium" for detail in match_details
                ):
                    medium_mentions += 1
                else:
                    weak_mentions += 1
                signal = label_signal(segments, index, match_details)
                if signal is not None:
                    target = signal["target_speaker"]
                    scores[target] += signal["weight"]
                    source_speaker = signal["source_speaker"]
                    if source_speaker is not None and source_speaker != target:
                        scores[source_speaker] -= 1
                    signal_events.append(
                        {
                            **signal,
                            "segment": compact_segment(segment, index=index),
                        }
                    )
                if len(mentions) < mentions_per_candidate:
                    entry = evidence_entry(segments, index, matches)
                    entry["match_details"] = match_details
                    if signal is not None:
                        entry["label_signal"] = signal
                    mentions.append(entry)

        role = candidate.get("role")
        role_key = role.casefold() if isinstance(role, str) else ""
        same_role_candidates = [
            name
            for name in role_groups.get(role_key, [])
            if name != candidate["name"]
        ]
        risks = []
        if ignored:
            risks.append("shared_roster_name_parts")
        if same_role_candidates:
            risks.append("same_role_candidates")
        if matched_mention_count and not strong_mentions:
            risks.append("partial_name_only")
        if matched_mention_count and not strong_mentions and not medium_mentions:
            risks.append("weak_name_parts_only")
        if not matched_mention_count:
            risks.append("no_text_matches")

        entry = dict(candidate)
        entry["search_terms"] = terms
        entry["ignored_shared_terms"] = ignored
        entry["same_role_candidates"] = same_role_candidates
        entry["match_summary"] = {
            "strong": strong_mentions,
            "medium": medium_mentions,
            "weak": weak_mentions,
            "total": matched_mention_count,
        }
        entry["risks"] = risks
        entry["mentions"] = mentions
        entry["speaker_lead"] = speaker_lead(scores, signal_events)
        result.append(entry)

    lead_owners: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in result:
        proposed = entry["speaker_lead"]["speaker"]
        if proposed is not None:
            lead_owners[proposed].append(entry)
    for speaker, owners in lead_owners.items():
        if len(owners) < 2:
            continue
        for entry in owners:
            entry["speaker_lead"]["blocked_speaker"] = speaker
            entry["speaker_lead"]["speaker"] = None
            entry["speaker_lead"]["score"] = None
            entry["speaker_lead"]["margin"] = None
            entry["risks"].append("speaker_lead_collision")
    return result


def build_inspection(
    source: Path,
    data: dict[str, Any],
    max_samples: int,
    dialogue_turns: int,
    candidates: Optional[list[dict[str, Any]]] = None,
    mentions_per_candidate: int = 12,
) -> dict[str, Any]:
    segments = data["segments"]
    positions = {id(segment): index for index, segment in enumerate(segments)}
    by_speaker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    unattributed = 0
    for segment in segments:
        speaker = segment["speaker"]
        if speaker is None:
            unattributed += 1
        else:
            by_speaker[speaker].append(segment)

    total_speaking = sum(duration(segment) for items in by_speaker.values() for segment in items)
    speakers: dict[str, Any] = {}
    for speaker in sorted(by_speaker):
        items = by_speaker[speaker]
        speaking = sum(duration(segment) for segment in items)
        character_counts = [len(str(item.get("text", ""))) for item in items]
        question_like_count = sum(
            bool(QUESTION_LIKE.search(str(item.get("text", "")))) for item in items
        )
        turn_count = sum(
            1
            for item in items
            if positions[id(item)] == 0
            or segments[positions[id(item)] - 1].get("speaker") != speaker
        )
        speakers[speaker] = {
            "segment_count": len(items),
            "turn_count": turn_count,
            "first_segment_index": positions[id(items[0])],
            "speaking_seconds": round(speaking, 3),
            "speaking_share": round(speaking / total_speaking, 4)
            if total_speaking
            else None,
            "character_count": sum(character_counts),
            "median_segment_characters": round(statistics.median(character_counts), 1),
            "question_like_segment_count": question_like_count,
            "question_like_rate": round(question_like_count / len(items), 4),
            "samples": choose_samples(items, max_samples, positions),
        }

    clues = [
        evidence_entry(segments, index)
        for index, segment in enumerate(segments)
        if is_identity_clue(str(segment.get("text", "")))
    ][:20]
    candidate_evidence = build_candidate_evidence(
        segments, candidates or [], mentions_per_candidate
    )
    lead_summary = [
        {
            "candidate": entry["name"],
            "speaker": entry["speaker_lead"]["speaker"],
            "score": entry["speaker_lead"]["score"],
            "margin": entry["speaker_lead"]["margin"],
            "blocked_speaker": entry["speaker_lead"].get("blocked_speaker"),
            "risks": entry["risks"],
        }
        for entry in candidate_evidence
        if entry["speaker_lead"]["speaker"] is not None
        or "blocked_speaker" in entry["speaker_lead"]
    ]

    return {
        "source": str(source),
        "segment_count": len(segments),
        "unattributed_segment_count": unattributed,
        "speakers": speakers,
        "opening_dialogue": [
            compact_segment(segment, index=index)
            for index, segment in enumerate(segments[: max(0, dialogue_turns)])
        ],
        "identity_clues": clues,
        "speaker_leads": lead_summary,
        "candidate_evidence": candidate_evidence,
    }


def parse_mapping(values: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise TranscriptError(f"invalid mapping {value!r}; expected SPEAKER_ID=NAME")
        speaker, name = (part.strip() for part in value.split("=", 1))
        if not speaker or not name:
            raise TranscriptError(f"invalid mapping {value!r}; id and name must be non-empty")
        if speaker in mapping:
            raise TranscriptError(f"duplicate mapping for {speaker}")
        if any(ord(character) < 32 for character in name):
            raise TranscriptError(f"name for {speaker} contains a control character")
        mapping[speaker] = name
    if not mapping:
        raise TranscriptError("at least one --map SPEAKER_ID=NAME is required")
    return mapping


def apply_mapping(
    source: Path, destination: Path, data: dict[str, Any], mapping: dict[str, str]
) -> dict[str, Any]:
    if source.resolve() == destination.resolve():
        raise TranscriptError("output must differ from input; preserve the anonymous transcript")
    if destination.exists():
        raise TranscriptError(f"output already exists: {destination}")
    if not destination.parent.is_dir():
        raise TranscriptError(f"output directory does not exist: {destination.parent}")
    if "speaker_mapping" in data:
        raise TranscriptError("input already contains speaker_mapping; use the original transcript")

    labels = {
        segment["speaker"]
        for segment in data["segments"]
        if segment["speaker"] is not None
    }
    unknown = sorted(set(mapping) - labels)
    if unknown:
        raise TranscriptError(f"mapping contains labels not present in input: {', '.join(unknown)}")

    enriched = dict(data)
    enriched["speaker_mapping"] = mapping
    enriched_segments = []
    mapped_counts: dict[str, int] = defaultdict(int)
    for original in data["segments"]:
        segment = dict(original)
        speaker = segment["speaker"]
        if speaker is not None:
            segment["speaker_id"] = speaker
            if speaker in mapping:
                segment["speaker"] = mapping[speaker]
                mapped_counts[speaker] += 1
        enriched_segments.append(segment)
    enriched["segments"] = enriched_segments

    temporary_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(enriched, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()

    return {
        "input": str(source),
        "output": str(destination),
        "mapping": mapping,
        "mapped_segment_counts": dict(sorted(mapped_counts.items())),
        "unresolved_speakers": sorted(labels - set(mapping)),
    }


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect or enrich EdgeSpeak diarized transcript JSON."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser(
        "inspect", help="Summarize speaker evidence without changing the transcript"
    )
    inspect_parser.add_argument("input", type=Path)
    inspect_parser.add_argument("--samples-per-speaker", type=int, default=6)
    inspect_parser.add_argument("--dialogue-turns", type=int, default=30)
    inspect_parser.add_argument(
        "--roster",
        type=Path,
        help="JSON roster with names, roles, affiliations, and optional ASR aliases",
    )
    inspect_parser.add_argument(
        "--candidate",
        action="append",
        default=[],
        metavar="NAME",
        help="Add a candidate name without creating a roster file; repeat as needed",
    )
    inspect_parser.add_argument("--mentions-per-candidate", type=int, default=12)

    apply_parser = subparsers.add_parser(
        "apply", help="Write a named copy while preserving anonymous speaker IDs"
    )
    apply_parser.add_argument("input", type=Path)
    apply_parser.add_argument("--output", "-o", type=Path, required=True)
    apply_parser.add_argument(
        "--map",
        action="append",
        default=[],
        metavar="SPEAKER_ID=NAME",
        help="Repeat for each evidence-backed identity",
    )
    return parser


def main() -> int:
    parser = create_parser()
    args = parser.parse_args()
    try:
        data = load_transcript(args.input)
        if args.command == "inspect":
            if (
                args.samples_per_speaker < 0
                or args.dialogue_turns < 0
                or args.mentions_per_candidate < 0
            ):
                raise TranscriptError("inspection limits must be non-negative")
            candidates = load_roster(args.roster) if args.roster else []
            known_names = {candidate["name"].casefold() for candidate in candidates}
            for name in args.candidate:
                name = name.strip()
                if not name:
                    raise TranscriptError("--candidate must be a non-empty name")
                if name.casefold() not in known_names:
                    candidates.append({"name": name, "aliases": []})
                    known_names.add(name.casefold())
            result = build_inspection(
                args.input,
                data,
                args.samples_per_speaker,
                args.dialogue_turns,
                candidates,
                args.mentions_per_candidate,
            )
        else:
            result = apply_mapping(
                args.input, args.output, data, parse_mapping(args.map)
            )
    except TranscriptError as exc:
        parser.exit(2, f"error: {exc}\n")

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

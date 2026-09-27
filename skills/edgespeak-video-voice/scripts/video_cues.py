#!/usr/bin/env python3
"""Turn EdgeSpeak word timing into cue tables that code-rendered video can consume.

Subcommands:

  build  Read an EdgeSpeak alignment (or word-timestamp transcription) JSON and write
         cues.json: every word and every sentence as {text, start, end}, optionally
         shifted by a lead-in (--lead) and with frame numbers (--fps). Optionally also
         write a browser script (--timing-js) that assigns the same object to
         window["CUES"] for HyperFrames / plain web animation.

  merge  Stitch several alignment JSONs produced from clips of one audio file back
         into a single alignment JSON, adding each clip's offset (chunk.json@12.34).

Standard library only (Python 3.9+). Never invents timing: a segment without words,
a word that ends before it starts, words that go backwards in time, a duration that
ends before the last word, or chunks whose words overlap in time is an error.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

TOOL_NAME = "video_cues.py"
# A word whose text ends with one of these (after trailing closing quotes / brackets) ends a sentence.
SENTENCE_END = tuple("。！？!?….")
CLOSERS = "\"'”’）)》】]」』"
PUNCT = "，。！？、；：,.!?;:…—-–\"'“”‘’（）()《》【】[]「」『』· \t\r\n"
TIME_EPS = 1e-6
BACKWARD_TOLERANCE = 0.02  # seconds; within one alignment, neighbouring word starts may round
OVERLAP_TOLERANCE = 0.001  # seconds; across merged chunks
DURATION_TOLERANCE = 0.001  # seconds; duration vs. last word end


class CueError(Exception):
    """A user-facing error: the input cannot yield trustworthy timing."""


# ---------------------------------------------------------------- numbers


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def finite(value: Any, where: str, allow_negative: bool = False) -> float:
    if not is_number(value):
        raise CueError(f"{where}: missing or non-numeric value {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise CueError(f"{where}: {value!r} is not a finite number")
    if number < 0 and not allow_negative:
        raise CueError(f"{where}: {value!r} must not be negative")
    return number


def finite_arg(text: str) -> float:
    """argparse type: a finite float (rejects nan / inf)."""
    try:
        number = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number")
    if not math.isfinite(number):
        raise argparse.ArgumentTypeError(f"{text!r} is not a finite number")
    return number


# ---------------------------------------------------------------- loading


def load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        raise CueError(f"input not found: {path}")
    except json.JSONDecodeError as exc:
        raise CueError(f"{path} is not valid JSON: {exc}")


def unwrap(doc: Any, path: Path) -> Dict[str, Any]:
    """Accept a bare EdgeSpeak response or an MCP-style wrapper {"result": {...}}."""
    if isinstance(doc, dict) and "segments" not in doc and isinstance(doc.get("result"), dict):
        doc = doc["result"]
    if not isinstance(doc, dict) or not isinstance(doc.get("segments"), list):
        raise CueError(f"{path}: expected an EdgeSpeak JSON with a segments[] array")
    if not doc["segments"]:
        raise CueError(f"{path}: segments[] is empty; there is no timing to convert")
    return doc


def read_duration(doc: Dict[str, Any], path: Path) -> Optional[float]:
    if "duration" not in doc or doc["duration"] is None:
        return None
    return finite(doc["duration"], f"{path}: duration")


def read_words(doc: Dict[str, Any], path: Path, warnings: List[str]) -> List[Dict[str, Any]]:
    """Return segments as [{text, words:[{text,start,end,score?}]}] after validation.

    A non-finite score is kept as None (JSON null) and reported in `warnings`;
    non-finite or negative times are rejected.
    """
    segments = []
    previous_start = -1.0
    bad_scores = 0
    for seg_index, segment in enumerate(doc["segments"]):
        where = f"{path}: segments[{seg_index}]"
        if not isinstance(segment, dict):
            raise CueError(f"{where} is not an object")
        raw_words = segment.get("words")
        if not isinstance(raw_words, list) or not raw_words:
            raise CueError(
                f"{where} has no words[]; word-level timing is required "
                "(run edgespeak-cli align, or transcribe with --timestamps word)"
            )
        words = []
        for word_index, raw in enumerate(raw_words):
            wwhere = f"{where}.words[{word_index}]"
            if not isinstance(raw, dict):
                raise CueError(f"{wwhere} is not an object")
            text = raw.get("word", raw.get("text"))
            if not isinstance(text, str) or not text.strip():
                raise CueError(f"{wwhere} has no word text")
            start = finite(raw.get("start"), f"{wwhere}.start")
            end = finite(raw.get("end"), f"{wwhere}.end")
            if end + TIME_EPS < start:
                raise CueError(f"{wwhere} ends ({end}) before it starts ({start})")
            if start + BACKWARD_TOLERANCE < previous_start:
                raise CueError(
                    f"{wwhere} starts at {start}, before the previous word ({previous_start}); "
                    "word times must move forward"
                )
            previous_start = max(previous_start, start)
            word: Dict[str, Any] = {"text": text.strip(), "start": start, "end": end}
            if "score" in raw and raw["score"] is not None:
                score = raw["score"]
                if is_number(score) and math.isfinite(float(score)):
                    word["score"] = float(score)
                else:
                    word["score"] = None
                    bad_scores += 1
            words.append(word)
        seg_text = segment.get("text")
        segments.append({"text": seg_text if isinstance(seg_text, str) else None, "words": words})
    if bad_scores:
        warnings.append(f"{bad_scores} word score(s) were not finite numbers and were written as null")
    return segments


# ---------------------------------------------------------------- text helpers


def is_cjk(char: str) -> bool:
    code = ord(char)
    return (
        0x3040 <= code <= 0x30FF  # kana
        or 0x3400 <= code <= 0x4DBF
        or 0x4E00 <= code <= 0x9FFF
        or 0xAC00 <= code <= 0xD7AF  # hangul
        or 0xF900 <= code <= 0xFAFF
        or 0xFF00 <= code <= 0xFFEF  # full-width forms
        or 0x3000 <= code <= 0x303F  # CJK punctuation
    )


def join_words(texts: List[str]) -> str:
    """Fallback only: rebuild text when the words cannot be located in the segment text."""
    out = ""
    for text in texts:
        if out and not (is_cjk(out[-1]) or is_cjk(text[0])):
            out += " "
        out += text
    return out


def locate(segment_text: Optional[str], words: List[Dict[str, Any]]) -> Optional[List[Tuple[int, int]]]:
    """Find each word in the segment text, scanning forward. None when any word is missing."""
    if not segment_text:
        return None
    spans = []
    cursor = 0
    for word in words:
        pos = segment_text.find(word["text"], cursor)
        if pos < 0:
            return None
        spans.append((pos, pos + len(word["text"])))
        cursor = pos + len(word["text"])
    return spans


def ends_sentence(text: str) -> bool:
    return text.rstrip(CLOSERS).endswith(SENTENCE_END)


def strip_punct(text: str) -> str:
    stripped = text.strip(PUNCT)
    return stripped if stripped else text


# ---------------------------------------------------------------- build


def r3(value: float) -> float:
    return round(value + 0.0, 3)


def frames(start: float, end: float, fps: float) -> Tuple[int, int]:
    """startFrame = floor(start*fps); endFrame = max(startFrame+1, ceil(end*fps)).

    Computed from unrounded times. endFrame is exclusive, so every cue stays on
    screen for at least one frame.
    """
    start_frame = int(math.floor(start * fps + TIME_EPS))
    end_frame = int(math.ceil(end * fps - TIME_EPS))
    return start_frame, max(start_frame + 1, end_frame)


def build_cues(
    doc: Dict[str, Any],
    path: Path,
    lead: float,
    fps: Optional[float],
    sentence_mode: str,
    strip: bool,
) -> Tuple[Dict[str, Any], List[str]]:
    warnings: List[str] = []
    segments = read_words(doc, path, warnings)
    raw_words: List[Dict[str, Any]] = []  # unrounded, lead applied
    sentences_raw: List[Dict[str, Any]] = []
    fallback_segments = 0

    for segment in segments:
        words = segment["words"]
        spans = locate(segment["text"], words)
        if spans is None:
            fallback_segments += 1

        groups: List[Tuple[int, int]] = []
        if sentence_mode == "punct":
            first = 0
            for index, word in enumerate(words):
                if ends_sentence(word["text"]) or index == len(words) - 1:
                    groups.append((first, index))
                    first = index + 1
        else:
            groups.append((0, len(words) - 1))

        for first, last in groups:
            if spans is not None:
                sentence_text = segment["text"][spans[first][0]:spans[last][1]].strip()
            else:
                sentence_text = join_words([w["text"] for w in words[first:last + 1]])
            base = len(raw_words)
            for word in words[first:last + 1]:
                raw_words.append(
                    {
                        "word": word,
                        "start": word["start"] + lead,
                        "end": word["end"] + lead,
                        "sentence": len(sentences_raw),
                    }
                )
            sentences_raw.append(
                {
                    "text": sentence_text,
                    "start": raw_words[base]["start"],
                    "end": max(w["end"] for w in raw_words[base:]),
                    "firstWord": base,
                    "lastWord": len(raw_words) - 1,
                }
            )

    last_end = max(w["end"] for w in raw_words) - lead
    audio_duration = read_duration(doc, path)
    if audio_duration is None:
        audio_duration = last_end
    elif audio_duration + DURATION_TOLERANCE < last_end:
        raise CueError(
            f"{path}: duration {audio_duration} ends before the last word ({last_end:.3f}s); "
            "the alignment does not belong to this audio or is corrupt"
        )
    total = audio_duration + lead

    words_out = []
    for item in raw_words:
        entry: Dict[str, Any] = {
            "text": strip_punct(item["word"]["text"]) if strip else item["word"]["text"],
            "start": r3(item["start"]),
            "end": r3(item["end"]),
            "sentence": item["sentence"],
        }
        if "score" in item["word"]:
            score = item["word"]["score"]
            entry["score"] = None if score is None else round(score, 4)
        if fps:
            entry["startFrame"], entry["endFrame"] = frames(item["start"], item["end"], fps)
        words_out.append(entry)

    sentences_out = []
    for item in sentences_raw:
        entry = {
            "text": item["text"],
            "start": r3(item["start"]),
            "end": r3(item["end"]),
            "firstWord": item["firstWord"],
            "lastWord": item["lastWord"],
        }
        if fps:
            entry["startFrame"], entry["endFrame"] = frames(item["start"], item["end"], fps)
        sentences_out.append(entry)

    result: Dict[str, Any] = {
        "generator": TOOL_NAME,
        "source": path.name,
        "lead": r3(lead),
        "audioDuration": r3(audio_duration),
        "duration": r3(total),
    }
    if fps:
        result["fps"] = fps
        result["durationInFrames"] = int(math.ceil(total * fps - TIME_EPS))
    result["sentences"] = sentences_out
    result["words"] = words_out
    if fallback_segments:
        warnings.append(
            f"{fallback_segments} segment(s): words not found in the segment text; "
            "sentence text was rebuilt from words"
        )
    return result, warnings


# ---------------------------------------------------------------- merge


def parse_chunk(spec: str) -> Tuple[Path, float]:
    if "@" not in spec:
        raise CueError(f"chunk {spec!r} must be written as path.json@offset_seconds")
    path_text, offset_text = spec.rsplit("@", 1)
    try:
        offset = float(offset_text)
    except ValueError:
        raise CueError(f"chunk {spec!r}: offset {offset_text!r} is not a number")
    return Path(path_text), finite(offset, f"chunk {spec!r}: offset")


def merge_chunks(specs: List[str]) -> Tuple[Dict[str, Any], List[str]]:
    warnings: List[str] = []
    merged_segments: List[Dict[str, Any]] = []
    texts: List[str] = []
    end_of_audio = 0.0
    previous_chunks_end = -1.0  # latest word end among earlier chunks
    for spec in specs:
        path, offset = parse_chunk(spec)
        doc = unwrap(load_json(path), path)
        chunk_last_end = -1.0
        for segment in read_words(doc, path, warnings):
            shifted = []
            for word in segment["words"]:
                start = word["start"] + offset
                end = word["end"] + offset
                if start + OVERLAP_TOLERANCE < previous_chunks_end:
                    raise CueError(
                        f"{spec}: word {word['text']!r} starts at {start:.3f}s, before a word from an "
                        f"earlier chunk ends ({previous_chunks_end:.3f}s); chunks overlap or are out of order"
                    )
                chunk_last_end = max(chunk_last_end, end)
                # Keep full precision: build derives frame numbers from unrounded times.
                item: Dict[str, Any] = {"word": word["text"], "start": round(start, 6), "end": round(end, 6)}
                if "score" in word:
                    item["score"] = word["score"]
                shifted.append(item)
            text = segment["text"] if segment["text"] else join_words([w["word"] for w in shifted])
            merged_segments.append(
                {
                    "id": len(merged_segments),
                    "start": shifted[0]["start"],
                    "end": max(w["end"] for w in shifted),
                    "text": text,
                    "words": shifted,
                }
            )
            texts.append(text)
        duration = read_duration(doc, path)
        if duration is not None and duration + DURATION_TOLERANCE < chunk_last_end - offset:
            raise CueError(f"{spec}: duration {duration} ends before the chunk's last word")
        chunk_end = offset + duration if duration is not None else chunk_last_end
        end_of_audio = max(end_of_audio, chunk_end, chunk_last_end)
        previous_chunks_end = max(previous_chunks_end, chunk_last_end)
    merged = {
        "task": "align",
        "duration": round(end_of_audio, 6),
        "text": join_words(texts),
        "segments": merged_segments,
        "merged_from": specs,
    }
    return merged, warnings


# ---------------------------------------------------------------- output


def check_targets(targets: List[Path], inputs: List[Path], overwrite: bool) -> None:
    seen: Dict[str, Path] = {}
    input_keys = {os.path.realpath(str(p)) for p in inputs}
    for target in targets:
        key = os.path.realpath(str(target))
        if key in seen:
            raise CueError(f"output paths collide: {seen[key]} and {target} are the same file")
        if key in input_keys:
            raise CueError(f"output {target} is also an input; write to a different path")
        seen[key] = target
        if target.exists() and not overwrite:
            raise CueError(f"{target} already exists; pass --overwrite to replace it")


def write_text(path: Path, content: str) -> None:
    """Write via an exclusively created temp file in the same directory, then rename atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def cmd_build(args: argparse.Namespace) -> Dict[str, Any]:
    if args.lead < 0:
        raise CueError("--lead must not be negative")
    if args.fps is not None and args.fps <= 0:
        raise CueError("--fps must be positive")
    if not args.var:
        raise CueError("--var must not be empty")
    source = Path(args.input)
    output = Path(args.output)
    timing_js = Path(args.timing_js) if args.timing_js else None
    check_targets([output] + ([timing_js] if timing_js else []), [source], args.overwrite)

    cues, warnings = build_cues(
        unwrap(load_json(source), source), source, args.lead, args.fps, args.sentences, args.strip_punct
    )
    write_text(output, dump(cues))
    if timing_js:
        header = f"// Generated by {TOOL_NAME} from {source.name}; do not edit by hand.\n"
        body = json.dumps(cues, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        name = json.dumps(args.var, ensure_ascii=False)
        write_text(timing_js, f"{header}window[{name}] = {body};\n")

    return {
        "cues_json": str(output.resolve()),
        "timing_js": str(timing_js.resolve()) if timing_js else None,
        "sentences": len(cues["sentences"]),
        "words": len(cues["words"]),
        "lead": cues["lead"],
        "fps": cues.get("fps"),
        "duration": cues["duration"],
        "durationInFrames": cues.get("durationInFrames"),
        "first_word": cues["words"][0],
        "last_word": cues["words"][-1],
        "warnings": warnings,
    }


def cmd_merge(args: argparse.Namespace) -> Dict[str, Any]:
    output = Path(args.output)
    check_targets([output], [parse_chunk(spec)[0] for spec in args.chunks], args.overwrite)
    merged, warnings = merge_chunks(args.chunks)
    write_text(output, dump(merged))
    return {
        "merged_json": str(output.resolve()),
        "chunks": len(args.chunks),
        "segments": len(merged["segments"]),
        "words": sum(len(s["words"]) for s in merged["segments"]),
        "duration": merged["duration"],
        "warnings": warnings,
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog=TOOL_NAME, description=__doc__.split("\n\n")[0])
    sub = root.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="alignment JSON -> cues.json (+ optional timing.js)")
    build.add_argument("input", help="edgespeak-cli align JSON, or transcribe JSON with word timestamps")
    build.add_argument("-o", "--output", required=True, help="cues.json path")
    build.add_argument("--timing-js", help='also write a script that sets window["<var>"] to the same cues')
    build.add_argument("--var", default="CUES", help="global property name used by --timing-js (default CUES)")
    build.add_argument("--lead", type=finite_arg, default=0.0, help="seconds of lead-in before the narration")
    build.add_argument("--fps", type=finite_arg, help="add startFrame/endFrame (Remotion etc.) at this frame rate")
    build.add_argument(
        "--sentences",
        choices=("punct", "segments"),
        default="punct",
        help="punct (default): split at sentence-ending punctuation and at segment boundaries; "
        "segments: one alignment segment = one sentence",
    )
    build.add_argument("--strip-punct", action="store_true", help="drop punctuation attached to word text")
    build.add_argument("--overwrite", action="store_true", help="replace existing output files")
    build.set_defaults(func=cmd_build)

    merge = sub.add_parser("merge", help="stitch clip-level alignments back onto one timeline")
    merge.add_argument("chunks", nargs="+", help="chunk.json@offset_seconds, in playback order")
    merge.add_argument("-o", "--output", required=True, help="merged alignment JSON path")
    merge.add_argument("--overwrite", action="store_true", help="replace an existing output file")
    merge.set_defaults(func=cmd_merge)
    return root


def main(argv: Optional[List[str]] = None) -> int:
    args = parser().parse_args(argv)
    try:
        report = args.func(args)
    except CueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

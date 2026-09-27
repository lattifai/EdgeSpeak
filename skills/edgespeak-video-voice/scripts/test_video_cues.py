import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("video_cues.py")
SPEC = importlib.util.spec_from_file_location("video_cues", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
video_cues = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(video_cues)


def word(text, start, end, score=0.9):
    return {"word": text, "start": start, "end": end, "score": score}


def two_sentence_single_segment():
    """One segment spanning two sentences, the shape align often returns."""
    text = "你好，世界。今天很好！"
    words = [
        word("你", 0.10, 0.30),
        word("好，", 0.30, 0.55),
        word("世", 0.70, 0.90),
        word("界。", 0.90, 1.20),
        word("今", 1.60, 1.80),
        word("天", 1.80, 2.00),
        word("很", 2.00, 2.20),
        word("好！", 2.20, 2.50),
    ]
    return {
        "task": "align",
        "duration": 2.8,
        "text": text,
        "segments": [{"id": 0, "start": 0.10, "end": 2.50, "text": text, "words": words}],
    }


def english_doc():
    text = "Hello there. Code can speak!"
    words = [
        word("Hello", 0.0, 0.4),
        word("there.", 0.4, 0.8),
        word("Code", 1.0, 1.3),
        word("can", 1.3, 1.5),
        word("speak!", 1.5, 1.9),
    ]
    return {"task": "align", "duration": 2.0, "text": text,
            "segments": [{"id": 0, "start": 0.0, "end": 1.9, "text": text, "words": words}]}


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def put(self, name, doc, raw=None):
        path = self.dir / name
        path.write_text(raw if raw is not None else json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        return path

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = video_cues.main([str(a) for a in argv])
            except SystemExit as exc:  # argparse errors
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def build_ok(self, doc, *extra):
        src = self.put("in.json", doc)
        out = self.dir / "cues.json"
        code, stdout, stderr = self.run_main("build", src, "-o", out, *extra)
        self.assertEqual(code, 0, stderr)
        return json.loads(out.read_text(encoding="utf-8")), json.loads(stdout)

    def build_fails(self, doc, reason, *extra, raw=None):
        src = self.put("in.json", doc, raw=raw)
        out = self.dir / "cues.json"
        code, _, stderr = self.run_main("build", src, "-o", out, *extra)
        self.assertNotEqual(code, 0)
        self.assertIn(reason, stderr)
        self.assertFalse(out.exists(), "a failed build must not write output")
        return stderr


class SentenceSplitTest(Base):
    def test_default_splits_single_segment_at_sentence_punctuation(self):
        cues, _ = self.build_ok(two_sentence_single_segment())
        self.assertEqual([s["text"] for s in cues["sentences"]], ["你好，世界。", "今天很好！"])
        self.assertEqual(cues["sentences"][0]["start"], 0.1)
        self.assertEqual(cues["sentences"][0]["end"], 1.2)
        self.assertEqual(cues["sentences"][1]["start"], 1.6)
        self.assertEqual((cues["sentences"][1]["firstWord"], cues["sentences"][1]["lastWord"]), (4, 7))
        self.assertEqual([w["sentence"] for w in cues["words"]], [0, 0, 0, 0, 1, 1, 1, 1])

    def test_segments_mode_keeps_one_sentence_per_segment(self):
        cues, _ = self.build_ok(two_sentence_single_segment(), "--sentences", "segments")
        self.assertEqual([s["text"] for s in cues["sentences"]], ["你好，世界。今天很好！"])

    def test_english_sentence_text_keeps_original_spacing(self):
        cues, _ = self.build_ok(english_doc())
        self.assertEqual([s["text"] for s in cues["sentences"]], ["Hello there.", "Code can speak!"])

    def test_closing_quote_after_period_still_ends_sentence(self):
        doc = two_sentence_single_segment()
        doc["text"] = doc["segments"][0]["text"] = "你好，世界。”今天很好！"
        doc["segments"][0]["words"][3]["word"] = "界。”"
        cues, _ = self.build_ok(doc)
        self.assertEqual(len(cues["sentences"]), 2)
        self.assertEqual(cues["sentences"][0]["text"], "你好，世界。”")

    def test_strip_punct_only_touches_word_text(self):
        cues, _ = self.build_ok(two_sentence_single_segment(), "--strip-punct")
        self.assertEqual(cues["words"][1]["text"], "好")
        self.assertEqual(cues["sentences"][0]["text"], "你好，世界。")


class LeadAndFrameTest(Base):
    def test_lead_shifts_everything_once(self):
        cues, _ = self.build_ok(two_sentence_single_segment(), "--lead", "0.5")
        self.assertEqual(cues["words"][0]["start"], 0.6)
        self.assertEqual(cues["sentences"][1]["start"], 2.1)
        self.assertEqual(cues["audioDuration"], 2.8)
        self.assertEqual(cues["duration"], 3.3)

    def test_frames_use_unrounded_times(self):
        # 0.0334 s rounds to 0.033 s; at 30 fps the raw time is frame 1.002 -> 1, the rounded one 0.99 -> 0.
        doc = {"duration": 1.0, "segments": [{"text": "a b", "words": [
            word("a", 0.0334, 0.0664), word("b", 0.5, 0.9)]}]}
        cues, _ = self.build_ok(doc, "--fps", "30")
        self.assertEqual(cues["words"][0]["start"], 0.033)
        self.assertEqual(cues["words"][0]["startFrame"], 1)
        self.assertEqual(cues["words"][0]["endFrame"], 2)
        self.assertEqual(cues["durationInFrames"], 30)

    def test_every_word_lasts_at_least_one_frame(self):
        doc = {"duration": 1.0, "segments": [{"text": "a", "words": [word("a", 0.5, 0.5)]}]}
        cues, _ = self.build_ok(doc, "--fps", "25")
        w = cues["words"][0]
        self.assertEqual(w["endFrame"] - w["startFrame"], 1)

    def test_non_finite_lead_and_fps_rejected(self):
        src = self.put("in.json", two_sentence_single_segment())
        for flag, value in (("--lead", "nan"), ("--lead", "inf"), ("--fps", "nan"), ("--fps", "-inf")):
            code, _, stderr = self.run_main("build", src, "-o", self.dir / "c.json", f"{flag}={value}")
            self.assertNotEqual(code, 0, (flag, value))
            self.assertIn("not a finite number", stderr)

    def test_negative_lead_and_zero_fps_rejected(self):
        self.build_fails(two_sentence_single_segment(), "--lead must not be negative", "--lead", "-1")
        self.build_fails(two_sentence_single_segment(), "--fps must be positive", "--fps", "0")


class ValidationTest(Base):
    def test_segment_without_words_rejected(self):
        doc = two_sentence_single_segment()
        doc["segments"][0]["words"] = []
        self.build_fails(doc, "has no words[]")

    def test_backwards_time_rejected(self):
        doc = two_sentence_single_segment()
        doc["segments"][0]["words"][4]["start"] = 0.2
        self.build_fails(doc, "word times must move forward")

    def test_end_before_start_rejected(self):
        doc = two_sentence_single_segment()
        doc["segments"][0]["words"][2]["end"] = 0.5
        self.build_fails(doc, "before it starts")

    def test_duration_before_last_word_rejected(self):
        doc = two_sentence_single_segment()
        doc["duration"] = 2.0
        self.build_fails(doc, "ends before the last word")

    def test_duration_equal_to_last_word_accepted(self):
        doc = two_sentence_single_segment()
        doc["duration"] = 2.5
        cues, _ = self.build_ok(doc)
        self.assertEqual(cues["audioDuration"], 2.5)

    def test_missing_duration_falls_back_to_last_word(self):
        doc = two_sentence_single_segment()
        del doc["duration"]
        cues, _ = self.build_ok(doc)
        self.assertEqual(cues["audioDuration"], 2.5)

    def test_non_finite_times_and_duration_rejected(self):
        raw = json.dumps(two_sentence_single_segment()).replace('"duration": 2.8', '"duration": NaN')
        self.build_fails(None, "not a finite number", raw=raw)
        raw = json.dumps(two_sentence_single_segment()).replace('"start": 0.7', '"start": Infinity')
        self.build_fails(None, "not a finite number", raw=raw)

    def test_non_finite_score_written_as_null_with_warning(self):
        raw = json.dumps(two_sentence_single_segment()).replace('"score": 0.9}', '"score": NaN}', 1)
        src = self.put("in.json", None, raw=raw)
        out = self.dir / "cues.json"
        code, stdout, stderr = self.run_main("build", src, "-o", out)
        self.assertEqual(code, 0, stderr)
        cues = json.loads(out.read_text(encoding="utf-8"))  # strict: output has no NaN
        self.assertIsNone(cues["words"][0]["score"])
        self.assertIn("NaN", raw)
        self.assertNotIn("NaN", out.read_text(encoding="utf-8"))
        self.assertTrue(any("written as null" in w for w in json.loads(stdout)["warnings"]))


class OutputSafetyTest(Base):
    def test_refuses_to_overwrite_without_flag(self):
        src = self.put("in.json", two_sentence_single_segment())
        out = self.dir / "cues.json"
        out.write_text("keep", encoding="utf-8")
        code, _, stderr = self.run_main("build", src, "-o", out)
        self.assertNotEqual(code, 0)
        self.assertIn("already exists", stderr)
        self.assertEqual(out.read_text(encoding="utf-8"), "keep")
        code, _, stderr = self.run_main("build", src, "-o", out, "--overwrite")
        self.assertEqual(code, 0, stderr)

    def test_output_and_timing_js_same_path_rejected(self):
        src = self.put("in.json", two_sentence_single_segment())
        out = self.dir / "same.json"
        code, _, stderr = self.run_main("build", src, "-o", out, "--timing-js", self.dir / "." / "same.json")
        self.assertNotEqual(code, 0)
        self.assertIn("output paths collide", stderr)
        self.assertFalse(out.exists())

    def test_output_equal_to_input_rejected(self):
        src = self.put("in.json", two_sentence_single_segment())
        before = src.read_text(encoding="utf-8")
        code, _, stderr = self.run_main("build", src, "-o", src, "--overwrite")
        self.assertNotEqual(code, 0)
        self.assertIn("also an input", stderr)
        self.assertEqual(src.read_text(encoding="utf-8"), before)

    def test_existing_dot_tmp_sibling_is_not_clobbered(self):
        src = self.put("in.json", two_sentence_single_segment())
        out = self.dir / "cues.json"
        sibling = self.dir / "cues.json.tmp"
        sibling.write_text("user file", encoding="utf-8")
        code, _, stderr = self.run_main("build", src, "-o", out)
        self.assertEqual(code, 0, stderr)
        self.assertEqual(sibling.read_text(encoding="utf-8"), "user file")
        leftovers = [p.name for p in self.dir.iterdir() if p.name.endswith(".tmp") and p != sibling]
        self.assertEqual(leftovers, [])

    def test_timing_js_uses_quoted_property_and_parses(self):
        src = self.put("in.json", two_sentence_single_segment())
        js = self.dir / "timing.js"
        code, _, stderr = self.run_main("build", src, "-o", self.dir / "c.json", "--timing-js", js,
                                        "--var", 'my-"cues"</script>')
        self.assertEqual(code, 0, stderr)
        lines = js.read_text(encoding="utf-8").splitlines()
        self.assertTrue(lines[0].startswith("// Generated by video_cues.py"))
        prefix = 'window["my-\\"cues\\"</script>"] = '
        self.assertTrue(lines[1].startswith(prefix), lines[1][:60])
        payload = json.loads(lines[1][len(prefix):].rstrip(";"))
        self.assertEqual(len(payload["sentences"]), 2)

    def test_empty_var_rejected(self):
        self.build_fails(two_sentence_single_segment(), "--var must not be empty", "--timing-js",
                         str(self.dir / "t.js"), "--var", "")


class MergeTest(Base):
    def split(self, doc, cut_word, offset):
        words = doc["segments"][0]["words"]
        a = {"duration": offset, "segments": [{"text": None, "words": words[:cut_word]}]}
        b_words = [dict(w, start=round(w["start"] - offset, 6), end=round(w["end"] - offset, 6))
                   for w in words[cut_word:]]
        b = {"duration": round(doc["duration"] - offset, 6), "segments": [{"text": None, "words": b_words}]}
        return self.put("a.json", a), self.put("b.json", b)

    def test_merge_keeps_sub_millisecond_precision_for_frames(self):
        # Merge must not round to ms: 0.0334 s is frame 1 at 30 fps, 0.033 s would be frame 0.
        a = self.put("a.json", {"duration": 0.5, "segments": [{"text": None, "words": [word("a", 0.0334, 0.2)]}]})
        b = self.put("b.json", {"duration": 0.5, "segments": [{"text": None, "words": [word("b", 0.1, 0.3)]}]})
        merged = self.dir / "merged.json"
        code, _, stderr = self.run_main("merge", f"{a}@0", f"{b}@0.5", "-o", merged)
        self.assertEqual(code, 0, stderr)
        data = json.loads(merged.read_text(encoding="utf-8"))
        self.assertEqual(data["segments"][0]["words"][0]["start"], 0.0334)
        src = self.dir / "in.json"
        src.write_text(merged.read_text(encoding="utf-8"), encoding="utf-8")
        code, _, stderr = self.run_main("build", src, "-o", self.dir / "cues.json", "--fps", "30")
        self.assertEqual(code, 0, stderr)
        cues = json.loads((self.dir / "cues.json").read_text(encoding="utf-8"))
        self.assertEqual(cues["words"][0]["startFrame"], 1)

    def test_round_trip_matches_original_timing(self):
        doc = two_sentence_single_segment()
        a, b = self.split(doc, 4, 1.4)
        merged = self.dir / "merged.json"
        code, _, stderr = self.run_main("merge", f"{a}@0", f"{b}@1.4", "-o", merged)
        self.assertEqual(code, 0, stderr)
        data = json.loads(merged.read_text(encoding="utf-8"))
        got = [(w["word"], w["start"], w["end"]) for s in data["segments"] for w in s["words"]]
        want = [(w["word"], w["start"], w["end"]) for w in doc["segments"][0]["words"]]
        self.assertEqual(got, want)
        self.assertEqual(data["duration"], 2.8)
        # and the merged file builds into the same word cues as the original
        original, _ = self.build_ok(doc)
        (self.dir / "cues.json").unlink()
        src = self.dir / "in.json"
        src.write_text(merged.read_text(encoding="utf-8"), encoding="utf-8")
        code, _, stderr = self.run_main("build", src, "-o", self.dir / "cues.json")
        self.assertEqual(code, 0, stderr)
        rebuilt = json.loads((self.dir / "cues.json").read_text(encoding="utf-8"))
        strip = lambda ws: [(w["start"], w["end"], w["text"]) for w in ws]
        self.assertEqual(strip(rebuilt["words"]), strip(original["words"]))

    def test_overlapping_interval_rejected(self):
        # b's first word is at local 0.2 s; offset 0.95 puts it at 1.15 s, inside a's last word (0.90-1.20).
        # Start times alone still move forward (1.15 > 0.90), so only an interval check catches this.
        doc = two_sentence_single_segment()
        a, b = self.split(doc, 4, 1.4)
        code, _, stderr = self.run_main("merge", f"{a}@0", f"{b}@0.95", "-o", self.dir / "m.json")
        self.assertNotEqual(code, 0)
        self.assertIn("chunks overlap", stderr)
        self.assertFalse((self.dir / "m.json").exists())

    def test_touching_within_one_millisecond_accepted(self):
        doc = two_sentence_single_segment()
        a, b = self.split(doc, 4, 1.4)
        # b's first word is at local 0.2; offset 0.9995 puts it at 1.1995, 0.5 ms before a ends (1.2).
        code, _, stderr = self.run_main("merge", f"{a}@0", f"{b}@0.9995", "-o", self.dir / "m.json")
        self.assertEqual(code, 0, stderr)

    def test_out_of_order_rejected(self):
        doc = two_sentence_single_segment()
        a, b = self.split(doc, 4, 1.4)
        code, _, stderr = self.run_main("merge", f"{b}@1.4", f"{a}@0", "-o", self.dir / "m.json")
        self.assertNotEqual(code, 0)
        self.assertIn("chunks overlap or are out of order", stderr)

    def test_bad_offsets_rejected(self):
        doc = two_sentence_single_segment()
        a, _ = self.split(doc, 4, 1.4)
        for offset, reason in (("nan", "not a finite number"), ("inf", "not a finite number"),
                               ("-1", "must not be negative"), ("x", "is not a number")):
            code, _, stderr = self.run_main("merge", f"{a}@{offset}", "-o", self.dir / "m.json")
            self.assertNotEqual(code, 0, offset)
            self.assertIn(reason, stderr)

    def test_chunk_duration_before_last_word_rejected(self):
        a = self.put("a.json", {"duration": 0.5, "segments": [{"text": "x", "words": [word("x", 0.2, 0.9)]}]})
        code, _, stderr = self.run_main("merge", f"{a}@0", "-o", self.dir / "m.json")
        self.assertNotEqual(code, 0)
        self.assertIn("ends before the chunk's last word", stderr)


class CliTest(Base):
    def test_script_runs_as_a_program(self):
        src = self.put("in.json", two_sentence_single_segment())
        proc = subprocess.run([sys.executable, str(SCRIPT), "build", str(src), "-o", str(self.dir / "c.json"),
                               "--fps", "30"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        report = json.loads(proc.stdout)
        self.assertEqual((report["sentences"], report["words"]), (2, 8))


if __name__ == "__main__":
    unittest.main()

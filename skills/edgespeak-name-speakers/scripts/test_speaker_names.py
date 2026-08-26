import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("speaker_names.py")
SPEC = importlib.util.spec_from_file_location("speaker_names", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
speaker_names = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(speaker_names)


class SpeakerNamesTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)
        self.source = self.directory / "transcript.json"
        self.data = {
            "text": "Welcome, June. June founded the lab. My name is Joon.",
            "segments": [
                {
                    "id": "seg_0",
                    "start": 0.0,
                    "end": 1.0,
                    "text": "Welcome to the show with June.",
                    "speaker": "speaker_1",
                },
                {
                    "id": "seg_1",
                    "start": 1.0,
                    "end": 2.0,
                    "text": "June founded the lab.",
                    "speaker": "speaker_1",
                },
                {
                    "id": "seg_2",
                    "start": 2.0,
                    "end": 3.5,
                    "text": "My name is Joon.",
                    "speaker": "speaker_0",
                },
                {
                    "id": "seg_3",
                    "start": 3.5,
                    "end": 4.0,
                    "text": "Thanks.",
                    "speaker": None,
                },
            ],
            "usage": {"type": "duration", "seconds": 4.0},
        }
        self.source.write_text(json.dumps(self.data), encoding="utf-8")

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_inspection_summarizes_speakers_and_clues(self):
        loaded = speaker_names.load_transcript(self.source)
        result = speaker_names.build_inspection(self.source, loaded, 6, 30)
        self.assertEqual(set(result["speakers"]), {"speaker_0", "speaker_1"})
        self.assertEqual(result["unattributed_segment_count"], 1)
        self.assertEqual(result["identity_clues"][0]["segment"]["speaker"], "speaker_1")
        self.assertEqual(result["identity_clues"][1]["segment"]["speaker"], "speaker_0")
        self.assertEqual(result["speakers"]["speaker_0"]["samples"][0]["index"], 2)
        self.assertEqual(result["speakers"]["speaker_0"]["first_segment_index"], 2)
        self.assertEqual(result["speakers"]["speaker_0"]["turn_count"], 1)
        self.assertIn("question_like_rate", result["speakers"]["speaker_1"])
        self.assertFalse(speaker_names.is_identity_clue("I am somebody who likes science fiction."))

    def test_candidate_evidence_uses_aliases_and_adjacent_speaker_turns(self):
        loaded = speaker_names.load_transcript(self.source)
        candidates = [
            {
                "name": "Joon Sung Park",
                "aliases": ["June"],
                "role": "guest",
            },
            {"name": "Sonya Huang", "aliases": [], "role": "host"},
        ]
        result = speaker_names.build_inspection(
            self.source, loaded, 6, 30, candidates, 12
        )
        joon = result["candidate_evidence"][0]
        sonya = result["candidate_evidence"][1]
        self.assertEqual(joon["mentions"][0]["matched_terms"], ["June"])
        self.assertEqual(
            joon["mentions"][0]["next_other_speaker"]["speaker"], "speaker_0"
        )
        self.assertEqual(joon["mentions"][2]["segment"]["speaker"], "speaker_0")
        self.assertEqual(
            joon["mentions"][0]["match_details"][0]["strength"], "strong"
        )
        self.assertTrue(
            joon["mentions"][2]["match_details"][0]["self_introduction"]
        )
        self.assertFalse(
            speaker_names.is_self_introduction("I am speaking with Joon.", "Joon")
        )
        self.assertEqual(
            joon["match_summary"],
            {"strong": 3, "medium": 0, "weak": 0, "total": 3},
        )
        self.assertEqual(joon["speaker_lead"]["speaker"], "speaker_0")
        self.assertEqual(joon["speaker_lead"]["score"], 15)
        self.assertEqual(joon["speaker_lead"]["event_count"], 2)
        self.assertEqual(result["speaker_leads"][0]["candidate"], "Joon Sung Park")
        self.assertEqual(result["speaker_leads"][0]["speaker"], "speaker_0")
        self.assertEqual(sonya["mentions"], [])
        self.assertIn("no_text_matches", sonya["risks"])

        no_mentions = speaker_names.build_inspection(
            self.source, loaded, 6, 30, candidates, 0
        )
        self.assertEqual(no_mentions["candidate_evidence"][0]["mentions"], [])
        self.assertEqual(
            no_mentions["candidate_evidence"][0]["speaker_lead"]["speaker"],
            "speaker_0",
        )

    def test_candidate_evidence_ignores_shared_name_parts_and_flags_same_role(self):
        segments = [
            {
                "speaker": "speaker_0",
                "text": "David, what do you think?",
                "start": 0.0,
                "end": 1.0,
            },
            {
                "speaker": "speaker_1",
                "text": "I agree.",
                "start": 1.0,
                "end": 2.0,
            },
        ]
        candidates = [
            {"name": "David Friedberg", "aliases": [], "role": "host"},
            {"name": "David Sacks", "aliases": [], "role": "host"},
        ]

        evidence = speaker_names.build_candidate_evidence(segments, candidates, 12)

        for candidate, peer in zip(
            evidence, ["David Sacks", "David Friedberg"], strict=True
        ):
            self.assertEqual(candidate["ignored_shared_terms"], ["David"])
            self.assertNotIn("David", candidate["search_terms"])
            self.assertEqual(candidate["same_role_candidates"], [peer])
            self.assertEqual(candidate["mentions"], [])
            self.assertIn("shared_roster_name_parts", candidate["risks"])
            self.assertIn("same_role_candidates", candidate["risks"])

    def test_candidate_evidence_marks_unshared_name_part_as_weak(self):
        segments = [
            {
                "speaker": "speaker_0",
                "text": "David Sacks is not here.",
                "start": 0.0,
                "end": 1.0,
            }
        ]
        candidates = [{"name": "David Friedberg", "aliases": []}]

        evidence = speaker_names.build_candidate_evidence(segments, candidates, 12)[0]

        self.assertEqual(evidence["mentions"][0]["matched_terms"], ["David"])
        self.assertEqual(
            evidence["mentions"][0]["match_details"][0]["strength"], "weak"
        )
        self.assertEqual(
            evidence["match_summary"],
            {"strong": 0, "medium": 0, "weak": 1, "total": 1},
        )
        self.assertIn("partial_name_only", evidence["risks"])
        self.assertIn("weak_name_parts_only", evidence["risks"])

    def test_candidate_evidence_flags_family_name_only(self):
        segments = [
            {
                "speaker": "speaker_0",
                "text": "We met in the park yesterday.",
                "start": 0.0,
                "end": 1.0,
            }
        ]
        candidates = [{"name": "Joon Sung Park", "aliases": []}]

        evidence = speaker_names.build_candidate_evidence(segments, candidates, 12)[0]

        self.assertEqual(
            evidence["match_summary"],
            {"strong": 0, "medium": 1, "weak": 0, "total": 1},
        )
        self.assertIn("partial_name_only", evidence["risks"])
        self.assertNotIn("weak_name_parts_only", evidence["risks"])

    def test_speaker_lead_uses_opening_address_and_blocks_collisions(self):
        segments = [
            {
                "speaker": "speaker_0",
                "text": "Sonya, what do you think?",
                "start": 0.0,
                "end": 1.0,
            },
            {
                "speaker": "speaker_1",
                "text": "Here is my answer.",
                "start": 1.0,
                "end": 2.0,
            },
        ]
        candidate = {"name": "Sonya Huang", "aliases": ["Sonya"]}

        evidence = speaker_names.build_candidate_evidence(segments, [candidate], 12)[0]

        self.assertEqual(evidence["speaker_lead"]["speaker"], "speaker_1")
        self.assertEqual(
            evidence["speaker_lead"]["events"][0]["type"],
            "opening_address_response",
        )

        collision = speaker_names.build_candidate_evidence(
            segments,
            [candidate, {"name": "Sonia Park", "aliases": ["Sonya"]}],
            12,
        )
        self.assertIsNone(collision[0]["speaker_lead"]["speaker"])
        self.assertIsNone(collision[1]["speaker_lead"]["speaker"])
        self.assertEqual(collision[0]["speaker_lead"]["blocked_speaker"], "speaker_1")
        self.assertIn("speaker_lead_collision", collision[0]["risks"])

    def test_speaker_lead_requires_repeated_named_questions(self):
        one_question = [
            {
                "speaker": "speaker_0",
                "text": "What do you think, Sonya?",
                "start": 0.0,
                "end": 1.0,
            },
            {
                "speaker": "speaker_1",
                "text": "The first answer.",
                "start": 1.0,
                "end": 2.0,
            },
        ]
        candidate = {"name": "Sonya Huang", "aliases": ["Sonya"]}

        first = speaker_names.build_candidate_evidence(
            one_question, [candidate], 12
        )[0]

        self.assertIsNone(first["speaker_lead"]["speaker"])
        self.assertEqual(first["speaker_lead"]["ranked_scores"][0]["score"], 3)
        self.assertFalse(
            speaker_names.is_named_question(
                "What do you think about Bill's fund?", "Bill"
            )
        )

        repeated = [
            *one_question,
            {
                "speaker": "speaker_0",
                "text": "How would you approach it, Sonya?",
                "start": 2.0,
                "end": 3.0,
            },
            {
                "speaker": "speaker_1",
                "text": "The second answer.",
                "start": 3.0,
                "end": 4.0,
            },
        ]

        second = speaker_names.build_candidate_evidence(repeated, [candidate], 12)[0]

        self.assertEqual(second["speaker_lead"]["speaker"], "speaker_1")
        self.assertEqual(second["speaker_lead"]["score"], 6)
        self.assertEqual(
            second["speaker_lead"]["events"][0]["type"],
            "named_question_response",
        )

    def test_load_roster_normalizes_metadata(self):
        roster = self.directory / "roster.json"
        roster.write_text(
            json.dumps(
                {
                    "speakers": [
                        {
                            "name": " Joon Sung Park ",
                            "role": " guest ",
                            "affiliation": " Stanford ",
                            "aliases": [" June "],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        self.assertEqual(
            speaker_names.load_roster(roster),
            [
                {
                    "name": "Joon Sung Park",
                    "role": "guest",
                    "affiliation": "Stanford",
                    "aliases": ["June"],
                }
            ],
        )

    def test_apply_preserves_ids_and_unmapped_labels(self):
        destination = self.directory / "named.json"
        loaded = speaker_names.load_transcript(self.source)
        result = speaker_names.apply_mapping(
            self.source, destination, loaded, {"speaker_0": "Joon Sung Park"}
        )
        named = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(named["segments"][2]["speaker"], "Joon Sung Park")
        self.assertEqual(named["segments"][2]["speaker_id"], "speaker_0")
        self.assertEqual(named["segments"][0]["speaker"], "speaker_1")
        self.assertEqual(named["segments"][0]["speaker_id"], "speaker_1")
        self.assertNotIn("speaker_id", named["segments"][3])
        self.assertEqual(result["unresolved_speakers"], ["speaker_1"])
        self.assertEqual(named["text"], self.data["text"])
        self.assertEqual(named["usage"], self.data["usage"])

    def test_apply_rejects_unknown_label_and_overwrite(self):
        loaded = speaker_names.load_transcript(self.source)
        with self.assertRaisesRegex(speaker_names.TranscriptError, "not present"):
            speaker_names.apply_mapping(
                self.source,
                self.directory / "unknown.json",
                loaded,
                {"speaker_9": "Nobody"},
            )

        destination = self.directory / "existing.json"
        destination.write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(speaker_names.TranscriptError, "already exists"):
            speaker_names.apply_mapping(
                self.source, destination, loaded, {"speaker_0": "Joon Sung Park"}
            )
        self.assertEqual(destination.read_text(encoding="utf-8"), "keep")

    def test_load_requires_diarization(self):
        source = self.directory / "plain.json"
        source.write_text(json.dumps({"segments": [{"text": "hello"}]}), encoding="utf-8")
        with self.assertRaisesRegex(speaker_names.TranscriptError, "--diarize"):
            speaker_names.load_transcript(source)


if __name__ == "__main__":
    unittest.main()

"""Opt-in text correctness tests; requires a locally authorized CLI runtime.

Set EDGESPEAK_TEST_TEXT_CLI to the matching CLI. These small text calls consume
its account's text allowance. No models are downloaded/loaded by catalog queries.
"""
import json
import os
import subprocess
import unittest
from unittest.mock import patch

from edgespeak import EdgeSpeak, slice_utf8

CLI = os.environ.get("EDGESPEAK_TEST_TEXT_CLI")


@unittest.skipUnless(CLI, "set EDGESPEAK_TEST_TEXT_CLI for authorized real text calls")
class RealTextGatewayTests(unittest.TestCase):
    def setUp(self):
        resolver = patch("edgespeak._bootstrap.ensure_cli", return_value=CLI)
        resolver.start()
        self.addCleanup(resolver.stop)
        self.client = EdgeSpeak(device="cpu")
        self.addCleanup(self.client.close)

    def test_tn_itn_accuracy_and_original_utf8_spans(self):
        for text, language, mode, expected in (
                ("The fee is $25.", "en", "tn", "The fee is twenty five dollars."),
                ("The fee is twenty five dollars.", "en", "itn", "The fee is $25."),
                ("收费$25。", "zh", "tn", "收费二十五美元。")):
            with self.subTest(language=language, mode=mode):
                result = self.client.text_normalizations(text, language=language, mode=mode, top_k=1)
                self.assertEqual(result["text"], text)
                self.assertEqual(result["mode"], mode)
                self.assertEqual(result["alternatives"][0]["text"], expected)
                spans = result["alternatives"][0]["spans"]
                self.assertTrue(spans)
                for span in spans:
                    self.assertEqual(slice_utf8(text, span["start_byte"], span["end_byte"]), span["source"])

    def test_read_only_queries_through_real_cli(self):
        self.assertEqual(self.client.health()["status"], "ok")
        self.assertIsInstance(self.client.models()["data"], list)
        self.assertIsInstance(self.client.models_running()["data"], list)
        self.assertIsInstance(self.client.models_downloads()["data"], list)
        summary = self.client.usage()
        self.assertIn("remaining", summary)
        self.assertIn("used", summary)

    def test_cli_normalize_uses_existing_gateway(self):
        env = {**os.environ, "EDGESPEAK_BASE_URL": str(self.client._http.base_url),
               "EDGESPEAK_API_KEY": self.client._http.headers["authorization"][7:]}
        result = subprocess.run([CLI, "normalize", "--text", "The fee is $25.",
                                 "--language", "en", "--top-k", "1", "--classes", "money"],
                                env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, "CLI normalize returned a nonzero exit status")
        body = json.loads(result.stdout)
        self.assertEqual(body["alternatives"][0]["text"], "The fee is twenty five dollars.")

"""Real text/model correctness tests; calls use existing local authorization."""
import json
import os
import subprocess
import unittest
from unittest.mock import patch

from edgespeak import EdgeSpeak, slice_utf8

from runtime_cli import resolve_cli


class RealTextGatewayTests(unittest.TestCase):
    def setUp(self):
        resolver = patch("edgespeak._bootstrap.ensure_cli", return_value=resolve_cli())
        resolver.start()
        self.addCleanup(resolver.stop)
        self.client = EdgeSpeak(device="cpu", max_concurrency=1)
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
        result = subprocess.run([resolve_cli(), "normalize", "--text", "The fee is $25.",
                                 "--language", "en", "--top-k", "1", "--classes", "money"],
                                env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, "CLI normalize returned a nonzero exit status")
        body = json.loads(result.stdout)
        self.assertEqual(body["alternatives"][0]["text"], "The fee is twenty five dollars.")


class RealGenerationGatewayTests(unittest.TestCase):
    def test_model_lifecycle_tokenize_and_three_generation_protocols(self):
        cli = resolve_cli()
        model = "Qwen/Qwen3-0.6B"
        prompt = "What is 2+2? Reply with only the digit 4. /no_think"
        messages = [{"role": "user", "content": prompt}]
        with patch("edgespeak._bootstrap.ensure_cli", return_value=cli):
            with EdgeSpeak(device="cpu", timeout=90, max_concurrency=1) as client:
                self.assertTrue(client.models_load(model)["success"])
                try:
                    tokens = client.tokenize("Hello world", model=model)
                    ids = tokens.get("tokens") if isinstance(tokens, dict) else tokens
                    self.assertIsInstance(ids, list)
                    self.assertTrue(ids)
                    self.assertTrue(all(type(token) is int and token >= 0 for token in ids))
                    env = {**os.environ, "EDGESPEAK_BASE_URL": str(client._http.base_url),
                           "EDGESPEAK_API_KEY": client._http.headers["authorization"][7:]}
                    result = subprocess.run([cli, "tokenize", "--content", "Hello world", "--model", model],
                                            env=env, capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode, 0, "CLI tokenize failed")
                    self.assertEqual(json.loads(result.stdout), tokens)
                    for streaming in (False, True):
                        for protocol in ("chat", "responses", "messages"):
                            with self.subTest(protocol=protocol, stream=streaming):
                                common = dict(model=model, temperature=0, stream=streaming)
                                if protocol == "chat":
                                    value = client.chat_completions(messages, max_tokens=96,
                                        options={"chat_template_kwargs": {"enable_thinking": False}}, **common)
                                elif protocol == "responses":
                                    value = client.responses(prompt, max_output_tokens=96, **common)
                                else:
                                    value = client.messages(messages, max_tokens=96, **common)
                                if streaming:
                                    with value:
                                        events = list(value)
                                    if protocol == "chat":
                                        text = "".join(choice.get("delta", {}).get("content") or ""
                                                       for event in events for choice in event.get("choices", []))
                                        self.assertTrue(any(choice.get("finish_reason") == "stop"
                                                            for event in events for choice in event.get("choices", [])))
                                    elif protocol == "responses":
                                        text = "".join(event["delta"] for event in events
                                                       if event.get("type") == "response.output_text.delta")
                                        self.assertEqual(events[-1]["type"], "response.completed")
                                    else:
                                        text = "".join(event["delta"].get("text", "") for event in events
                                                       if event.get("type") == "content_block_delta")
                                        self.assertEqual(events[-1]["type"], "message_stop")
                                elif protocol == "chat":
                                    text = value["choices"][0]["message"]["content"]
                                elif protocol == "responses":
                                    self.assertEqual(value["status"], "completed")
                                    text = "".join(part.get("text", "") for item in value["output"]
                                                   for part in item.get("content", []))
                                else:
                                    text = "".join(part.get("text", "") for part in value["content"])
                                self.assertEqual(text.strip(), "4")
                finally:
                    self.assertTrue(client.models_unload(model)["success"])

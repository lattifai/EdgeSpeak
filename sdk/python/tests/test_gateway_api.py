"""Request contracts for gateway capabilities; no model downloads or account calls."""
import json
import os
import unittest
from unittest.mock import patch

import httpx
from edgespeak import EdgeSpeak, EdgeSpeakError, slice_utf8


class GatewayApiTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.response = httpx.Response(200, json={"object": "list", "data": []})
        # Construct the real SDK client, swapping only httpx's transport.
        original = httpx.Client
        def factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(self.handle)
            return original(*args, **kwargs)
        with patch.dict(os.environ, {"EDGESPEAK_API_KEY": "not-an-account-key"}), patch("edgespeak._client.httpx.Client", side_effect=factory):
            self.client = EdgeSpeak(base_url="http://localhost:1118/v1", gateway_key="gateway-only")
        self.addCleanup(self.client.close)

    def handle(self, request):
        self.requests.append(request)
        return self.response

    def test_read_routes_do_not_start_lifecycle_operations(self):
        for method, path in ((self.client.models, "models"),
                (self.client.models_running, "models/running"),
                (self.client.models_downloads, "models/downloads"),
                (self.client.health, "health")):
            self.assertEqual(method(), {"object": "list", "data": []})
            request = self.requests[-1]
            self.assertEqual((request.method, request.url.path), ("GET", "/v1/" + path))
            self.assertEqual(request.headers["authorization"], "Bearer gateway-only")
            self.assertFalse(request.content)
        self.assertEqual(len(self.requests), 4)

    def test_usage_query_contract(self):
        self.response = httpx.Response(200, json={"remaining": None})
        self.assertIsNone(self.client.usage(refresh=True)["remaining"])
        self.assertEqual(dict(self.requests[-1].url.params), {"refresh": "true"})
        before = len(self.requests)
        with self.assertRaises(ValueError):
            self.client.usage(refresh=1)
        self.assertEqual(len(self.requests), before)

    def test_model_mutations_encode_id_in_body_not_url(self):
        for method, path in ((self.client.models_load, "models/load"),
                (self.client.models_unload, "models/unload"),
                (self.client.models_download, "models/download"),
                (self.client.models_download_cancel, "models/download/cancel")):
            self.response = httpx.Response(202, json={"model": "Vendor/Model", "state": "queued"})
            self.assertEqual(method("Vendor/Model")["state"], "queued")
            request = self.requests[-1]
            self.assertEqual((request.method, request.url.path), ("POST", "/v1/" + path))
            self.assertEqual(json.loads(request.content), {"model": "Vendor/Model"})
            for invalid in ("", " ", "x" * 513, 1):
                with self.assertRaises(ValueError):
                    method(invalid)
        self.assertEqual(len(self.requests), 4)

    def test_normalization_preserves_original_candidates_and_multibyte_offsets(self):
        result = {"task": "normalize", "model": "EdgeSpeak/Skylark", "mode": "tn", "language": "zh", "text": "收费$25。",
                  "alternatives": [{"rank": 0, "text": "收费二十五美元。", "spans": [{"start_byte": 6, "end_byte": 9, "class": "money", "source": "$25", "output": "二十五美元"}]}]}
        self.response = httpx.Response(200, json=result)
        actual = self.client.text_normalizations("收费$25。", language="zh", classes=["money"], top_k=1)
        self.assertEqual(actual, result)
        span = actual["alternatives"][0]["spans"][0]
        self.assertEqual(slice_utf8(actual["text"], span["start_byte"], span["end_byte"]), "$25")
        self.assertEqual(json.loads(self.requests[-1].content), {"text": "收费$25。", "language": "zh", "mode": "tn", "classes": ["money"], "top_k": 1})
        self.assertEqual(self.requests[-1].url.path, "/v1/text/normalizations")
        self.client.text_normalizations("twenty five dollars", language="en", mode="itn")
        self.assertNotIn("top_k", json.loads(self.requests[-1].content))
        self.assertEqual(json.loads(self.requests[-1].content)["mode"], "itn")

    def test_normalization_invalid_options_do_not_send_requests(self):
        for options in ({"text": ""}, {"text": "字" * (256 * 1024 // 3 + 1)},
                {"language": ""}, {"language": None}, {"mode": "normalize"},
                {"top_k": True}, {"top_k": 0}, {"top_k": 17},
                {"classes": "money"}, {"classes": []}, {"classes": ["unknown"]}):
            with self.subTest(options=list(options)), self.assertRaises(ValueError):
                self.client.text_normalizations(**{"text": "25", "language": "en", **options})
        self.assertFalse(self.requests)

    def test_utf8_slice_rejects_bounds_and_partial_characters(self):
        for start, end in ((-1, 2), (0, 8), (3, 2), (True, 2), (1, 1), (0, 1)):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                slice_utf8("字a", start, end)
        self.assertEqual(slice_utf8("字a", 3, 4), "a")
        self.assertEqual(slice_utf8("字a", 3, 3), "")

    def test_gateway_errors_preserve_model_code(self):
        self.response = httpx.Response(404, json={"error": {"code": "model_not_found", "message": "server-secret"}})
        with self.assertRaises(EdgeSpeakError) as error:
            self.client.models_load("absent")
        self.assertEqual(error.exception.code, "model_not_found")
        self.assertNotIn("server-secret", str(error.exception))
        self.assertEqual(len(self.requests), 1)

    def test_held_speech_apis_are_not_exposed(self):
        for name in ("audio_speech", "audio_voices", "audio_voices_create", "audio_voices_delete", "audio_speech_examples"):
            self.assertFalse(hasattr(self.client, name), name)

    def test_old_gateway_missing_route_is_explicit(self):
        self.response = httpx.Response(404, content=b"Not Found")
        with self.assertRaises(EdgeSpeakError) as error:
            self.client.text_normalizations("25", language="en")
        self.assertEqual(error.exception.code, "unsupported_gateway_capability")
        self.assertIn("gateway runtime", str(error.exception))

    def test_new_and_released_404_error_contracts_are_separate(self):
        self.response = httpx.Response(404, json={"error": {"code": None, "type": "not_found_error"}})
        with self.assertRaises(EdgeSpeakError) as error:
            self.client.models_load("absent")
        self.assertEqual(error.exception.code, "not_found_error")
        self.response = httpx.Response(404, content=b"missing route")
        with self.assertRaises(EdgeSpeakError) as error:
            self.client.segment("legacy method")
        self.assertEqual(error.exception.code, "http_error")
        self.response = httpx.Response(404, json={"error": {"type": "not_found_error"}})
        with self.assertRaises(EdgeSpeakError) as error:
            self.client.segment("legacy method")
        self.assertEqual(error.exception.code, "http_error")

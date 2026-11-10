"""Regressions for SDK usability defects found while running public benchmarks."""
import os
import unittest
from unittest.mock import patch

import httpx

from edgespeak import AsyncEdgeSpeak, EdgeSpeak, EdgeSpeakError
from edgespeak import _process
from edgespeak._errors import payload_error


ACCOUNT_KEY = "esak_" + "k" * 43
OWNED = (None, None, "http://127.0.0.1:1118/v1", "gateway-token")
GATEWAY = "http://127.0.0.1:1118/v1"
ALIGNMENT = {"reason": "search_incomplete", "search_effort_used": "standard", "search_path": "whole_audio",
             "search_limit": "none", "retry_recommended": True, "estimated_extra_bytes": 3221225472}
ALIGNMENT_FAILED = {"error": {"message": "Alignment could not be completed.", "type": "invalid_request_error",
                              "code": "alignment_failed", "alignment": ALIGNMENT}}


def attached(response):
    return EdgeSpeak(base_url=GATEWAY, transport=httpx.MockTransport(lambda request: response))


class AccountKeyEnvironmentTests(unittest.TestCase):
    """EDGESPEAK_API_KEY is also the CLI gateway token; that must not crash EdgeSpeak()."""

    def test_gateway_token_in_environment_is_ignored_with_warning(self):
        with patch.dict(os.environ, {"EDGESPEAK_API_KEY": "my-gateway-secret"}), \
                patch("edgespeak._client.start_process", return_value=OWNED) as start:
            with self.assertLogs("edgespeak", "WARNING") as logs:
                with EdgeSpeak():
                    pass
            start.assert_called_once_with(30, None, None)
        self.assertIn("EDGESPEAK_API_KEY", logs.output[0])
        self.assertNotIn("my-gateway-secret", "\n".join(logs.output))

    def test_empty_environment_value_is_ignored_silently(self):
        with patch.dict(os.environ, {"EDGESPEAK_API_KEY": ""}), \
                patch("edgespeak._client.start_process", return_value=OWNED) as start, \
                patch("edgespeak._errors._LOG.warning") as warning:
            with EdgeSpeak():
                pass
            start.assert_called_once_with(30, None, None)
            warning.assert_not_called()

    def test_malformed_account_key_in_environment_names_the_variable(self):
        with patch.dict(os.environ, {"EDGESPEAK_API_KEY": "esak_short"}), \
                patch("edgespeak._client.start_process") as start:
            with self.assertRaisesRegex(ValueError, "EDGESPEAK_API_KEY environment variable") as error:
                EdgeSpeak()
            start.assert_not_called()
        self.assertNotIn("api_key parameter", str(error.exception))
        self.assertNotIn("esak_short", str(error.exception))

    def test_invalid_parameter_names_the_parameter(self):
        with patch.dict(os.environ, {}, clear=False), patch("edgespeak._client.start_process") as start:
            os.environ.pop("EDGESPEAK_API_KEY", None)
            with self.assertRaisesRegex(ValueError, "api_key parameter"):
                EdgeSpeak(api_key="gateway-token")
            start.assert_not_called()

    def test_valid_environment_account_key_is_still_used(self):
        with patch.dict(os.environ, {"EDGESPEAK_API_KEY": ACCOUNT_KEY}), \
                patch("edgespeak._client.start_process", return_value=OWNED) as start:
            with EdgeSpeak():
                pass
            start.assert_called_once_with(30, ACCOUNT_KEY, None)

    def test_inherited_cli_account_variable_error_names_that_variable(self):
        with patch.dict(os.environ, {"EDGESPEAK_ACCESS_TOKEN": "not-an-account-key"}), \
                patch("edgespeak._bootstrap.ensure_cli") as ensure:
            with self.assertRaisesRegex(ValueError, "EDGESPEAK_ACCESS_TOKEN") as error:
                _process.start_process(30)
            ensure.assert_not_called()
        self.assertNotIn("set EDGESPEAK_API_KEY", str(error.exception))


class AsyncAccountKeyEnvironmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_gateway_token_in_environment_is_ignored_with_warning(self):
        with patch.dict(os.environ, {"EDGESPEAK_API_KEY": "my-gateway-secret"}):
            with self.assertLogs("edgespeak", "WARNING") as logs:
                client = AsyncEdgeSpeak()
        self.assertIsNone(client._api_key)
        self.assertNotIn("my-gateway-secret", "\n".join(logs.output))
        await client.aclose()

    async def test_malformed_account_key_in_environment_names_the_variable(self):
        with patch.dict(os.environ, {"EDGESPEAK_API_KEY": "esak_short"}):
            with self.assertRaisesRegex(ValueError, "EDGESPEAK_API_KEY environment variable"):
                AsyncEdgeSpeak()


class ErrorDetailTests(unittest.TestCase):
    """error.alignment drives the documented search_effort=extended retry."""

    def test_alignment_details_and_param_are_preserved(self):
        with attached(httpx.Response(422, json=ALIGNMENT_FAILED)) as client:
            with self.assertRaises(EdgeSpeakError) as caught:
                client.align(b"encoded", text="hello")
        error = caught.exception
        self.assertEqual(error.code, "alignment_failed")
        self.assertEqual(error.alignment, ALIGNMENT)
        self.assertTrue(error.alignment["retry_recommended"])
        with attached(httpx.Response(400, json={"error": {"code": "bad_request", "param": "search_effort"}})) as client:
            with self.assertRaises(EdgeSpeakError) as caught:
                client.align(b"encoded", text="hello")
        self.assertEqual(caught.exception.param, "search_effort")
        self.assertIsNone(caught.exception.alignment)

    def test_alignment_details_survive_progress_stream(self):
        import json
        body = json.dumps({"progress": 0.4}) + "\n" + json.dumps(ALIGNMENT_FAILED) + "\n"
        with attached(httpx.Response(200, text=body)) as client:
            with client.align(b"encoded", text="hello", progress=True) as events:
                with self.assertRaises(EdgeSpeakError) as caught:
                    list(events)
        self.assertEqual(caught.exception.alignment, ALIGNMENT)

    def test_malformed_details_are_dropped_not_echoed(self):
        error = payload_error({"error": {"code": "alignment_failed", "param": "text; secret value",
                                         "alignment": {"reason": "Free text secret", "search_path": "streaming",
                                                       "retry_recommended": "yes", "estimated_extra_bytes": -1,
                                                       "unexpected": "secret"}}}, 422)
        self.assertEqual(error.alignment, {"search_path": "streaming"})
        self.assertIsNone(error.param)
        self.assertIsNone(payload_error({"error": {"code": "alignment_failed", "alignment": "secret"}}).alignment)
        self.assertNotIn("secret", str(error) + repr(error.alignment))
        self.assertEqual(payload_error({"error": {"code": "bad_request", "param": "file[2]"}}).param, "file[2]")

    def test_attributes_exist_on_locally_created_errors(self):
        error = EdgeSpeakError("request_timeout")
        self.assertIsNone(error.alignment)
        self.assertIsNone(error.param)
        self.assertIsNone(error.limit_bytes)


class AsyncErrorDetailTests(unittest.IsolatedAsyncioTestCase):
    async def test_alignment_details_are_preserved(self):
        client = AsyncEdgeSpeak(base_url=GATEWAY, transport=httpx.MockTransport(
            lambda request: httpx.Response(422, json=ALIGNMENT_FAILED)))
        async with client:
            with self.assertRaises(EdgeSpeakError) as caught:
                await client.align(b"encoded", text="hello")
        self.assertEqual(caught.exception.alignment, ALIGNMENT)


class LimitGuidanceTests(unittest.TestCase):
    """32 MiB / 120 s are upsampling limits; other endpoints use the same codes."""

    def test_transcription_and_alignment_do_not_claim_upsampling_limits(self):
        for code in ("upload_too_large", "audio_too_long"):
            for call in (lambda c: c.transcribe(b"encoded"), lambda c: c.align(b"encoded", text="hello")):
                with self.subTest(code=code), attached(httpx.Response(413, json={"error": {"code": code}})) as client:
                    with self.assertRaises(EdgeSpeakError) as caught:
                        call(client)
                message = str(caught.exception)
                self.assertNotIn("32 MiB", message)
                self.assertNotIn("120 seconds", message)

    def test_server_reported_upload_limit_is_included(self):
        with attached(httpx.Response(413, json={"error": {"code": "upload_too_large", "param": "body",
                                                           "limit_bytes": 2 * 1024 ** 3}})) as client:
            with self.assertRaises(EdgeSpeakError) as caught:
                client.transcribe(b"encoded")
        self.assertEqual(caught.exception.limit_bytes, 2 * 1024 ** 3)
        self.assertIn("2147483648 bytes", str(caught.exception))
        self.assertEqual(caught.exception.param, "body")

    def test_upsampling_keeps_its_specific_limits(self):
        for code, text in (("upload_too_large", "32 MiB"), ("audio_too_long", "120 seconds")):
            with self.subTest(code=code), attached(httpx.Response(413, json={"error": {"code": code}})) as client:
                with self.assertRaisesRegex(EdgeSpeakError, text):
                    client.upsample(b"encoded")


class AsyncLimitGuidanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_endpoint_specific_limit_guidance(self):
        client = AsyncEdgeSpeak(base_url=GATEWAY, transport=httpx.MockTransport(
            lambda request: httpx.Response(413, json={"error": {"code": "audio_too_long"}})))
        async with client:
            with self.assertRaises(EdgeSpeakError) as caught:
                await client.transcribe(b"encoded")
            self.assertNotIn("120 seconds", str(caught.exception))
            with self.assertRaisesRegex(EdgeSpeakError, "120 seconds"):
                await client.upsample(b"encoded")


if __name__ == "__main__":
    unittest.main()

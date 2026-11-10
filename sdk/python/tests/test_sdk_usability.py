"""Regressions for SDK usability defects found while running public benchmarks."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx

from edgespeak import AsyncEdgeSpeak, EdgeSpeak, EdgeSpeakError, MIN_CLI_VERSION, RuntimeStartError
from edgespeak import _bootstrap as boot
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


class OwnedStreamingTests(unittest.TestCase):
    """The headless CLI has no streaming transcription; fail before any request."""

    def test_owned_stream_raises_clear_value_error_without_request(self):
        requests = []
        transport = httpx.MockTransport(lambda request: requests.append(request) or httpx.Response(400, json={}))
        with patch("edgespeak._client.start_process", return_value=OWNED), patch("edgespeak._client.stop_process"):
            with EdgeSpeak(transport=transport) as client:
                with self.assertRaisesRegex(ValueError, "base_url") as caught:
                    client.transcribe(b"encoded", stream=True)
        self.assertIn("stream=True", str(caught.exception))
        self.assertEqual(requests, [])

    def test_attached_stream_is_still_sent(self):
        body = 'data: {"type":"transcript.text.done","text":"hi"}\n\n'
        with attached(httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})) as client:
            with client.transcribe(b"encoded", stream=True) as events:
                self.assertEqual(list(events)[-1]["text"], "hi")


class AsyncOwnedStreamingTests(unittest.IsolatedAsyncioTestCase):
    async def test_owned_stream_raises_before_cli_startup(self):
        with patch("edgespeak._async_client.start_process") as start:
            client = AsyncEdgeSpeak()
            with self.assertRaisesRegex(ValueError, "base_url"):
                async with client.transcribe(b"encoded", stream=True):
                    pass
            start.assert_not_called()
            await client.aclose()


class CliSelectionTests(unittest.TestCase):
    """Users must be able to see, and pin, which CLI the SDK runs."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def test_highest_compatible_version_wins_and_ties_keep_preference_order(self):
        a, b, c, d = (Path(self.directory.name) / name for name in "abcd")
        versions = {a: "0.6.8", b: "0.7.10", c: None, d: "0.7.10"}
        with patch.object(boot, "_candidates", return_value=[a, b, c, d]), \
                patch.object(boot, "_cli_version", side_effect=lambda cli, *_: versions[cli]):
            self.assertEqual(boot._find(), b)
        with patch.object(boot, "_candidates", return_value=[c]), patch.object(boot, "_cli_version", return_value=None):
            self.assertIsNone(boot._find())

    def test_explicit_cli_path_is_verified_and_never_falls_back(self):
        cli = Path(self.directory.name) / "edgespeak-cli"
        cli.write_text("")
        with patch.object(boot, "_cli_version", return_value=MIN_CLI_VERSION), \
                patch.object(boot, "_find") as find, patch.object(boot, "_install") as install:
            self.assertEqual(boot.ensure_cli(str(cli)), cli.resolve())
            find.assert_not_called()
            install.assert_not_called()
        for path, version in ((cli, None), (Path(self.directory.name) / "missing", MIN_CLI_VERSION)):
            with self.subTest(path=path), patch.object(boot, "_cli_version", return_value=version), \
                    patch.object(boot, "_find") as find, patch.object(boot, "_install") as install:
                with self.assertRaisesRegex(RuntimeStartError, "cli_path"):
                    boot.ensure_cli(path)
                find.assert_not_called()
                install.assert_not_called()

    def test_cli_path_is_forwarded_and_rejected_when_attached(self):
        owned = _process.OwnedProcess(None, None, GATEWAY, "token", Path("/opt/cli"), "0.7.0")
        with patch("edgespeak._client.start_process", return_value=owned) as start:
            with EdgeSpeak(cli_path="/opt/cli") as client:
                start.assert_called_once_with(30, None, None, cli_path="/opt/cli")
                self.assertEqual(client.cli_path, Path("/opt/cli"))
                self.assertEqual(client.cli_version, "0.7.0")
                with self.assertRaises(AttributeError):
                    client.cli_path = Path("other")
        with self.assertRaisesRegex(ValueError, "cli_path"):
            EdgeSpeak(base_url=GATEWAY, cli_path="/opt/cli")
        with attached(httpx.Response(200, json={})) as client:
            self.assertIsNone(client.cli_path)
            self.assertIsNone(client.cli_version)

    @unittest.skipIf(os.name == "nt", "POSIX executable fixture")
    def test_owned_client_reports_and_logs_the_running_cli(self):
        script = Path(self.directory.name) / "fake-cli"
        script.write_text(f"#!{sys.executable}\n" + 'import json, sys\nprint(json.dumps({"version":"9.8.7","protocol":"edgespeak-sdk-v2","event":"ready","base_url":"http://127.0.0.1:43210/v1"}), flush=True)\nsys.stdin.buffer.read()\n')
        script.chmod(0o700)
        with patch("edgespeak._bootstrap.ensure_cli", return_value=script), \
                self.assertLogs("edgespeak", "INFO") as logs:
            with EdgeSpeak() as client:
                self.assertEqual(client.cli_path, script)
                self.assertEqual(client.cli_version, "9.8.7")
        self.assertTrue(any(str(script) in line and "9.8.7" in line for line in logs.output), logs.output)


class AsyncCliSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_cli_path_and_version_after_startup(self):
        owned = _process.OwnedProcess(object(), os.getpid(), GATEWAY, "token", Path("/opt/cli"), "0.7.0")
        with patch("edgespeak._async_client.start_process", return_value=owned) as start, \
                patch("edgespeak._async_client.stop_process"):
            client = AsyncEdgeSpeak(cli_path="/opt/cli", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))
            self.assertIsNone(client.cli_path)
            await client.health()
            self.assertEqual(start.call_args.kwargs, {"cli_path": "/opt/cli"})
            self.assertEqual(client.cli_path, Path("/opt/cli"))
            self.assertEqual(client.cli_version, "0.7.0")
            await client.aclose()
        with self.assertRaisesRegex(ValueError, "cli_path"):
            AsyncEdgeSpeak(base_url=GATEWAY, cli_path="/opt/cli")


class InstallPlatformTests(unittest.TestCase):
    """The official installer only ships macOS arm64; Rosetta Python maps to it."""

    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        home = patch.object(boot.Path, "home", return_value=Path(self.home.name))
        home.start()
        self.addCleanup(home.stop)

    def test_intel_mac_is_rejected_before_download(self):
        with patch.object(boot.platform, "system", return_value="Darwin"), \
                patch.object(boot.platform, "machine", return_value="x86_64"), \
                patch.object(boot, "_apple_silicon", return_value=False), \
                patch.object(boot.httpx.Client, "get") as download:
            with self.assertRaisesRegex(RuntimeStartError, "Apple Silicon"):
                boot._install()
            download.assert_not_called()

    def test_apple_silicon_probe(self):
        import subprocess
        for output, expected in ((b"1\n", True), (b"0\n", False), (b"", False)):
            with self.subTest(output=output), patch.object(boot.subprocess, "run",
                    return_value=subprocess.CompletedProcess([], 0, output, b"")):
                self.assertIs(boot._apple_silicon(), expected)
        with patch.object(boot.subprocess, "run", side_effect=OSError):
            self.assertFalse(boot._apple_silicon())


class ThreadSafetyDocumentationTests(unittest.TestCase):
    def test_clients_document_thread_use(self):
        self.assertIn("thread", EdgeSpeak.__doc__)
        self.assertIn("EventStream", EdgeSpeak.__doc__)
        self.assertIn("thread", AsyncEdgeSpeak.__doc__)

    def test_one_sync_client_serves_concurrent_threads(self):
        from concurrent.futures import ThreadPoolExecutor
        with attached(httpx.Response(200, json={"text": "hi", "segments": []})) as client, ThreadPoolExecutor(4) as pool:
            results = list(pool.map(lambda _: client.transcribe(b"encoded")["text"], range(16)))
        self.assertEqual(results, ["hi"] * 16)


class FollowAudioTests(unittest.TestCase):
    """Gateway 0.7.6 expands lyric repeats by default; SDK users must be able to opt out."""

    def capture(self, **kwargs):
        requests = []
        def handle(request):
            request.read()
            requests.append(request)
            return httpx.Response(200, json={"text": "a", "segments": [],
                                             "follow_audio": {"applied": True, "lines": [{"source_line": 0}]}})
        with EdgeSpeak(base_url=GATEWAY, transport=httpx.MockTransport(handle)) as client:
            result = client.align(b"encoded", text="[Verse]\na\n[Chorus]\nb", **kwargs)
        return requests[0].content, result

    def test_follow_audio_values_reach_the_wire(self):
        for value, wire in ((False, b"false"), (True, b"true")):
            with self.subTest(value=value):
                body, result = self.capture(follow_audio=value)
                self.assertIn(b'name="follow_audio"\r\n\r\n' + wire + b"\r\n", body)
        body, result = self.capture()
        self.assertNotIn(b'name="follow_audio"', body)
        self.assertTrue(result["follow_audio"]["applied"])

    def test_follow_audio_must_be_boolean(self):
        with attached(httpx.Response(200, json={})) as client:
            for value in ("false", 0, 1):
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, "follow_audio"):
                    client.align(b"encoded", text="hello", follow_audio=value)


class ReviewFollowUpTests(unittest.TestCase):
    """Regressions for AGR review findings on the usability commits."""

    def test_unmapped_code_guidance_is_punctuated_before_alignment_reason(self):
        message = str(payload_error(ALIGNMENT_FAILED, 422))
        self.assertIn("alignment_failed. Alignment reason: search_incomplete.", message)

    def test_sysctl_probe_uses_absolute_path_and_checks_exit_code(self):
        import subprocess
        with patch.object(boot.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, b"1\n", b"")) as run:
            self.assertTrue(boot._apple_silicon())
        self.assertEqual(run.call_args.args[0][0], "/usr/sbin/sysctl")
        with patch.object(boot.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, b"1\n", b"")):
            self.assertFalse(boot._apple_silicon())

    def test_find_skips_protocol_probe_for_versions_that_cannot_win(self):
        import subprocess
        a, b = Path("/a/edgespeak-cli"), Path("/b/edgespeak-cli")
        calls = []
        def run(command, **kwargs):
            calls.append((command[0], command[1]))
            version = b"edgespeak-cli 0.7.0" if command[0] == str(a) else b"edgespeak-cli 0.6.9"
            return subprocess.CompletedProcess(command, 0, version if command[1] == "--version" else b"[--sdk] edgespeak-sdk-v2", b"")
        with patch.object(boot, "_candidates", return_value=[a, b]), patch.object(boot.subprocess, "run", side_effect=run):
            self.assertEqual(boot._find(), a)
        self.assertEqual(calls, [(str(a), "--version"), (str(a), "serve"), (str(b), "--version")])


class AsyncReviewFollowUpTests(unittest.IsolatedAsyncioTestCase):
    async def test_alignment_details_survive_async_progress_stream(self):
        import json
        body = json.dumps({"progress": 0.4}) + "\n" + json.dumps(ALIGNMENT_FAILED) + "\n"
        async with AsyncEdgeSpeak(base_url=GATEWAY, transport=httpx.MockTransport(
                lambda request: httpx.Response(200, text=body))) as client:
            with self.assertRaises(EdgeSpeakError) as caught:
                async with client.align(b"encoded", text="hello", progress=True) as events:
                    async for _ in events:
                        pass
        self.assertEqual(caught.exception.alignment, ALIGNMENT)


if __name__ == "__main__":
    unittest.main()

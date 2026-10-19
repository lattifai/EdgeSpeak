import gc
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import httpx

from edgespeak import EdgeSpeak, EdgeSpeakError, RuntimeStartError


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.audio = Path(self.directory.name) / "speech.wav"
        self.audio.write_bytes(b"RIFF-test-audio")
        self.requests = []
        resolver = patch("edgespeak._bootstrap.ensure_cli", return_value=Path(self.directory.name) / "fake-cli")
        resolver.start()
        self.addCleanup(resolver.stop)

    def attached(self, response=None):
        client = EdgeSpeak(base_url="http://127.0.0.1:1118/v1", gateway_key="test-secret")
        client._http.close()
        def handle(request):
            self.requests.append(request)
            return response or httpx.Response(200, json={"text": "hello", "segments": []})
        client._http = httpx.Client(base_url="http://127.0.0.1:1118/v1/", transport=httpx.MockTransport(handle), headers=client._http.headers.copy())
        self.addCleanup(client._http.close)
        self.addCleanup(client.close)
        return client

    def test_audio_contracts_and_files_close(self):
        client = self.attached()
        self.assertEqual(client.transcribe(self.audio, diarize=True)["text"], "hello")
        body = self.requests[-1].content
        self.assertIn(b'diarized_json', body)
        self.assertIn(b'RIFF-test-audio', body)
        self.assertEqual(self.requests[-1].url.path, "/v1/audio/transcriptions")
        client.align(self.audio, text="hello", search_effort="extended")
        self.assertIn(b'extended', self.requests[-1].content)
        self.assertEqual(self.requests[-1].url.path, "/v1/audio/alignments")
        client.diarize(self.audio, num_speakers=2)
        self.assertEqual(self.requests[-1].url.path, "/v1/speaker/diarizations")
        client.speaker_embedding(self.audio)
        self.assertEqual(self.requests[-1].url.path, "/v1/speaker/embeddings")
        client.speaker_similarity([1.0, 0.0], [0.0, 1.0])
        self.assertEqual(json.loads(self.requests[-1].content), {"embedding_a": [1.0, 0.0], "embedding_b": [0.0, 1.0]})

    def test_close_is_idempotent_and_never_stops_attached_service(self):
        with patch("edgespeak._client.stop_process") as stop:
            client = self.attached()
            client.close()
            client.close()
            stop.assert_not_called()
            with self.assertRaises(RuntimeError):
                client.transcribe(self.audio)

    def test_remote_plaintext_and_url_credentials_rejected(self):
        for url in ("http://example.com/v1", "https://user:secret@example.com/v1", "https://example.com/v1?key=secret"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                EdgeSpeak(base_url=url)

    def test_invalid_inherited_account_key_never_launches_cli(self):
        with patch("edgespeak._process.subprocess.Popen") as spawn:
            for key in ("", " ", "gateway-token", "esak_short"):
                with patch.dict(os.environ, {"EDGESPEAK_ACCESS_TOKEN": key}), self.assertRaises(ValueError):
                    EdgeSpeak()
            spawn.assert_not_called()

    def test_account_key_validation_and_attached_ambiguity(self):
        with patch("edgespeak._client.start_process") as start:
            for key in ("", "gateway-token", "esak_short", 123):
                with self.assertRaises(ValueError):
                    EdgeSpeak(api_key=key)
            with self.assertRaises(ValueError):
                EdgeSpeak(base_url="http://localhost:1118/v1", api_key="esak_" + "a" * 43)
            start.assert_not_called()

    @unittest.skipIf(os.name == "nt", "POSIX executable fixture")
    def test_account_key_only_reaches_child_environment(self):
        script = Path(self.directory.name) / "fake-cli"
        script.write_text(f"#!{sys.executable}\n" + 'import json, sys\nfrom edgespeak import MIN_CLI_VERSION\nprint(json.dumps({"version":MIN_CLI_VERSION,"protocol":"edgespeak-sdk-v2","event":"ready","base_url":"http://127.0.0.1:43210/v1"}), flush=True)\nsys.stdin.buffer.read()\n')
        script.chmod(0o700)
        from edgespeak import _process
        original = _process.subprocess.Popen
        calls = []
        def record(*args, **kwargs):
            calls.append((args, kwargs))
            return original(*args, **kwargs)
        key = "esak_" + "a" * 43
        with patch.dict(os.environ, {"EDGESPEAK_LICENSE_KEY": "desktop-secret"}), patch.object(_process.subprocess, "Popen", side_effect=record):
            with EdgeSpeak(api_key=key) as client:
                self.assertNotIn(key, repr(client.__dict__))
        args, kwargs = calls[0]
        self.assertNotIn(key, repr(args))
        self.assertEqual(kwargs["env"]["EDGESPEAK_ACCESS_TOKEN"], key)
        self.assertNotEqual(kwargs["env"]["EDGESPEAK_API_KEY"], key)
        self.assertNotIn("EDGESPEAK_LICENSE_KEY", kwargs["env"])

    def test_gateway_errors_do_not_echo_server_secrets(self):
        client = self.attached(httpx.Response(403, json={"error": {"code": "license_required", "message": "test-secret"}}))
        with self.assertRaises(EdgeSpeakError) as result:
            client.transcribe(self.audio)
        self.assertEqual(result.exception.code, "license_required")
        self.assertEqual(result.exception.status_code, 403)
        self.assertNotIn("test-secret", str(result.exception))

    def test_validation_before_request(self):
        client = self.attached()
        with self.assertRaises(ValueError):
            client.align(self.audio, text=" ")
        with self.assertRaises(ValueError):
            client.diarize(self.audio, num_speakers=True)
        self.assertEqual(self.requests, [])

    @unittest.skipIf(os.name == "nt", "POSIX executable fixture; Windows covered by real CLI smoke")
    def test_owned_process_close_and_garbage_collection(self):
        script = Path(self.directory.name) / "fake-cli"
        script.write_text(f"#!{sys.executable}\n" + '''import json, sys
from edgespeak import MIN_CLI_VERSION
print(json.dumps({"version": MIN_CLI_VERSION, "protocol": "edgespeak-sdk-v2", "event": "ready", "base_url": "http://127.0.0.1:43210/v1"}), flush=True)
sys.stdin.buffer.read()
''')
        script.chmod(0o700)
        from edgespeak import _client
        original = _client.start_process
        children = []
        def record(*args):
            result = original(*args)
            children.append(result[0])
            return result
        with patch.object(_client, "start_process", side_effect=record):
            with EdgeSpeak():
                self.assertIsNone(children[-1].poll())
            self.assertEqual(children[-1].poll(), 0)
            client = EdgeSpeak()
            del client
            gc.collect()
            self.assertEqual(children[-1].poll(), 0)

    @unittest.skipUnless(hasattr(os, "fork"), "fork is POSIX only")
    def test_forked_worker_does_not_keep_parent_service_alive(self):
        script = Path(self.directory.name) / "fake-cli"
        script.write_text(f"#!{sys.executable}\n" + 'import json, sys\nfrom edgespeak import MIN_CLI_VERSION\nprint(json.dumps({"version":MIN_CLI_VERSION,"protocol":"edgespeak-sdk-v2","event":"ready","base_url":"http://127.0.0.1:43210/v1"}), flush=True)\nsys.stdin.buffer.read()\n')
        script.chmod(0o700)
        from edgespeak import _client
        original = _client.start_process
        children = []
        def record(*args):
            result = original(*args)
            children.append(result[0])
            return result
        with patch.object(_client, "start_process", side_effect=record):
            client = EdgeSpeak()
        read_fd, write_fd = os.pipe()
        child = os.fork()
        if child == 0:
            os.close(write_fd)
            os.read(read_fd, 1)
            os._exit(0)
        os.close(read_fd)
        try:
            client.close()
            self.assertEqual(children[-1].poll(), 0)
        finally:
            os.close(write_fd)
            os.waitpid(child, 0)

    @unittest.skipIf(os.name == "nt", "POSIX executable fixture")
    def test_bad_handshake_and_timeout_cleanup(self):
        script = Path(self.directory.name) / "fake-cli"
        from edgespeak import _process
        original = _process.subprocess.Popen
        children = []
        def record(*args, **kwargs):
            result = original(*args, **kwargs)
            children.append(result)
            return result
        for program in ('print("not-json", flush=True)\n', ''):
            script.write_text(f"#!{sys.executable}\nimport sys\n" + program + 'sys.stdin.buffer.read()\n')
            script.chmod(0o700)
            with patch.object(_process.subprocess, "Popen", side_effect=record):
                with self.assertRaises(RuntimeStartError):
                    EdgeSpeak(startup_timeout=.1)
            self.assertIsNotNone(children[-1].poll())

    @unittest.skipUnless(hasattr(os, "fork"), "fork is POSIX only")
    def test_fork_waits_for_spawn_registration(self):
        script = Path(self.directory.name) / "fake-cli"
        script.write_text(f"#!{sys.executable}\n" + 'import json, sys\nfrom edgespeak import MIN_CLI_VERSION\nprint(json.dumps({"version":MIN_CLI_VERSION,"protocol":"edgespeak-sdk-v2","event":"ready","base_url":"http://127.0.0.1:43210/v1"}), flush=True)\nsys.stdin.buffer.read()\n')
        script.chmod(0o700)
        # Isolate fork and cap the test duration so a lock regression cannot
        # hang the test runner. Pause Popen after it creates the lifetime pipe.
        probe = '''
import os, sys, threading
from unittest.mock import patch
from edgespeak import _process
created, release = threading.Event(), threading.Event()
original = _process.subprocess.Popen
processes, results = [], []
def spawn(*args, **kwargs):
    process = original(*args, **kwargs)
    processes.append(process)
    created.set()
    assert release.wait(3)
    return process
def start():
    with patch("edgespeak._bootstrap.ensure_cli", return_value=sys.argv[1]):
        results.append(_process.start_process(3))
with patch.object(_process.subprocess, "Popen", side_effect=spawn):
    worker = threading.Thread(target=start)
    worker.start()
    assert created.wait(3)
    timer = threading.Timer(0.2, release.set)
    timer.start()
    child = os.fork()
    if child == 0:
        # The fork hook must see even a service whose Popen was in flight.
        os._exit(0 if processes[0].stdin.closed else 1)
    _, status = os.waitpid(child, 0)
    worker.join(3)
    timer.join()
    assert results
    process, owner, _, _ = results[0]
    _process.stop_process(process, owner)
    assert process.returncode == 0
    assert os.waitstatus_to_exitcode(status) == 0
'''
        result = subprocess.run([sys.executable, "-c", probe, str(script)],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cleanup_failure_still_stops_owned_service(self):
        from unittest.mock import MagicMock
        with patch("edgespeak._client.start_process", return_value=(object(), None, "http://127.0.0.1:1118/v1", "token")), patch("edgespeak._client.stop_process") as stop:
            client = EdgeSpeak()
            stream = MagicMock()
            stream._close_from_client.side_effect = RuntimeError("transport cleanup failed")
            client._streams.add(stream)
            with self.assertRaisesRegex(RuntimeError, "cleanup failed"):
                client.close()
            stop.assert_called_once()
            client.close()

    def test_attached_gateway_ignores_account_environment_on_actual_requests(self):
        account_values = ("esak_" + "a" * 43, "invalid-account-key", "")
        original_http_client = httpx.Client
        for account_key in account_values:
            for gateway_key in (None, "gateway-only-token"):
                requests = []
                def handle(request):
                    requests.append(request)
                    return httpx.Response(200, json={"status": "ok"})
                def http_client(**kwargs):
                    return original_http_client(**kwargs, transport=httpx.MockTransport(handle))
                with self.subTest(account_key=account_key, gateway_key=gateway_key), \
                        patch.dict(os.environ, {"EDGESPEAK_API_KEY": account_key}), \
                        patch("edgespeak._client.httpx.Client", side_effect=http_client), \
                        patch("edgespeak._client.start_process") as start, \
                        patch("edgespeak._client.stop_process") as stop:
                    with EdgeSpeak(base_url="http://127.0.0.1:1118/v1", gateway_key=gateway_key) as client:
                        self.assertEqual(client._request("GET", "health"), {"status": "ok"})
                    self.assertEqual(len(requests), 1)
                    expected = f"Bearer {gateway_key}" if gateway_key else None
                    self.assertEqual(requests[0].headers.get("authorization"), expected)
                    self.assertEqual(os.environ["EDGESPEAK_API_KEY"], account_key)
                    start.assert_not_called()
                    stop.assert_not_called()

    def test_sdk_api_key_environment_is_translated_without_leaking_to_gateway(self):
        key = "esak_" + "b" * 43
        explicit = "esak_" + "c" * 43
        with patch.dict(os.environ, {"EDGESPEAK_API_KEY": key}), patch("edgespeak._client.start_process", return_value=(None, None, "http://127.0.0.1:1118/v1", "private-gateway-token")) as start:
            with EdgeSpeak() as client:
                start.assert_called_once_with(30, key, None)
                self.assertNotIn(key, str(client._http.headers))
            start.reset_mock()
            with EdgeSpeak(api_key=explicit):
                start.assert_called_once_with(30, explicit, None)
            start.reset_mock()
            with EdgeSpeak(base_url="http://127.0.0.1:1118/v1") as client:
                start.assert_not_called()
                self.assertNotIn('authorization', client._http.headers)
        with patch.dict(os.environ, {"EDGESPEAK_API_KEY": "gateway-token"}), patch("edgespeak._client.start_process") as start:
            with self.assertRaises(ValueError):
                EdgeSpeak()
            start.assert_not_called()


class UpsamplingTests(unittest.TestCase):
    setUp = ClientTests.setUp
    attached = ClientTests.attached
    def test_upsampling_uploads_file_and_returns_wav(self):
        import io
        import wave
        data = io.BytesIO()
        with wave.open(data, 'wb') as wav:
            wav.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
            wav.writeframes(b'\0\0' * 8000)
        expected = data.getvalue()
        for rate, media_type in ((8000, 'audio/wav'), (16000, 'Audio/WAV'),
                                 (24000, 'audio/WAV; codec=pcm'), (44100, 'audio/wav'),
                                 (48000, 'audio/wav')):
            with self.subTest(rate=rate, media_type=media_type):
                import struct
                expected = expected[:24] + struct.pack('<II', rate, rate * 2) + expected[32:]
                client = self.attached(httpx.Response(200, content=expected, headers={'content-type': media_type}))
                self.assertEqual(client.upsample(self.audio, sample_rate=rate), expected)
                request = self.requests[-1]
                self.assertEqual(request.url.path, '/v1/audio/upsamplings')
                self.assertIn(str(rate).encode(), request.content)
                self.assertIn(b'RIFF-test-audio', request.content)
                self.assertEqual(request.headers['authorization'], 'Bearer test-secret')

    def test_invalid_rate_never_sends_request(self):
        client = self.attached()
        for rate in (True, 0, -1, 48001, 96000, 24000.0, '24000', None):
            with self.subTest(rate=rate):
                with self.assertRaises(ValueError):
                    client.upsample(self.audio, sample_rate=rate)
        self.assertFalse(self.requests)

    def test_invalid_audio_response_and_server_error(self):
        client = self.attached(httpx.Response(200, content=b'not WAV', headers={'content-type': 'audio/wav'}))
        with self.assertRaises(EdgeSpeakError) as error:
            client.upsample(self.audio)
        self.assertEqual(error.exception.code, 'invalid_response')
        client = self.attached(httpx.Response(503, json={'error': {'code': 'service_unavailable'}}))
        with self.assertRaises(EdgeSpeakError) as error:
            client.upsample(self.audio)
        self.assertEqual(error.exception.status_code, 503)

    def test_audio_error_codes_include_actionable_guidance(self):
        for code, hint in [('audio_invalid', 'valid WAV'), ('audio_format_unsupported', 'PCM16'),
                           ('audio_channels_unsupported', '1–8'), ('audio_too_long', '120'),
                           ('upload_too_large', '32 MiB')]:
            with self.subTest(code=code):
                status = 413 if code in ('audio_too_long', 'upload_too_large') else 400
                client = self.attached(httpx.Response(status, json={'error': {'code': code, 'message': 'ignored server prose'}}))
                with self.assertRaises(EdgeSpeakError) as error:
                    client.upsample(self.audio)
                self.assertEqual(error.exception.code, code)
                self.assertEqual(error.exception.status_code, status)
                self.assertIn(hint, str(error.exception))
                self.assertNotIn('ignored server prose', str(error.exception))

    def test_old_gateway_explains_missing_capability(self):
        client = self.attached(httpx.Response(404, json={"error": {"code": "not_found"}}))
        with self.assertRaises(EdgeSpeakError) as error:
            client.upsample(self.audio)
        self.assertEqual(error.exception.code, "audio_upsampling_unavailable")
        self.assertIn("Update the gateway runtime", str(error.exception))


if __name__ == "__main__":
    unittest.main()

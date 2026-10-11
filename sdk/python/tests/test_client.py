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
        client._http = httpx.Client(base_url="http://127.0.0.1:1118/v1/", transport=httpx.MockTransport(handle))
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
        script.write_text(f"#!{sys.executable}\n" + 'import json, sys\nprint(json.dumps({"version":"0.6.3","protocol":"edgespeak-sdk-v1","event":"ready","base_url":"http://127.0.0.1:43210/v1"}), flush=True)\nsys.stdin.buffer.read()\n')
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
print(json.dumps({"version": "0.6.3", "protocol": "edgespeak-sdk-v1", "event": "ready", "base_url": "http://127.0.0.1:43210/v1"}), flush=True)
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
        script.write_text(f"#!{sys.executable}\n" + 'import json, sys\nprint(json.dumps({"version":"0.6.3","protocol":"edgespeak-sdk-v1","event":"ready","base_url":"http://127.0.0.1:43210/v1"}), flush=True)\nsys.stdin.buffer.read()\n')
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
        script.write_text(f"#!{sys.executable}\n" + 'import json, sys\nprint(json.dumps({"version":"0.6.3","protocol":"edgespeak-sdk-v1","event":"ready","base_url":"http://127.0.0.1:43210/v1"}), flush=True)\nsys.stdin.buffer.read()\n')
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


if __name__ == "__main__":
    unittest.main()

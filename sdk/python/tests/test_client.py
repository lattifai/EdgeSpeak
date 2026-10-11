import gc
import json
import os
from pathlib import Path
import sys
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
print(json.dumps({"protocol": "edgespeak-sdk-v1", "event": "ready", "base_url": "http://127.0.0.1:43210/v1"}), flush=True)
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
            with EdgeSpeak(cli_path=script):
                self.assertIsNone(children[-1].poll())
            self.assertEqual(children[-1].poll(), 0)
            client = EdgeSpeak(cli_path=script)
            del client
            gc.collect()
            self.assertEqual(children[-1].poll(), 0)

    @unittest.skipUnless(hasattr(os, "fork"), "fork is POSIX only")
    def test_forked_worker_does_not_keep_parent_service_alive(self):
        script = Path(self.directory.name) / "fake-cli"
        script.write_text(f"#!{sys.executable}\n" + 'import json, sys\nprint(json.dumps({"protocol":"edgespeak-sdk-v1","event":"ready","base_url":"http://127.0.0.1:43210/v1"}), flush=True)\nsys.stdin.buffer.read()\n')
        script.chmod(0o700)
        from edgespeak import _client
        original = _client.start_process
        children = []
        def record(*args):
            result = original(*args)
            children.append(result[0])
            return result
        with patch.object(_client, "start_process", side_effect=record):
            client = EdgeSpeak(cli_path=script)
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
                    EdgeSpeak(cli_path=script, startup_timeout=.1)
            self.assertIsNotNone(children[-1].poll())


if __name__ == "__main__":
    unittest.main()

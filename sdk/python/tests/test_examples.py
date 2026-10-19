"""Run standalone examples through real SDK clients and controlled HTTP responses."""

import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx
from edgespeak import EdgeSpeakError

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
BASE_URL = "http://127.0.0.1:1118/v1"


class ExampleTests(unittest.TestCase):
    def test_every_script_has_standalone_help(self):
        # A fresh interpreter cannot rely on runpy's imports from earlier cases.
        for script in sorted(EXAMPLES.glob("*.py")):
            with self.subTest(script=script.name), tempfile.TemporaryDirectory() as cwd:
                result = subprocess.run(
                    [sys.executable, str(script), "--help"],
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("--base-url", result.stdout)
                self.assertIn("EDGESPEAK_API_KEY", result.stdout)

    def test_workflows_and_cleanup_in_owned_and_attached_modes(self):
        for attached in (False, True):
            self.run_workflows(attached)

    def test_failed_requests_still_close_clients_and_owned_processes(self):
        for attached in (False, True):
            self.run_workflows(attached, fail=True)

    def run_workflows(self, attached, fail=False):
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "audio.wav"
            audio.write_bytes(b"RIFF test")
            reference = Path(directory) / "reference.srt"
            reference.write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nHello.\n", encoding="utf-8"
            )
            plain = Path(directory) / "text.txt"
            plain.write_text("Hello. Next.", encoding="utf-8")
            transcript = Path(directory) / "transcript.json"
            transcript.write_text(
                json.dumps(
                    {
                        "segments": [
                            {"text": "Hello.", "start": 0, "end": 1, "speaker": "A"}
                        ]
                    }
                ),
                encoding="utf-8",
            )
            cases = []
            for prefix in ("", "async_"):
                cases += [
                    (
                        prefix + "align.py",
                        [str(audio), "--text", "Hello."],
                        ["/v1/audio/alignments"],
                    ),
                    (
                        prefix + "align.py",
                        [str(audio), "--text-file", str(reference), "--progress"],
                        ["/v1/health", "/v1/audio/alignments"],
                    ),
                    (
                        prefix + "segment.py",
                        ["--text", "Hello. Next.", "--paragraph-threshold", ".6"],
                        ["/v1/text/segmentations"],
                    ),
                    (
                        prefix + "segment.py",
                        ["--text-file", str(plain)],
                        ["/v1/text/segmentations"],
                    ),
                    (
                        prefix + "segment.py",
                        ["--segments-file", str(transcript), "--max-chars", "40"],
                        ["/v1/text/segmentations"],
                    ),
                    (
                        prefix + "speakers.py",
                        [str(audio)] * 3 + ["--num-speakers", "2"],
                        [
                            "/v1/speaker/diarizations",
                            "/v1/speaker/embeddings",
                            "/v1/speaker/similarity",
                        ],
                    ),
                ]
            cases += [
                (
                    "transcribe.py",
                    [
                        str(audio),
                        "--diarize",
                        "--semantic",
                        "--timestamp-granularity",
                        "word",
                    ],
                    ["/v1/audio/transcriptions"],
                ),
                (
                    "transcribe.py",
                    [str(audio), "--response-format", "text"],
                    ["/v1/audio/transcriptions"],
                ),
                (
                    "transcribe.py",
                    [str(audio), "--stream"],
                    ["/v1/audio/transcriptions"],
                ),
                (
                    "async_transcribe.py",
                    [str(audio), str(audio)],
                    ["/v1/audio/transcriptions"] * 2,
                ),
                (
                    "async_transcribe.py",
                    [str(audio), str(audio), "--align"],
                    ["/v1/audio/transcriptions"] * 2 + ["/v1/audio/alignments"] * 2,
                ),
            ]
            self.assertEqual(
                {name for name, _, _ in cases},
                {script.name for script in EXAMPLES.glob("*.py")},
                "Every shipped Python example needs workflow coverage",
            )
            for filename, args, routes in cases:
                requests, clients, responses = [], [], []

                def handler(request):
                    request.read()
                    requests.append(request)
                    if fail:
                        response = httpx.Response(
                            500,
                            json={
                                "error": {
                                    "code": "internal_error",
                                    "message": "Test failure",
                                }
                            },
                        )
                    elif request.url.path.endswith("/health"):
                        response = httpx.Response(
                            200, json={"capabilities": ["alignment_reference_formats"]}
                        )
                    elif request.url.path.endswith("/embeddings"):
                        response = httpx.Response(
                            200,
                            json={
                                "data": [
                                    {"embedding": [1.0] * 256},
                                    {"embedding": [1.0] * 256},
                                ]
                            },
                        )
                    elif request.headers.get("progress") == "1":
                        response = httpx.Response(
                            200, text='{"progress":1}\n{"task":"align","segments":[]}\n'
                        )
                    elif b'name="stream"\r\n\r\ntrue' in request.content:
                        response = httpx.Response(
                            200,
                            headers={"content-type": "text/event-stream"},
                            text='data: {"text":"Hello."}\n\ndata: [DONE]\n\n',
                        )
                    elif b'name="response_format"\r\n\r\ntext' in request.content:
                        response = httpx.Response(200, text="Hello.")
                    else:
                        response = httpx.Response(
                            200, json={"text": "Hello.", "segments": []}
                        )
                    responses.append(response)
                    return response

                async def async_handler(request):
                    await request.aread()
                    return handler(request)

                asynchronous = filename.startswith("async_")
                module = (
                    "edgespeak._async_client" if asynchronous else "edgespeak._client"
                )
                client_type = "AsyncClient" if asynchronous else "Client"
                real_http = getattr(httpx, client_type)

                def http_factory(*args, **kwargs):
                    kwargs["transport"] = httpx.MockTransport(
                        async_handler if asynchronous else handler
                    )
                    client = real_http(*args, **kwargs)
                    clients.append(client)
                    return client

                argv = (
                    [filename] + args + (["--base-url", BASE_URL] if attached else [])
                )
                with self.subTest(
                    example=filename, args=args, attached=attached, fail=fail
                ), patch.object(sys, "argv", argv), patch.dict(
                    os.environ,
                    {
                        "EDGESPEAK_API_KEY": ("esak_" + "a" * 43),
                        "EDGESPEAK_GATEWAY_KEY": "gateway-test-only",
                    },
                ), patch(
                    module + ".start_process",
                    return_value=(object(), None, BASE_URL, "owned-test-token"),
                ) as start, patch(
                    module + ".stop_process"
                ) as stop, patch(
                    module + ".httpx." + client_type, side_effect=http_factory
                ), contextlib.redirect_stdout(
                    io.StringIO()
                ) as output:
                    if fail:
                        with self.assertRaises(EdgeSpeakError):
                            runpy.run_path(
                                str(EXAMPLES / filename), run_name="__main__"
                            )
                    else:
                        runpy.run_path(str(EXAMPLES / filename), run_name="__main__")
                        expected_routes = (
                            routes
                            if attached
                            else [r for r in routes if r != "/v1/health"]
                        )
                        self.assertEqual(
                            [r.url.path for r in requests], expected_routes
                        )
                        self.assertTrue(output.getvalue().strip())
                        if "--progress" not in args:
                            self.assertIn("Hello.", output.getvalue())
                        if "--progress" in args or "--align" in args:
                            self.assertIn('"progress": 1', output.getvalue())
                        if "--text-file" in args and "align" in filename:
                            self.assertIn(b"Hello.", requests[-1].content)
                            self.assertNotIn(
                                str(reference).encode(), requests[-1].content
                            )
                        if "speakers" in filename:
                            self.assertEqual(
                                requests[1].content.count(b'name="file";'), 2
                            )
                            self.assertEqual(
                                len(json.loads(requests[2].content)["embedding_a"]), 256
                            )
                    self.assertTrue(clients)
                    self.assertTrue(all(client.is_closed for client in clients))
                    self.assertTrue(all(response.is_closed for response in responses))
                    for request in requests:
                        expected_token = (
                            "gateway-test-only" if attached else "owned-test-token"
                        )
                        self.assertEqual(
                            request.headers["Authorization"], "Bearer " + expected_token
                        )
                        self.assertNotIn(("esak_" + "a" * 43).encode(), request.content)
                    if attached:
                        start.assert_not_called()
                        stop.assert_not_called()
                    else:
                        expected = (
                            (30, "esak_" + "a" * 43, None, 2)
                            if filename == "async_transcribe.py"
                            else (30, "esak_" + "a" * 43, None)
                        )
                        start.assert_called_once_with(*expected)
                        stop.assert_called_once()

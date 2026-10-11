"""Execute the shipped command-line examples against the SDK HTTP boundary."""
import contextlib
import io
import json
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx
from edgespeak import EdgeSpeak

EXAMPLES = Path(__file__).resolve().parents[1] / 'examples'


class ExampleTests(unittest.TestCase):
    def test_all_example_workflows_send_expected_routes(self):
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / 'audio.wav'
            audio.write_bytes(b'RIFF test')
            reference = Path(directory) / 'reference.srt'
            reference.write_text('1\n00:00:00,000 --> 00:00:01,000\nHello.\n')
            transcript = Path(directory) / 'transcript.json'
            transcript.write_text(json.dumps({'segments': [{'text': 'Hello.', 'start': 0, 'end': 1, 'speaker': 'A'}]}))
            requests = []
            def handler(request):
                request.read()
                requests.append(request)
                if request.url.path.endswith("/health"):
                    return httpx.Response(200, json={"capabilities": ["alignment_reference_formats"]})
                if request.url.path.endswith('/embeddings'):
                    return httpx.Response(200, json={'data': [{'embedding': [1.] * 256}, {'embedding': [1.] * 256}]})
                if request.headers.get('progress') == '1':
                    return httpx.Response(200, text='{"progress":1}\n{"task":"align","segments":[]}\n')
                return httpx.Response(200, json={'text': 'Hello.', 'segments': []})
            real_http = httpx.Client
            def http_factory(*args, **kwargs):
                kwargs['transport'] = httpx.MockTransport(handler)
                return real_http(*args, **kwargs)
            cases = [
                ('transcribe.py', [str(audio), '--diarize', '--semantic'], ['/v1/audio/transcriptions']),
                ('align.py', [str(audio), '--text-file', str(reference), '--progress'], ['/v1/health', '/v1/audio/alignments']),
                ('segment.py', ['--text', 'Hello. Next.', '--paragraph-threshold', '.6'], ['/v1/text/segmentations']),
                ('segment.py', ['--segments-file', str(transcript), '--max-chars', '40'], ['/v1/text/segmentations']),
                ('speakers.py', [str(audio)] * 3 + ['--num-speakers', '2'], ['/v1/speaker/diarizations', '/v1/speaker/embeddings', '/v1/speaker/similarity']),
            ]
            with patch.object(sys, 'path', [str(EXAMPLES)] + sys.path), patch('edgespeak._client.httpx.Client', side_effect=http_factory):
                for filename, args, routes in cases:
                    with self.subTest(example=filename, args=args), patch.object(sys, 'argv', [filename] + args + ['--base-url', 'http://127.0.0.1:1118/v1']), contextlib.redirect_stdout(io.StringIO()) as output:
                        requests.clear()
                        runpy.run_path(str(EXAMPLES / filename), run_name='__main__')
                        self.assertEqual([r.url.path for r in requests], routes)
                        self.assertTrue(output.getvalue().strip())
                        if filename == 'align.py':
                            self.assertIn(b'Hello.', requests[-1].content)
                            self.assertNotIn(str(reference).encode(), requests[-1].content)
                        if filename == 'speakers.py':
                            self.assertEqual(requests[1].content.count(b'name="file";'), 2)
                            self.assertEqual(len(json.loads(requests[2].content)['embedding_a']), 256)

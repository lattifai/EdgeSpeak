import json
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
import tempfile
import unittest

import httpx

from edgespeak import EdgeSpeak, EdgeSpeakError


class DiffAlignTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.audio = Path(self.directory.name) / 'sample.wav'
        self.audio.write_bytes(b'RIFF-probe')
        self.requests = []
        self.capabilities = ['diff_alignment']
        self.client = EdgeSpeak(base_url='http://127.0.0.1:18119/v1')
        self.client._http.close()
        def handle(request):
            self.requests.append(request)
            if request.url.path.endswith('/health'):
                return httpx.Response(200, json={'capabilities': self.capabilities})
            return httpx.Response(200, json={'segments': [], 'speaker_source': 'input_text'})
        self.client._http = httpx.Client(base_url='http://127.0.0.1:18119/v1/', transport=httpx.MockTransport(handle))
        self.addCleanup(self.client.close)

    def test_uploads_both_inputs_as_structured_unicode(self):
        reference = [{'text': 'Hello 世界', 'speaker': 'A'}]
        transcript = [{'text': 'Hello new 世界'}]
        result = self.client.diff_align(self.audio, reference_segments=reference,
                                        transcript_segments=transcript, offset=12.5)
        self.assertEqual(result['speaker_source'], 'input_text')
        request = self.requests[-1]
        self.assertEqual(request.url.path, '/v1/audio/diff-alignments')
        message = BytesParser(policy=default).parsebytes(
            b'Content-Type: ' + request.headers['content-type'].encode() + b'\r\n\r\n' + request.content)
        fields = {part.get_param('name', header='content-disposition'): part.get_payload(decode=True)
                  for part in message.iter_parts()}
        self.assertEqual(json.loads(fields['reference_segments']), reference)
        self.assertEqual(json.loads(fields['transcript_segments']), transcript)
        self.assertEqual(fields['offset'], b'12.5')
        self.assertEqual(fields['file'], b'RIFF-probe')
        self.assertNotIn('text', fields)

    def test_old_gateway_is_rejected_before_audio_upload(self):
        self.capabilities = []
        with self.assertRaises(EdgeSpeakError):
            self.client.diff_align(self.audio, reference_segments=[{'text': 'a'}],
                                   transcript_segments=[{'text': 'b'}])
        self.assertEqual(len(self.requests), 1)
        self.assertTrue(self.requests[0].url.path.endswith('/health'))

    def test_invalid_segments_do_not_make_requests(self):
        for invalid in ([], 'hello', [{'text': ''}], [{'text': 2}], [{'text': 'x', 'speaker': 2}],
                        [{'text': 'x', 'start': 1}], [{'text': 'bad\0text'}]):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.client.diff_align(self.audio, reference_segments=invalid,
                                       transcript_segments=[{'text': 'b'}])
        self.assertEqual(self.requests, [])

    def test_invalid_offset_does_not_make_requests(self):
        for offset in (True, -1, float('nan'), float('inf'), '1'):
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                self.client.diff_align(self.audio, reference_segments=[{'text': 'a'}],
                                       transcript_segments=[{'text': 'b'}], offset=offset)
        self.assertEqual(self.requests, [])

import asyncio
import json
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
import tempfile
import unittest

import httpx

from edgespeak import AsyncEdgeSpeak, EdgeSpeak, EdgeSpeakError


def multipart_fields(request):
    message = BytesParser(policy=default).parsebytes(
        b'Content-Type: ' + request.headers['content-type'].encode() + b'\r\n\r\n' + request.content)
    return {part.get_param('name', header='content-disposition'): part.get_payload(decode=True)
            for part in message.iter_parts()}


SEGMENTS = [
    {'speaker': 'A', 'text': 'Hello 世界', 'start': 0.0, 'end': 2.5},
    {'speaker': 'B', 'text': 'Right', 'start': 2.0, 'end': 3.0},
]


class OverlapAlignTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.audio = Path(self.directory.name) / 'sample.wav'
        self.audio.write_bytes(b'RIFF-probe')
        self.requests = []
        self.capabilities = ['overlap_alignment']
        self.client = EdgeSpeak(base_url='http://127.0.0.1:18119/v1')
        self.client._http.close()
        self.client._http = httpx.Client(base_url='http://127.0.0.1:18119/v1/',
                                         transport=httpx.MockTransport(self.handle))
        self.addCleanup(self.client.close)

    def handle(self, request):
        self.requests.append(request)
        if request.url.path.endswith('/health'):
            return httpx.Response(200, json={'capabilities': self.capabilities})
        return httpx.Response(200, json={'task': 'overlap_align', 'segments': []})

    def test_uploads_segments_and_options(self):
        result = self.client.overlap_align(
            self.audio, segments=SEGMENTS, model='lattice-2', language='en', offset=12.5,
            protected_terms=['EdgeSpeak'], text_normalization={'enabled': False},
            search_effort='extended', pronunciation_mode='default')
        self.assertEqual(result['task'], 'overlap_align')
        request = self.requests[-1]
        self.assertEqual(request.url.path, '/v1/audio/overlap-alignments')
        fields = multipart_fields(request)
        self.assertEqual(json.loads(fields['segments']), SEGMENTS)
        self.assertEqual(json.loads(fields['protected_terms']), ['EdgeSpeak'])
        self.assertEqual(json.loads(fields['text_normalization']), {'enabled': False})
        self.assertEqual(fields['offset'], b'12.5')
        self.assertEqual(fields['search_effort'], b'extended')
        self.assertEqual(fields['pronunciation_mode'], b'default')
        self.assertEqual(fields['model'], b'lattice-2')
        self.assertEqual(fields['language'], b'en')
        self.assertEqual(fields['file'], b'RIFF-probe')
        # 网关字段白名单之外的字段一律不发。
        self.assertLessEqual(set(fields), {'file', 'segments', 'model', 'language', 'offset',
                                           'text_normalization', 'protected_terms',
                                           'search_effort', 'pronunciation_mode'})

    def test_defaults_send_only_segments(self):
        self.client.overlap_align(self.audio, segments=SEGMENTS)
        self.assertEqual(set(multipart_fields(self.requests[-1])), {'file', 'segments'})

    def test_old_gateway_is_rejected_before_audio_upload(self):
        self.capabilities = []
        with self.assertRaises(EdgeSpeakError):
            self.client.overlap_align(self.audio, segments=SEGMENTS)
        self.assertEqual(len(self.requests), 1)
        self.assertTrue(self.requests[0].url.path.endswith('/health'))

    def test_invalid_segments_do_not_make_requests(self):
        good = {'speaker': 'A', 'text': 'x', 'start': 0, 'end': 1}
        for invalid in ([], 'hello', [{'text': 'x'}], [{**good, 'text': ''}],
                        [{**good, 'speaker': ''}], [{**good, 'speaker': 2}],
                        [{**good, 'start': -1}], [{**good, 'end': 0}],
                        [{**good, 'start': float('nan')}], [{**good, 'start': True}],
                        [{**good, 'extra': 1}], [{**good, 'text': 'bad\0'}]):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.client.overlap_align(self.audio, segments=invalid)
        self.assertEqual(self.requests, [])

    def test_invalid_options_do_not_make_requests(self):
        for options in ({'offset': -1}, {'offset': True}, {'search_effort': 'fast'},
                        {'pronunciation_mode': 'pinyin'}, {'protected_terms': 'EdgeSpeak'},
                        {'protected_terms': [1]},
                        {'text_normalization': {'pins': [{'start': 0, 'end': 1}]}}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.client.overlap_align(self.audio, segments=SEGMENTS, **options)
        self.assertEqual(self.requests, [])


class AsyncOverlapAlignTests(unittest.TestCase):
    def test_async_client_uses_the_same_route(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        audio = Path(directory.name) / 'sample.wav'
        audio.write_bytes(b'RIFF-probe')
        requests = []

        def handle(request):
            requests.append(request)
            if request.url.path.endswith('/health'):
                return httpx.Response(200, json={'capabilities': ['overlap_alignment']})
            return httpx.Response(200, json={'task': 'overlap_align', 'segments': []})

        async def run():
            client = AsyncEdgeSpeak(base_url='http://127.0.0.1:18119/v1',
                                    transport=httpx.MockTransport(handle))
            try:
                return await client.overlap_align(audio, segments=SEGMENTS, offset=1.0)
            finally:
                await client.aclose()

        result = asyncio.run(run())
        self.assertEqual(result['task'], 'overlap_align')
        self.assertEqual(requests[-1].url.path, '/v1/audio/overlap-alignments')
        self.assertEqual(json.loads(multipart_fields(requests[-1])['segments']), SEGMENTS)


if __name__ == '__main__':
    unittest.main()

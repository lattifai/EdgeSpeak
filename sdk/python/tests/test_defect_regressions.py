"""Regressions from the SDK defect review, including wire framing."""
from contextlib import ExitStack
import json
import unittest
import httpx
import numpy as np
from edgespeak import EdgeSpeak, EdgeSpeakError
from edgespeak._streaming import EventStream
from test_speech_features import SpeechFixture

class ChunkStream(httpx.SyncByteStream):
    def __init__(self, payload):
        self.payload = payload
    def __iter__(self):
        for byte in self.payload:
            yield bytes([byte])

class DefectRegressions(SpeechFixture):
    def test_unicode_separators_and_null_errors_in_audio_streams(self):
        for protocol in ('sse', 'ndjson'):
            for separator in ('\u2028', '\u2029', '\x85'):
                value = {'delta': 'a' + separator + 'b', 'error': None}
                terminal = {'type': 'transcript.text.done'} if protocol == 'sse' else {'task': 'align', 'segments': []}
                frames = [json.dumps(event, ensure_ascii=False) for event in (value, terminal)]
                wire = ''.join('data: ' + frame + '\r\n\r\n' for frame in frames) if protocol == 'sse' else '\r\n'.join(frames) + '\r\n'
                response = httpx.Response(200, stream=ChunkStream(wire.encode('utf-8')))
                client = self.client()
                with self.subTest(protocol=protocol, separator=repr(separator)), EventStream(client, response, ExitStack(), protocol) as events:
                    self.assertEqual(list(events), [value, terminal])
                self.assertTrue(response.is_closed)

    def test_semantic_options_rejected_before_io(self):
        client = self.client()
        invalid = [dict(min_chars=-1), dict(max_chars=True), dict(min_chars=65536), dict(start_margin=float('nan')), dict(end_margin='1'), dict(semantic_sentence_enabled='yes')]
        for method in (client.transcribe, client.align):
            for options in invalid:
                with self.subTest(method=method.__name__, options=options), self.assertRaises(ValueError):
                    method('missing.wav', **({'text': 'hello'} if method == client.align else {}), **options)
        for options in (dict(threshold=float('nan')), dict(threshold=True), dict(threshold=1.1), dict(progress=1)):
            with self.subTest(options=options), self.assertRaises(ValueError):
                client.align('missing.wav', text='hello', **options)
        self.assertEqual(self.requests, [])

    def test_segment_options_rejected_before_network(self):
        client = self.client()
        for options in (dict(threshold=float('nan')), dict(min_chars=-1), dict(options=[]), dict(options={'start_margin': float('inf')}), dict(paragraph_threshold=True), dict(threshold=.8, paragraph_threshold=.2), dict(options={'paragraph_threshold': .8, 'min_chars': 3})):
            with self.subTest(options=options), self.assertRaises(ValueError):
                client.segment('hello', **options)
        self.assertEqual(self.requests, [])

    def test_numpy_embedding_scalars_are_json_numbers(self):
        client = self.client()
        client.speaker_similarity(np.array([1, 0], dtype=np.float32), np.array([0, 1], dtype=np.int64))
        self.assertEqual(json.loads(self.requests[-1].content), {'embedding_a': [1., 0.], 'embedding_b': [0., 1.]})

    def test_plain_404_audio_and_segment_report_missing_capability(self):
        client = self.client(httpx.Response(404, text='not found'))
        for call in (lambda: client.transcribe(self.audio), lambda: client.diarize(self.audio), lambda: client.segment('hello')):
            with self.assertRaises(EdgeSpeakError) as failure:
                call()
            self.assertEqual(failure.exception.code, 'unsupported_gateway_capability')

    def test_transport_hooks_limits_and_request_id(self):
        seen = []
        transport = httpx.MockTransport(lambda request: httpx.Response(403, headers={"x-request-id": "req-123"}, json={"error": {"code": "api_key_revoked"}}))
        with EdgeSpeak(base_url='http://localhost:1118/v1', transport=transport,
                       limits=httpx.Limits(max_connections=2),
                       event_hooks={"request": [lambda request: seen.append(request.url.path)]}) as client:
            with self.assertRaises(EdgeSpeakError) as failure:
                client.health()
        self.assertEqual(failure.exception.request_id, "req-123")
        self.assertEqual(seen, ["/v1/health"])


    def test_stable_cli_build_metadata_is_compatible(self):
        from edgespeak._bootstrap import compatible_version, MIN_CLI_VERSION
        self.assertTrue(compatible_version(MIN_CLI_VERSION + '+build.123'))
        for suffix in ('-beta.1', '.1', '+', '+bad..part'):
            self.assertFalse(compatible_version(MIN_CLI_VERSION + suffix))

    def test_non_null_stream_errors_remain_errors_and_close_resources(self):
        for protocol in ('sse', 'ndjson'):
            event = json.dumps({'error': {'code': 'api_key_revoked', 'message': 'secret'}})
            wire = ('data: ' + event + '\n\n') if protocol == 'sse' else event + '\n'
            response = httpx.Response(200, text=wire)
            cleanup = []
            resources = ExitStack()
            resources.callback(lambda: cleanup.append(True))
            with self.assertRaises(EdgeSpeakError) as failure:
                next(EventStream(self.client(), response, resources, protocol))
            self.assertEqual(failure.exception.code, 'api_key_revoked')
            self.assertNotIn('secret', str(failure.exception))
            self.assertTrue(response.is_closed)
            self.assertEqual(cleanup, [True])

    def test_numpy_generation_scalars_are_encoded_without_optional_imports(self):
        client = self.client()
        client.chat_completions([{'role': 'user', 'content': 'hello'}], model='model', temperature=np.float32(.5), top_p=np.float32(.75))
        body = json.loads(self.requests[-1].content)
        self.assertEqual((body['temperature'], body['top_p']), (.5, .75))

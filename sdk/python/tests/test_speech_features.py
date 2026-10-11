import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from edgespeak import EdgeSpeak, EdgeSpeakError
from edgespeak._reference import reference_input


class SpeechFeaturesTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.audio = Path(self.directory.name) / 'clip.wav'
        self.audio.write_bytes(b'RIFF fixture')
        self.requests = []

    def client(self, response=None):
        client = EdgeSpeak(base_url='http://127.0.0.1:1118/v1')
        self.addCleanup(client.close)
        client._http.close()
        def handler(request):
            request.read()
            self.requests.append(request)
            if request.url.path.endswith("/health") and response is None:
                return httpx.Response(200, json={"capabilities": ["alignment_reference_formats"]})
            return response or httpx.Response(200, json={'text': 'hello', 'segments': []})
        client._http = httpx.Client(base_url='http://127.0.0.1:1118/v1/', transport=httpx.MockTransport(handler))
        self.addCleanup(client._http.close)
        return client

    def test_transcribe_speaker_word_and_semantic_options_use_api_wire_types(self):
        client = self.client()
        client.transcribe(self.audio, diarize=True, word_timestamp_enabled=True,
                          timestamp_granularities=['word', 'segment'],
                          semantic_sentence_enabled=True, min_chars=5, max_chars=32,
                          start_margin=0, end_margin=.1)
        body = self.requests[-1].content
        for value in [b'diarized_json', b'\r\ntrue\r\n', b'\r\nword\r\n', b'\r\nsegment\r\n']:
            self.assertIn(value, body)
        self.assertEqual(body.count(b'name="timestamp_granularities[]"'), 2)
        self.assertNotIn(b'\r\nTrue\r\n', body)
        with self.assertRaises(ValueError):
            client.transcribe(self.audio, diarize=True, response_format='json')

    def test_text_response_and_nbest(self):
        client = self.client(httpx.Response(200, text='你好。'))
        self.assertEqual(client.transcribe(self.audio, response_format='text'), '你好。')
        client = self.client()
        client.transcribe(self.audio, candidates=4, word_timestamp_enabled=False)
        self.assertIn(b'\r\nfalse\r\n', self.requests[-1].content)
        self.assertIn(b'name="candidates"\r\n\r\n4', self.requests[-1].content)

    def test_alignment_uploads_reference_contents_and_all_advanced_options(self):
        reference = Path(self.directory.name) / 'captions.ass'
        reference.write_text('[Events]\nFormat: Start, End, Text\nDialogue: 0,1,hello', encoding='utf-8')
        client = self.client()
        client.align(self.audio, text_file=reference, start=1, end=2, search_effort='auto',
                     protected_terms=['EdgeSpeak', 'New York'], audio_track=0, audio_channel=1, threshold=.7,
                     text_normalization={'enabled': True, 'top_k': 2}, semantic_sentence_enabled=True)
        body = self.requests[-1].content
        self.assertIn(b'name="text_format"\r\n\r\nass', body)
        self.assertIn(b'Format: Start, End, Text', body)
        self.assertIn(b'name="threshold"\r\n\r\n0.7', body)
        self.assertIn(b'"enabled": true', body)
        self.assertEqual(body.count(b'name="protected_terms[]"'), 2)
        self.assertNotIn(str(reference).encode(), body)
        self.assertNotIn(b'text_path', body)
        client.align(self.audio, text={'segments': [{'text': '你好'}]})
        self.assertIn(b'name="text_format"\r\n\r\njson', self.requests[-1].content)
        with self.assertRaises(ValueError):
            client.align(self.audio, text='text', text_file=reference)

    def test_reference_reader_bounds_size_and_accepts_utf8_bom(self):
        path = Path(self.directory.name) / 'text.srt'
        path.write_bytes(b'\xef\xbb\xbfHello')
        self.assertEqual(reference_input(None, path, None), ('Hello', 'srt'))
        with patch('edgespeak._reference._MAX_REFERENCE_BYTES', 2):
            with self.assertRaises(ValueError):
                reference_input(None, path, None)
        with self.assertRaises(ValueError):
            reference_input('hello', None, 'unsupported')

    def test_segment_plain_paragraph_and_timed_speakers_preserved(self):
        client = self.client()
        client.segment('First. Second.', threshold=.3, paragraph_threshold=.6)
        self.assertEqual(json.loads(self.requests[-1].content), {
            'text': 'First. Second.', 'threshold': .3, 'paragraph_threshold': .6})
        segments = [{'text': 'hello', 'start': 0.0, 'end': 2.0, 'speaker': 'A'}]
        client.segment(segments=segments, min_chars=3, max_chars=20, start_margin=0)
        body = json.loads(self.requests[-1].content)
        self.assertEqual(body['segments'], segments)
        self.assertEqual(body['start_margin'], 0)
        self.assertNotIn('semantic_sentence_enabled', body)
        with self.assertRaises(ValueError):
            client.segment('hello', segments=segments)

    def test_speaker_batch_repeats_audio_parts_and_closes_on_failure(self):
        client = self.client()
        client.speaker_embedding([self.audio, self.audio])
        self.assertEqual(self.requests[-1].content.count(b'name="file";'), 2)
        opened = []
        original = Path.open
        def record(path, *args, **kwargs):
            file = original(path, *args, **kwargs)
            opened.append(file)
            return file
        with patch.object(Path, 'open', record):
            with self.assertRaises(FileNotFoundError):
                client.speaker_embedding([self.audio, self.audio.with_name('missing.wav')])
        self.assertTrue(all(file.closed for file in opened))

    def test_alignment_ndjson_progress_and_transcription_sse(self):
        response = httpx.Response(200, text='{"progress":0.5}\n{"task":"align","segments":[]}\n')
        client = self.client(response)
        with client.align(self.audio, text='hello', progress=True) as events:
            self.assertEqual(list(events), [{'progress': .5}, {'task': 'align', 'segments': []}])
        self.assertTrue(response.is_closed)
        self.assertEqual(self.requests[-1].headers['progress'], '1')
        response = httpx.Response(200, text=': heartbeat\nevent: delta\ndata: {"delta":"hello"}\n\ndata: [DONE]\n\n')
        client = self.client(response)
        with client.transcribe(self.audio, stream=True) as events:
            self.assertEqual(list(events), [{'delta': 'hello'}])
        self.assertIn(b'name="response_format"\r\n\r\njson', self.requests[-1].content)
        self.assertTrue(response.is_closed)

    def test_stream_requires_terminal_result_even_after_progress_reaches_one(self):
        for progress, body in [(True, '{"progress":1}\n'),
                               (False, 'data: {"type":"transcript.text.delta","delta":"hello"}\n\n')]:
            with self.subTest(progress=progress):
                response = httpx.Response(200, text=body)
                client = self.client(response)
                events = (client.align(self.audio, text='hello', progress=True) if progress
                          else client.transcribe(self.audio, stream=True))
                with self.assertRaises(EdgeSpeakError) as error:
                    list(events)
                self.assertEqual(error.exception.code, 'incomplete_stream')
                self.assertTrue(response.is_closed)
        client = self.client(httpx.Response(200, text='data: {"type":"transcript.text.done","text":"hello"}\n\n'))
        self.assertEqual(list(client.transcribe(self.audio, stream=True))[0]['text'], 'hello')

    def test_stream_error_is_sanitized_and_client_close_closes_open_stream(self):
        response = httpx.Response(200, text='{"error":{"code":"alignment_failed","message":"secret"}}\n')
        client = self.client(response)
        events = client.align(self.audio, text='hello', progress=True)
        with self.assertRaises(EdgeSpeakError) as error:
            next(events)
        self.assertEqual(error.exception.code, 'alignment_failed')
        self.assertNotIn('secret', str(error.exception))
        self.assertTrue(response.is_closed)
        response = httpx.Response(200, text='{"progress":0.5}\n')
        client = self.client(response)
        events = client.align(self.audio, text='hello', progress=True)
        client.close()
        self.assertTrue(response.is_closed)
        with self.assertRaises(EdgeSpeakError) as error:
            list(events)
        self.assertEqual(error.exception.code, "stream_closed")

    def test_old_gateway_rejects_structured_reference_before_audio_upload(self):
        client = self.client(httpx.Response(200, json={"status": "ok"}))
        with self.assertRaises(EdgeSpeakError) as error:
            client.align(self.audio, text={"segments": [{"text": "hello"}]})
        self.assertEqual(error.exception.code, "unsupported_gateway_capability")
        self.assertEqual([r.url.path for r in self.requests], ["/v1/health"])

    def test_terminal_event_closes_before_eof_and_uploads_close_on_broken_stream(self):
        class Wire(httpx.SyncByteStream):
            def __init__(self, terminal):
                self.terminal = terminal
                self.closed = False
            def __iter__(self):
                yield self.terminal
                raise httpx.ReadError("private transport details")
            def close(self):
                self.closed = True
        for payload, terminal in [(b'{"task":"align","segments":[]}\n', True),
                                  (b'{"progress":0.5}\n', False)]:
            with self.subTest(terminal=terminal):
                wire = Wire(payload)
                client = self.client(httpx.Response(200, stream=wire))
                opened = []
                original = Path.open
                def record(path, *args, **kwargs):
                    stream = original(path, *args, **kwargs)
                    opened.append(stream)
                    return stream
                with patch.object(Path, 'open', record):
                    events = client.align(self.audio, text='hello', progress=True)
                next(events)
                if terminal:
                    self.assertTrue(wire.closed)
                    self.assertEqual(list(events), [])
                else:
                    with self.assertRaises(EdgeSpeakError) as error:
                        next(events)
                    self.assertEqual(error.exception.code, 'connection_failed')
                    self.assertNotIn('private', str(error.exception))
                self.assertTrue(all(file.closed for file in opened))

    def test_stream_http_failure_closes_response(self):
        response = httpx.Response(401, json={"error": {"code": "api_key_expired"}})
        client = self.client(response)
        with self.assertRaises(EdgeSpeakError) as error:
            client.align(self.audio, text='hello', progress=True)
        self.assertEqual(error.exception.code, 'api_key_expired')
        self.assertTrue(response.is_closed)

    def test_reference_format_validated_before_open_and_binary_flags(self):
        import os
        with patch('edgespeak._reference.os.open') as open_file:
            with self.assertRaises(ValueError):
                reference_input(None, 'missing.wav', 'unsupported')
            open_file.assert_not_called()
        path = Path(self.directory.name) / 'text.srt'
        path.write_bytes(b'Hello\r\nworld\x1a!')
        with patch('edgespeak._reference.os.open', wraps=os.open) as open_file:
            self.assertEqual(reference_input(None, path, ' SRT '), ('Hello\r\nworld\x1a!', 'srt'))
            if hasattr(os, 'O_BINARY'):
                self.assertTrue(open_file.call_args.args[1] & os.O_BINARY)

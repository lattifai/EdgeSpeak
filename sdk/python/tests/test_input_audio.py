"""Memory audio wire contract and sample fidelity, without runtime model dependencies."""
import io
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import wave

import httpx
import numpy as np

from edgespeak import EdgeSpeak, EdgeSpeakError
from edgespeak._input_audio import MAX_MEMORY_AUDIO_BYTES, prepare_audio as plan_audio, AudioPlan
from types import SimpleNamespace


def prepare_audio(audio, sample_rate, **kwargs):
    """Read a prepared upload to assert its encoded sample fidelity."""
    plan = plan_audio(audio, sample_rate, **kwargs)
    if plan.size == 0:
        return plan.source
    _, stream, _ = plan.open()
    with stream:
        return SimpleNamespace(payload=stream.read())


def samples(payload):
    with wave.open(io.BytesIO(payload), 'rb') as wav:
        return wav.getparams(), np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2').reshape(-1, wav.getnchannels())


class MemoryAudioTests(unittest.TestCase):
    def client(self, response=None, error=False):
        self.requests = []
        client = EdgeSpeak(base_url='http://127.0.0.1:1118/v1')
        client._http.close()
        def handler(request):
            request.read()
            self.requests.append(request)
            if error:
                raise httpx.ConnectError('fixture', request=request)
            return response or httpx.Response(200, json={'text': 'hello', 'segments': []})
        client._http = httpx.Client(base_url='http://127.0.0.1:1118/v1/', transport=httpx.MockTransport(handler))
        self.addCleanup(client.close)
        return client

    def test_array_wav_preserves_rate_order_frames_and_input(self):
        for channels in (1, 2, 6, 8):
            original = np.arange(19 * channels, dtype=np.int16).reshape(19, channels)
            for data in (original, original.astype('>i2'), original[::-2], original[:, ::-1], np.asfortranarray(original)):
                with self.subTest(channels=channels, dtype=data.dtype):
                    before = data.copy()
                    params, decoded = samples(prepare_audio(data, np.int64(24000)).payload)
                    self.assertEqual((params.framerate, params.nchannels, params.nframes), (24000, channels, len(data)))
                    np.testing.assert_array_equal(decoded, data)
                    np.testing.assert_array_equal(data, before)
        mono = np.array([0, 23, -25], dtype=np.int16)
        np.testing.assert_array_equal(samples(prepare_audio(mono, 8000).payload)[1][:, 0], mono)

    def test_float_rounding_endpoints_and_chunk_boundaries(self):
        for dtype in (np.float32, np.float64, '>f8'):
            audio = np.tile(np.array([-1, -.5, 0, .5, 1], dtype=dtype), 14000)
            params, decoded = samples(prepare_audio(audio, 48000).payload)
            self.assertEqual(params.nframes, len(audio))
            np.testing.assert_array_equal(decoded[:, 0], np.rint(audio.astype(np.float64) * 32767).astype(np.int16))

    def test_invalid_arrays_and_rates_rejected(self):
        for data in (np.array(0), np.empty((0,)), np.empty((2, 0)), np.empty((2, 9)),
                     np.zeros((2, 3, 1)), np.zeros(2, dtype=np.int32), np.zeros(2, dtype=np.float16),
                     np.zeros(2, dtype=bool), np.zeros(2, dtype=complex), np.array([object()]),
                     np.array([np.nan]), np.array([np.inf]), np.array([1.001]),
                     np.ma.array([1, 2], mask=[False, True])):
            with self.subTest(shape=data.shape, dtype=data.dtype), self.assertRaises(ValueError):
                prepare_audio(data, 16000)
        for rate in (None, True, False, 16000.0, 0, -1, 384001, '16000', np.bool_(True)):
            with self.subTest(rate=rate), self.assertRaises(ValueError):
                prepare_audio(np.zeros(2), rate)

    def test_array_selection_checked_before_allocating_wav(self):
        data = np.zeros((3, 2))
        for channel in (-1, True, 1.9, 'left', '1.0', [], 2):
            with self.subTest(channel=channel), patch('edgespeak._input_audio.io.BytesIO') as buffer, self.assertRaises(ValueError):
                prepare_audio(data, 16000, audio_channel=channel)
            buffer.assert_not_called()
        for track in (False, 0.0, 1):
            with self.subTest(track=track), self.assertRaises(ValueError):
                prepare_audio(data, 16000, audio_track=track)
        self.assertNotIn('secret payload', repr(plan_audio(b'secret payload', None)))

    def test_unsupported_values_and_encoded_rate_override(self):
        for data in (None, 123, [0.0], bytearray(b'a'), memoryview(b'a'), io.BytesIO(b'a')):
            with self.subTest(type=type(data)), self.assertRaises(ValueError):
                prepare_audio(data, None)
        for data in ('a.wav', Path('a.wav'), b'RIFF'):
            with self.subTest(type=type(data)), self.assertRaisesRegex(ValueError, 'only for NumPy'):
                prepare_audio(data, 16000)
        with self.assertRaises(ValueError):
            prepare_audio(b'', None)

    def test_size_guard_before_allocation_and_boundary(self):
        # A zero-stride virtual array tests the real cap without allocating a huge fixture.
        count = (MAX_MEMORY_AUDIO_BYTES - 44) // 2 + 1
        oversized = np.lib.stride_tricks.as_strided(np.zeros(1, dtype=np.int16), shape=(count,), strides=(0,))
        with patch('edgespeak._input_audio.io.BytesIO') as buffer, self.assertRaisesRegex(ValueError, '256 MiB'):
            prepare_audio(oversized, 16000)
        buffer.assert_not_called()
        self.assertEqual(len(prepare_audio(np.zeros(2, dtype=np.int16), 16000, max_bytes=48).payload), 48)
        with self.assertRaises(ValueError):
            prepare_audio(np.zeros(3, dtype=np.int16), 16000, max_bytes=48)
        self.assertEqual(prepare_audio(b'x' * 48, None, max_bytes=48).payload, b'x' * 48)
        with self.assertRaises(ValueError):
            prepare_audio(b'x' * 49, None, max_bytes=48)

    def test_both_methods_upload_exact_bytes_and_array_wav(self):
        client = self.client()
        encoded = prepare_audio(np.array([1, -2], dtype=np.int16), 8000).payload
        for method, kwargs in ((client.transcribe, {}), (client.align, {'text': 'hello'})):
            method(encoded, **kwargs)
            body = self.requests[-1].content
            self.assertIn(b'filename="audio.bin"', body)
            self.assertIn(b'Content-Type: application/octet-stream', body)
            self.assertIn(encoded, body)
            method(np.array([[1, -2], [3, -4]], dtype=np.int16), sample_rate=24000, **kwargs)
            body = self.requests[-1].content
            self.assertIn(b'filename="audio.wav"', body)
            self.assertIn(b'Content-Type: audio/wav', body)
            wav = body.split(b'Content-Type: audio/wav\r\n\r\n', 1)[1].split(b'\r\n--', 1)[0]
            params, decoded = samples(wav)
            self.assertEqual((params.framerate, params.nchannels), (24000, 2))
            np.testing.assert_array_equal(decoded, [[1, -2], [3, -4]])
            self.assertNotIn(b'name="sample_rate"', body)

    def test_local_errors_precede_reference_and_network(self):
        client = self.client()
        with patch('edgespeak._requests.reference_input') as reference:
            for value, options in ((b'', {}), (np.zeros((5, 2)), {}),
                                   (np.zeros((5, 2)), {'sample_rate': 16000, 'audio_track': 1}),
                                   (np.zeros((5, 2)), {'sample_rate': 16000, 'audio_channel': 2})):
                with self.subTest(options=options), self.assertRaises(ValueError):
                    client.align(value, text_file='missing.json', **options)
            reference.assert_not_called()
        self.assertEqual(self.requests, [])
        with self.assertRaises(ValueError):
            client.transcribe(np.array([np.nan]), sample_rate=16000)
        self.assertEqual(self.requests, [])
        client.align(np.zeros((5, 2)), sample_rate=16000, text='hello', audio_track=0, audio_channel='1')

    def test_explicit_repeat_after_transport_failure_sends_full_payload(self):
        client = self.client(error=True)
        payload = b'fixture-complete-encoded-audio'
        for _ in range(2):
            with self.assertRaises(EdgeSpeakError):
                client.transcribe(payload)
        self.assertEqual(len(self.requests), 2)  # no automatic billing retry
        for request in self.requests:
            self.assertIn(payload, request.content)

    def test_memory_buffers_close_on_sync_failure_and_stream_exit(self):
        original = AudioPlan.open
        opened = []
        def buffer(plan, *args, **kwargs):
            value = original(plan, *args, **kwargs)
            opened.append(value[1])
            return value
        client = self.client()
        with patch.object(AudioPlan, 'open', buffer):
            client.transcribe(b'encoded fixture')
        self.assertTrue(opened[-1].closed)
        client = self.client(error=True)
        with patch.object(AudioPlan, 'open', buffer), self.assertRaises(EdgeSpeakError):
            client.align(b'encoded fixture', text='hello')
        self.assertTrue(opened[-1].closed)
        for alignment in (False, True):
            response = httpx.Response(200, text='{"progress":0.5}\n{"task":"align","segments":[]}\n' if alignment else 'data: {"delta":"hello"}\n\ndata: [DONE]\n\n')
            client = self.client(response)
            with patch.object(AudioPlan, 'open', buffer):
                stream = client.align(b'encoded fixture', text='hello', progress=True) if alignment else client.transcribe(b'encoded fixture', stream=True)
                handle = opened[-1]
                with stream:
                    list(stream)
                self.assertTrue(handle.closed)
                self.assertTrue(response.is_closed)

    def test_memory_upload_early_stream_close_and_http_denial_release_buffers(self):
        original = AudioPlan.open
        opened = []
        def buffer(plan, *args, **kwargs):
            value = original(plan, *args, **kwargs)
            opened.append(value[1])
            return value
        for response, streaming in ((httpx.Response(200, text='data: {"delta":"hello"}\n\n'), True),
                                    (httpx.Response(401, json={'error': {'code': 'api_key_expired'}}), False)):
            client = self.client(response)
            with patch.object(AudioPlan, 'open', buffer):
                if streaming:
                    stream = client.transcribe(b'encoded fixture', stream=True)
                    stream.close()
                else:
                    with self.assertRaises(EdgeSpeakError):
                        client.transcribe(b'encoded fixture')
            self.assertTrue(opened[-1].closed)
            self.assertTrue(response.is_closed)

    def test_no_numpy_install_required_or_imported_and_hints_resolve(self):
        script = '''
import importlib.abc, sys, typing
class BlockNumpy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'numpy' or fullname.startswith('numpy.'):
            raise AssertionError('NumPy must not be imported')
sys.meta_path.insert(0, BlockNumpy())
from edgespeak import EdgeSpeak
from edgespeak._input_audio import prepare_audio
plan = prepare_audio(b'encoded', None)
_, source, _ = plan.open()
assert source.read() == b'encoded'
source.close()
assert prepare_audio('audio.wav', None).source == 'audio.wav'
assert 'sample_rate' in typing.get_type_hints(EdgeSpeak.transcribe)
assert 'sample_rate' in typing.get_type_hints(EdgeSpeak.align)
assert 'numpy' not in sys.modules
'''
        result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, env=os.environ)
        self.assertEqual(result.returncode, 0, result.stderr)

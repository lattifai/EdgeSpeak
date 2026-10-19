"""Unified audio inputs, payload limits and upload resource lifetime."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import httpx
import numpy as np

from edgespeak import AudioSamples, EdgeSpeak
from edgespeak._audio_budget import AudioBudget
from edgespeak._input_audio import AudioPlan, prepare_audio


class AudioResourceTests(unittest.TestCase):
    def client(self, **kwargs):
        self.requests = []
        def handle(request):
            request.read()
            self.requests.append(request)
            if request.url.path.endswith('/health'):
                return httpx.Response(200, json={'capabilities': ['diff_alignment']})
            return httpx.Response(200, json={'data': [], 'segments': []})
        client = EdgeSpeak(base_url='http://localhost:1118/v1', transport=httpx.MockTransport(handle), **kwargs)
        self.addCleanup(client.close)
        return client

    def test_all_new_methods_encoded_and_array_inputs(self):
        c = self.client()
        for value, options in ((b'encoded', {}), (np.zeros((4, 2), dtype=np.int16), {'sample_rate': 8000}),
                               (AudioSamples(np.zeros(4), 24000), {})):
            for method, extra in ((c.diarize, {}), (c.speaker_embedding, {}),
                                  (c.diff_align, {'reference_segments': [{'text': 'a'}], 'transcript_segments': [{'text': 'a'}]})):
                method(value, **options, **extra)
                request = self.requests[-1]
                self.assertIn('content-length', request.headers)
                self.assertNotIn('transfer-encoding', request.headers)
                self.assertIn(b'filename="audio.', request.content)
        with self.assertRaisesRegex(ValueError, '120 seconds'):
            c.upsample(np.zeros(121), input_sample_rate=1)
        with self.assertRaisesRegex(ValueError, '32 MiB'):
            c.upsample(np.lib.stride_tricks.as_strided(np.zeros(1, dtype=np.int16), shape=(17*1024*1024,), strides=(0,)), input_sample_rate=384000)

    def test_batch_rates_order_and_single_paths(self):
        c = self.client()
        c.speaker_embedding([AudioSamples(np.zeros(1), 8000), np.ones(2, dtype=np.int16), b'encoded'], sample_rate=16000)
        body = self.requests[-1].content
        self.assertEqual(body.count(b'name="file"'), 3)
        self.assertLess(body.index((8000).to_bytes(4, 'little')), body.index((16000).to_bytes(4, 'little')))
        self.assertLess(body.index((16000).to_bytes(4, 'little')), body.index(b'encoded'))
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/'speech.wav'; p.write_bytes(b'file payload')
            c.speaker_embedding(str(p))
            self.assertEqual(self.requests[-1].content.count(b'name="file"'), 1)
        for value, rate in (([], None), ([[b'a']], None), ([b'a'], 16000), (AudioSamples(np.zeros(2), 8000), 8000)):
            with self.assertRaises(ValueError):
                c.speaker_embedding(value, sample_rate=rate)

    def test_limits_exact_none_paths_and_aggregate(self):
        c = self.client(max_memory_audio_bytes=48, max_in_flight_audio_bytes=60)
        c.transcribe(np.zeros(2), sample_rate=16000)
        with self.assertRaisesRegex(ValueError, 'max_memory_audio_bytes=48'):
            c.transcribe(np.zeros(3), sample_rate=16000)
        with self.assertRaisesRegex(ValueError, 'max_in_flight_audio_bytes=60'):
            c.speaker_embedding([b'a'*31, b'b'*31])
        self.assertEqual(c._audio_budget.used, 0)
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/'speech.wav'; p.write_bytes(b'x'*100)
            c.transcribe(p)
        self.client(max_memory_audio_bytes=None, max_in_flight_audio_bytes=None).transcribe(b'x'*100)
        for name in ('max_memory_audio_bytes', 'max_in_flight_audio_bytes', 'audio_spool_threshold_bytes'):
            for value in (True, 0, -1, 1.5):
                with self.assertRaises(ValueError):
                    self.client(**{name: value})

    def test_spool_opt_in_and_failure_releases_budget(self):
        c = self.client()
        with patch('edgespeak._input_audio.tempfile.TemporaryFile', side_effect=AssertionError('default must not write disk')):
            c.diarize(np.zeros(20), sample_rate=16000)
        c = self.client(audio_spool_threshold_bytes=1)
        original = AudioPlan.open
        opened = []
        def record(plan, *args):
            value = original(plan, *args); opened.append(value[1]); return value
        with patch.object(AudioPlan, 'open', record):
            c.transcribe(np.zeros(10), sample_rate=8000)
        self.assertTrue(opened[0].closed)
        self.assertIn('content-length', self.requests[-1].headers)
        with patch('edgespeak._input_audio.tempfile.TemporaryFile', side_effect=OSError('fixture full')):
            with self.assertRaises(OSError):
                c.transcribe(np.zeros(10), sample_rate=8000)
        self.assertEqual(c._audio_budget.used, 0)
        self.assertNotIn('array', repr(AudioSamples(np.zeros(2), 8000)))

    def test_budget_released_before_stream_is_consumed(self):
        c = EdgeSpeak(base_url='http://localhost:1118/v1', max_in_flight_audio_bytes=4,
                      transport=httpx.MockTransport(lambda r: httpx.Response(200, text='data: [DONE]\n\n')))
        self.addCleanup(c.close)
        stream = c.transcribe(b'1234', stream=True)
        self.assertEqual(c._audio_budget.used, 0)
        stream.close()

    def test_close_wakes_sync_waiter(self):
        budget = AudioBudget(4); lease = budget.acquire(4)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(budget.acquire, 1)
            budget.close()
            with self.assertRaisesRegex(RuntimeError, 'closed'):
                pending.result(timeout=2)
        lease.close(); lease.close()
        self.assertEqual(budget.used, 0)


class AsyncBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_waiter_and_close(self):
        budget = AudioBudget(4); lease = await budget.acquire_async(4)
        pending = asyncio.create_task(budget.acquire_async(1))
        await asyncio.sleep(0); pending.cancel()
        with self.assertRaises(asyncio.CancelledError): await pending
        self.assertEqual(budget.used, 4)
        pending = asyncio.create_task(budget.acquire_async(1))
        await asyncio.sleep(0); budget.close()
        with self.assertRaisesRegex(RuntimeError, 'closed'): await pending
        lease.close()
        self.assertEqual(budget.used, 0)

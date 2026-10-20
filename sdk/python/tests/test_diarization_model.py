import unittest
import httpx
from edgespeak import EdgeSpeak, AsyncEdgeSpeak, EdgeSpeakError

class DiarizationModelTests(unittest.TestCase):
    def test_explicit_selection_and_old_gateway_rejection(self):
        for capabilities in (["diarization_model_selection"], []):
            requests = []
            def handle(request):
                requests.append(request)
                if request.url.path.endswith("health"):
                    return httpx.Response(200, json={"capabilities": capabilities})
                return httpx.Response(200, json={"segments": [], "speakers": []})
            with EdgeSpeak(base_url="http://localhost:18220/v1") as client:
                client._http.close()
                client._http = httpx.Client(base_url="http://localhost:18220/v1/", transport=httpx.MockTransport(handle))
                if capabilities:
                    client.diarize(b"audio", model="EdgeSpeak/Lattice-2")
                    self.assertIn(b'EdgeSpeak/Lattice-2', requests[-1].content)
                    self.assertIn(b'name="model"', requests[-1].content)
                else:
                    with self.assertRaises(EdgeSpeakError) as raised:
                        client.diarize(b"audio", model="EdgeSpeak/Lattice-2")
                    self.assertEqual(raised.exception.code, "unsupported_gateway_capability")
                    self.assertEqual(len(requests), 1)

class AsyncDiarizationModelTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_selection_and_old_gateway_rejection(self):
        for capabilities in (["diarization_model_selection"], []):
            requests = []
            async def handle(request):
                await request.aread()
                requests.append(request)
                if request.url.path.endswith("health"):
                    return httpx.Response(200, json={"capabilities": capabilities})
                return httpx.Response(200, json={"segments": [], "speakers": []})
            async with AsyncEdgeSpeak(base_url="http://localhost:18220/v1", transport=httpx.MockTransport(handle)) as client:
                if capabilities:
                    await client.diarize(b"audio", model="EdgeSpeak/Lattice-1")
                    self.assertIn(b'EdgeSpeak/Lattice-1', requests[-1].content)
                else:
                    with self.assertRaises(EdgeSpeakError) as raised:
                        await client.diarize(b"audio", model="EdgeSpeak/Lattice-1")
                    self.assertEqual(raised.exception.code, "unsupported_gateway_capability")
                    self.assertEqual(len(requests), 1)

class TranscriptionDiarizationModelTests(unittest.TestCase):
    def test_sync_selection_and_capability_guard(self):
        for supported in (True, False):
            requests = []
            def handle(request):
                requests.append(request)
                if request.url.path.endswith('health'):
                    return httpx.Response(200, json={'capabilities': ['transcription_diarization_model_selection'] if supported else ['diarization_model_selection']})
                return httpx.Response(200, json={'text': 'test', 'segments': []})
            with EdgeSpeak(base_url='http://localhost:18220/v1') as client:
                client._http.close()
                client._http = httpx.Client(base_url='http://localhost:18220/v1/', transport=httpx.MockTransport(handle))
                options = dict(model='lattice-2-flash', diarize=True, diarization_model='EdgeSpeak/Lattice-2', word_timestamp_enabled=True)
                if supported:
                    client.transcribe(b'audio', **options)
                    self.assertIn(b'name="diarization_model"', requests[-1].content)
                    self.assertIn(b'EdgeSpeak/Lattice-2', requests[-1].content)
                    self.assertIn(b'lattice-2-flash', requests[-1].content)
                else:
                    with self.assertRaises(EdgeSpeakError):
                        client.transcribe(b'audio', **options)
                    self.assertEqual(len(requests), 1)
                with self.assertRaises(ValueError):
                    client.transcribe(b'audio', diarization_model='EdgeSpeak/Lattice-2')

class AsyncTranscriptionDiarizationModelTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_selection_and_capability_guard(self):
        for supported in (True, False):
            requests = []
            async def handle(request):
                await request.aread()
                requests.append(request)
                if request.url.path.endswith('health'):
                    return httpx.Response(200, json={'capabilities': ['transcription_diarization_model_selection'] if supported else []})
                return httpx.Response(200, json={'text': 'test', 'segments': []})
            async with AsyncEdgeSpeak(base_url='http://localhost:18220/v1', transport=httpx.MockTransport(handle)) as client:
                if supported:
                    await client.transcribe(b'audio', diarize=True, diarization_model='EdgeSpeak/Lattice-2')
                    self.assertIn(b'name="diarization_model"', requests[-1].content)
                else:
                    with self.assertRaises(EdgeSpeakError):
                        await client.transcribe(b'audio', diarize=True, diarization_model='EdgeSpeak/Lattice-2')
                    self.assertEqual(len(requests), 1)

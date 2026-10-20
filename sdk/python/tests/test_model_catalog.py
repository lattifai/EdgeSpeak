import copy
import unittest
import httpx
from edgespeak import EdgeSpeak, AsyncEdgeSpeak
from edgespeak._model_catalog import group_models

CATALOG = {"object": "list", "data": [
    {"id": "EdgeSpeak/Lattice-2-Flash", "supported_endpoints": ["/v1/audio/transcriptions"],
     "installed": True, "default_for": ["/v1/audio/transcriptions"], "execution_location": "local"},
    {"id": "EdgeSpeak/Lattice-2", "supported_endpoints": ["/v1/audio/alignments", "/v1/audio/diff-alignments", "/v1/speaker/diarizations"],
     "installed": False, "features": ["future_feature"]},
    {"id": "Provider/Future", "supported_endpoints": ["/v1/chat/completions", "/v1/future"]},
    {"id": "Provider/Legacy"},
    {"id": "Provider/Speech", "supported_endpoints": ["/v1/audio/speech"]},
]}

class ModelCatalogTests(unittest.TestCase):
    def test_capabilities_metadata_unknown_states_and_no_registry_guessing(self):
        source = copy.deepcopy(CATALOG)
        groups = group_models(source)
        self.assertEqual(groups['transcription']['models'][0], CATALOG['data'][0])
        self.assertEqual(groups['alignment']['models'], groups['diarization']['models'])
        self.assertFalse(groups['alignment']['models'][0]['installed'])
        self.assertNotIn('installed', groups['text_generation']['models'][0])
        self.assertEqual([m['id'] for m in groups['other']['models']], ['Provider/Future', 'Provider/Legacy'])
        self.assertEqual(groups['other']['supported_endpoints'], ['/v1/future'])
        self.assertEqual(groups['speech']['sdk_methods'], [])
        groups['alignment']['models'][0]['features'].append('changed')
        self.assertEqual(source, CATALOG)
        self.assertNotIn('changed', groups['diarization']['models'][0]['features'])
        self.assertEqual(group_models({'object':'list', 'data':[]}), {})
        for group in groups.values():
            for method in group['sdk_methods']:
                self.assertTrue(callable(getattr(EdgeSpeak, method)))
                self.assertTrue(callable(getattr(AsyncEdgeSpeak, method)))

    def test_sync_only_reads_catalog_and_preserves_data(self):
        calls=[]
        def handle(request):
            calls.append((request.method, request.url.path))
            return httpx.Response(200, json=CATALOG)
        with EdgeSpeak(base_url='http://localhost:1118/v1') as client:
            client._http.close()
            client._http=httpx.Client(base_url='http://localhost:1118/v1/', transport=httpx.MockTransport(handle))
            self.assertEqual(client.models()["groups"], group_models(CATALOG))
            self.assertEqual(client.models()["data"], CATALOG["data"])
        self.assertEqual(calls, [('GET','/v1/models')]*2)

class AsyncModelCatalogTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_matches_sync_and_only_reads_catalog(self):
        calls=[]
        async def handle(request):
            calls.append((request.method,request.url.path))
            return httpx.Response(200,json=CATALOG)
        async with AsyncEdgeSpeak(base_url='http://localhost:1118/v1',transport=httpx.MockTransport(handle)) as client:
            self.assertEqual((await client.models())["groups"],group_models(CATALOG))
        self.assertEqual(calls,[('GET','/v1/models')])

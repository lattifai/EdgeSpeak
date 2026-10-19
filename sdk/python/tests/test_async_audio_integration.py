"""Real short-audio equivalence across sync/async, paths/bytes/NumPy."""
import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave

import numpy as np

from edgespeak import AsyncEdgeSpeak, AudioSamples, EdgeSpeak
from runtime_cli import resolve_cli


def assert_alignment(test, actual, expected):
    test.assertEqual(len(actual['segments']),len(expected['segments']))
    for a,b in zip(actual['segments'],expected['segments']):
        test.assertEqual(a['text'],b['text'])
        test.assertAlmostEqual(a['start'],b['start'],delta=.03)
        test.assertAlmostEqual(a['end'],b['end'],delta=.03)


class RealAsyncAudioTests(unittest.TestCase):
    def test_real_sync_async_all_audio_inputs(self):
        fixture=getattr(self,'audio_fixture',None) or Path(__file__).resolve().parents[4]/'code/desktop/tests/data/example.wav'
        with wave.open(str(fixture),'rb') as source:
            self.assertEqual((source.getsampwidth(),source.getnchannels()),(2,1))
            rate=source.getframerate(); raw=source.readframes(4*rate)
        samples=np.frombuffer(raw,dtype='<i2').copy()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'speech.wav'
            with wave.open(str(path),'wb') as wav:
                wav.setparams((1,2,rate,0,'NONE','not compressed')); wav.writeframes(raw)
            variants=[(path,{}),(path.read_bytes(),{}),(samples,{'sample_rate':rate}),(AudioSamples(samples,rate),{})]
            with patch('edgespeak._bootstrap.ensure_cli',return_value=resolve_cli()):
                with EdgeSpeak(device='cpu',timeout=180,startup_timeout=60) as sync:
                    expected=sync.transcribe(path)
                    self.assertTrue(expected['text'].strip())
                    reference=expected['text']
                    aligned=sync.align(path,text=reference)
                    self.assertTrue(aligned['segments'])
                    turns=sync.diarize(path)
                    embedding=sync.speaker_embedding(path)
                    reference_segments=[{'text':reference}]
                    diff=sync.diff_align(path,reference_segments=reference_segments,transcript_segments=reference_segments)
                    downsampled=sync.upsample(path,sample_rate=8000)
                    for value,options in variants[1:]:
                        with self.subTest(mode='sync',input=type(value).__name__):
                            self.assertEqual(sync.diarize(value,**options),turns)
                            actual=sync.speaker_embedding(value,**options)
                            np.testing.assert_allclose(actual['data'][0]['embedding'],embedding['data'][0]['embedding'],atol=1e-5)
                            actual=sync.diff_align(value,reference_segments=reference_segments,transcript_segments=reference_segments,**options)
                            self.assertEqual(actual,diff)
                            upoptions={'input_sample_rate':rate} if isinstance(value,np.ndarray) else {}
                            self.assertEqual(sync.upsample(value,sample_rate=8000,**upoptions),downsampled)
                async def run():
                    async with AsyncEdgeSpeak(device='cpu',timeout=180,startup_timeout=60,max_concurrency=1) as client:
                        for value,options in variants:
                            with self.subTest(mode='async',input=type(value).__name__):
                                actual=await client.transcribe(value,**options)
                                self.assertEqual(actual['text'],reference)
                                assert_alignment(self,await client.align(value,text=reference,**options),aligned)
                                self.assertEqual(await client.diarize(value,**options),turns)
                                actual=await client.speaker_embedding(value,**options)
                                np.testing.assert_allclose(actual['data'][0]['embedding'],embedding['data'][0]['embedding'],atol=1e-5)
                                actual=await client.diff_align(value,reference_segments=reference_segments,transcript_segments=reference_segments,**options)
                                self.assertEqual(actual,diff)
                                upoptions={'input_sample_rate':rate} if isinstance(value,np.ndarray) else {}
                                self.assertEqual(await client.upsample(value,sample_rate=8000,**upoptions),downsampled)
                        batch=await client.speaker_embedding([path,path.read_bytes(),AudioSamples(samples,rate)])
                        self.assertEqual(len(batch['data']),3)
                        for index,item in enumerate(batch['data']):
                            self.assertEqual(item['index'],index)
                            np.testing.assert_allclose(item['embedding'],embedding['data'][0]['embedding'],atol=1e-5)
                        async with client.align(AudioSamples(samples,rate),text=reference,progress=True) as events:
                            result=[event async for event in events]
                        assert_alignment(self,result[-1],aligned)
                        self.assertEqual(client._audio_budget.used,0)
                asyncio.run(run())

    def test_real_unified_concurrency_owned_and_attached(self):
        fixture=Path(__file__).resolve().parents[4]/'code/desktop/tests/data/example.wav'
        with wave.open(str(fixture),'rb') as source:
            rate=source.getframerate(); raw=source.readframes(4*rate)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'short.wav'
            with wave.open(str(path),'wb') as wav:
                wav.setparams((1,2,rate,0,'NONE','not compressed'));wav.writeframes(raw)
            with patch('edgespeak._bootstrap.ensure_cli',return_value=resolve_cli()):
                with EdgeSpeak(device='cpu',max_concurrency=1,startup_timeout=60) as owner:
                    reference=owner.transcribe(path)['text']
                    expected=owner.align(path,text=reference)
                    async def run():
                        # Client can admit three jobs while the existing server remains capped at one.
                        async with AsyncEdgeSpeak(base_url=str(owner._http.base_url).rstrip('/'),
                            gateway_key=owner._http.headers['authorization'].removeprefix('Bearer '),
                            max_concurrency=3) as attached:
                            jobs=asyncio.gather(attached.transcribe(path.read_bytes()),
                                attached.align(path.read_bytes(),text=reference),
                                attached.upsample(path.read_bytes(),sample_rate=8000))
                            self.assertIsInstance(await asyncio.wait_for(attached.health(),5),dict)
                            transcript,aligned,audio=await asyncio.wait_for(jobs,120)
                            self.assertEqual(transcript['text'],reference)
                            assert_alignment(self,aligned,expected)
                            self.assertTrue(audio.startswith(b'RIFF'))
                        self.assertIsInstance(owner.health(),dict)
                    asyncio.run(run())

    def test_real_async_owned_and_attached_lifetimes(self):
        from test_cli_integration import wait_closed
        async def run():
            async with AsyncEdgeSpeak(device='cpu') as first, AsyncEdgeSpeak(device='cpu') as second:
                a,b=str(first._http.base_url),str(second._http.base_url)
                self.assertNotEqual(a,b)
                async with AsyncEdgeSpeak(base_url=a,gateway_key=first._http.headers['authorization'][7:]) as attached:
                    self.assertEqual((await attached.health())['status'],'ok')
                self.assertEqual((await first.health())['status'],'ok')
                await first.aclose()
                await asyncio.to_thread(wait_closed,a)
                self.assertEqual((await second.health())['status'],'ok')
            await asyncio.to_thread(wait_closed,b)
        with patch('edgespeak._bootstrap.ensure_cli',return_value=resolve_cli()):
            asyncio.run(run())

    def test_real_async_gc_closes_owned_cli_lease(self):
        import gc
        from test_cli_integration import wait_closed
        async def run():
            client=AsyncEdgeSpeak(device='cpu')
            await client.health()
            url=str(client._http.base_url)
            # Isolate the CLI fallback: network cleanup requires explicit aclose.
            await client._http.aclose()
            del client; gc.collect()
            await asyncio.to_thread(wait_closed,url)
        with patch('edgespeak._bootstrap.ensure_cli',return_value=resolve_cli()):
            asyncio.run(run())

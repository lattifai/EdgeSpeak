"""Async lifecycle, cancellation, upload and stream regressions."""
import asyncio
import inspect
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import wave

import httpx
import numpy as np

from edgespeak import AsyncEdgeSpeak, AsyncEventStream, AsyncStreamRequest, AudioSamples, EdgeSpeak, EdgeSpeakError
from edgespeak._input_audio import AudioPlan


class Chunks(httpx.AsyncByteStream):
    def __init__(self, payload):
        self.payload = payload
        self.closed = False
    async def __aiter__(self):
        for byte in self.payload:
            yield bytes([byte])
    async def aclose(self): self.closed = True


class AsyncClientTests(unittest.IsolatedAsyncioTestCase):
    async def client(self, handler=None, **kwargs):
        self.requests = []
        async def default(request):
            await request.aread()
            self.requests.append(request)
            return httpx.Response(200, json={'text':'hello', 'segments':[], 'data':[]})
        c = AsyncEdgeSpeak(base_url='http://localhost:1118/v1', transport=httpx.MockTransport(handler or default), **kwargs)
        self.addAsyncCleanup(c.aclose)
        return c

    async def test_all_audio_methods_and_wire_input(self):
        c = await self.client()
        for value, options in ((b'encoded',{}),(np.zeros((3,2),dtype=np.int16),{'sample_rate':8000}),(AudioSamples(np.zeros(4),24000),{})):
            for method,extra in ((c.transcribe,{}),(c.align,{'text':'hello'}),(c.diarize,{}),(c.speaker_embedding,{})):
                await method(value,**options,**extra)
                request = self.requests[-1]
                self.assertEqual(int(request.headers['content-length']),len(request.content))
                self.assertNotIn('transfer-encoding',request.headers)
                self.assertIn(b'filename="audio.',request.content)
                self.assertNotIn(b'name="sample_rate"',request.content)
                self.assertEqual(c._audio_budget.used,0)
        await c.speaker_embedding([b'encoded', AudioSamples(np.zeros(3),16000)])
        self.assertEqual(self.requests[-1].content.count(b'name="file"'),2)

    async def test_validation_is_deferred_and_signatures_match(self):
        c = AsyncEdgeSpeak(base_url='http://localhost:1118/v1')
        call = c.transcribe(b'')
        self.assertIsNone(c._loop)
        with self.assertRaises(ValueError): await call
        self.addAsyncCleanup(c.aclose)
        sync_names = [n for n in vars(EdgeSpeak) if not n.startswith('_') and n != 'close']
        for name in sync_names:
            self.assertTrue(hasattr(AsyncEdgeSpeak,name),name)
            self.assertEqual(inspect.signature(getattr(EdgeSpeak,name)).parameters,
                             inspect.signature(getattr(AsyncEdgeSpeak,name)).parameters,name)

    async def test_generation_stream_unicode_null_error_and_terminal(self):
        for method,kwargs,payload in (
            ('chat_completions',{'messages':[{'role':'user','content':'hi'}]},'data: {"delta":"字\\u2028文","error":null}\r\n\r\ndata: [DONE]\r\n\r\n'),
            ('responses',{'input':'hi'},'event: response.completed\ndata: {"response":{"status":"completed"}}\n\n'),
            ('messages',{'messages':[{'role':'user','content':'hi'}],'max_tokens':2},'event: message_stop\ndata: {}\n\n')):
            chunks = Chunks(payload.encode())
            c = await self.client(lambda r:httpx.Response(200,stream=chunks,headers={'content-type':'text/event-stream'}))
            request = getattr(c,method)(model='fixture',stream=True,**kwargs)
            self.assertIsInstance(request,AsyncStreamRequest)
            async with request as events:
                result = [event async for event in events]
            self.assertTrue(result)
            self.assertTrue(chunks.closed)
            self.assertEqual(c._slots._value,c._max_concurrency)
            with self.assertRaisesRegex(RuntimeError,'once'): await request

    async def test_audio_stream_budget_freed_and_nested_request(self):
        async def handler(request):
            await request.aread()
            return httpx.Response(200,stream=Chunks(b'data: {"text":"hi"}\n\ndata: [DONE]\n\n'))
        c = await self.client(handler,max_in_flight_audio_bytes=4,max_concurrency=2)
        async with c.transcribe(b'1234',stream=True) as events:
            self.assertEqual(c._audio_budget.used,0)
            async for event in events:
                async with c.transcribe(b'1234',stream=True) as inner:
                    self.assertEqual(len([e async for e in inner]),1)

    async def test_stream_errors_and_cancel_close_response(self):
        for payload,code in ((b'data: {"x":1}\n\n','incomplete_stream'),
                             (b'data: {"error":{"code":"api_key_expired"}}\n\n','api_key_expired')):
            chunks = Chunks(payload)
            c = await self.client(lambda r:httpx.Response(200,stream=chunks))
            with self.assertRaises(EdgeSpeakError) as caught:
                async with c.transcribe(b'encoded',stream=True) as stream:
                    async for _ in stream: pass
            self.assertEqual(caught.exception.code,code)
            self.assertTrue(chunks.closed)

    async def test_network_cancel_and_close_drain_calls(self):
        started = asyncio.Event()
        async def handler(request):
            started.set()
            await asyncio.Event().wait()
        c = await self.client(handler)
        request = asyncio.create_task(c.diarize(b'encoded'))
        await started.wait()
        await c.aclose()
        with self.assertRaises(asyncio.CancelledError): await request
        self.assertEqual(c._audio_budget.used,0)
        self.assertEqual(c._slots._value,c._max_concurrency)
        await c.aclose()

    async def test_cancel_encoding_waits_for_worker_and_loop_keeps_ticking(self):
        c = await self.client()
        entered = threading.Event(); finish = threading.Event(); opened=[]
        original=AudioPlan.open
        def slow(plan,*args):
            entered.set(); finish.wait(3)
            value=original(plan,*args); opened.append(value[1]); return value
        with patch.object(AudioPlan,'open',slow):
            task=asyncio.create_task(c.diarize(np.zeros(4),sample_rate=8000))
            for _ in range(100):
                if entered.is_set(): break
                await asyncio.sleep(.01)
            self.assertTrue(entered.is_set())
            task.cancel()
            await asyncio.sleep(.02)
            self.assertFalse(task.done())
            self.assertEqual(c._audio_budget.used,52)
            finish.set()
            with self.assertRaises(asyncio.CancelledError): await task
        self.assertTrue(opened[0].closed)
        self.assertEqual(c._audio_budget.used,0)

    async def test_budget_wait_does_not_take_http_slot(self):
        c = await self.client(max_in_flight_audio_bytes=4,max_concurrency=1)
        lease=await c._audio_budget.acquire_async(4)
        waiting=asyncio.create_task(c.diarize(b'1234'))
        await asyncio.sleep(.01)
        await asyncio.wait_for(c.health(),1)
        waiting.cancel()
        with self.assertRaises(asyncio.CancelledError): await waiting
        lease.close()

    async def test_shared_startup_one_cancel_other_survives(self):
        entered=threading.Event(); finish=threading.Event(); process=object()
        def start(*args):
            entered.set(); finish.wait(3)
            return process,os.getpid(),'http://localhost:1118/v1','gateway'
        with patch('edgespeak._async_client.start_process',start) as start_mock, patch('edgespeak._async_client.stop_process') as stop:
            c=AsyncEdgeSpeak(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={})))
            self.addAsyncCleanup(c.aclose)
            a=asyncio.create_task(c.health()); b=asyncio.create_task(c.health())
            for _ in range(100):
                if entered.is_set() and c._startup_waiters==2: break
                await asyncio.sleep(.01)
            a.cancel()
            with self.assertRaises(asyncio.CancelledError): await a
            self.assertFalse(b.done())
            finish.set(); await b
            self.assertEqual(c._startup_waiters,0)
            self.assertFalse(stop.called)
            await c.aclose()
            stop.assert_called_once_with(process,os.getpid())

    async def test_all_startup_waiters_cancel_releases_late_process(self):
        entered=threading.Event(); finish=threading.Event(); process=object()
        def start(*args):
            entered.set(); finish.wait(3)
            return process,os.getpid(),'http://localhost:1118/v1','gateway'
        with patch('edgespeak._async_client.start_process',start),patch('edgespeak._async_client.stop_process') as stop:
            c=AsyncEdgeSpeak()
            self.addAsyncCleanup(c.aclose)
            task=asyncio.create_task(c.health())
            for _ in range(100):
                if entered.is_set(): break
                await asyncio.sleep(.01)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task
            finish.set()
            await c.aclose()
            stop.assert_called_once_with(process,os.getpid())

    async def test_attached_environment_hooks_transport_and_errors(self):
        seen=[]
        async def hook(request): seen.append(request.headers.get('authorization'))
        with patch.dict(os.environ,{'EDGESPEAK_API_KEY':'bad account env','HTTPS_PROXY':'http://invalid'}):
            c=await self.client(event_hooks={'request':[hook]},gateway_key='gateway')
            await c.health()
        self.assertEqual(seen,['Bearer gateway'])
        self.assertFalse(c._http._trust_env)
        c=await self.client(lambda r:httpx.Response(401,json={'error':{'code':'api_key_expired'}}))
        with self.assertRaises(EdgeSpeakError) as error: await c.health()
        self.assertEqual(error.exception.code,'api_key_expired')
        with patch('edgespeak._async_client.os.getpid',return_value=-1):
            with self.assertRaisesRegex(RuntimeError,'fork'): await c.health()

    async def test_paths_spool_and_upsample_header_rate(self):
        output=io.BytesIO()
        with wave.open(output,'wb') as wav:
            wav.setparams((2,2,8000,0,'NONE','not compressed')); wav.writeframes(bytes(8))
        requests=[]
        async def handler(request):
            requests.append(request); await request.aread()
            return httpx.Response(200,content=output.getvalue(),headers={'content-type':'audio/wav'})
        c=await self.client(handler,audio_spool_threshold_bytes=1)
        result=await c.upsample(AudioSamples(np.zeros((4,2)),16000),sample_rate=8000)
        self.assertEqual(result,output.getvalue())
        self.assertIn(b'name="sample_rate"\r\n\r\n8000',requests[-1].content)
        self.assertNotIn(b'input_sample_rate',requests[-1].content)
        self.assertIn((16000).to_bytes(4,'little'),requests[-1].content)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'fixture.wav'; path.write_bytes(output.getvalue())
            await c.upsample(path,sample_rate=8000)
            self.assertEqual(int(requests[-1].headers['content-length']),len(requests[-1].content))
        self.assertEqual(c._audio_budget.used,0)

    async def test_json_routes_and_invalid_generation(self):
        c=await self.client()
        await c.usage(refresh=True)
        await c.models(); await c.models_running(); await c.models_downloads()
        for method in (c.models_load,c.models_unload,c.models_download,c.models_download_cancel): await method('fixture')
        await c.text_normalizations('12',language='en')
        await c.segment('hello')
        await c.speaker_similarity([1,0],[1,0])
        await c.tokenize('hello',model='fixture')
        await c.chat_completions([{'role':'user','content':'hi'}],model='fixture')
        await c.responses('hello',model='fixture')
        await c.messages([{'role':'user','content':'hi'}],model='fixture',max_tokens=2)
        before=len(self.requests)
        for call in (c.transcribe(b'encoded',candidates=9),c.align(b'encoded',text='a',start=0),
                     c.chat_completions([],model='fixture'),c.responses('a',model='fixture',top_p=2),
                     c.messages([],model='fixture',max_tokens=0)):
            with self.assertRaises(ValueError): await call
        self.assertEqual(before,len(self.requests))

    async def test_cross_loop_and_transport_closed_without_use(self):
        c=await self.client()
        await c.health()
        def other_loop():
            async def run(): await c.health()
            with self.assertRaisesRegex(RuntimeError,'different event loop'): asyncio.run(run())
        await asyncio.to_thread(other_loop)
        class Transport(httpx.AsyncBaseTransport):
            closed=False
            async def aclose(self): self.closed=True
        transport=Transport()
        unused=AsyncEdgeSpeak(base_url='http://localhost:1118/v1',transport=transport)
        await unused.aclose()
        self.assertTrue(transport.closed)

    async def test_http_hook_failure_closes_upload_and_slots(self):
        async def fail(request): raise LookupError('fixture hook')
        c=await self.client(event_hooks={'request':[fail]})
        with self.assertRaises(LookupError): await c.diarize(b'encoded')
        self.assertEqual(c._audio_budget.used,0)
        self.assertEqual(c._slots._value,c._max_concurrency)

    async def test_close_still_closes_transport_when_stream_close_raises(self):
        class BadChunks(Chunks):
            async def aclose(self):
                self.closed=True
                raise LookupError('fixture close')
        class Transport(httpx.AsyncBaseTransport):
            closed=False
            async def handle_async_request(self,request):
                await request.aread()
                return httpx.Response(200,stream=BadChunks(b'data: {"x":1}\n\n'))
            async def aclose(self): self.closed=True
        transport=Transport()
        c=AsyncEdgeSpeak(base_url='http://localhost:1118/v1',transport=transport)
        stream=await c.transcribe(b'encoded',stream=True)
        with self.assertRaises(LookupError): await c.aclose()
        self.assertTrue(transport.closed)
        self.assertEqual(c._slots._value,c._max_concurrency)
        with self.assertRaises(EdgeSpeakError): await stream.__anext__()

    async def test_repeat_cancel_during_stream_cleanup_drains_close(self):
        entered=asyncio.Event(); finish=asyncio.Event()
        class SlowClose(Chunks):
            async def aclose(self):
                entered.set(); await finish.wait(); self.closed=True
        chunks=SlowClose(b'data: {"x":1}\n\n')
        c=await self.client(lambda r:httpx.Response(200,stream=chunks))
        stream=await c.transcribe(b'encoded',stream=True)
        closing=asyncio.create_task(stream.aclose())
        await entered.wait(); closing.cancel(); await asyncio.sleep(0); closing.cancel()
        await asyncio.sleep(.01)
        self.assertFalse(closing.done())
        finish.set()
        with self.assertRaises(asyncio.CancelledError): await closing
        self.assertTrue(chunks.closed)
        self.assertEqual(c._slots._value,c._max_concurrency)

    async def test_aggregate_budget_bounds_actual_conversions(self):
        c=await self.client(max_in_flight_audio_bytes=8,max_concurrency=3)
        finish=threading.Event(); entered=[]; original=AudioPlan.open
        def block(plan,*args):
            entered.append(plan.size)
            finish.wait(3)
            return original(plan,*args)
        with patch.object(AudioPlan,'open',block):
            calls=[asyncio.create_task(c.diarize(b'1234')) for _ in range(3)]
            for _ in range(100):
                if len(entered)==2: break
                await asyncio.sleep(.01)
            self.assertEqual(len(entered),2)
            self.assertEqual(c._audio_budget.used,8)
            await asyncio.wait_for(c.health(),1)
            calls[-1].cancel()
            with self.assertRaises(asyncio.CancelledError): await calls[-1]
            finish.set(); await asyncio.gather(*calls[:2])
        self.assertEqual(c._audio_budget.used,0)

    async def test_close_from_request_hook_reports_error_instead_of_deadlock(self):
        async def hook(request): await c.aclose()
        c=await self.client(event_hooks={'request':[hook]})
        with self.assertRaisesRegex(RuntimeError,'active client request/hook'):
            await asyncio.wait_for(c.health(),1)

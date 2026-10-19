"""Unified request ceilings and control-plane liveness."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
import io
import json
import subprocess
import threading
import unittest
from unittest.mock import patch, MagicMock
import httpx
from edgespeak import EdgeSpeak, AsyncEdgeSpeak, MIN_CLI_VERSION
from edgespeak._process import start_process, RuntimeStartError

URL='http://localhost:1118/v1'

class ConcurrencyTests(unittest.TestCase):
    def test_validation_and_owned_forwarding(self):
        for cls in (EdgeSpeak,AsyncEdgeSpeak):
            for n in (0,-1,65,True,1.5,'2'):
                with self.subTest(cls=cls,n=n),self.assertRaisesRegex(ValueError,'max_concurrency'):
                    cls(base_url=URL,max_concurrency=n)
        for n in (None,1,64):
            with patch('edgespeak._client.start_process',return_value=(None,os.getpid(),URL,'key')) as start:
                with EdgeSpeak(max_concurrency=n): pass
                self.assertEqual(start.call_args.args,(30,None,None)+(() if n is None else (n,)))
            with patch('edgespeak._client.start_process') as start:
                with EdgeSpeak(base_url=URL,max_concurrency=n): pass
                start.assert_not_called()

    def test_unsupported_cli_probe_never_starts_or_leaks_output(self):
        for result in (subprocess.CompletedProcess([],0,b'old help',b'sensitive'),subprocess.CompletedProcess([],1,b'--max-concurrency',b'')):
            with patch('edgespeak._bootstrap.ensure_cli',return_value='cli'),patch('edgespeak._process.subprocess.run',return_value=result),patch('edgespeak._process.subprocess.Popen') as spawn:
                with self.assertRaisesRegex(RuntimeStartError,'does not support max_concurrency') as error:
                    start_process(1,max_concurrency=2)
                self.assertNotIn('sensitive',str(error.exception));spawn.assert_not_called()
        with patch('edgespeak._bootstrap.ensure_cli',return_value='cli'),patch('edgespeak._process.subprocess.run',side_effect=subprocess.TimeoutExpired('cli',1)):
            with self.assertRaisesRegex(RuntimeStartError,'Cannot verify'): start_process(1,max_concurrency=2)

    def test_supported_cli_gets_same_ceiling_in_argv(self):
        process=MagicMock(); process.poll.return_value=None;process.wait.return_value=0
        # Ready addresses must be canonical loopback, independent of constructor URL tests.
        process.stdout=io.BytesIO((json.dumps({'event':'ready','protocol':'edgespeak-sdk-v2','version':MIN_CLI_VERSION,'base_url':'http://127.0.0.1:1118/v1'})+'\n').encode())
        with patch('edgespeak._bootstrap.ensure_cli',return_value='cli'),patch('edgespeak._process.subprocess.run',return_value=subprocess.CompletedProcess([],0,b'--max-concurrency',b'')) as probe,patch('edgespeak._process.subprocess.Popen',return_value=process) as spawn:
            with EdgeSpeak(max_concurrency=2): pass
            self.assertEqual(spawn.call_args.args[0],['cli','serve','--sdk','--max-concurrency','2'])
            self.assertEqual(probe.call_args.args[0],['cli','serve','--help'])

    def test_sync_audio_stream_releases_upload_but_not_request_ticket(self):
        def handler(req):
            req.read()
            if req.method=='GET': return httpx.Response(200,json={'capabilities':{'alignment':True}})
            return httpx.Response(200,headers={'content-type':'application/x-ndjson'},content=b'{"text":"hi","segments":[]}\n')
        with EdgeSpeak(base_url=URL,max_concurrency=1,transport=httpx.MockTransport(handler)) as c:
            stream=c.align(b'encoded',text='hi',progress=True)
            self.assertEqual(c._audio_budget.used,0)
            self.assertEqual(c._request_budget.used,1)
            stream.close()
            self.assertEqual(c._request_budget.used,0)

    def test_sync_cross_route_ceiling_and_health_bypass(self):
        entered,release=threading.Event(),threading.Event()
        lock=threading.Lock();active=peak=0
        def handler(req):
            nonlocal active,peak
            if req.method=='GET': return httpx.Response(200,json={'ok':True})
            with lock: active+=1;peak=max(peak,active)
            entered.set()
            try:
                if not release.wait(3): raise AssertionError('release timeout')
                return httpx.Response(200,json={})
            finally:
                with lock: active-=1
        with EdgeSpeak(base_url=URL,max_concurrency=1,transport=httpx.MockTransport(handler)) as c,ThreadPoolExecutor(2) as pool:
            first=pool.submit(c.text_normalizations,'one',language='en')
            self.assertTrue(entered.wait(2))
            second=pool.submit(c._request,'POST','speaker/similarity',json={})
            try:
                self.assertTrue(c.health()['ok']);self.assertFalse(second.done())
            finally: release.set()
            first.result(3);second.result(3)
            self.assertEqual(peak,1);self.assertEqual(c._request_budget.used,0)

    def test_sync_stream_holds_slot_until_close(self):
        def handler(req):
            req.read()
            if req.method=='GET': return httpx.Response(200,json={'ok':True})
            return httpx.Response(200,headers={'content-type':'text/event-stream'},content=b'data: [DONE]\n\n')
        with EdgeSpeak(base_url=URL,max_concurrency=1,transport=httpx.MockTransport(handler)) as c:
            stream=c.chat_completions([{'role':'user','content':'hi'}],model='test',stream=True)
            self.assertEqual(c._request_budget.used,1);self.assertTrue(c.health()['ok'])
            stream.close();stream.close();self.assertEqual(c._request_budget.used,0)

class AsyncConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_ceiling_control_bypass_and_cancel(self):
        async def handler(req):
            await req.aread()
            if req.method=='GET' or '/models/' in req.url.path: return httpx.Response(200,json={'ok':True})
            return httpx.Response(200,headers={'content-type':'text/event-stream'},content=b'data: [DONE]\n\n')
        async with AsyncEdgeSpeak(base_url=URL,max_concurrency=1,transport=httpx.MockTransport(handler)) as c:
            stream=await c.chat_completions([{'role':'user','content':'hi'}],model='test',stream=True)
            pending=asyncio.create_task(c.text_normalizations('one',language='en'))
            await asyncio.sleep(0);self.assertFalse(pending.done())
            self.assertTrue((await asyncio.wait_for(c.health(),1))['ok'])
            self.assertTrue((await asyncio.wait_for(c._request('POST','models/unload',json={}),1))['ok'])
            pending.cancel()
            with self.assertRaises(asyncio.CancelledError): await pending
            self.assertEqual(c._slots._value,0)
            await stream.aclose();self.assertEqual(c._slots._value,1)

    async def test_owned_forwarding(self):
        for n in (None,2):
            with patch('edgespeak._async_client.start_process',return_value=(None,os.getpid(),URL,'key')) as start,patch('edgespeak._async_client.stop_process'):
                async with AsyncEdgeSpeak(max_concurrency=n): pass
                self.assertEqual(start.call_args.args,(30,None,None)+(() if n is None else (n,)))

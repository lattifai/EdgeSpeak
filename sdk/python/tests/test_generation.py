"""Protocol-specific generation/speech stream contracts and cleanup."""
import json
import unittest

import httpx
from edgespeak import EdgeSpeak, EdgeSpeakError, EventStream


class TrackedStream(httpx.SyncByteStream):
    def __init__(self, chunks, error=None):
        self.chunks = chunks
        self.error = error
        self.closed = False
    def __iter__(self):
        yield from self.chunks
        if self.error:
            raise self.error
    def close(self):
        self.closed = True


class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.response = httpx.Response(200, json={"id": "response"})
        self.client = EdgeSpeak(base_url="http://localhost:1118/v1", gateway_key="gateway-token")
        self.client._http.close()
        def handle(request):
            self.requests.append(request)
            return self.response
        self.client._http = httpx.Client(base_url="http://localhost:1118/v1/", transport=httpx.MockTransport(handle))
        self.addCleanup(self.client._http.close)
        self.addCleanup(self.client.close)

    def events(self, data, *, media_type="text/event-stream", error=None):
        # Split into individual bytes, including boundaries inside UTF-8 and CRLF.
        stream = TrackedStream([bytes([b]) for b in data.encode()], error)
        self.response = httpx.Response(200, headers={"content-type": media_type}, stream=stream)
        return stream

    def call(self, protocol):
        if protocol == "chat":
            return self.client.chat_completions([{"role": "user", "content": "hello"}], model="model", stream=True)
        if protocol == "responses":
            return self.client.responses("hello", model="model", stream=True)
        if protocol == "messages":
            return self.client.messages([{"role": "user", "content": "hello"}], model="model", max_tokens=10, stream=True)
        raise AssertionError("unknown protocol")

    def test_json_routes_and_protocol_parameters(self):
        messages = [{"role": "user", "content": [{"type": "text", "text": "Describe"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]}]
        self.client.chat_completions(messages, model="vision", temperature=.2, max_tokens=64, options={"tools": []})
        request = self.requests[-1]
        self.assertEqual(request.url.path, "/v1/chat/completions")
        self.assertEqual(json.loads(request.content), {"model": "vision", "messages": messages, "stream": False, "temperature": .2, "max_tokens": 64, "tools": []})
        self.client.responses("hello", model="model", instructions="concise", max_output_tokens=32, options={"reasoning": {"effort": "low"}})
        self.assertEqual(self.requests[-1].url.path, "/v1/responses")
        self.assertEqual(json.loads(self.requests[-1].content)["max_output_tokens"], 32)
        self.client.messages(messages, model="model", system="concise", max_tokens=32)
        self.assertEqual(self.requests[-1].url.path, "/v1/messages")
        self.assertEqual(json.loads(self.requests[-1].content)["system"], "concise")
        self.client.tokenize("hello", model="model", options={"with_pieces": True})
        self.assertEqual(json.loads(self.requests[-1].content), {"content": "hello", "model": "model", "with_pieces": True})
        self.client.tokenize(model="remote", options={"prompt": "hello"})
        self.assertNotIn("content", json.loads(self.requests[-1].content))

    def test_chat_waits_for_done_after_finish_reason_and_usage(self):
        stream = self.events(': ping\r\n\r\ndata: {"choices":[{"finish_reason":"stop"}]}\r\n\r\ndata: {"choices":[],"usage":{"total_tokens":7}}\r\n\r\ndata: [DONE]\r\n\r\n')
        values = list(self.call("chat"))
        self.assertEqual(len(values), 2)
        self.assertEqual(values[1]["usage"]["total_tokens"], 7)
        self.assertTrue(stream.closed)

    def test_responses_and_messages_only_close_at_protocol_terminal(self):
        for protocol, middle, terminal in (("responses", "response.output_text.delta", "response.completed"),
                                           ("messages", "content_block_stop", "message_stop")):
            with self.subTest(protocol=protocol):
                stream = self.events(f'event: {middle}\ndata: {{"text":"字"}}\n\nevent: {terminal}\ndata: {{"type":"{terminal}"}}\n\n')
                values = list(self.call(protocol))
                self.assertEqual([v["type"] for v in values], [middle, terminal])
                self.assertTrue(stream.closed)

    def test_eof_and_wrong_done_are_not_success(self):
        for protocol in ("chat", "responses", "messages"):
            stream = self.events('data: {"type":"delta"}\n\n')
            with self.subTest(protocol=protocol), self.assertRaises(EdgeSpeakError) as error:
                list(self.call(protocol))
            self.assertEqual(error.exception.code, "incomplete_stream")
            self.assertTrue(stream.closed)
        for protocol in ("responses", "messages"):
            self.events('data: [DONE]\n\n')
            with self.assertRaises(EdgeSpeakError):
                list(self.call(protocol))

    def test_stream_errors_failed_and_incomplete_are_distinct_and_safe(self):
        cases = [("responses", {"type": "response.failed", "response": {"error": {"code": "model_failed", "message": "private-secret"}}}, "model_failed"),
                 ("responses", {"type": "response.incomplete", "response": {"incomplete_details": {"reason": "max_output_tokens"}}}, "incomplete_response"),
                 ("messages", {"type": "error", "error": {"type": "overloaded_error", "message": "private-secret"}}, "overloaded_error")]
        for protocol, value, code in cases:
            stream = self.events("data: " + json.dumps(value) + "\n\n")
            with self.subTest(protocol=protocol, code=code), self.assertRaises(EdgeSpeakError) as error:
                list(self.call(protocol))
            self.assertEqual(error.exception.code, code)
            self.assertNotIn("private-secret", str(error.exception))
            self.assertTrue(stream.closed)
        for status, code in (("failed", "model_failed"), ("incomplete", "incomplete_response")):
            self.response = httpx.Response(200, json={"status": status, "error": {"code": "model_failed"}})
            with self.assertRaises(EdgeSpeakError) as error:
                self.client.responses("hello", model="model")
            self.assertEqual(error.exception.code, code)

    def test_close_timeout_wrong_content_type_and_http_error_cleanup(self):
        for protocol in ("chat", "responses", "messages"):
            stream = self.events('data: {"type":"delta"}\n\n')
            with self.call(protocol) as events:
                next(events)
            self.assertTrue(stream.closed)
            stream = self.events('', error=httpx.ReadTimeout("private-secret"))
            with self.assertRaises(EdgeSpeakError) as error:
                list(self.call(protocol))
            self.assertEqual(error.exception.code, "request_timeout")
            self.assertTrue(stream.closed)
            stream = self.events('{}', media_type="application/json")
            with self.assertRaises(EdgeSpeakError) as error:
                self.call(protocol)
            self.assertEqual(error.exception.code, "invalid_response")
            self.assertTrue(stream.closed)
        stream = self.events('data: {"type":"delta"}\n\n')
        events = self.call("responses")
        self.client.close()
        self.assertTrue(stream.closed)
        with self.assertRaises(EdgeSpeakError) as error:
            next(events)
        self.assertEqual(error.exception.code, "stream_closed")

    def test_invalid_generation_inputs_never_send(self):
        calls = [lambda: self.client.chat_completions([], model="model"),
                 lambda: self.client.chat_completions("hello", model="model"),
                 lambda: self.client.responses("hello", model="", stream=True),
                 lambda: self.client.responses("hello", model="model", stream=1),
                 lambda: self.client.responses("hello", model="model", temperature=float('nan')),
                 lambda: self.client.messages([], model="model", max_tokens=1),
                 lambda: self.client.messages([{}], model="model", max_tokens=True),
                 lambda: self.client.tokenize(model="model")]
        for key in ("model", "stream", "input", "temperature"):
            calls.append(lambda key=key: self.client.responses("hello", model="model", options={key: "override"}))
        for call in calls:
            with self.assertRaises(ValueError):
                call()
        self.assertFalse(self.requests)


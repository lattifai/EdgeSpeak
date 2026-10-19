"""Protocol-specific generation stream contracts and cleanup."""
import json
from contextlib import ExitStack
import os
from unittest.mock import patch
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
        def handle(request):
            self.requests.append(request)
            return self.response
        original = httpx.Client
        def factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handle)
            return original(*args, **kwargs)
        self.factory = factory
        with patch("edgespeak._client.httpx.Client", side_effect=factory):
            self.client = EdgeSpeak(base_url="http://localhost:1118/v1", gateway_key="gateway-token")
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
        self.assertEqual(self.requests[-1].headers["anthropic-version"], "2023-06-01")
        self.client.messages(messages, model="model", max_tokens=32, anthropic_beta="test-beta")
        self.assertEqual(self.requests[-1].headers["anthropic-beta"], "test-beta")
        self.assertNotIn("anthropic_beta", json.loads(self.requests[-1].content))
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
            stream = self.events('data: [DONE]\n\n')
            with self.assertRaises(EdgeSpeakError) as error:
                list(self.call(protocol))
            self.assertEqual(error.exception.code, "incomplete_stream")
            self.assertTrue(stream.closed)

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
                 lambda: self.client.tokenize(model="model"),
                 lambda: self.client.chat_completions([{}], model="model", max_tokens=True),
                 lambda: self.client.responses("hi", model="model", max_output_tokens=0),
                 lambda: self.client.responses("hi", model="model", top_p=2),
                 lambda: self.client.responses("hi", model="model", temperature=True),
                 lambda: self.client.messages([{}], model="model", max_tokens=1, anthropic_version="x\r\nInjected: key"),
                 lambda: self.client.messages([{}], model="model", max_tokens=1, options={"anthropic_beta": "other"})]
        for key in ("model", "stream", "input", "temperature"):
            calls.append(lambda key=key: self.client.responses("hello", model="model", options={key: "override"}))
        for call in calls:
            with self.assertRaises(ValueError):
                call()
        self.assertFalse(self.requests)


    def test_tokenize_accepts_provider_token_array_and_rejects_invalid_json(self):
        self.response = httpx.Response(200, json=[9, 12, 0])
        self.assertEqual(self.client.tokenize("hello", model="remote"), [9, 12, 0])
        for value in ([True], [-1], ["token"], "text", None):
            self.response = httpx.Response(200, content=json.dumps(value), headers={"content-type": "application/json"})
            with self.assertRaises(EdgeSpeakError) as error:
                self.client.tokenize("hello", model="remote")
            self.assertEqual(error.exception.code, "invalid_response")

    def test_openai_nested_and_responses_flat_error_codes_close_streams(self):
        for protocol, value, code in (
                ("chat", {"error": {"code": "rate_limit_exceeded", "message": "private-secret"}}, "rate_limit_exceeded"),
                ("responses", {"type": "error", "code": "server_error", "message": "private-secret"}, "server_error"),
                ("messages", {"type": "error", "error": {"code": None, "type": "overloaded_error"}}, "overloaded_error")):
            stream = self.events("data: " + json.dumps(value) + "\n\ndata: [DONE]\n\n")
            with self.assertRaises(EdgeSpeakError) as error:
                list(self.call(protocol))
            self.assertEqual(error.exception.code, code)
            self.assertNotIn("private-secret", str(error.exception))
            self.assertTrue(stream.closed)

    def test_non_2xx_sse_errors_close_response_and_preserve_code(self):
        for protocol in ("chat", "responses", "messages"):
            stream = TrackedStream([b'{"error":{"code":"api_key_revoked","message":"private-secret"}}'])
            self.response = httpx.Response(401, stream=stream, headers={"content-type": "application/json"})
            with self.assertRaises(EdgeSpeakError) as error:
                self.call(protocol)
            self.assertEqual(error.exception.code, "api_key_revoked")
            self.assertTrue(stream.closed)

    def test_constructor_auth_is_shared_by_json_sse_and_error_paths(self):
        self.client.responses("hi", model="model")
        self.assertEqual(self.requests[-1].headers["authorization"], "Bearer gateway-token")
        stream = self.events('data: {"type":"response.completed"}\n\n')
        list(self.call("responses"))
        self.assertEqual(self.requests[-1].headers["authorization"], "Bearer gateway-token")
        self.assertTrue(stream.closed)
        self.response = httpx.Response(404, content=b"no route")
        with self.assertRaises(EdgeSpeakError):
            self.client.responses("hi", model="model")
        self.assertEqual(self.requests[-1].headers["authorization"], "Bearer gateway-token")
        key = "esak_" + "a" * 43
        with patch.dict(os.environ, {"EDGESPEAK_API_KEY": key}), patch("edgespeak._client.start_process", return_value=(None, os.getpid(), "http://localhost:1118/v1", "owned-token")) as start, patch("edgespeak._client.httpx.Client", side_effect=self.factory):
            with EdgeSpeak() as owned:
                self.response = httpx.Response(200, json={"id": "response"})
                owned.responses("hi", model="model")
                stream = self.events('data: {"type":"response.completed"}\n\n')
                list(owned.responses("hi", model="model", stream=True))
                self.assertTrue(stream.closed)
            start.assert_called_once_with(30, key, None)
            self.assertEqual(os.environ["EDGESPEAK_API_KEY"], key)
        for request in self.requests[-2:]:
            self.assertEqual(request.headers["authorization"], "Bearer owned-token")
            self.assertNotIn(key, str(request.headers))
            self.assertNotIn(key.encode(), request.content)

    def test_null_error_is_not_a_generation_failure(self):
        for protocol, terminal in (("chat", "data: [DONE]\n\n"), ("responses", 'data: {"type":"response.completed"}\n\n'), ("messages", 'data: {"type":"message_stop"}\n\n')):
            stream = self.events('data: {"error":null,"choices":[]}\n\n' + terminal)
            values = list(self.call(protocol))
            self.assertIsNone(values[0]["error"])
            self.assertTrue(stream.closed)

    def test_generation_quota_keeps_reason_and_reset_without_message_leak(self):
        quota = {"error": {"code": "license_required", "message": json.dumps({"code": "errors.usage.exhausted", "params": {"resets_at": "2026-11-01T00:00:00Z"}})}}
        for protocol in ("chat", "responses", "messages"):
            self.response = httpx.Response(403, json=quota)
            with self.assertRaises(EdgeSpeakError) as error:
                self.call(protocol)
            self.assertEqual(error.exception.code, "license_required")
            self.assertEqual(error.exception.reason, "usage_exhausted")
            self.assertNotIn("errors.usage.exhausted", str(error.exception))
            self.assertNotIn("errors.usage.exhausted", repr(error.exception))
            self.assertEqual(error.exception.resets_at, "2026-11-01T00:00:00+00:00")
            stream = self.events("data: " + json.dumps(quota) + "\n\n")
            with self.assertRaises(EdgeSpeakError) as error:
                list(self.call(protocol))
            self.assertEqual(error.exception.reason, "usage_exhausted")
            self.assertNotIn("errors.usage.exhausted", str(error.exception))
            self.assertNotIn("errors.usage.exhausted", repr(error.exception))
            self.assertEqual(error.exception.resets_at, "2026-11-01T00:00:00+00:00")
            self.assertTrue(stream.closed)

    def test_error_body_read_failure_explicitly_closes_response(self):
        for protocol in ("chat", "responses", "messages"):
            stream = TrackedStream([b'{"error":'], httpx.ReadError("private-secret"))
            self.response = httpx.Response(503, stream=stream)
            with patch.object(self.response, "close", wraps=self.response.close) as close:
                with self.assertRaises(EdgeSpeakError) as error:
                    self.call(protocol)
                self.assertEqual(error.exception.code, "connection_failed")
                self.assertNotIn("private-secret", str(error.exception))
                close.assert_called()
            self.assertTrue(stream.closed)

    def test_flat_responses_quota_keeps_structured_reset(self):
        value = {"type": "error", "code": "license_required", "message": json.dumps({"code": "errors.usage.exhausted", "params": {"resetsAt": "2026-11-01T00:00:00Z"}})}
        self.events("data: " + json.dumps(value) + "\n\n")
        with self.assertRaises(EdgeSpeakError) as error:
            list(self.call("responses"))
        self.assertEqual(error.exception.reason, "usage_exhausted")
        self.assertEqual(error.exception.resets_at, "2026-11-01T00:00:00+00:00")

    def test_legacy_sse_ignores_event_name_and_preserves_type_error_payload(self):
        stream = self.events('event: error\ndata: {"type":"error","text":"字"}\n\ndata: [DONE]\n\n')
        with EventStream(self.client, self.response, ExitStack(), "sse") as events:
            self.assertEqual(list(events), [{"type": "error", "text": "字"}])
        self.assertTrue(stream.closed)

    def test_sse_preserves_unicode_separators_inside_json_text(self):
        text = "a\u0085b\u2028c\u2029d"
        for protocol, value, terminal in (
                ("chat", {"choices": [{"delta": {"content": text}}]}, "data: [DONE]\r\n\r\n"),
                ("responses", {"type": "response.output_text.delta", "delta": text}, 'data: {"type":"response.completed"}\r\n\r\n'),
                ("messages", {"type": "content_block_delta", "delta": {"text": text}}, 'data: {"type":"message_stop"}\r\n\r\n')):
            stream = self.events("data: " + json.dumps(value, ensure_ascii=False) + "\r\n\r\n" + terminal)
            self.assertEqual(list(self.call(protocol))[0], value)
            self.assertTrue(stream.closed)

    def test_flat_error_messages_are_never_exposed(self):
        for message in ("private-secret", {"private": "secret"}, None):
            self.events("data: " + json.dumps({"type": "error", "code": "server_error", "message": message}) + "\n\n")
            with self.assertRaises(EdgeSpeakError) as error:
                list(self.call("responses"))
            self.assertEqual(error.exception.code, "server_error")
            self.assertNotIn("private", str(error.exception))
            self.assertNotIn("private", repr(error.exception))

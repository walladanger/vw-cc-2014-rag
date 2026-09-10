"""Provider contract tests: synthetic transport and loopback only, never public inference."""
import asyncio
import base64
import importlib
import importlib.util
import io
import json
import logging
import os
import threading
import unittest
from unittest.mock import patch

import httpx


PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aXioAAAAASUVORK5CYII=')


def completion(text='ok', model='local-model', finish='stop'):
    return {'id': 'completion-1', 'model': model, 'choices': [
        {'index': 0, 'message': {'role': 'assistant', 'content': text}, 'finish_reason': finish}]}


def sse(delta=None, finish=None, model='local-model', identity='stream-1'):
    return 'data: ' + json.dumps({'id': identity, 'model': model, 'choices': [
        {'index': 0, 'delta': delta or {}, 'finish_reason': finish}]}, ensure_ascii=False) + '\r\n\r\n'


class BytesStream(httpx.AsyncByteStream):
    def __init__(self, chunks, block=False):
        self.chunks, self.block = chunks, block
        self.closed = False
        self.waiting = asyncio.Event()

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk
        if self.block:
            self.waiting.set()
            await asyncio.Event().wait()

    async def aclose(self):
        self.closed = True


class SyntheticServer:
    def __init__(self):
        self.requests = []
        self.override = None

    async def __call__(self, request):
        self.requests.append(request)
        if self.override:
            return await self.override(request)
        if request.url.path == '/v1/models':
            return httpx.Response(200, json={'data': [{'id': 'local-model', 'owned_by': 'fixture'}]})
        body = json.loads(request.content)
        if request.url.path == '/v1/embeddings':
            return httpx.Response(200, json={'model': 'local-model', 'data': [
                {'index': i, 'embedding': [float(i), 1., 2.]} for i in reversed(range(len(body['input'])))]})
        if body.get('stream'):
            raw = (': heartbeat\r\n\r\n' + sse({'role': 'assistant'}) + sse({'content': 'café'})
                   + sse(finish='stop') + 'data: [DONE]\r\n\r\n').encode()
            return httpx.Response(200, headers={'content-type': 'text/event-stream'},
                                  stream=BytesStream([raw[i:i+1] for i in range(len(raw))]))
        fmt = body.get('response_format', {})
        text = '{"ok":true}' if fmt else 'ok'
        return httpx.Response(200, json=completion(text))


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('cc_workshop.inference'),
                             'CC-T009 inference package is not implemented')
        self.api = importlib.import_module('cc_workshop.inference')

    def test_literal_policy_accepts_only_canonical_local_destinations(self):
        accepted = {'http://localhost:8080': 'http://127.0.0.1:8080/v1/',
                    'https://LOCALHOST/v1': 'https://127.0.0.1/v1/',
                    'http://127.255.255.254': 'http://127.255.255.254/v1/',
                    'http://10.0.0.1': 'http://10.0.0.1/v1/',
                    'http://172.16.0.1': 'http://172.16.0.1/v1/',
                    'http://172.31.255.254': 'http://172.31.255.254/v1/',
                    'http://192.168.1.2/v1/': 'http://192.168.1.2/v1/',
                    'http://[::1]:8080': 'http://[::1]:8080/v1/',
                    'http://[fd12::1]': 'http://[fd12::1]/v1/'}
        with patch('socket.getaddrinfo', side_effect=AssertionError('DNS must not run')):
            for raw, expected in accepted.items():
                with self.subTest(raw=raw):
                    self.assertEqual(self.api.EndpointConfig('fixture', 'generation', raw, '1').base_url, expected)

    def test_public_metadata_and_ambiguous_urls_fail_before_network(self):
        denied = ['http://8.8.8.8', 'https://api.openai.com/v1', 'http://169.254.169.254',
                  'http://100.64.0.1', 'http://172.15.1.1', 'http://192.0.2.1', 'http://0.0.0.0',
                  'http://224.0.0.1', 'http://[fe80::1]', 'http://[2001:db8::1]', 'http://[::]',
                  'http://[::ffff:127.0.0.1]', 'http://[fd12::1%25eth0]', 'http://home.local',
                  'http://localhost.', 'http://localhost.evil', 'http://127.1', 'http://2130706433',
                  'http://0177.0.0.1', 'http://0x7f000001', 'http://user:secret@127.0.0.1',
                  'http://127.0.0.1?x=1', 'http://127.0.0.1#x', 'http://127.0.0.1/v1/../api',
                  'http://127.0.0.1/%76%31', 'http://127.0.0.1\\evil', ' http://127.0.0.1',
                  'http://127.0.0.1:0', 'http://127.0.0.1:65536', 'ftp://127.0.0.1',
                  'http://%31%32%37.0.0.1', 'http://127.0.0.1/?', 'http://127.0.0.1/#']
        for raw in denied:
            with self.subTest(raw=raw), self.assertRaises(self.api.ProviderError) as caught:
                self.api.EndpointConfig('fixture', 'generation', raw, '1')
            self.assertEqual(caught.exception.code, 'INVALID_ENDPOINT')


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.assertIsNotNone(importlib.util.find_spec('cc_workshop.inference'),
                             'CC-T009 inference package is not implemented')
        self.a = importlib.import_module('cc_workshop.inference')
        self.server = SyntheticServer()
        self.client = self.a.ProviderClient(self.a.EndpointConfig('fixture', 'generation', 'http://localhost:8080', '1'),
                                            transport=httpx.MockTransport(self.server))
        self.addAsyncCleanup(self.client.aclose)

    def request(self, content='SYNTHETIC_ONLY', **kwargs):
        return self.a.ChatRequest('local-model', (self.a.ChatMessage('user', content),), **kwargs)

    async def enable(self, *features):
        declared = self.a.ProviderCapabilities('local-model',
            states={x: 'supported' for x in features}, schema_dialect='openai_json_schema')
        report = await self.client.probe_capabilities('local-model', frozenset(features), declared=declared)
        for feature in features:
            self.assertEqual(report.capabilities.states[feature], 'supported', report)
        self.server.requests.clear()
        return report

    async def response(self, body, status=200, headers=None):
        async def override(request):
            return httpx.Response(status, json=body, headers=headers)
        self.server.override = override

    async def test_model_catalog_does_not_enable_user_content(self):
        self.assertEqual((await self.client.list_models())[0].id, 'local-model')
        with self.assertRaises(self.a.ProviderError) as caught:
            await self.client.complete(self.request())
        self.assertEqual(caught.exception.code, 'CAPABILITY_UNAVAILABLE')
        self.assertEqual(len(self.server.requests), 1)

    async def test_text_probe_then_completion_has_exact_identity_and_confined_wire(self):
        await self.enable('text')
        result = await self.client.complete(self.request(max_tokens=12, temperature=0.0))
        self.assertEqual((result.text, result.response_model_id, result.complete), ('ok', 'local-model', True))
        req = self.server.requests[0]
        self.assertEqual(str(req.url), 'http://127.0.0.1:8080/v1/chat/completions')
        self.assertEqual(json.loads(req.content), {'model': 'local-model', 'messages': [
            {'role': 'user', 'content': 'SYNTHETIC_ONLY'}], 'max_tokens': 12, 'temperature': 0.0, 'stream': False})

    async def test_capabilities_do_not_transfer_to_another_model_or_configuration(self):
        await self.enable('text')
        with self.assertRaises(self.a.ProviderError):
            await self.client.complete(self.a.ChatRequest('other-model', (self.a.ChatMessage('user', 'x'),)))
        self.assertEqual(self.server.requests, [])

    async def test_unsupported_vision_blocks_before_serializing_or_sending(self):
        await self.enable('text')
        image = self.a.ImagePart(PNG, 'image/png')
        request = self.request((self.a.TextPart('synthetic image'), image))
        with self.assertRaises(self.a.ProviderError) as caught:
            await self.client.complete(request)
        self.assertEqual(caught.exception.code, 'CAPABILITY_UNAVAILABLE')
        self.assertEqual(self.server.requests, [])
        self.assertNotIn(base64.b64encode(PNG).decode(), repr(image))

    async def test_explicit_unsupported_vision_skips_even_synthetic_probe(self):
        declared = self.a.ProviderCapabilities('local-model', states={'vision': 'unsupported'})
        report = await self.client.probe_capabilities('local-model', frozenset({'vision'}), declared=declared)
        self.assertEqual(report.capabilities.states['vision'], 'unsupported')
        self.assertEqual(self.server.requests, [])

    async def test_vision_probe_and_inline_image_serialization(self):
        await self.enable('text', 'vision')
        await self.client.complete(self.request((self.a.TextPart('image'), self.a.ImagePart(PNG, 'image/png'))))
        part = json.loads(self.server.requests[0].content)['messages'][0]['content'][1]
        self.assertEqual(part, {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(PNG).decode()}})

    async def test_invalid_images_and_request_types_are_rejected_locally(self):
        for data, mime in [(b'not-image', 'image/png'), (PNG, 'image/jpeg'), (PNG, 'image/svg+xml')]:
            with self.subTest(mime=mime), self.assertRaises(ValueError):
                self.a.ImagePart(data, mime)
        with self.assertRaises(ValueError):
            self.request(max_tokens=True)
        with self.assertRaises(ValueError):
            self.a.ChatMessage('tool', 'x')
        with self.assertRaises(ValueError):
            self.a.EmbeddingRequest('local-model', ('',), 3)

    async def test_schema_output_validates_locally_and_never_returns_partial_or_wrong_json(self):
        await self.enable('text', 'json_schema')
        schema = self.a.JsonSchemaSpec('result', {'type': 'object', 'properties': {'ok': {'type': 'boolean'}},
                                                 'required': ['ok'], 'additionalProperties': False})
        result = await self.client.complete_json(self.request(), schema)
        self.assertEqual(result.value, {'ok': True})
        wire = json.loads(self.server.requests[-1].content)
        self.assertTrue(wire['response_format']['json_schema']['strict'])
        for text, finish in [('{"ok":"true"}', 'stop'), ('{"ok":true,"extra":1}', 'stop'),
                             ('{"ok":true,"ok":false}', 'stop'), ('{"ok":NaN}', 'stop'),
                             ('{', 'stop'), ('{"ok":true}', 'length')]:
            await self.response(completion(text, finish=finish))
            with self.subTest(text=text, finish=finish), self.assertRaises(self.a.ProviderError) as caught:
                await self.client.complete_json(self.request(), schema)
            self.assertEqual(caught.exception.code, 'INVALID_STRUCTURED_OUTPUT')
        with self.assertRaises(ValueError):
            self.a.JsonSchemaSpec('bad', {'$ref': 'https://example.org/schema'})

    async def test_schema_capability_requires_declared_and_probed_dialect(self):
        report = await self.client.probe_capabilities('local-model', frozenset({'json_schema'}))
        self.assertEqual(report.capabilities.states['json_schema'], 'unknown')
        self.assertEqual(self.server.requests, [])

    async def test_wrong_identity_and_malformed_completions_fail_closed(self):
        await self.enable('text')
        cases = [(completion(model='other-model'), 'MODEL_IDENTITY_MISMATCH'),
                 ({'model': 'local-model', 'choices': []}, 'INVALID_RESPONSE'),
                 (completion(finish='tool_calls'), 'INVALID_RESPONSE')]
        bad_tool = completion(); bad_tool['choices'][0]['message']['tool_calls'] = [{'type': 'function'}]
        cases.append((bad_tool, 'INVALID_RESPONSE'))
        for payload, code in cases:
            await self.response(payload)
            with self.subTest(code=code), self.assertRaises(self.a.ProviderError) as caught:
                await self.client.complete(self.request())
            self.assertEqual(caught.exception.code, code)

    async def test_embedding_probe_and_vectors_are_restored_to_input_order(self):
        await self.enable('embeddings')
        result = await self.client.embed(self.a.EmbeddingRequest('local-model', ('first', 'second'), 3))
        self.assertEqual(result.vectors, ((0., 1., 2.), (1., 1., 2.)))
        self.assertEqual(json.loads(self.server.requests[-1].content)['encoding_format'], 'float')

    async def test_embedding_shape_boolean_duplicate_and_identity_fail_closed(self):
        await self.enable('embeddings')
        for data in [[{'index': 0, 'embedding': [True, 1., 2.]}],
                     [{'index': 0, 'embedding': [1., 2.]}],
                     [{'index': 0, 'embedding': [1., 2., 3.]}, {'index': 0, 'embedding': [1., 2., 3.]}], []]:
            await self.response({'model': 'local-model', 'data': data})
            with self.subTest(data=data), self.assertRaises(self.a.ProviderError) as caught:
                await self.client.embed(self.a.EmbeddingRequest('local-model', ('first',), 3))
            self.assertEqual(caught.exception.code, 'EMBEDDING_SHAPE_MISMATCH')

    async def test_redirects_are_not_followed_even_to_another_local_address(self):
        for status in (301, 302, 307, 308):
            await self.response({}, status, {'location': 'http://169.254.169.254/latest/meta-data/'})
            self.server.requests.clear()
            with self.subTest(status=status), self.assertRaises(self.a.ProviderError) as caught:
                await self.client.list_models()
            self.assertEqual(caught.exception.code, 'REDIRECT_FORBIDDEN')
            self.assertEqual(len(self.server.requests), 1)

    async def test_normalized_errors_and_repr_do_not_expose_sensitive_content(self):
        await self.enable('text')
        markers = ['FAKE_VIN_123', 'CREDENTIAL_MARKER', 'PROMPT_MARKER', 'PROVIDER_PRIVATE_BODY']
        logs = io.StringIO(); handler = logging.StreamHandler(logs)
        logging.getLogger().addHandler(handler)
        self.addCleanup(logging.getLogger().removeHandler, handler)
        request = self.request(' '.join(markers))
        for status, code in [(401, 'AUTHENTICATION_FAILED'), (429, 'RATE_LIMITED'), (503, 'PROVIDER_UNAVAILABLE')]:
            await self.response({'error': ' '.join(markers)}, status)
            with self.assertRaises(self.a.ProviderError) as caught:
                await self.client.complete(request)
            self.assertEqual(caught.exception.code, code)
            for marker in markers:
                self.assertNotIn(marker, str(caught.exception) + repr(caught.exception) + repr(request) + logs.getvalue())

    async def test_stream_handles_split_utf8_heartbeats_and_valid_terminal_markers(self):
        await self.enable('text', 'streaming')
        async with self.client.stream(self.request()) as events:
            items = [item async for item in events]
        self.assertEqual(''.join(x.text for x in items if x.kind == 'text_delta'), 'café')
        self.assertEqual(items[-1].kind, 'finished')
        self.assertEqual([x.sequence for x in items], list(range(1, len(items)+1)))

    async def test_stream_rejects_eof_changed_identity_and_tools_and_closes(self):
        await self.enable('text', 'streaming')
        cases = [(sse({'content': 'partial'}), 'STREAM_INCOMPLETE'),
                 (sse({'content': 'a'}) + sse({'content': 'b'}, model='other'), 'MODEL_IDENTITY_MISMATCH'),
                 (sse({'tool_calls': [{}]}), 'INVALID_RESPONSE')]
        for raw, code in cases:
            stream = BytesStream([raw.encode()])
            async def override(request):
                return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=stream)
            self.server.override = override
            with self.subTest(code=code), self.assertRaises(self.a.ProviderError) as caught:
                async with self.client.stream(self.request()) as events:
                    _ = [x async for x in events]
            self.assertEqual(caught.exception.code, code)
            self.assertTrue(stream.closed)

    async def test_token_cancellation_before_dispatch_never_resolves_secret(self):
        token = self.a.CancellationToken(); self.assertTrue(token.cancel()); self.assertFalse(token.cancel())
        with self.assertRaises(self.a.ProviderError) as caught:
            await self.client.list_models(cancel=token)
        self.assertEqual(caught.exception.code, 'CANCELLED')
        self.assertEqual(self.server.requests, [])

    async def test_thread_cancellation_aborts_blocked_transport_without_cancelling_other_work(self):
        entered, aborted = asyncio.Event(), asyncio.Event()
        async def blocked(request):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                aborted.set()
        self.server.override = blocked
        token = self.a.CancellationToken()
        task = asyncio.create_task(self.client.list_models(cancel=token))
        await asyncio.wait_for(entered.wait(), 1)
        thread = threading.Thread(target=token.cancel); thread.start(); thread.join()
        with self.assertRaises(self.a.ProviderError) as caught:
            await asyncio.wait_for(task, 1)
        self.assertEqual(caught.exception.code, 'CANCELLED')
        self.assertTrue(aborted.is_set())
        self.server.override = None
        self.assertEqual(len(await self.client.list_models()), 1)

    async def test_midstream_cancellation_closes_response(self):
        await self.enable('text', 'streaming')
        stream = BytesStream([sse({'content': 'partial'}).encode()], block=True)
        async def override(request):
            return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=stream)
        self.server.override = override
        token = self.a.CancellationToken()
        async def consume():
            async with self.client.stream(self.request(), cancel=token) as events:
                return [x async for x in events]
        task = asyncio.create_task(consume())
        await asyncio.wait_for(stream.waiting.wait(), 1)
        token.cancel()
        with self.assertRaises(self.a.ProviderError) as caught:
            await asyncio.wait_for(task, 1)
        self.assertEqual(caught.exception.code, 'CANCELLED')
        self.assertTrue(stream.closed)

    async def test_consumer_break_and_external_task_cancellation_release_stream(self):
        await self.enable('text', 'streaming')
        stream = BytesStream([sse({'content': 'partial'}).encode()], block=True)
        async def override(request):
            return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=stream)
        self.server.override = override
        async with self.client.stream(self.request()) as events:
            async for item in events:
                break
        self.assertTrue(stream.closed)
        stream = BytesStream([], block=True)
        task = asyncio.create_task(self.client.list_models())
        await asyncio.wait_for(stream.waiting.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(stream.closed)

    async def test_close_is_idempotent_and_prevents_new_dispatch(self):
        await self.client.aclose(); await self.client.aclose()
        with self.assertRaises(self.a.ProviderError) as caught:
            await self.client.list_models()
        self.assertEqual(caught.exception.code, 'CLIENT_CLOSED')

    async def test_response_and_deadline_limits_fail_with_bounded_cleanup(self):
        limited = self.a.ProviderClient(self.a.EndpointConfig('fixture', 'generation', 'http://127.0.0.1', '1'),
            transport=httpx.MockTransport(self.server), limits=self.a.ClientLimits(max_response_bytes=32, total_timeout=0.05))
        self.addAsyncCleanup(limited.aclose)
        with self.assertRaises(self.a.ProviderError) as caught:
            await limited.list_models()
        self.assertEqual(caught.exception.code, 'RESPONSE_TOO_LARGE')
        async def blocked(request):
            await asyncio.Event().wait()
        self.server.override = blocked
        with self.assertRaises(self.a.ProviderError) as caught:
            await limited.list_models()
        self.assertEqual(caught.exception.code, 'DEADLINE_EXCEEDED')

    async def test_real_loopback_socket_closes_on_cancel_and_ignores_environment_proxy(self):
        connected, disconnected = asyncio.Event(), asyncio.Event()
        async def handle(reader, writer):
            try:
                await reader.readuntil(b'\r\n\r\n')
                connected.set()
                await reader.read()
                disconnected.set()
            finally:
                writer.close(); await writer.wait_closed()
        server = await asyncio.start_server(handle, '127.0.0.1', 0)
        self.addAsyncCleanup(server.wait_closed)
        self.addCleanup(server.close)
        port = server.sockets[0].getsockname()[1]
        with patch.dict(os.environ, {'HTTP_PROXY': 'http://127.0.0.1:1', 'HTTPS_PROXY': 'http://127.0.0.1:1',
                                    'ALL_PROXY': 'http://127.0.0.1:1', 'NO_PROXY': ''}):
            async with self.a.ProviderClient(self.a.EndpointConfig('fixture', 'generation', f'http://127.0.0.1:{port}', '1')) as client:
                token = self.a.CancellationToken()
                task = asyncio.create_task(client.list_models(cancel=token))
                await asyncio.wait_for(connected.wait(), 2)
                token.cancel()
                with self.assertRaises(self.a.ProviderError) as caught:
                    await asyncio.wait_for(task, 2)
                self.assertEqual(caught.exception.code, 'CANCELLED')
                await asyncio.wait_for(disconnected.wait(), 2)


if __name__ == '__main__':
    unittest.main()

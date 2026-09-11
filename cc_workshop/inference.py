"""Local-only inference provider contract for CC Workshop."""

from __future__ import annotations

import asyncio
import base64
import ipaddress
import json
import math
import posixpath
import re
import threading
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable
from urllib.parse import unquote, urlsplit

import httpx

_ALLOWED_FEATURES = frozenset({"text", "vision", "json_schema", "embeddings", "streaming"})
_ALLOWED_STATES = frozenset({"supported", "unsupported", "unknown"})
_MESSAGE_ROLES = frozenset({"system", "user", "assistant"})


class ProviderError(RuntimeError):
    """Sanitized provider failure."""

    def __init__(self, code: str, message: str | None = None, *, retryable: bool = False):
        self.code = str(code)
        self.retryable = bool(retryable)
        super().__init__(message or self.code)

    def __repr__(self) -> str:
        return f"ProviderError(code={self.code!r}, retryable={self.retryable!r})"


@dataclass(frozen=True, slots=True)
class EndpointConfig:
    provider_id: str
    role: str
    endpoint: str
    config_revision: str
    base_url: str = field(init=False)

    def __post_init__(self) -> None:
        provider_id = str(self.provider_id or "").strip()
        role = str(self.role or "").strip()
        revision = str(self.config_revision or "").strip()
        if not provider_id:
            raise ProviderError("INVALID_ENDPOINT", "Invalid provider endpoint")
        if not role:
            raise ProviderError("INVALID_ENDPOINT", "Invalid provider endpoint")
        if not revision:
            raise ProviderError("INVALID_ENDPOINT", "Invalid provider endpoint")
        object.__setattr__(self, "provider_id", provider_id)
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "config_revision", revision)
        object.__setattr__(self, "base_url", _canonical_base_url(self.endpoint))

    @property
    def cache_key(self) -> tuple[str, str, str, str]:
        return (self.provider_id, self.role, self.base_url, self.config_revision)


def _canonical_base_url(raw: str) -> str:
    if not isinstance(raw, str) or not raw:
        raise ProviderError("INVALID_ENDPOINT", "Invalid provider endpoint")
    if raw != raw.strip() or "\\" in raw:
        raise ProviderError("INVALID_ENDPOINT", "Invalid provider endpoint")
    split = urlsplit(raw)
    if split.scheme.lower() not in {"http", "https"}:
        raise ProviderError("INVALID_ENDPOINT", "Invalid provider endpoint")
    if split.username or split.password or split.query or split.fragment or "?" in raw or "#" in raw:
        raise ProviderError("INVALID_ENDPOINT", "Invalid provider endpoint")
    if "%" in split.netloc:
        raise ProviderError("INVALID_ENDPOINT", "Invalid provider endpoint")
    try:
        port = split.port
    except ValueError as exc:
        raise ProviderError("INVALID_ENDPOINT", "Invalid provider endpoint") from exc
    if port is not None and not (1 <= port <= 65535):
        raise ProviderError("INVALID_ENDPOINT", "Invalid provider endpoint")
    host = split.hostname or ""
    if not host:
        raise ProviderError("INVALID_ENDPOINT", "Invalid provider endpoint")
    if host != host.strip() or "/" in host or "\\" in host:
        raise ProviderError("INVALID_ENDPOINT", "Invalid provider endpoint")
    canonical_host = _canonical_local_host(host)
    path = split.path or ""
    if unquote(path) != path:
        raise ProviderError("INVALID_ENDPOINT", "Invalid provider endpoint")
    normalized = posixpath.normpath(path or "/")
    if path.endswith("/") and not normalized.endswith("/"):
        normalized += "/"
    if normalized in {".", "/"}:
        pass
    elif normalized in {"/v1", "/v1/"}:
        pass
    else:
        raise ProviderError("INVALID_ENDPOINT", "Invalid provider endpoint")
    port_text = f":{port}" if port is not None else ""
    return f"{split.scheme.lower()}://{canonical_host}{port_text}/v1/"


def _canonical_local_host(host: str) -> str:
    lowered = host.lower()
    if lowered == "localhost":
        return "127.0.0.1"
    if lowered.endswith(".") or lowered.startswith("localhost"):
        raise ProviderError("INVALID_ENDPOINT", "Invalid provider endpoint")
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ProviderError("INVALID_ENDPOINT", "Invalid provider endpoint") from exc
    if address.version == 4:
        if address.is_loopback or address in ipaddress.ip_network("10.0.0.0/8") or address in ipaddress.ip_network("172.16.0.0/12") or address in ipaddress.ip_network("192.168.0.0/16"):
            return str(address)
        raise ProviderError("INVALID_ENDPOINT", "Invalid provider endpoint")
    if address.ipv4_mapped is not None or address.is_link_local or address.is_multicast or address.is_unspecified:
        raise ProviderError("INVALID_ENDPOINT", "Invalid provider endpoint")
    if address.is_loopback or address in ipaddress.ip_network("fc00::/7"):
        return f"[{address.compressed}]"
    raise ProviderError("INVALID_ENDPOINT", "Invalid provider endpoint")


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    model_id: str
    states: dict[str, str] = field(default_factory=dict)
    schema_dialect: str = ""

    def __post_init__(self) -> None:
        model_id = _nonblank(self.model_id, "model_id")
        states: dict[str, str] = {}
        for key, value in dict(self.states).items():
            feature = str(key).strip()
            state = str(value).strip()
            if feature not in _ALLOWED_FEATURES or state not in _ALLOWED_STATES:
                raise ValueError("invalid provider capability state")
            states[feature] = state
        object.__setattr__(self, "model_id", model_id)
        object.__setattr__(self, "states", states)
        object.__setattr__(self, "schema_dialect", str(self.schema_dialect or "").strip())

    def state(self, feature: str) -> str:
        return self.states.get(feature, "unknown")


@dataclass(frozen=True, slots=True)
class CapabilityReport:
    capabilities: ProviderCapabilities


@dataclass(frozen=True, slots=True)
class ModelInfo:
    id: str
    owned_by: str = ""


@dataclass(frozen=True, slots=True)
class TextPart:
    text: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "text", _nonblank(self.text, "text"))


@dataclass(frozen=True, slots=True)
class ImagePart:
    data: bytes
    mime_type: str

    def __post_init__(self) -> None:
        data = bytes(self.data or b"")
        mime = str(self.mime_type or "").strip().lower()
        if mime not in {"image/png", "image/jpeg"}:
            raise ValueError("unsupported image MIME type")
        if mime == "image/png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("image bytes do not match MIME type")
        if mime == "image/jpeg" and not data.startswith(b"\xff\xd8"):
            raise ValueError("image bytes do not match MIME type")
        object.__setattr__(self, "data", data)
        object.__setattr__(self, "mime_type", mime)

    def __repr__(self) -> str:
        return f"ImagePart(mime_type={self.mime_type!r}, bytes={len(self.data)})"


MessageContent = str | tuple[TextPart | ImagePart, ...]


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: str
    content: MessageContent

    def __post_init__(self) -> None:
        role = str(self.role or "").strip()
        if role not in _MESSAGE_ROLES:
            raise ValueError("unsupported chat message role")
        content = self.content
        if isinstance(content, str):
            pass
        else:
            if not isinstance(content, tuple) or not content:
                raise ValueError("message content must be text or content parts")
            if not all(isinstance(item, (TextPart, ImagePart)) for item in content):
                raise ValueError("unsupported message content part")
        object.__setattr__(self, "role", role)


@dataclass(frozen=True, slots=True)
class ChatRequest:
    model_id: str
    messages: tuple[ChatMessage, ...]
    max_tokens: int | None = None
    temperature: float | None = None

    def __post_init__(self) -> None:
        model_id = _nonblank(self.model_id, "model_id")
        messages = tuple(self.messages)
        if not messages or not all(isinstance(message, ChatMessage) for message in messages):
            raise ValueError("messages must contain ChatMessage values")
        if self.max_tokens is not None:
            if isinstance(self.max_tokens, bool) or not isinstance(self.max_tokens, int) or self.max_tokens < 1:
                raise ValueError("max_tokens must be a positive integer")
        if self.temperature is not None:
            if isinstance(self.temperature, bool) or not isinstance(self.temperature, (int, float)) or not math.isfinite(float(self.temperature)):
                raise ValueError("temperature must be finite")
        object.__setattr__(self, "model_id", model_id)
        object.__setattr__(self, "messages", messages)
        if self.temperature is not None:
            object.__setattr__(self, "temperature", float(self.temperature))

    def __repr__(self) -> str:
        return f"ChatRequest(model_id={self.model_id!r}, messages={len(self.messages)}, max_tokens={self.max_tokens!r}, temperature={self.temperature!r})"


@dataclass(frozen=True, slots=True)
class EmbeddingRequest:
    model_id: str
    input: tuple[str, ...]
    dimensions: int

    def __post_init__(self) -> None:
        model_id = _nonblank(self.model_id, "model_id")
        values = tuple(self.input)
        if not values or any(not isinstance(item, str) or not item for item in values):
            raise ValueError("embedding input must contain non-empty strings")
        if isinstance(self.dimensions, bool) or not isinstance(self.dimensions, int) or self.dimensions < 1:
            raise ValueError("dimensions must be a positive integer")
        object.__setattr__(self, "model_id", model_id)
        object.__setattr__(self, "input", values)


@dataclass(frozen=True, slots=True)
class JsonSchemaSpec:
    name: str
    schema: dict[str, Any]

    def __post_init__(self) -> None:
        name = _nonblank(self.name, "name")
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_-]*$", name):
            raise ValueError("invalid schema name")
        if not isinstance(self.schema, dict) or _contains_ref(self.schema):
            raise ValueError("external schema references are not allowed")
        object.__setattr__(self, "name", name)


@dataclass(frozen=True, slots=True)
class CompletionResult:
    text: str
    response_model_id: str
    complete: bool


@dataclass(frozen=True, slots=True)
class JsonResult:
    value: Any
    response_model_id: str
    complete: bool


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    vectors: tuple[tuple[float, ...], ...]
    response_model_id: str


@dataclass(frozen=True, slots=True)
class StreamEvent:
    kind: str
    sequence: int
    text: str = ""


@dataclass(frozen=True, slots=True)
class ClientLimits:
    max_response_bytes: int = 2_000_000
    total_timeout: float | None = 30.0

    def __post_init__(self) -> None:
        if isinstance(self.max_response_bytes, bool) or not isinstance(self.max_response_bytes, int) or self.max_response_bytes < 1:
            raise ValueError("max_response_bytes must be positive")
        if self.total_timeout is not None:
            if isinstance(self.total_timeout, bool) or not isinstance(self.total_timeout, (int, float)) or self.total_timeout <= 0:
                raise ValueError("total_timeout must be positive")
            object.__setattr__(self, "total_timeout", float(self.total_timeout))


class CancellationToken:
    def __init__(self) -> None:
        self._cancelled = False
        self._callbacks: list[Callable[[], None]] = []
        self._lock = threading.Lock()

    @property
    def cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    def cancel(self) -> bool:
        callbacks: list[Callable[[], None]]
        with self._lock:
            if self._cancelled:
                return False
            self._cancelled = True
            callbacks = list(self._callbacks)
            self._callbacks.clear()
        for callback in callbacks:
            with suppress(Exception):
                callback()
        return True

    def register(self, callback: Callable[[], None]) -> Callable[[], None]:
        with self._lock:
            if self._cancelled:
                run_now = True
            else:
                self._callbacks.append(callback)
                run_now = False
        if run_now:
            callback()
            return lambda: None

        def unregister() -> None:
            with self._lock:
                with suppress(ValueError):
                    self._callbacks.remove(callback)

        return unregister


class ProviderClient:
    def __init__(self, endpoint: EndpointConfig, *, transport: httpx.AsyncBaseTransport | None = None, limits: ClientLimits | None = None):
        self.endpoint = endpoint
        self.limits = limits or ClientLimits()
        self._client = httpx.AsyncClient(
            base_url=endpoint.base_url,
            transport=transport,
            follow_redirects=False,
            trust_env=False,
            timeout=None,
        )
        self._closed = False
        self._capabilities: dict[tuple[tuple[str, str, str, str], str], ProviderCapabilities] = {}

    async def __aenter__(self) -> "ProviderClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if not self._closed:
            self._closed = True
            await self._client.aclose()

    async def list_models(self, *, cancel: CancellationToken | None = None) -> list[ModelInfo]:
        data = await self._send_json("GET", "models", cancel=cancel)
        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise ProviderError("INVALID_RESPONSE", "Invalid provider response")
        result: list[ModelInfo] = []
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
                raise ProviderError("INVALID_RESPONSE", "Invalid provider response")
            result.append(ModelInfo(item["id"], str(item.get("owned_by", ""))))
        return result

    async def probe_capabilities(self, model_id: str, desired: frozenset[str], *, declared: ProviderCapabilities | None = None, cancel: CancellationToken | None = None) -> CapabilityReport:
        model = _nonblank(model_id, "model_id")
        states: dict[str, str] = {}
        if declared is not None and declared.model_id != model:
            declared = None
        for feature in desired:
            if feature not in _ALLOWED_FEATURES:
                states[feature] = "unknown"
                continue
            state = declared.state(feature) if declared is not None else "unknown"
            if feature == "json_schema" and (declared is None or declared.schema_dialect != "openai_json_schema" or state != "supported"):
                states[feature] = "unknown" if state != "unsupported" else "unsupported"
            elif state in {"supported", "unsupported"}:
                states[feature] = state
            else:
                states[feature] = "unknown"
        capabilities = ProviderCapabilities(model, states=states, schema_dialect=(declared.schema_dialect if declared else ""))
        self._capabilities[(self.endpoint.cache_key, model)] = capabilities
        return CapabilityReport(capabilities)

    async def complete(self, request: ChatRequest, *, cancel: CancellationToken | None = None, response_format: dict[str, Any] | None = None) -> CompletionResult:
        self._require_capability(request.model_id, "text")
        if _request_has_image(request):
            self._require_capability(request.model_id, "vision")
        body = _chat_request_body(request, stream=False, response_format=response_format)
        data = await self._send_json("POST", "chat/completions", json_body=body, cancel=cancel)
        return _completion_from_response(data, request.model_id)

    async def complete_json(self, request: ChatRequest, schema: JsonSchemaSpec, *, cancel: CancellationToken | None = None) -> JsonResult:
        self._require_capability(request.model_id, "json_schema")
        response_format = {
            "type": "json_schema",
            "json_schema": {"name": schema.name, "schema": schema.schema, "strict": True},
        }
        completion = await self.complete(request, cancel=cancel, response_format=response_format)
        if not completion.complete:
            raise ProviderError("INVALID_STRUCTURED_OUTPUT", "Invalid structured output")
        value = _strict_json_loads(completion.text)
        if not _validate_minimal_schema(value, schema.schema):
            raise ProviderError("INVALID_STRUCTURED_OUTPUT", "Invalid structured output")
        return JsonResult(value, completion.response_model_id, True)

    async def embed(self, request: EmbeddingRequest, *, cancel: CancellationToken | None = None) -> EmbeddingResult:
        self._require_capability(request.model_id, "embeddings")
        data = await self._send_json("POST", "embeddings", json_body={
            "model": request.model_id,
            "input": list(request.input),
            "encoding_format": "float",
        }, cancel=cancel)
        response_model = str(data.get("model", request.model_id)) if isinstance(data, dict) else ""
        if response_model != request.model_id:
            raise ProviderError("MODEL_IDENTITY_MISMATCH", "Provider model identity changed")
        rows = data.get("data") if isinstance(data, dict) else None
        if not isinstance(rows, list) or len(rows) != len(request.input):
            raise ProviderError("EMBEDDING_SHAPE_MISMATCH", "Embedding shape mismatch")
        seen: set[int] = set()
        vectors: dict[int, tuple[float, ...]] = {}
        for row in rows:
            if not isinstance(row, dict) or isinstance(row.get("index"), bool) or not isinstance(row.get("index"), int):
                raise ProviderError("EMBEDDING_SHAPE_MISMATCH", "Embedding shape mismatch")
            index = row["index"]
            if index < 0 or index >= len(request.input) or index in seen:
                raise ProviderError("EMBEDDING_SHAPE_MISMATCH", "Embedding shape mismatch")
            embedding = row.get("embedding")
            if not isinstance(embedding, list) or len(embedding) != request.dimensions:
                raise ProviderError("EMBEDDING_SHAPE_MISMATCH", "Embedding shape mismatch")
            vector: list[float] = []
            for value in embedding:
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                    raise ProviderError("EMBEDDING_SHAPE_MISMATCH", "Embedding shape mismatch")
                vector.append(float(value))
            seen.add(index)
            vectors[index] = tuple(vector)
        return EmbeddingResult(tuple(vectors[i] for i in range(len(request.input))), response_model)

    def stream(self, request: ChatRequest, *, cancel: CancellationToken | None = None) -> "StreamSession":
        self._require_capability(request.model_id, "text")
        self._require_capability(request.model_id, "streaming")
        if _request_has_image(request):
            self._require_capability(request.model_id, "vision")
        return StreamSession(self, request, cancel)

    def _require_open(self) -> None:
        if self._closed:
            raise ProviderError("CLIENT_CLOSED", "Provider client is closed")

    def _require_capability(self, model_id: str, feature: str) -> None:
        capabilities = self._capabilities.get((self.endpoint.cache_key, model_id))
        if capabilities is None or capabilities.state(feature) != "supported":
            raise ProviderError("CAPABILITY_UNAVAILABLE", "Provider capability unavailable")

    async def _send_json(self, method: str, path: str, *, json_body: dict[str, Any] | None = None, cancel: CancellationToken | None = None) -> Any:
        response = await self._send_response(method, path, json_body=json_body, cancel=cancel, stream=False)
        try:
            raw = await self._read_limited(response, cancel=cancel)
            self._raise_for_status(response)
            try:
                return json.loads(raw.decode("utf-8"))
            except Exception as exc:
                raise ProviderError("INVALID_RESPONSE", "Invalid provider response") from exc
        finally:
            await response.aclose()

    async def _send_response(self, method: str, path: str, *, json_body: dict[str, Any] | None = None, cancel: CancellationToken | None = None, stream: bool = False) -> httpx.Response:
        self._require_open()
        if cancel is not None and cancel.cancelled:
            raise ProviderError("CANCELLED", "Provider request cancelled", retryable=True)
        request = self._client.build_request(method, path, json=json_body)
        response = await self._await_cancellable(self._client.send(request, stream=True), cancel=cancel)
        if 300 <= response.status_code < 400:
            await response.aclose()
            raise ProviderError("REDIRECT_FORBIDDEN", "Provider redirects are disabled")
        return response

    async def _read_limited(self, response: httpx.Response, *, cancel: CancellationToken | None = None) -> bytes:
        chunks: list[bytes] = []
        total = 0
        iterator = response.aiter_bytes().__aiter__()
        while True:
            try:
                chunk = await self._await_cancellable(iterator.__anext__(), cancel=cancel)
            except StopAsyncIteration:
                break
            total += len(chunk)
            if total > self.limits.max_response_bytes:
                raise ProviderError("RESPONSE_TOO_LARGE", "Provider response is too large")
            chunks.append(chunk)
        return b"".join(chunks)

    async def _await_cancellable(self, awaitable, *, cancel: CancellationToken | None = None):
        if cancel is not None and cancel.cancelled:
            raise ProviderError("CANCELLED", "Provider request cancelled", retryable=True)
        loop = asyncio.get_running_loop()
        task = asyncio.create_task(awaitable)
        token_fired = False

        def on_cancel() -> None:
            nonlocal token_fired
            token_fired = True
            loop.call_soon_threadsafe(task.cancel)

        unregister = cancel.register(on_cancel) if cancel is not None else (lambda: None)
        try:
            if self.limits.total_timeout is None:
                return await task
            return await asyncio.wait_for(task, self.limits.total_timeout)
        except asyncio.TimeoutError as exc:
            task.cancel()
            with suppress(BaseException):
                await task
            raise ProviderError("DEADLINE_EXCEEDED", "Provider deadline exceeded", retryable=True) from exc
        except asyncio.CancelledError:
            task.cancel()
            with suppress(BaseException):
                await task
            if token_fired or (cancel is not None and cancel.cancelled):
                raise ProviderError("CANCELLED", "Provider request cancelled", retryable=True)
            raise
        finally:
            unregister()

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        if response.status_code in {401, 403}:
            raise ProviderError("AUTHENTICATION_FAILED", "Provider authentication failed")
        if response.status_code == 429:
            raise ProviderError("RATE_LIMITED", "Provider rate limited", retryable=True)
        if response.status_code in {502, 503, 504}:
            raise ProviderError("PROVIDER_UNAVAILABLE", "Provider unavailable", retryable=True)
        raise ProviderError("PROVIDER_ERROR", "Provider request failed", retryable=response.status_code >= 500)


class StreamSession:
    def __init__(self, client: ProviderClient, request: ChatRequest, cancel: CancellationToken | None):
        self._client = client
        self._request = request
        self._cancel = cancel
        self._response: httpx.Response | None = None
        self._events: AsyncIterator[StreamEvent] | None = None

    async def __aenter__(self) -> AsyncIterator[StreamEvent]:
        body = _chat_request_body(self._request, stream=True)
        self._response = await self._client._send_response("POST", "chat/completions", json_body=body, cancel=self._cancel, stream=True)
        self._client._raise_for_status(self._response)
        self._events = self._iter_events()
        return self._events

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._response is not None:
            await self._response.aclose()
            self._response = None

    async def _iter_events(self) -> AsyncIterator[StreamEvent]:
        assert self._response is not None
        iterator = self._response.aiter_bytes().__aiter__()
        buffer = b""
        sequence = 0
        finished = False
        try:
            while True:
                try:
                    chunk = await self._client._await_cancellable(iterator.__anext__(), cancel=self._cancel)
                except StopAsyncIteration:
                    break
                buffer += chunk
                while True:
                    marker = _frame_marker(buffer)
                    if marker is None:
                        break
                    frame, buffer = buffer[: marker[0]], buffer[marker[1]:]
                    event = _parse_sse_frame(frame)
                    if event is None:
                        continue
                    if event == "[DONE]":
                        continue
                    payload = _loads_provider_json(event)
                    model = str(payload.get("model", ""))
                    if model != self._request.model_id:
                        raise ProviderError("MODEL_IDENTITY_MISMATCH", "Provider model identity changed")
                    choices = payload.get("choices")
                    if not isinstance(choices, list) or not choices:
                        raise ProviderError("INVALID_RESPONSE", "Invalid provider response")
                    choice = choices[0]
                    if not isinstance(choice, dict):
                        raise ProviderError("INVALID_RESPONSE", "Invalid provider response")
                    delta = choice.get("delta") or {}
                    if not isinstance(delta, dict) or "tool_calls" in delta:
                        raise ProviderError("INVALID_RESPONSE", "Invalid provider response")
                    content = delta.get("content")
                    if content is not None:
                        if not isinstance(content, str):
                            raise ProviderError("INVALID_RESPONSE", "Invalid provider response")
                        sequence += 1
                        yield StreamEvent("text_delta", sequence, content)
                    finish = choice.get("finish_reason")
                    if finish is not None:
                        if finish != "stop":
                            raise ProviderError("INVALID_RESPONSE", "Invalid provider response")
                        finished = True
                        sequence += 1
                        yield StreamEvent("finished", sequence, "")
            if not finished:
                raise ProviderError("STREAM_INCOMPLETE", "Provider stream ended before completion", retryable=True)
        except Exception:
            await self.aclose()
            raise
        finally:
            if finished:
                await self.aclose()


def _chat_request_body(request: ChatRequest, *, stream: bool, response_format: dict[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": request.model_id,
        "messages": [_wire_message(message) for message in request.messages],
    }
    if request.max_tokens is not None:
        body["max_tokens"] = request.max_tokens
    if request.temperature is not None:
        body["temperature"] = request.temperature
    body["stream"] = stream
    if response_format is not None:
        body["response_format"] = response_format
    return body


def _wire_message(message: ChatMessage) -> dict[str, Any]:
    if isinstance(message.content, str):
        return {"role": message.role, "content": message.content}
    parts: list[dict[str, Any]] = []
    for part in message.content:
        if isinstance(part, TextPart):
            parts.append({"type": "text", "text": part.text})
        elif isinstance(part, ImagePart):
            encoded = base64.b64encode(part.data).decode("ascii")
            parts.append({"type": "image_url", "image_url": {"url": f"data:{part.mime_type};base64,{encoded}"}})
    return {"role": message.role, "content": parts}


def _request_has_image(request: ChatRequest) -> bool:
    for message in request.messages:
        if not isinstance(message.content, str) and any(isinstance(part, ImagePart) for part in message.content):
            return True
    return False


def _completion_from_response(data: Any, expected_model: str) -> CompletionResult:
    if not isinstance(data, dict):
        raise ProviderError("INVALID_RESPONSE", "Invalid provider response")
    model = data.get("model")
    if model != expected_model:
        raise ProviderError("MODEL_IDENTITY_MISMATCH", "Provider model identity changed")
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ProviderError("INVALID_RESPONSE", "Invalid provider response")
    choice = choices[0]
    message = choice.get("message")
    if not isinstance(message, dict) or "tool_calls" in message:
        raise ProviderError("INVALID_RESPONSE", "Invalid provider response")
    text = message.get("content")
    if not isinstance(text, str):
        raise ProviderError("INVALID_RESPONSE", "Invalid provider response")
    finish = choice.get("finish_reason")
    if finish not in {"stop", "length"}:
        raise ProviderError("INVALID_RESPONSE", "Invalid provider response")
    return CompletionResult(text, model, finish == "stop")


def _strict_json_loads(text: str) -> Any:
    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    try:
        return json.loads(text, object_pairs_hook=pairs_hook, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except Exception as exc:
        raise ProviderError("INVALID_STRUCTURED_OUTPUT", "Invalid structured output") from exc


def _validate_minimal_schema(value: Any, schema: dict[str, Any]) -> bool:
    if schema.get("type") == "object":
        if not isinstance(value, dict):
            return False
        required = schema.get("required", [])
        if not isinstance(required, list) or any(key not in value for key in required):
            return False
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            return False
        if schema.get("additionalProperties") is False and any(key not in properties for key in value):
            return False
        for key, subschema in properties.items():
            if key not in value:
                continue
            expected_type = subschema.get("type") if isinstance(subschema, dict) else None
            if expected_type == "boolean" and not isinstance(value[key], bool):
                return False
            if expected_type == "string" and not isinstance(value[key], str):
                return False
            if expected_type == "number" and (isinstance(value[key], bool) or not isinstance(value[key], (int, float))):
                return False
        return True
    return True


def _contains_ref(value: Any) -> bool:
    if isinstance(value, dict):
        if "$ref" in value:
            return True
        return any(_contains_ref(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_ref(item) for item in value)
    return False


def _nonblank(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def _frame_marker(buffer: bytes) -> tuple[int, int] | None:
    candidates = [(buffer.find(b"\r\n\r\n"), 4), (buffer.find(b"\n\n"), 2)]
    candidates = [(index, length) for index, length in candidates if index >= 0]
    if not candidates:
        return None
    index, length = min(candidates, key=lambda item: item[0])
    return index, index + length


def _parse_sse_frame(frame: bytes) -> str | None:
    text = frame.decode("utf-8")
    data: list[str] = []
    for raw_line in text.replace("\r\n", "\n").split("\n"):
        line = raw_line.strip()
        if not line or line.startswith(":"):
            continue
        if line.startswith("data:"):
            data.append(line[5:].lstrip())
    if not data:
        return None
    return "\n".join(data)


def _loads_provider_json(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except Exception as exc:
        raise ProviderError("INVALID_RESPONSE", "Invalid provider response") from exc
    if not isinstance(payload, dict):
        raise ProviderError("INVALID_RESPONSE", "Invalid provider response")
    return payload

# CC-T009 inference provider interface proposal

Status: research and test design only; no application implementation.
Prepared: 2026-09-10.
Inputs: `work/briefs/CC-T009.md`, approved plan section 3.9, isolated repository and HTTPX installation, official primary documentation.
Dependency: CC-T002 must pass its contract gate before implementation starts.
Ownership after authorization: `cc_workshop/inference/**` and associated provider-conformance tests only.

## 1. Decisions fixed for implementation

1. Use **HTTPX 0.28.1 AsyncClient** behind one asynchronous ProviderClient; do not add an OpenAI SDK dependency.
2. Support exactly GET `/v1/models`, POST `/v1/chat/completions`, and POST `/v1/embeddings`. Process startup, health, model downloads, unloading and device management remain separate CC-T010/011/012 responsibilities.
3. Accept literal loopback, RFC1918 IPv4 and IPv6 ULA addresses. Accept exact `localhost` by rewriting it to `127.0.0.1` without DNS. **Home-network endpoints must be entered as IP addresses, not DNS hostnames.** Root approved this policy.
4. Reject all other hostnames and public/link-local/unspecified/multicast/reserved addressing outside those exact ranges. No redirects, environment proxies, custom Host headers, URL credentials or arbitrary transport destinations.
5. Keep capabilities per endpoint configuration revision and exact model identity. Generic OpenAI compatibility is not evidence of vision, embeddings, schema output, or stream behavior.
6. Cancel the active asynchronous transport task and close its response on cancellation. Stopping the UI iterator alone is insufficient.
7. Never pass invalid or incomplete structured content to the answer renderer. Streaming text is internal unverified model output until the answer/evidence layer accepts a completed result.
8. Use local mocks and optional loopback-only synthetic servers in conformance tests. No vehicle data or public inference requests are needed.
9. This lane owns EndpointConfig, capability, request/result, ProviderError and cancellation types under inference. CC-T002 owns common VehicleContext/Unavailable/applicability types; this lane must consume those public contracts without editing their modules.

## 2. Evidence and compatibility limits

Official llama.cpp server documentation advertises the selected routes, streaming chat, multimodal content, and schema-constrained output, while explicitly limiting its compatibility claim. It distinguishes the OpenAI embedding route from native embedding APIs. Its model metadata and chat-template requirements mean capability must be tied to the loaded model. Documentation also permits remote/local media references; this application will deliberately emit only inline data URLs from already-authorized local bytes. [llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)

Ollama documents partial OpenAI compatibility, including chat, streaming, vision and embeddings. This establishes it as a candidate local adapter, not a proven model/profile. The schema-format and image examples vary sufficiently that serializer dialects must be tested rather than inferred from the provider name. [Ollama compatibility](https://docs.ollama.com/api/openai-compatibility)

The OpenAI chat reference supplies the common request/response vocabulary. The application uses this vocabulary against local endpoints only; OpenAI cloud credentials, Responses API, hosted tools and cloud endpoints are outside this interface. [OpenAI Chat reference](https://developers.openai.com/api/reference/cli/resources/chat)

HTTPX supports asynchronous clients and asynchronous response iteration. Stream contexts close responses; manual streaming requires explicit response closure. Those mechanisms support cancellable transport ownership. [HTTPX asynchronous API](https://www.python-httpx.org/async/)

HTTPX supplies mock/custom transports suitable for a deterministic conformance suite. Its timeout configuration separates connect, read, write and pool timeouts. Environment proxy configuration is enabled by default unless disabled. [HTTPX transports](https://www.python-httpx.org/advanced/transports/), [timeouts](https://www.python-httpx.org/advanced/timeouts/), [environment variables](https://www.python-httpx.org/environment_variables/)

Python's broad `is_private` classification is not the application's network policy. The installed interpreter classified both metadata address `169.254.169.254` and documentation address `192.0.2.1` as private. Use explicit network membership. [Python ipaddress reference](https://docs.python.org/3/library/ipaddress.html)

Upstream master documentation is current research evidence, not a release pin. CC-T010/011 must record the exact shipped runtime revision and execute relevant conformance tests against it.

## 3. Actual installed HTTPX evidence

Read directly in the isolated `.venv`:
- `httpx/_client.py`: AsyncClient defaults include `follow_redirects=False`, `trust_env=True`; `stream()` is an async context manager; `aclose()` is asynchronous.
- `httpx/_models.py`: `Response.aiter_raw()`, `aiter_bytes()`, `aiter_lines()`, and `aclose()` are available. Response closure calls the underlying asynchronous byte stream's closure.
- `httpx/_transports/base.py`: public `AsyncBaseTransport.handle_async_request()` and `aclose()` extension points.
- `httpx/_transports/mock.py`: MockTransport accepts synchronous or asynchronous handlers.
- `httpx/_exceptions.py`: typed timeout, connection, protocol, decoding and status-error classes are available for normalization.

Read-only inspection command, run from `work/cc-workshop`:

```powershell
.\.venv\Scripts\python.exe -c "import httpx, inspect, ipaddress; print('httpx='+httpx.__version__); print('AsyncClient='+str(inspect.signature(httpx.AsyncClient))); print('AsyncClient.stream='+str(inspect.signature(httpx.AsyncClient.stream))); print('MockTransport='+str(inspect.signature(httpx.MockTransport))); print('IPv4 is_private is too broad for our policy:', [(x, ipaddress.ip_address(x).is_private) for x in ('127.0.0.1','10.0.0.1','169.254.169.254','192.0.2.1')])"
```

Observed relevant output:

```text
httpx=0.28.1
AsyncClient: follow_redirects=False; trust_env=True; default timeout=5 seconds; transport=AsyncBaseTransport|None
AsyncClient.stream: asynchronous response stream context API
MockTransport=(handler: SyncHandler | AsyncHandler) -> None
IPv4 is_private is too broad for our policy: [('127.0.0.1', True), ('10.0.0.1', True), ('169.254.169.254', True), ('192.0.2.1', True)]
```

The middle signature entries above are condensed from the inspected signatures; no runtime request was made.

## 4. Public callable interface

Use immutable dataclasses or the project's approved strict model base after CC-T002, with explicit exports from `cc_workshop.inference`. Public API:

```python
class ProviderClient:
    def __init__(
        self,
        endpoint: EndpointConfig,
        *,
        secret_resolver: Callable[[str], str | None] | None = None,
        capabilities: CapabilityRegistry | None = None,
        transport: httpx.AsyncBaseTransport | None = None,  # test/internal injection
    ) -> None: ...

    async def __aenter__(self) -> "ProviderClient": ...
    async def __aexit__(self, exc_type, exc, tb) -> None: ...
    async def aclose(self) -> None: ...

    async def list_models(
        self, *, cancel: CancellationToken | None = None
    ) -> tuple[ModelDescriptor, ...]: ...

    async def probe_capabilities(
        self,
        model_id: str,
        requested: frozenset[CapabilityName],
        *,
        declared: ProviderCapabilities | None = None,
        cancel: CancellationToken | None = None,
    ) -> ProbeReport: ...

    async def complete(
        self, request: ChatRequest, *,
        cancel: CancellationToken | None = None,
    ) -> CompletionResult: ...

    def stream(
        self, request: ChatRequest, *,
        cancel: CancellationToken | None = None,
    ) -> AsyncContextManager[AsyncIterator[ProviderEvent]]: ...

    async def complete_json(
        self, request: ChatRequest, schema: JsonSchemaSpec, *,
        cancel: CancellationToken | None = None,
    ) -> StructuredResult: ...

    async def embed(
        self, request: EmbeddingRequest, *,
        cancel: CancellationToken | None = None,
    ) -> EmbeddingResult: ...


class CancellationToken:
    def cancel(self) -> bool: ...  # thread-safe; first transition True, then False
    @property
    def cancelled(self) -> bool: ...
```

An instance owns one immutable endpoint configuration and one HTTPX client. Do not reuse an AsyncClient across event loops. The later Flask/job integration must own a long-lived inference event loop or create/close a client inside its owned worker loop; do not add `asyncio.run()` wrappers to this provider package.

Only internal tests may inject a transport. Production constructors receive no arbitrary proxy, mount, hook, URL callback or custom headers.

### Input and result types

| Type | Required fields and invariants |
|---|---|
| EndpointConfig | provider_id, role generation/embedding, base_url, config_revision, optional credential_ref; canonical URL validated at construction and each dispatch; secrets excluded from repr/serialization |
| ModelDescriptor | id, optional owned_by, safe documented capability hints; provider's unexpected fields are not promoted to capabilities |
| ProviderCapabilities | provider_id, endpoint/config fingerprint, model_id, response_model_id, checked_at, per-capability state, schema_dialect, declared/probed evidence, cancellation_mode; defaults unknown |
| CapabilityName | text, vision, embeddings, streaming, json_schema, json_object, transport_cancellation |
| CapabilityState | unknown, supported, unsupported; transient network failure produces unknown with normalized reason |
| ChatMessage | role system/user/assistant; content text or tuple of TextPart/ImagePart; no tools, executable directives, arbitrary fields or remote-media URLs |
| ImagePart | already-authorized local image bytes plus validated PNG/JPEG media type; bytes excluded from repr; serialize to inline data URL only after capability check |
| ChatRequest | model_id, immutable messages, max_tokens, optional temperature, optional stop strings; request_id generated locally; no endpoint/model-manager options |
| JsonSchemaSpec | name, schema mapping, strict=True; schema itself validated locally; external references forbidden |
| EmbeddingRequest | model_id, tuple of nonempty text inputs, expected_dimension; encoding_format fixed float; no remote sources |
| CompletionResult | request_id, requested_model_id, response_model_id, text, finish_reason, complete flag, optional normalized token usage; explicitly not an evidence-verified answer |
| StructuredResult | request_id, model identities, locally schema-validated value, schema identity/hash, finish_reason; only terminal complete validated result returned |
| EmbeddingResult | request_id, model identities, ordered tuple of finite float vectors, dimensions, optional usage |
| ProviderEvent | request_id, monotonically increasing sequence, kind text_delta/usage/finished, bounded text or normalized metadata; no raw reasoning_content/tool payloads |
| ProviderError | stable code, safe_message, provider_id, request_id, optional HTTP status, retryable flag; never stores raw request/response bodies, key or image data |
| ProbeReport | endpoint/model/config binding, per-feature result and safe failure reason; no secrets or user content |

Source/garage authorization stays in the caller: the provider accepts already-selected evidence text or local image bytes and cannot load arbitrary filesystem paths. It does not infer vehicle applicability.

Request/response dictionaries remain private serializer details. No generic `**kwargs` passthrough is permitted.

## 5. Endpoint validation and dispatch policy

### Exact accepted destinations

- IPv4 loopback: `127.0.0.0/8`.
- RFC1918: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`.
- IPv6 loopback: `::1/128`.
- IPv6 unique-local: `fc00::/7`.
- Exact case-insensitive `localhost` is immediately canonicalized to `127.0.0.1`; never resolve it through DNS.
- Only `http` or `https`; canonical root paths accepted as empty, `/`, `/v1` or `/v1/`, normalized to a single `/v1/` base.
- Valid port 1..65535; absent port uses the scheme's default. Bundled defaults remain generation 8080 and embeddings 8081.
- Preserve correct brackets for canonical IPv6 URLs.

### Reject before dispatch

- Every DNS hostname other than exact localhost, including .local, localdomain, localhost.example, numeric lookalikes and trailing-dot aliases.
- Public IPs; `169.254.0.0/16`; IPv6 `fe80::/10`; multicast, unspecified, broadcast and all other ranges.
- IPv4-mapped IPv6, 6to4, Teredo, scoped IPv6 (% zone identifiers) and other mixed encodings. No address-family ambiguity is needed for home LAN use.
- URL userinfo; query strings; fragments; path traversal; encoded slashes/backslashes/hosts; whitespace/control characters; malformed or repeated authority separators.
- Short IPv4 (`127.1`), decimal integers, hexadecimal/octal IPv4 not accepted by strict ipaddress parsing.
- Any supplied absolute per-operation URL. The transport's method/path allowlist constructs the three supported route URLs.
- Arbitrary headers, especially Host, Proxy-Authorization, Cookie, Forwarded and X-Forwarded-Host.

Construct the HTTPX client with `trust_env=False`, `follow_redirects=False`, explicit bounded timeouts, no proxy/mount configuration, HTTP/1.1, TLS verification enabled, and `Accept-Encoding: identity`. Reject any 3xx status as REDIRECT_FORBIDDEN without requesting Location, even when its target is another private address. Reject nonidentity response content encoding for the bounded v1 parser.

Do not use `ipaddress.is_private` as an allow decision. Use explicit membership tests. Validate the canonical URL against the immutable EndpointConfig immediately before every GET/POST. No model output or response can select the next host/path.

DNS rebinding is prevented by construction: network hostnames are never accepted; localhost is replaced by a literal; every actual socket destination is a validated IP literal. No initial DNS check followed by a second unconstrained DNS lookup is used.

Private-range validation does not prove endpoint ownership. The bundled supervisor must verify its recorded child process/port and expected model before enabling requests. External endpoints require explicit configuration and a successful local capability/identity probe; a generic models response alone is not authentication.

Credentials resolve server-side by credential_ref and are held only in process memory for Authorization. They never appear in URL, browser persistent settings, exports, errors or normal logs. Optional HTTPS must validate its certificate for the IP address; do not silently disable verification when a home certificate fails.

## 6. Capability and model identity contract

- Initial capabilities are all unknown. Required unsupported or unknown capabilities raise CAPABILITY_UNAVAILABLE before any user-content request is serialized or sent.
- A model catalog's generic “OpenAI compatible” label is insufficient. Explicit bundled manifest declarations may establish which harmless probe is appropriate, but activation still requires corresponding conformance evidence.
- Probe only the explicitly configured local endpoint with synthetic text, a built-in tiny PNG, small embedding strings and a tiny known schema.
- If vision is declared unsupported or catalog metadata explicitly excludes it, skip the image probe and record unsupported. Unknown vision does not permit sending user images; a deliberately requested synthetic vision probe may test a declared candidate.
- Ordinary complete() requires text support and vision support when ImagePart is present; stream() additionally requires streaming; embed() requires embeddings.
- complete_json() requires a **declared/probed schema dialect**. Record dialect as openai_json_schema, llama_cpp_schema or none. A JSON-object probe proves JSON syntax only; it does not prove server schema enforcement.
- Prefer the standard nested OpenAI json_schema format when the pinned local profile passes it. If llama.cpp requires its documented schema variation, use an explicit dialect serializer; never guess from an HTTP 400 and retry user content in another mode.
- Always perform local strict JSON parsing and schema validation regardless of provider's claim. No silent fallback from schema mode to unconstrained generation.
- Each request captures the expected response model ID from its proven capability record. The standard case requires exact equality with requested model ID; any canonical alias must have been explicitly established in the probe record. A model switch invalidates existing capability results.
- Require matching identity in ordinary responses, embedding responses and the first substantive SSE event. If later SSE chunks include model/id, they must remain unchanged; omitted repeated model metadata is allowed only after identity has been established.
- Reject mismatches as MODEL_IDENTITY_MISMATCH; never update the active profile based on the unexpected response.
- Capabilities bind to endpoint canonical URL/config revision, model alias, observed response model ID and runtime/profile revision when available. Changing any binding requires revalidation.
- Management readiness and real identity remain CC-T011 responsibilities. No automatic model download/load/unload or remote function execution is added to ProviderClient.

## 7. Parsing, streaming and bounded resource semantics

Transport defaults are application limits, not claims about provider maxima:
- HTTPX connect 5s, pool 5s, write 30s, read-idle 120s; total operation deadline 300s. Validated settings may lower these; hardware work may later change defaults with measured evidence.
- Maximum complete response: 8 MiB; SSE line/event: 64 KiB; accumulated content: 8 MiB; 100,000 events maximum.
- Maximum request JSON: 32 MiB; up to 4 PNG/JPEG images, 8 MiB each before base64 and request-size enforcement; 40-megapixel decoded-image ceiling.
- Embedding batch: 1..64 strings; text/request bytes bounded; all returned vectors nonempty, finite and equal to expected_dimension. bool is not a numeric vector value.
- Maximum messages: 128. max_tokens must be a positive bounded integer within the selected model/profile limit; never send a negative/unlimited generation count.
- Bounds are checked before transmission and while reading. Use strict incremental UTF-8 decoding and a bounded SSE assembler, not unbounded aiter_lines() buffering.

Normal response validation:
- Require JSON object and expected data structure. Reject duplicate JSON keys, nonfinite JSON constants, missing choice/message/content fields and invalid field types.
- Request one completion. Accept exactly one indexed completion for this interface; reject unexpected tools/functions, audio and other unsupported output payloads.
- Preserve safe token usage only when nonnegative integers; absent usage stays absent.
- A finish reason of length/incomplete never yields StructuredResult, even when partial text happens to parse as JSON. Model refusal/content filtering becomes a safe normalized result/error, not a factual answer.
- Unknown extra telemetry fields may be ignored; they never enter the answer renderer or logs.

SSE validation:
- Support CRLF/LF line endings, comments/heartbeats and multi-line data fields, assembling events across arbitrary byte chunk boundaries.
- Accept JSON data events and terminal [DONE]; require matching request response identity and consistent choice index.
- Ignore role-only deltas and valid empty-choice usage events; emit only bounded text_delta, usage and finished events to internal consumers.
- Provider errors, malformed JSON, type errors, excessive sizes, unexpected tool calls and changing identity abort and close transport.
- EOF without a complete finish marker plus [DONE] is STREAM_INCOMPLETE. Do not invent a successful terminal event.
- Intermediary reasoning_content is not exposed, persisted or rendered by this interface.
- Backpressure is pull-based; do not accumulate an unbounded background token queue.
- complete_json() may accumulate an internally streamed response for cancellation/resource control, but exposes only the fully validated terminal value.

Embedding validation:
- Force encoding_format=float. Validate response model identity before accepting data.
- Require one unique index for each input, no duplicates/gaps, and reorder vectors to input order.
- Reject nonfinite numbers, boolean values, inconsistent dimensions, empty vectors and partial batches.
- Do not silently normalize or truncate vectors. Normalization identity belongs to the embedding profile/index contract.

## 8. Cancellation and lifetime semantics

CancellationToken is thread-safe for use from a synchronous Flask/UI/job cancellation path. It registers active request tasks through their owning event loop and schedules cancellation with loop.call_soon_threadsafe. Unregister every task in finally blocks.

- Cancellation before dispatch: raise CANCELLED; no request/credential resolution/network call.
- Cancellation during connect/write/read or an SSE wait: cancel the request task, await bounded cleanup and close any response stream.
- Consumer breaks stream iteration: async context exit closes the response even without explicit token cancellation.
- Caller task is externally cancelled: preserve asyncio.CancelledError after cleanup; token-triggered cancellation maps to the public safe CANCELLED error.
- Cancel one operation only; do not close other concurrent requests or kill a shared model process.
- aclose() prevents new work, cancels/awaits owned in-flight operations and closes the HTTPX client; repeated closure is safe.
- Release callbacks, tasks, streams and any retained image buffers on all exits.
- Conformance timing target: cancellation completion within 1 second for an event-blocked mock and within 2 seconds on a loopback test server, without waiting for the read-idle timeout.

Report cancellation as **transport aborted**. The common three-endpoint subset has no universal generation-cancel acknowledgement. Do not claim GPU work stopped merely because a socket closed. The pinned bundled-runtime integration must separately demonstrate that disconnect releases the slot or record the limitation; it must never kill an unrelated/shared process.

## 9. Error normalization and ordinary logs

Stable codes:
- INVALID_ENDPOINT, CAPABILITY_UNAVAILABLE, MODEL_NOT_FOUND, MODEL_IDENTITY_MISMATCH.
- AUTHENTICATION_FAILED (401/403), RATE_LIMITED (429), PROVIDER_UNAVAILABLE (5xx/connect).
- CONNECT_TIMEOUT, READ_TIMEOUT, WRITE_TIMEOUT, POOL_TIMEOUT, DEADLINE_EXCEEDED.
- REDIRECT_FORBIDDEN, INVALID_RESPONSE, INVALID_STRUCTURED_OUTPUT, RESPONSE_TOO_LARGE.
- STREAM_INCOMPLETE, EMBEDDING_SHAPE_MISMATCH, PROVIDER_REFUSED, CANCELLED, CLIENT_CLOSED.

No automatic retries for generation or embeddings in v1: avoid duplicate work, ambiguous partial streams and implicit resubmission of image/evidence content. The caller can explicitly retry a failed operation. Safe error messages are fixed templates; never concatenate provider body/exception repr or Authorization values.

Ordinary log allowlist: local request_id, opaque provider_id, operation name, elapsed milliseconds, HTTP status, normalized error code, byte counts, finish status and safe model/profile ID only where it is not a private filesystem path. Do not log body text, response excerpts, messages, image bytes/data URLs, raw schema data, credentials, full URLs, provider-supplied errors, VINs or local source paths. No HTTPX/httpcore debug body logging is enabled.

## 10. Test-first conformance suite

Use unittest.IsolatedAsyncioTestCase to match the repository's existing unittest suite. HTTPX MockTransport and custom AsyncByteStream fixtures need no server. Use a small asyncio loopback server only where socket closure must be demonstrated; guard its bind address so no test listens on LAN.

| Group | Cases and required evidence |
|---|---|
| Endpoint accepted | IPv4 loopback, each RFC1918 boundary, ::1, fc00/fdff ULA, exact localhost normalized; correct final /v1 paths |
| Endpoint rejected | Public IPv4/v6, metadata 169.254.169.254, all link-local, unspecified, multicast, mapped IPv6, scope IDs, encoded hosts, userinfo, query/fragment, traversal, backslash, short/octal/integer IP, hostile localhost suffix |
| DNS rebinding | All nonliteral hostnames rejected before transport; monkeypatch resolver to raise if invoked by validator; configured localhost produces literal request authority |
| Dispatch confinement | Only three allowed method/path combinations; attempts to override Host/absolute request destination rejected; every request retains canonical authority |
| Redirect/proxy escape | 301/302/307/308 to public or private targets stop after one request; malicious HTTP_PROXY/HTTPS_PROXY/ALL_PROXY ignored; no proxy receives traffic |
| Model catalog | Valid/missing/empty lists, duplicate IDs, malformed envelope and model-specific capability hints; catalog alone never marks vision/schema supported |
| Text completion | Exact wire request, matching identity, one completion, absent/valid usage; malformed choices, invalid types, wrong model, unexpected tools and refusal behavior |
| Vision gate | Unsupported/unknown vision rejects before MockTransport records a user-image request; supported vision emits only validated inline PNG/JPEG, never remote/local filesystem URL |
| Probe isolation | Synthetic probes only; declarations and successful evidence recorded separately; unsupported feature independent of other features; timeout leaves unknown |
| Structured output | Dialect-specific serializers; unknown dialect refused; correct schema succeeds; malformed JSON, duplicate keys, NaN, wrong types, missing/extra forbidden fields, external refs and finish=length all rejected |
| SSE | Byte-split UTF-8, CRLF, heartbeat comments, multiline data, role-only events, valid usage event, ordered deltas, finish + DONE; malformed/oversized events, changed IDs/models, EOF without DONE fail |
| Embeddings | Ordered and shuffled indexed data, empty input rejection, duplicate/missing indices, boolean/nonfinite entries, wrong dimension, partial batch, wrong model; no silent normalization |
| Cancellation | Before dispatch, blocked connect handler, blocked first byte, blocked midstream, consumer break, external task cancellation; active stream's aclose spy called and unrelated concurrent request continues |
| Real local cancellation | Synthetic loopback server sees socket close while awaiting more data; no public request; assert completion deadlines |
| Cleanup | Client close twice; exception paths release resources; late cancellation does not corrupt completed results; event-loop misuse detected/documented |
| Limits | Request bytes, image count/bytes/pixels, event line/content count, response bytes, deadline and read-idle enforce bounded failure |
| Logging | Marker strings for a fake VIN, secret, image payload, prompt and provider error absent from captured logs/errors/repr; output diagnostics contain only allowlisted fields |

### Implementation sequence after CC-T002 gate

1. Write endpoint rejection/acceptance and transport confinement tests; implement EndpointConfig and canonicalization.
2. Write types/error/capability gate tests; implement public types and safe serialization/repr.
3. Write models/text/embedding MockTransport tests; implement ordinary operations and strict identity/shape validation.
4. Write cancellation/stream lifetime tests with custom async byte streams; implement request lifecycle and bounded SSE parser.
5. Write image/schema dialect conformance tests; implement capability probes, vision serialization and complete_json validation.
6. Add loopback-only cancellation/proxy-isolation tests; run the new provider_conformance suite and whole legacy suite once integration is ready.
7. Report mocked/loopback transport results separately from real llama.cpp/Ollama model conformance; real model tests remain pending until their local assets/services exist.
8. Root reviews the T009 gate and integrates with later inference supervision/router work. No implementation or tracker status is marked complete based on this proposal.

## 11. Suggested owned files

- `cc_workshop/inference/__init__.py`: public exports.
- `types.py`: immutable config/capability/request/result/error contracts.
- `endpoint.py`: literal-only URL/address policy.
- `client.py`: HTTPX ownership, operations, model identity, cancellation.
- `streaming.py`: bounded UTF-8/SSE assembler.
- `capabilities.py`: per-model synthetic probe logic and serializer dialect selection.
- Associated tests: `tests/test_provider_endpoints.py`, `tests/test_provider_conformance.py`, `tests/test_provider_streaming.py`.

Keep all provider-specific management out of these inference request types. No Flask routes, shared garage contracts, source readers, renderer modules, model downloads, runtime binaries, application settings UI or tracker files are edited in this lane without a separately authorized integration task.


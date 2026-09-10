# CC-T010/011 runtime and model candidates

Observed 2026-09-10. Metadata research only: no model/archive downloads, inference requests, runtime execution, benchmarks or application changes. Machine-readable inventory: `work/model-runtime-candidates.json`. Every entry is a candidate; none is supported or performance-qualified.

## Runtime

The latest stable [llama.cpp release v0.4.0](https://github.com/ggml-org/llama.cpp/releases/tag/v0.4.0) links **b10809** for binaries. Its own asset list contains only `nightly-tag.txt`. The annotated v0.4.0 tag dereferences to `5266f24da75dc449bd56cbed7addb9c8e4a6a73e`, matching b10809. This is more precise than the release API's different `target_commitish` value.

First evaluation candidate: [llama-b10809-bin-win-cpu-x64.zip](https://github.com/ggml-org/llama.cpp/releases/download/b10809/llama-b10809-bin-win-cpu-x64.zip), **18,407,457 bytes**, published SHA256 `9df3158ed228a641a4b127942d7f459f24c9e13f04682659d05c00c80099b6b5`. It retains GitHub's prerelease flag despite being linked by the stable release. [Pinned license](https://github.com/ggml-org/llama.cpp/blob/5266f24da75dc449bd56cbed7addb9c8e4a6a73e/LICENSE): MIT.

The newest nightly observed was [b10892](https://github.com/ggml-org/llama.cpp/releases/tag/b10892), published 2026-09-10 11:54:20 UTC. Its Windows CPU x64 ZIP is 18,424,730 bytes, published SHA256 `71de55b9a4ca6115e1536a37b43065040dc6c231d4c2c0cf46d071b4d32d814b`. Retain as a second evaluation candidate; freshness does not establish compatibility. Archive layout, binary signatures, Windows/CPU requirements and operation on the user's machine have not been examined.

## Model pairs

Exact Hub revisions and every weight/projector filename, size and LFS SHA256 are in the JSON. These are publisher-advertised hashes; local bytes have not yet been independently verified.

| Candidate | Immutable revision | Language weights | Matching F16 projector | Matching Q8_0 projector | Declared license |
|---|---|---:|---:|---:|---|
| Qwen3-VL-4B-Instruct Q4_K_M | `1cd86afb9a95c410a6038ab3b40d8b578c892266` | 2,497,281,664 bytes | 836,180,256 bytes | 453,974,304 bytes | Apache-2.0 |
| Qwen3-VL-8B-Instruct Q4_K_M | `f982a07559d4a2f6c8744d840bf6fccab30eea96` | 5,027,784,800 bytes | 1,159,029,824 bytes | 752,289,728 bytes | Apache-2.0 |
| EmbeddingGemma-300M Q8_0 | `0f741b5a6585bd53aeb15cd1372c56f2a0f65e12` | 333,590,944 bytes | n/a | n/a | Derived card missing; upstream Gemma |

The publisher's pinned [4B card](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct-GGUF/blob/1cd86afb9a95c410a6038ab3b40d8b578c892266/README.md) and [8B card](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct-GGUF/blob/f982a07559d4a2f6c8744d840bf6fccab30eea96/README.md) describe separate language and vision weights with mixed quantization permitted. The candidate manifest must bind the same model size and revision, and require exactly one matching projector. These statements establish publisher intent, not tested behavior. The 8B card's web-server example contains 235B paths; use the exact listed 8B filenames instead of copying that example.

EmbeddingGemma's [GGUF card](https://huggingface.co/ggml-org/embeddinggemma-300M-GGUF/blob/0f741b5a6585bd53aeb15cd1372c56f2a0f65e12/README.md) demonstrates llama-server's native `/embedding`, not the provider contract's `/v1/embeddings`. That contract therefore needs a real runtime probe. The conversion repository is public and ungated but declares no license field or license file in its inspected listing. Its [upstream model](https://huggingface.co/google/embeddinggemma-300m/blob/57c266a740f537b4dc058e1b0cda161fd15afa75/README.md) is pinned at `57c266a740f537b4dc058e1b0cda161fd15afa75`, labels its license Gemma, and requires usage-license acknowledgement for access. Carry forward [Google's Gemma terms](https://ai.google.dev/gemma/terms) and resolve the installation/distribution policy before marking this candidate distributable. Public GGUF access is not evidence that the user has accepted those terms. The upstream card states 768 output dimensions; actual GGUF output shape remains unverified.

## Implementation implications

1. Pin the selected runtime ZIP checksum and model revisions before downloads. Use exact immutable Hub URLs built from the JSON, with expected size and SHA256 checked before atomic promotion.
2. Preserve the runtime MIT notice and model license provenance. Treat EmbeddingGemma's terms as an unresolved distribution gate, not an inference-capability failure.
3. Inspect the ZIP safely before selecting executable paths. Launch local verified model files; do not let runtime startup trigger automatic Hub downloads.
4. Keep disk download sizes distinct from required RAM/VRAM. Quantization, context size, images, caches and runtime overhead require measurement before hardware tiers can be advertised.
5. Test synthetic text, vision, structured output, streams, cancellation and embeddings. Verify identity, dimensions, finite values and request ordering under the CC-T009 contract. No vehicle data should be sent to public inference.
6. Runtime launch, lifecycle, hash verification and resource checks remain T010/011 implementation work. This research does not change the T009 implementation gate or any tracker status.

## Evidence method

Used the installed Hugging Face plugin for repository metadata and read its Hub CLI skill. Retrieved precise file metadata through `HfApi(token=False).model_info(..., files_metadata=True)` and a bounded public pinned README text request. These requests sent no Hub credentials and downloaded no weights. Used the installed GitHub connector for release assets, exact tag objects and pinned LICENSE text. Published checksums, sizes and license labels are transcribed into the JSON with their source URLs. No signed URLs or tokens are stored.

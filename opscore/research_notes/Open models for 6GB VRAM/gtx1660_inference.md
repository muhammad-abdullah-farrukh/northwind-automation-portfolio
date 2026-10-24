# GTX 1660 SUPER (TU116, 6 GB) local inference with Ollama / llama.cpp

## 1. Measured tokens/sec for 1B-9B models

### Takeaway
On a 1660-class card, Q4 models of 3B and under generate at about 26-38 t/s. 7-8B Q4 models that fit fully in VRAM generate at about 16-21 t/s in Ollama. Prompt-processing figures are scarce, and one source (LocalScore, 8B) conflicts sharply with the others. I found no measured 1660 data for Gemma 3 4B, Phi-4-mini, Qwen3 or Granite.

### Cited Findings
- Ollama 0.5.11 on a GTX 1660 (plain, not Super), 4-bit, generation rate (vendor blog from a GPU hosting company; the 1660 is slightly slower than the Super): Llama 3.2 3B 38.36 t/s (2.0 GB); Qwen2.5 3B 26.28 (1.9 GB); Qwen2.5 7B 18.24 (4.7 GB); Llama 3.1 8B 16.67 (4.9 GB); DeepSeek-R1 8B 16.26 (4.9 GB); DeepSeek-R1 7B 18.29; DeepSeek-R1 1.5B 30.16; Mistral 7B 40.2 (4.1 GB); CodeLlama 7B 21.42; DeepSeek-Coder 6.7B 21.31; Gemma 7B 9.69 (5.0 GB, likely partial spill); CodeGemma 7B 9.39. — [DatabaseMart](https://www.databasemart.com/blog/ollama-gpu-benchmark-gtx1660)
- llama.cpp CUDA, GTX 1660, Llama 2 7B Q4_0: pp512 148.91 t/s and tg128 41.35 t/s without flash attention; pp512 154.45 and tg128 41.43 with it. — [llama.cpp discussion #15013](https://github.com/ggml-org/llama.cpp/discussions/15013)
- llama.cpp Vulkan, GTX 1660 Ti Mobile, Llama 2 7B Q4_0: pp512 511.67 and tg128 56.60 without FA; pp512 514.34 and tg128 57.30 with FA. Mobile part, so not directly comparable to a desktop 1660 SUPER. — [llama.cpp discussion #10879](https://github.com/ggml-org/llama.cpp/discussions/10879)
- LocalScore, GTX 1660 Ti: Llama 3.2 1B Instruct 829 prompt t/s and 37.1 gen t/s; Qwen2.5-3B-Instruct 306 prompt and 20.1 gen (TTFT 4.66 s). — [LocalScore 1660 Ti](https://www.localscore.ai/accelerator/765)
- LocalScore, Llama 3.1 8B Q4_K_M: GTX 1660 SUPER 129 prompt t/s, 9.6 gen t/s, TTFT 10.9 s; GTX 1660 129 prompt, 9.0 gen. Far below DatabaseMart's 16.7 t/s for the same model. — [LocalScore model 1](https://www.localscore.ai/model/1); conflicts with [DatabaseMart](https://www.databasemart.com/blog/ollama-gpu-benchmark-gtx1660)
- Gemma 3 4B and Phi-4-mini: about 2.5 GB each at Q4_K_M, so both fit easily in 6 GB. Size claim from a content-farm blog, not a 1660 speed measurement. — [localaimaster](https://localaimaster.com/vram/best-ollama-models-6gb-vram)

### Inferences
- Token generation is memory-bandwidth bound. Weights read per token are roughly 2.0 GB for 3B, 2.5 GB for 4B and 4.7-4.9 GB for 7-8B. At 336 GB/s the theoretical ceiling is about 100-170 t/s, and real runs reach 25-50% of that (estimate).
- Rough estimates only, not measured: Gemma 3 4B and Phi-4-mini around 25-35 t/s, Qwen3 4B around 25-30 t/s, Qwen3 8B and Granite 8B around 15-18 t/s, Granite 3B near the Llama 3.2 3B figure.
- The LocalScore 8B result (9.6 t/s) is likely caused by its test context or by layers spilling off the GPU. Treat 16-18 t/s as the best case for 8B Q4_K_M and about 10 t/s as a plausible lower bound.

### Gaps
- No measured Ollama numbers found for Gemma 3 4B, Phi-4-mini, Qwen3 (any size) or Granite 3B/8B on a 1660-class card.
- Prompt-processing speeds for 3B and 8B models in Ollama not found. Only llama.cpp pp512 for a 7B model (about 150 t/s on CUDA) and LocalScore's 129 t/s for 8B.
- DatabaseMart tested the plain 1660 on Ollama 0.5.11 (early 2025). No late-2026 measurements found.

## 2. Known 1660-specific issues (FP16, flash attention, compute 7.5, Ollama quirks)

### Takeaway
The 1660 is Turing compute capability 7.5 without tensor cores. Flash attention works on it but gives only a small gain. I found no confirmed 1660-specific Ollama bug; most "issue" material concerned other GPUs or Vulkan.

### Cited Findings
- TU116 (GTX 1660 Ti) is compute capability 7.5 without tensor cores, and llama.cpp's CUDA backend uses dp4a INT8 kernels rather than mma tensor-core paths on such cards. Search-result summary, not a primary source. — [Ian Paterson CUDA benchmark post](https://ianlpaterson.com/blog/llama-cpp-build-from-source-cuda-benchmark/) (not fetched)
- Flash attention on the 1660 gives roughly +4% pp512 and no change in tg128 (148.9 to 154.5 pp; 41.35 to 41.43 tg). — [discussion #15013](https://github.com/ggml-org/llama.cpp/discussions/15013)
- Quantized-KV flash attention can silently fall back to CPU, with prefill slowdowns of 25-45x, when llama.cpp is built without -DGGML_CUDA_FA_ALL_QUANTS=ON. This affects build-from-source, not the Ollama binary, and comes from a search summary rather than a fetched page. — [Ian Paterson](https://ianlpaterson.com/blog/llama-cpp-build-from-source-cuda-benchmark/)
- Vulkan flash attention has a precision issue on fp16-capable GPUs (the FP32 variant is compiled but not bound), causing long-context corruption for MLA models. — [llama.cpp issue #28124](https://github.com/ggml-org/llama.cpp/issues/28124)
- Ollama falls back to f16 KV for architectures that do not support quantized KV or flash attention. — [ModelPiper](https://modelpiper.com/blog/ollama-kv-cache-quantization); see also [ollama issue #13337](https://github.com/ollama/ollama/issues/13337)

### Inferences
- The "FP16 problem" reputation of 16-series cards (black or green images in Stable Diffusion) does not appear in any LLM result I found. Not verified for LLMs specifically.

### Gaps
- No Ollama issue specific to the 1660 SUPER (for example a 6 GB offload mis-estimate) was verified.
- I did not read the Ollama FAQ or release notes directly.

## 3. Context length, KV cache quantization and VRAM budgeting in about 5 GB

### Takeaway
OLLAMA_FLASH_ATTENTION=1 is required for OLLAMA_KV_CACHE_TYPE=q8_0, which roughly halves KV memory at negligible quality cost. That lets 3-4B models carry long context and 7B models a moderate one on 6 GB.

### Cited Findings
- KV cache quantization (q8_0 or q4_0) requires flash attention. q8_0 cuts the KV cache by about 47-50% (example: 1,792 MB at f16 becomes about 952 MB). Reported perplexity increase is 0.002-0.05. — [ModelPiper](https://modelpiper.com/blog/ollama-kv-cache-quantization)
- Measured Ollama footprints (default context): 3B models 1.9-2.0 GB, 7B 4.7 GB, 8B 4.9 GB. Gemma 7B at 5.0 GB ran at 9.7 t/s, consistent with spill. — [DatabaseMart](https://www.databasemart.com/blog/ollama-gpu-benchmark-gtx1660)

### Inferences
- Treat about 5.0-5.3 GB as usable of 6 GB when the card also drives a display; up to about 5.5 GB if headless. Estimate.
- Budget rule: weights + KV (layers x 2 x kv_heads x head_dim x ctx x bytes per element) + about 0.3-0.5 GB compute buffer + about 0.5 GB headroom for Windows.
- 8B Q4_K_M (about 4.9 GB) leaves little room, so only a small context fits fully on GPU. A 3-4B model at Q4 (about 2-2.5 GB) leaves roughly 2.5-3 GB, which likely fits 16-32k context with q8_0 KV for GQA models (calculate per model). 7B at Q4_K_M is borderline at 4k-8k.
- Running Ollama natively on Windows avoids WSL2 passthrough overhead, which I could not quantify.

### Gaps
- No measured KV-cache or context-length data for a 1660 specifically.
- No measured Docker Desktop/WSL2 VRAM or speed overhead found.
- No per-model context tables (Qwen3, Gemma 3, Granite).

## 4. Vulkan vs CUDA, and partial CPU offload on a Ryzen 5 3600

### Takeaway
On the same Llama 2 7B Q4_0 test, CUDA on a desktop 1660 gave 41 t/s generation, while Vulkan on a 1660 Ti Mobile gave about 57 t/s. The rows are not like-for-like, so there is no clean verdict for this card. On an RTX 3080 CUDA wins decisively. Partial offload to a Ryzen 5 3600 beats CPU-only but expect roughly 5-10 t/s for 8B.

### Cited Findings
- RTX 3080: Vulkan pp512 1706 and tg128 62, versus CUDA pp512 4499 and tg128 131. — [discussion #10879](https://github.com/ggml-org/llama.cpp/discussions/10879)
- Ryzen 5 3600, Mixtral 8x7B Q4_K_M, CPU/RAM only: about 7 t/s. — [HF TheBloke discussion](https://huggingface.co/TheBloke/Mixtral-8x7B-v0.1-GGUF/discussions/9)
- Dual-channel DDR4-3600 offers about 58 GB/s and gives about 5 t/s for 8B Q4 models. Search-result summary, page not fetched. — [promptquorum](https://www.promptquorum.com/local-llms/fastest-local-llms-low-end-pcs)
- Offloading layers to CPU creates a performance cliff. Title and snippet only, not fetched. — [sergiiob.dev](https://sergiiob.dev/posts/gpu-vram-cpu-offload-llama-cpp-deep-dive/)

### Inferences
- If 8B Q4_K_M at modest context runs fully on GPU, expect about 15-17 t/s. Offloading 2-4 of 32 layers to the 3600 would likely give about 8-12 t/s; half or more offloaded gives about 5-7 t/s. Estimates from the bandwidth ratio (336 GB/s vs about 40-58 GB/s).
- 8B is usable for interactive chat only if it fits almost entirely in VRAM; for batch or agent work that tolerates 5-10 t/s it is acceptable. A 3-4B model is the safer main model.
- Ollama uses CUDA on Nvidia by default; Vulkan is only worth trying if the CUDA path misbehaves.

### Gaps
- No CUDA vs Vulkan comparison on the same desktop 1660 SUPER.
- No measured partial-offload numbers for a Ryzen 5 3600 with 8B models.

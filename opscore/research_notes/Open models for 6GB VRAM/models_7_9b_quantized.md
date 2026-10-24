# 6-9B and small-MoE open models on a 6 GB GPU (GTX 1660 SUPER, ~5 GB free), as of Oct 2026

Note: research was capped at ~16 tool calls. Several sources are aggregator/SEO sites (willitrunai, codersera, etc.); treat their numbers as unverified. Primary sources are marked as such.

## Which 6-9B / small-MoE models genuinely fit in ~5 GB (weights + KV at 4-8k), with GGUF sizes?

### Takeaway
With ~5 GB free, only Q3-class quants of 8-9B dense models fit with headroom for KV cache. Q4_K_M of Qwen3-8B (5.03 GB) and Qwen3.5-9B (5.68 GB) exceed the budget, so they need partial CPU offload or a 3-bit quant. 30-35B-A3B MoEs (16-19+ GB at Q3/Q4) do not fit; they only work via expert offload to system RAM, and 16 GB RAM is marginal for them.

### Cited Findings
- Qwen3-8B GGUF (bartowski): IQ3_M 3.90 GB, Q3_K_M 4.12 GB, Q3_K_L 4.43 GB, IQ4_XS 4.56 GB, Q4_K_S 4.80 GB, Q4_K_M 5.03 GB — [bartowski/Qwen_Qwen3-8B-GGUF](https://huggingface.co/bartowski/Qwen_Qwen3-8B-GGUF)
- Qwen3.5-9B GGUF (Unsloth): UD-IQ2_M 3.65 GB, UD-IQ3_XXS 4.02 GB, Q3_K_S 4.32 GB, Q3_K_M 4.67 GB, UD-Q3_K_XL 5.05 GB, IQ4_XS 5.17 GB, Q4_K_M 5.68 GB, UD-Q4_K_XL 5.97 GB, Q8_0 9.53 GB — [unsloth/Qwen3.5-9B-GGUF](https://huggingface.co/unsloth/Qwen3.5-9B-GGUF)
- Qwen3.5-9B: 9B params, Apache 2.0, hybrid Gated DeltaNet architecture (32 layers), native 262k context, multimodal (vision-language), thinking mode on by default — [Qwen/Qwen3.5-9B model card](https://huggingface.co/Qwen/Qwen3.5-9B)
- Granite 4.1 (dense 3B / 8B / 30B; 8B has 40 layers, 4096 embedding, GQA), Apache 2.0 — [IBM Granite 4.1 blog](https://huggingface.co/blog/ibm-granite/granite-4-1)
- Granite 4.0-H-Tiny is a 7B-class hybrid instruct model — [ibm-granite/granite-4.0-h-tiny](https://huggingface.co/ibm-granite/granite-4.0-h-tiny) (active-parameter count not verified)
- Gemma 4 family: E2B (~2.3B effective), E4B (~4.5B effective, 7.5B incl. embeddings), 12B Unified, 26B-A4B MoE (25.2B total, 3.8B active), 31B dense; Apache 2.0 (changed from the old Gemma terms) — [Codersera Gemma 4 guide](https://codersera.com/blog/gemma-4-complete-guide-2026/), [Unsloth Gemma 4](https://unsloth.ai/docs/models/gemma-4)
- Unsloth 4-bit memory estimates for Gemma 4: E4B 5.5-6 GB, 12B 7-8 GB, 26B-A4B 16-18 GB, i.e. 12B and 26B-A4B do not fit 5 GB — [Unsloth Gemma 4](https://unsloth.ai/docs/models/gemma-4)
- Qwen3.5-35B-A3B (256 experts, 3B active): Unsloth Q3_K_XL 16.06 GB, Q4_K_XL 19.17 GB — [Unsloth Qwen3.5 GGUF benchmarks](https://unsloth.ai/docs/models/qwen3.5/gguf-benchmarks)
- Nemotron-3-Nano-30B-A3B GGUF: Q3_K 18.99-19.59 GB, Q4_K_S 22.39 GB, Q4_K ~24.7 GB; NVIDIA Open Model License (permits self-hosting) — [bartowski GGUF](https://huggingface.co/bartowski/nvidia_Nemotron-3-Nano-30B-A3B-GGUF), [Unsloth GGUF](https://huggingface.co/unsloth/Nemotron-3-Nano-30B-A3B-GGUF)
- Aggregator claim that Qwen3-8B needs 4.9 GB at Q4_K_M and "runs on 6-8 GB" — [willitrunai](https://willitrunai.com/models/qwen-3-8b) (differs from the 5.03 GB file above)
- Aggregator claim that Phi-4-mini 3.8B Q5 does 15-30 tok/s on 6 GB cards, and Mistral 7B / Qwen2.5 7B need Q3_K_S/M on 6 GB — [mayhemcode](https://www.mayhemcode.com/2026/06/best-local-llms-for-4gb-6gb-and-8gb.html) (low-reliability blog, no benchmark numbers)

### Inferences
- Rule of thumb: weights should be at most ~4.2-4.5 GB to leave room for CUDA context (~0.3-0.5 GB) plus KV cache. That points to Qwen3-8B at Q3_K_M/IQ3_M, Qwen3.5-9B at Q3_K_M (4.67 GB, tight), or Granite 4.1 8B at a similar 3-bit quant (GGUF sizes not retrieved; ~4.0-4.4 GB at Q3_K_M by analogy to Qwen3-8B).
- Qwen3.5-9B uses linear-attention layers, so its KV cache should be much smaller than a standard transformer's at 4-8k context (inference from architecture; no measurement found). Qwen3-8B KV at 4-8k in f16 is probably ~0.5-1 GB (my estimate, unverified).
- The 1660 SUPER has no tensor cores and 336 GB/s bandwidth, so decode should be bandwidth-limited (no measured numbers found for this card).

### Gaps
- Exact GGUF sizes for Granite 4.1 8B, Llama 3.1/3.3 8B, Ministral 8B, Phi-4 variants, Gemma 4 E4B were not retrieved (tinyweights.dev fetch failed; call budget reached).
- "Nemotron-3.5 lightning" and a "Gemma 4 ~9B" were not found; Gemma 4 has E4B and 12B instead. Qwen3.6 exists (35B-A3B) but only 3.5-9B and the 35B-A3B were examined.
- No measured KV-cache figures at 4k/8k for any model.

## Quality loss from Q3/Q4 quantization

### Takeaway
Q4_K_M is generally close to lossless; Q3 costs materially more, and the loss is larger on tail metrics (KLD 99.9th percentile) than on mean perplexity. Quant behavior is model-specific: Gemma 4 E4B was catastrophic at Q4_K_M/Q3_K_M in llama.cpp.

### Cited Findings
- Qwen3.5 (Unsloth/Benjamin Marie benchmark; model size not clear from the extract, likely 35B-A3B): Q4_K_M PPL 6.6053, KLD(99.9%) 0.548; Q4_K_XL PPL 6.5918, KLD 0.410; Q3_K_M PPL 6.732, KLD 0.973; Q3_K_XL PPL 6.7245, KLD 0.954; IQ3_XXS PPL 6.7829, KLD 1.530 — [Unsloth Qwen3.5 GGUF benchmarks](https://unsloth.ai/docs/models/qwen3.5/gguf-benchmarks). Mean PPL differs by only ~2% between Q4_K_M and Q3_K_M, but tail KLD roughly doubles.
- Llama-3-8B perplexity delta vs FP16: Q4_K_M +0.18, Q3_K_M +0.66 (another source in the same summary gives +0.10-0.15 vs +0.25-0.40; llama.cpp's own table for 7B: Q4_K_M +0.0535, Q3_K_M +0.2437) — [DEV Community quantization comparison](https://dev.to/kunal_d6a8fea2309e1571ee7/llm-quantization-levels-compared-q4km-vs-q80-vs-fp16-2026-3kg2); secondary, figures conflict.
- Gemma 4 E4B perplexity: BF16 7.11, Q8_0 7.14, Q6_K 7.39, Q5_K_M 8.31, Q4_K_M 23.06, Q3_K_M 919.46; E2B degraded gradually; cause unresolved in the issue — [llama.cpp issue #22407](https://github.com/ggml-org/llama.cpp/issues/22407) (primary). Check whether later llama.cpp builds fixed it before using.
- Google QAT for Gemma 4 claims a 54% reduction in perplexity drop at Q4_0 vs post-training quantization — [3h4x blog](https://3h4x.github.io/tech/2026/06/08/gemma4-qat-vs-non-qat) (secondary summary of a Google claim).
- Unsloth Dynamic quants (UD-) are claimed to beat vanilla Q4_K_M at similar size — [Unsloth Dynamic 2.0](https://unsloth.ai/docs/basics/unsloth-dynamic-2.0-ggufs) (vendor claim).

### Inferences
- For strict JSON/tool-call reliability, Q3 tail errors (high 99.9% KLD) are the main risk; evaluate on the Northwind task set before committing.
- A 4B model at Q5/Q6 (~3-3.5 GB) leaves ample KV room and avoids Q3 tail risk.

### Gaps
- No head-to-head task benchmark (IFEval/BFCL/JSON) of Q3 vs Q4 vs FP16 for the same 8B model was found.
- Qwen3-8B and Granite 4.1 8B specific PPL/KLD tables not found.

## CPU spill: tokens/sec on Ryzen 5 3600 / 16 GB RAM

### Takeaway
No measurement for this exact hardware was found. For MoE with expert offload, speed is good per GB, but 16 GB system RAM cannot hold a 16-19 GB 30-35B model alongside Windows. Dense-model layer spill speeds on this CPU are not documented in what I found.

### Cited Findings
- `--n-cpu-moe` / `-ot ".ffn_.*_exps.=CPU"` keeps non-expert layers on GPU and experts in RAM — [Unsloth Qwen3-Coder guide](https://unsloth.ai/docs/models/tutorials/qwen3-coder-how-to-run-locally)
- Qwen3.6-35B-A3B: RTX 3090 full-VRAM 157.66 tok/s; RTX 3060 12 GB with `--n-cpu-moe 24` ~38-39 tok/s (needs 32 GB+ DDR4); GTX 1650 4 GB with all experts in RAM ~20 tok/s — [InsiderLLM](https://insiderllm.com/guides/best-way-run-qwen-3-6-35b-moe-locally/) (secondary; RAM for the 1650 case not stated)
- Reported but unverified: Qwen3.5-35B-A3B Q6_K at ~20 tok/s on a laptop with 6 GB VRAM + 32 GB RAM — surfaced via a search snippet; original post not located.
- Qwen3-30B-A3B Q4_K_M (16.49 GiB), Vulkan: 20.87 tok/s generation (hardware unclear) — [DEV Community Qwen3 hardware report](https://dev.to/ai4b/comprehensive-hardware-requirements-report-for-qwen3-part-ii-4i5l)
- Unsloth: Qwen3-30B-A3B dynamic 4-bit needs ~18 GB combined RAM+VRAM for 6+ tok/s — [Unsloth Qwen3-Coder guide](https://unsloth.ai/docs/models/tutorials/qwen3-coder-how-to-run-locally)

### Inferences
- With 16 GB RAM + 6 GB VRAM (22 GB total, ~5 GB usable VRAM), a ~16 GB Q3 MoE would only just fit combined, leaving little for the OS; expect swapping risk. Practically 35B-A3B is out unless RAM goes to 32 GB.
- Ryzen 5 3600 (DDR4 dual channel) is the throughput bottleneck for spilled layers; every layer moved to CPU slows decode notably (no data).

### Gaps
- No Ryzen 5 3600 or GTX 1660 SUPER specific tok/s found; recommend running `llama-bench` locally with an `-ngl` sweep for Qwen3-8B Q3_K_M and Q4_K_M.
- The canirun.ai GTX 1660 SUPER page (https://www.canirun.ai/device/gtx-1660-super/) was surfaced but not fetched.

## Published benchmark scores (IFEval, BFCL, MMLU-Pro, JSON)

### Takeaway
Granite 4.1 8B has the best-documented instruct-mode numbers for this class (IFEval 87.1, BFCL v3 68.3, MMLU-Pro 56.0). Qwen3.5-9B's headline numbers (MMLU-Pro 82.5, IFEval 91.5) look like thinking-mode vendor figures and are not comparable. All scores are full precision, not Q3/Q4.

### Cited Findings
- Granite 4.1 8B instruct: IFEval 87.06, BFCL v3 68.27, MMLU-Pro 55.99, GSM8K 92.49, HumanEval 87.2%. Granite 4.1 30B: IFEval 89.65, BFCL v3 73.68, MMLU-Pro 64.09 — [IBM Granite 4.1 blog](https://huggingface.co/blog/ibm-granite/granite-4-1) (primary)
- Granite 4.0-H-Tiny: IFEval avg 81.44 (instruction-strict 84.78, prompt-strict 78.1), BFCL v3 57.65 — [ibm-granite/granite-4.0-h-tiny](https://huggingface.co/ibm-granite/granite-4.0-h-tiny)
- Qwen3.5-9B: MMLU-Pro 82.5, IFEval 91.5, GPQA Diamond 81.7 — [model card](https://huggingface.co/Qwen/Qwen3.5-9B) (vendor; thinking mode default, treat as upper bound)
- Qwen3-4B-Instruct-2507 (4B comparator): MMLU-Pro 69.6, IFEval 83.4, BFCL-v3 61.9 — [HF model card](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507) (as relayed by search summary)
- Gemma 4 MMLU-Pro: 31B 85.2%, 26B-A4B 82.6% — [Unsloth Gemma 4](https://unsloth.ai/docs/models/gemma-4); no IFEval/BFCL found.
- Nemotron-3-Nano-30B-A3B: BFCL v4 53.8; an IFEval value of 42.21 appeared in a search summary but seems implausible (different metric/setup?) — [RedHatAI FP8 card](https://huggingface.co/RedHatAI/NVIDIA-Nemotron-3-Nano-30B-A3B-FP8); UNVERIFIED.
- Granite 4.0 Nano (1B/350M) reported by IBM to beat similar-size peers on IFEval and BFCL v3; no numbers retrieved — [IBM Granite 4.0 Nano blog](https://huggingface.co/blog/ibm-granite/granite-4-nano)
- A local benchmark of Granite 4.1 8B vs Llama 3.1 / Qwen 2.5 / Mistral 7B exists — [Abivarma/Granite4-1](https://github.com/Abivarma/Granite4-1) (not read)

### Inferences
- Granite 4.1 8B (Apache 2.0, strong IFEval/BFCL, plain dense GQA) looks like the best-fit 8B for structured-output and tool-calling work at Q3/Q4. Qwen3-4B-Instruct-2507 reaches ~96% of its IFEval at roughly half the memory, so the 8B-at-Q3 premium over a 4B at Q5/Q6 may be small for these tasks (different eval setups; inference only).

### Gaps
- No published JSON-extraction benchmark for any of these models; no BFCL/IFEval for Qwen3-8B, Llama 3.1/3.3 8B, Ministral 8B, Phi-4 variants, Gemma 4 E4B/12B retrieved.
- No benchmark scores for quantized (Q3/Q4) variants.
- Licenses: Qwen3/3.5, Granite 4.x, Gemma 4 are Apache 2.0; Nemotron-3 uses NVIDIA Open Model License. Llama 3.x and Ministral licenses were not verified this session.

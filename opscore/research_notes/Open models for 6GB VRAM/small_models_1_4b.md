# Open-weight LLMs 1B-4.5B for a 6 GB VRAM GPU (GTX 1660 SUPER, ~5 GB free), as of Oct 2026

## Which models exist in this class and which are newest (2026)?

### Takeaway
2026 entries: Qwen3.5 (0.8B/2B/4B; ~Feb 2026), Gemma 4 E2B/E4B (Apr 2026), Granite 4.1 3B (29 Apr 2026). Late-2025 holdovers: Ministral 3 3B (Dec 2025), LFM2.5 1.2B (Nov 2025), Granite 4.0 (Oct 2025), Qwen3-4B-2507. Older: Phi-4-mini, SmolLM3, Llama 3.2, Gemma 3. Gemma 4 E4B (6.6 GB Q4) does NOT fit ~5 GB free; E2B Q4 (4.6 GB) barely does with tiny context.

### Cited Findings
- Qwen3.5 on Ollama: 0.8B, 2B, 4B, 9B, 27B, 35B-A3B, 122B-A10B; all 256K ctx, text+image; capabilities vision/tools/thinking — [Ollama tags](https://ollama.com/library/qwen3.5/tags), [Ollama page](https://ollama.com/library/qwen3.5)
- Qwen3.5-4B: Apache 2.0, 262,144 native ctx, hybrid Gated DeltaNet architecture, thinking ON by default (disable with enable_thinking False); release ~Feb 2026 (inferred from metadata, weak) — [HF card](https://huggingface.co/Qwen/Qwen3.5-4B)
- Qwen3.5-2B: Apache 2.0, 262K ctx, thinking OFF by default — [HF card](https://huggingface.co/Qwen/Qwen3.5-2B)
- Gemma 4 released 2 Apr 2026: E2B (2.3B effective), E4B (4.5B effective, ~8B with embeddings), 26B, 31B; Apache 2.0; text/image/audio — [Labellerr](https://www.labellerr.com/blog/gemma-4-open-weight-ai-model-overview/), [HF E4B card](https://huggingface.co/google/gemma-4-E4B-it). (A different date, 2 Jul 2026, was derived by a fetch summarizer from an arXiv tech-report ID; Apr 2026 is the more consistent date.)
- Gemma 4 E4B-it: 128K ctx, thinking via `<|think|>`, native function calling, 42 layers — [HF card](https://huggingface.co/google/gemma-4-E4B-it)
- Ollama also lists gemma4:12b (7.7-8 GB, 256K) - outside size class — [Ollama tags](https://ollama.com/library/gemma4/tags)
- Granite 4.1 3B: Apache 2.0, 131,072 ctx, released 29 Apr 2026 — [HF card](https://huggingface.co/ibm-granite/granite-4.1-3b)
- Granite 4.0 Micro (3B): Apache 2.0, 128K ctx, 2 Oct 2025 — [HF card](https://huggingface.co/ibm-granite/granite-4.0-micro)
- Ministral 3 3B Instruct 2512: Apache 2.0, 256K ctx, 2 Dec 2025, 3.4B LM + 0.4B vision encoder, native function calling and JSON output — [HF card](https://huggingface.co/mistralai/Ministral-3-3B-Instruct-2512)
- LFM2.5-1.2B-Instruct: 1.17B, 32K ctx, 28 Nov 2025, custom "LFM1.0" license (not plain Apache; commercial terms not verified here) — [HF card](https://huggingface.co/LiquidAI/LFM2.5-1.2B-Instruct)
- LFM2.5-Thinking 1.2B on Ollama (731 MB, 32K) — [Ollama](https://ollama.com/library/lfm2.5-thinking)
- Phi-4-mini-instruct: 3.8B, MIT, 128K ctx, Feb 2025 — [HF card](https://huggingface.co/microsoft/Phi-4-mini-instruct)
- SmolLM3-3B: Apache 2.0, 64k trained / 128k with YaRN, dual /think /no_think — [HF card](https://huggingface.co/HuggingFaceTB/SmolLM3-3B)
- Qwen3-4B-Instruct-2507 / Thinking-2507: Apache 2.0, 262K ctx — [HF card](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507)
- Nemotron 3 Nano mentioned as ~3B active (MoE, 1M ctx); total params/size not verified, likely too big for 6 GB — [Turing Post via search snippet](https://www.turingpost.com/p/slmslist)

### Inferences
- Best 2026 fits for ~5 GB free: Qwen3.5-4B Q4 (3.4 GB), Qwen3.5-2B, Granite 4.1 3B, Ministral 3 3B Q4 (3.0 GB), Gemma 4 E2B only at QAT/Q4.

### Gaps
- Llama 3.2 successors (none found); Phi-5; SmolLM4; exact Nemotron Nano size; Qwen3.5 exact release date; LFM license terms; Granite 4.1 Ollama tag (not checked).

## Download sizes / Ollama and GGUF availability (Ollama tags, GB)

### Takeaway
Ollama has all major families. Q4_K_M is roughly 0.6-0.9 GB per B params; Q8 roughly 1.1-1.3 GB per B. Q8 of 4B models (4.3-5.3 GB) is too big once KV cache is added on ~5 GB free.

### Cited Findings
- Qwen3.5: 0.8b 1.0 (q8 1.0, bf16 1.8); 2b q4_K_M 1.9, q8 2.7, bf16 4.6; 4b q4_K_M 3.4, q8 5.3, bf16 9.3; 9b q4 6.6 — [Ollama](https://ollama.com/library/qwen3.5/tags)
- Gemma 4: e2b qat 4.3, q4_K_M 4.6, q8 8.1; e4b qat 6.1, q4_K_M 6.6, q8 12 (large due to embeddings); 128K ctx — [Ollama](https://ollama.com/library/gemma4/tags)
- Qwen3 4B (2507): q4_K_M 2.5, q8 4.3, fp16 8.1; tags qwen3:4b-instruct-2507-*, qwen3:4b-thinking-2507-* — [Ollama tags via search snippet](https://ollama.com/library/qwen3/tags)
- Ministral-3 3B: q4_K_M 3.0, q8 4.5, fp16 7.7; 256K — [Ollama](https://ollama.com/library/ministral-3/tags)
- Granite4: micro/3b 2.1 (128K), 3b-h 1.9 (1M ctx claimed), 1b-h 1.6, 350m 0.7, 7b-a1b-h tiny 4.2 — [Ollama](https://ollama.com/library/granite4/tags)
- Phi4-mini 3.8b q4_K_M 2.5 (128K); q8 4.1; fp16 7.7 (listing showed 4K ctx for q8/fp16, probably a listing artifact) — [Ollama](https://ollama.com/library/phi4-mini/tags)
- Gemma 3: 1b q4 0.815 (32K, text), 4b q4_K_M 3.3, q8 5.0, qat 4.0 (128K, vision) — [Ollama](https://ollama.com/library/gemma3/tags)
- Llama 3.2: 1B 0.58-2.5 GB, 3B 1.4 (q2_K) to 6.4 (fp16), 128K — [Ollama](https://ollama.com/library/llama3.2/tags)

### Inferences
- Comfortable on ~5 GB free with 8-16K ctx: all Q4 models up to 3.4 GB. Qwen3.5 hybrid linear attention likely keeps KV cache small at long ctx (inference, not measured).
- Gemma 4 E4B Q4 (6.6 GB) will spill to CPU on this GPU.

### Gaps
- No measured VRAM or tok/s on a GTX 1660 SUPER. Q5 tag sizes not listed on Ollama for most models.

## Published benchmarks (vendor model cards; eval setups differ, not directly comparable)

### Takeaway
Qwen3.5-4B (thinking) leads on knowledge and IFEval; Granite 4.x and Qwen3-4B-2507 are strong on tool calling for size; Gemma 4 E4B strong on reasoning but too big.

### Cited Findings
- Qwen3.5-4B: MMLU-Pro 79.1, IFEval 89.8, BFCL-V4 50.3, AA-LCR 57.0 — [HF](https://huggingface.co/Qwen/Qwen3.5-4B)
- Qwen3.5-2B (non-thinking): MMLU-Pro 55.3, IFEval 61.2, BFCL-V4 43.6 — [HF](https://huggingface.co/Qwen/Qwen3.5-2B)
- Qwen3-4B-Instruct-2507: MMLU-Pro 69.6, IFEval 83.4, BFCL-v3 61.9, TAU1-Retail 48.7, AIME25 47.4 — [HF](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507)
- Gemma 4 E4B-it: MMLU-Pro 69.4, GPQA-D 58.6, LiveCodeBench v6 52.0, MRCR v2 8-needle 128k 25.4 — [HF](https://huggingface.co/google/gemma-4-E4B-it); E2B MMLU-Pro 60.0 — [Labellerr](https://www.labellerr.com/blog/gemma-4-open-weight-ai-model-overview/)
- Granite 4.1 3B: IFEval 82.30, BFCL v3 60.80, MMLU 67.02, GSM8K 86.88 — [HF](https://huggingface.co/ibm-granite/granite-4.1-3b)
- Granite 4.0 Micro: MMLU 65.98, GSM8K 85.45, IFEval 82.31, BFCL v3 59.98 — [HF](https://huggingface.co/ibm-granite/granite-4.0-micro)
- Phi-4-mini: MMLU 67.3, MMLU-Pro 52.8, GSM8K 88.6, MATH 64.0 — [HF](https://huggingface.co/microsoft/Phi-4-mini-instruct)
- SmolLM3-3B: IFEval 76.7 (no-think), BFCL 92.3 (card figure; likely vendor harness, not comparable to BFCL v3 leaderboard), GSM8K 67.6, AIME25 9.3 -> 36.7 with thinking — [HF](https://huggingface.co/HuggingFaceTB/SmolLM3-3B)
- LFM2.5-1.2B-Instruct: IFEval 86.23, MMLU-Pro 44.35, GPQA 38.89, BFCLv3 49.12 — [HF](https://huggingface.co/LiquidAI/LFM2.5-1.2B-Instruct); LFM2.5-Thinking: GSM8K 85.6, MATH-500 88.0, IFEval 88.4 — [Ollama](https://ollama.com/library/lfm2.5-thinking)
- Ministral 3 3B Instruct: Arena Hard 0.305, MATH 0.830 (no MMLU/IFEval/BFCL on card) — [HF](https://huggingface.co/mistralai/Ministral-3-3B-Instruct-2512)

### Inferences
- On BFCL v3, Qwen3-4B-Instruct-2507 (61.9), Granite 4.1 3B (60.8), Granite 4.0 Micro (60.0) lead; Qwen3.5 reports v4 (different), not comparable.

### Gaps
- BFCL leaderboard table could not be read (page content not rendered). No Artificial Analysis, JSON/structured-output, or independent long-context scores found. No Llama 3.2 or Gemma 3 benchmark numbers pulled.

## Tool calling, JSON schema output in Ollama, and thinking models

### Takeaway
Ollama structured outputs are generic (`format` = JSON schema), so they apply to any model; tool calling depends on the model template. Ollama marks Qwen3.5 as tools+thinking+vision.

### Cited Findings
- Structured outputs: pass JSON schema in `format` (or OpenAI-compatible `response_format`); lower temperature recommended; docs do not discuss thinking-model interactions — [Ollama docs](https://docs.ollama.com/capabilities/structured-outputs)
- Qwen3.5: Ollama capabilities "vision, tools, thinking" — [Ollama](https://ollama.com/library/qwen3.5)
- Granite 4: Ollama describes improved tool calling — [Ollama](https://ollama.com/library/granite4/tags)
- Phi4-mini: Ollama notes function calling support — [Ollama](https://ollama.com/library/phi4-mini/tags)
- Thinking models: Qwen3.5-4B (default on), Qwen3-4B-Thinking-2507, SmolLM3 (/think), Gemma 4 (`<|think|>`), LFM2.5-Thinking; Qwen3.5-2B default off — HF cards above
- LFM2.5 emits Pythonic tool calls between special tokens (may need parser support) — [HF](https://huggingface.co/LiquidAI/LFM2.5-1.2B-Instruct)

### Inferences
- Likely best picks for tool calling + schema output: qwen3.5:4b (Q4 3.4 GB, thinking off for latency), qwen3:4b-instruct-2507 (2.5 GB), granite4:3b (2.1 GB). Verify with a local test.

### Gaps
- Per-model Ollama "tools" badge not verified for Granite 4.1, Ministral 3, LFM, SmolLM3. Known Ollama issues combining `format` with thinking not verified.

# Benchmarks that predict small (<9B) local LLM performance: structured output, extraction, instruction following, tool calling (as of 2026-10-02)

Caveat for the report writer: about 13 tool calls were used. Several numbers come from WebFetch summaries of pages or PDFs. Where a summary looked unreliable it is flagged. Vendor-reported (V) and independent (I) numbers are labeled. The BFCL leaderboard (gorilla.cs.berkeley.edu) was NOT fetched directly. BFCL numbers below come from aggregators and model cards.

## Which small open models lead on BFCL / tool calling?

### Takeaway
No clean independent sub-9B BFCL ranking was found. Vendor-reported BFCL v3/v4 numbers put Qwen3.5-9B (66.1 on v4) and Qwen3-4B-Instruct-2507 (61.9 on v3) at or near the top of the small class. Granite 4.x and LFM2.5 are lower on self-reported v3/v4. BFCL v3 and v4 scores are not comparable with each other, and every v4 number on llm-stats is self-reported.

### Cited Findings
- (V) Qwen3.5-9B BFCL-V4 = 66.1; Qwen3.5-4B = 50.3. The model card also lists IFEval 91.5 (9B) and 89.8 (4B). — [Qwen3.5-4B HF card](https://huggingface.co/Qwen/Qwen3.5-4B)
- (V) Qwen3-4B-Instruct-2507: BFCL-v3 61.9, IFEval 83.4, MMLU-Pro 69.6, AIME25 47.4. — [Qwen3-4B-Instruct-2507 HF card](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507)
- (V) IBM Granite-4.0-H-Micro (3B) BFCL v3 = 57.56; H-Tiny (7B total, 1B active) = 57.65. — [Granite 4.0 H-Tiny card](https://huggingface.co/ibm-granite/granite-4.0-h-tiny) (via search snippet; page not fetched)
- (V, self-reported, aggregator) BFCL-V4 scores for sub-10B models listed on llm-stats: LFM2.5-2.6B 0.569; Granite 4.2 3B 0.524; Granite 4.2 8B 0.524; Qwen3.5-4B 0.503; Qwen3.5-2B 0.436; Qwen3.5-0.8B 0.253. All 22 entries are self-reported and none verified. The list omits Qwen3.5-9B (66.1 on the HF card). — [llm-stats BFCL-V4](https://llm-stats.com/benchmarks/bfcl-v4)
- (I, leaderboard via search snippet, not verified on the official site) BFCL Qwen3-4B (Prompt) overall 62.04%, with live 75.52%, non-live 82.58%, multi-turn 35.25%. xLAM-2-3b-fc-r (FC) overall 65.74%, live 81.03%, non-live 88.22%, multi-turn 55.62%. xLAM-2-1b-fc-r overall 53.97%, multi-turn 8.38%. The snippet also says Qwen3 8B "achieved 80.53%", with no category given and unclear context. Treat that figure as unreliable. Qwen3 sizes 1.7B-32B were added to BFCL in May 2025. — search results citing [BFCL changelog](https://github.com/ShishirPatil/gorilla/blob/main/berkeley-function-call-leaderboard/CHANGELOG.md) and [APIGen-MT](https://arxiv.org/pdf/2504.03601)
- Multi-turn is the weak point of small models: xLAM-2-3b 55.6%, Qwen3-4B 35%, xLAM-2-1b 8% (same source as above). BFCL v4 also covers agentic/web-search and memory categories, so v3-era numbers overstate agentic ability. The v4 category breakdown was not retrieved.
- (V) Phi-4-mini technical report lists IFEval 70.1 (0-shot) against Llama-3.2-3B-Instruct 68.0, Qwen2.5-7B 69.5, Llama-3.1-8B 74.1 and Gemma2-9B 73.2. — [Phi-4-Mini Technical Report](https://arxiv.org/pdf/2503.01743)
- CONTRADICTED. A blog claims BFCL v4 "high 80s" for Qwen3-4B, "mid-to-high 80s" for Gemma 4 E4B and "low-to-mid 80s" for Phi-4-mini. The blog says it is not first-party: "synthesized from public benchmarks, vendor model cards", May 10 2026. It conflicts with the 50-66 v4 range above and gives no per-model numbers. Do not use it. — [Ertas AI](https://www.ertas.ai/blog/on-device-tool-calling-2026-qwen3-gemma4-phi4)
- A TinyLLM arXiv paper (2511.22138) evaluates small models on agentic and tool tasks with BFCL. My fetch summary appeared to hallucinate the model list (Phi-2, Llama-2-7B) and I could not confirm specifics. It is unusable until re-read. — [TinyLLM](https://arxiv.org/pdf/2511.22138)

### Inferences
- Within vendor-reported numbers, Qwen3.5-9B > Qwen3-4B-2507 (v3, different benchmark version) > Granite 4.x ≈ LFM2.5 on tool calling. Cross-family comparison is weak because the numbers are self-reported, mix v3 and v4, and use unknown prompt versus native function-calling (FC) modes.
- For a single-turn extraction pipeline, the BFCL non-live / simple-function subscores matter more than the overall score. These were not collected for most models.

### Gaps
- Official BFCL leaderboard rows for Gemma 3/4, Llama 3.2, Phi-4-mini, SmolLM3 and Ministral were not retrieved. gorilla.cs.berkeley.edu is a dynamic page. Fetch its CSV (data_overall.csv) directly.
- No independent BFCL v4 numbers for Qwen3.5 small models.

## Which models lead on IFEval?

### Takeaway
Vendor-reported IFEval puts Qwen3.5-9B (91.5), Qwen3.5-4B (89.8), Granite 4.0 H-Micro (86.9 instruction-level strict) and Qwen3-4B-Instruct-2507 (83.4) in the 83-92 range. IFEval is near saturation for 2026-era small models and is vendor-reported, with differing metric variants (prompt vs instruction, strict vs loose).

### Cited Findings
- (V) Qwen3.5-9B 91.5; Qwen3.5-4B 89.8. — [Qwen3.5-4B card](https://huggingface.co/Qwen/Qwen3.5-4B)
- (V) Qwen3-4B-Instruct-2507 = 83.4. — [Qwen3-4B-Instruct-2507 card](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507)
- (V) Granite-4.0-H-Micro IFEval instruction-strict 86.94 and prompt-strict 81.71. H-Tiny scores 84.78 and 78.1. — [Granite 4.0 H-Tiny card](https://huggingface.co/ibm-granite/granite-4.0-h-tiny) (snippet)
- (V) Phi-4-mini 70.1, with older comparisons (Llama-3.2-3B 68.0, Ministral-3B 47.5, Qwen2.5-3B 59.0). — [Phi-4-mini report](https://arxiv.org/pdf/2503.01743)
- An aggregator reports Qwen3-4B-Instruct-2507 at 69.6 MMLU-Pro and Phi-4-mini at 67.3 MMLU. Treat it as low-reliability. — [Intuz list](https://www.intuz.com/blog/best-small-language-models/)

### Inferences
- The strict/loose and prompt/instruction variants differ by roughly 5 points (the Granite figures show this). Compare like for like.
- IFEval above ~85 no longer separates models well. For format-following, JSON-specific tests (below) are more informative.

### Gaps
- No independent IFEval rerun comparing Gemma 3/4, SmolLM3, Ministral 3 and Llama 3.2 on the same harness. Gemma, SmolLM3 and Ministral card numbers were not retrieved.

## Structured output / JSON schema benchmarks

### Takeaway
The only direct, independent small-model comparison found (Sept 2026, 0.6-4B) shows that native JSON-schema validity is high for Qwen3-4B (100%) but weaker for Llama 3.2 (78.6%) and Phi-4-mini (92.9%). Constrained decoding raises all of them to 100% validity, and content accuracy remains the real differentiator.

### Cited Findings
- (I, arXiv Sept 20 2026) Five models, 14 tasks (JSON generation, schema adherence, function calling, data extraction). Native schema validity: Llama-1B 78.6%, Llama-3B 78.6%, Qwen-0.6B 92.9%, Qwen-4B 100%, Phi-4-mini 92.9%. Constrained decoding gave 100% for all. Content accuracy native vs best constrained: Llama-1B 0.771 vs 0.986; Llama-3B 0.777 vs 0.991; Qwen-0.6B 0.871 vs 0.943; Qwen-4B 1.000 vs 1.000; Phi-4-mini 0.929 vs 1.000. Instruction-semantic failures survive masking. — [Constrained Decoding in Small LLMs (arXiv 2609.23742)](https://arxiv.org/html/2609.23742v1). Caveat: the 14-task suite is small and Qwen-4B's 100% suggests ceiling effects.
- (I) JSONSchemaBench has ~10K real-world schemas. Constrained-decoding coverage collapses from 86% on simple schemas to 3% on ultra-complex ones. XGrammar emitted non-compliant output silently in 38 cases. Model-agnostic, with Llama-3.2-1B as the test model. — [JSONSchemaBench](https://arxiv.org/pdf/2501.10868) and [Beancount.io summary](https://beancount.io/bean-labs/research-logs/2026/07/08/jsonschemabench-structured-outputs-language-models)
- (I) The Structured Output Benchmark (SOB), arXiv 2604.25359, measures value accuracy, JSON validity and schema compliance. It reports that "JSON validity often exceeds value accuracy". My fetch summary listed Llama 2/Mistral 7B and looked unreliable, so per-model numbers are not captured. — [SOB](https://arxiv.org/pdf/2604.25359)
- (I) Runtime bug: in Ollama, think=false combined with format (structured output) silently disabled the JSON constraint for gemma4:26b-a4b on Ollama 0.20.0 (Apr 3 2026), the same class as an earlier qwen3.5 issue (#14645). Workaround: omit think. — [ollama#15260](https://github.com/ollama/ollama/issues/15260)

### Inferences
- Use grammar/schema-constrained decoding (llama.cpp GBNF, XGrammar, Outlines) for a 4B local model. Validity then becomes a non-issue and eval effort should go to field-value accuracy.
- Check that the runtime applies the schema mask when thinking is off. This is runtime-specific (Ollama).

### Gaps
- No leaderboard comparing Gemma 3/4, Granite 4.x, SmolLM3 and Ministral on JSON-schema tasks. No per-model SOB numbers.

## Extraction tasks (documents, invoices)

### Takeaway
Independent evidence is thin, and no invoice-specific benchmark with sub-9B text models was found. The closest result: a fine-tuning study of noisy-text field extraction where 4B models land within ~0.5 F1 of an 8B model.

### Cited Findings
- (I, arXiv June 6 2026) Merchant-info extraction (10 fields from bank transaction strings), F1: LLaMA 3.1 8B (LoRA) 96.75; Qwen 3.5 4B (JSON-only prompt, no thinking) 96.60; Gemma 3 4B (fine-tuned) 96.24; Qwen 3.5 4B (fine-tuned, nothink) 96.24; Qwen 3.5 2B 95.18; Qwen 3.5 0.8B 94.75; Gemma 3 1B 93.93; Gemma 3 270M 87.35. Think and Nothink training templates differ by <0.004 F1. — [How Small Can You Go? (arXiv 2606.08051)](https://arxiv.org/html/2606.08051v1). Caveats: the task is short strings, not full invoices, and mostly fine-tuned.
- A GitHub benchmark (slm-doc-extract-bench) compares OCR+text SLM pipelines (Phi-4-mini, Gemma3, Llama 3.2) against VLMs (Qwen2.5/3-VL, InternVL3, SmolVLM2) on field F1 and JSON validity. Results sit in results/leaderboard.md and were not retrieved. — [repo](https://github.com/carlacasaroti/slm-doc-extract-bench)
- Candidates not read in full: [Pixels to Pairs KV-extraction benchmark (2609.17538)](https://arxiv.org/pdf/2609.17538) and [UNIKIE-BENCH (2602.07038)](https://arxiv.org/pdf/2602.07038). A SROIE snippet says Qwen2.5-7B was strongest of the 7B-class text models tested, then Mistral-7B and DeepSeek-7B. — [search result](https://arxiv.org/pdf/2405.20585) (weak source)

### Inferences
- Prompt-only 4B models are plausibly adequate for field extraction when the schema is constrained. The Northwind case should be validated on a small in-house invoice set, since public benchmarks do not cover it.

### Gaps
- No public invoice benchmark with comparable numbers for Gemma/Granite/SmolLM3/Ministral. Pixels-to-Pairs and UNIKIE need reading.

## MMLU-Pro, reasoning, long-context, hallucination

### Takeaway
Only vendor numbers for Qwen were gathered. MMLU-Pro, GSM8K and AIME are weak predictors of extraction and tool-calling quality, and GSM8K is saturated for 4B+ models. Hallucination benchmarks were not retrieved.

### Cited Findings
- (V) MMLU-Pro: Qwen3.5-9B 82.5, Qwen3.5-4B 79.1 (thinking-mode scores). — [Qwen3.5-4B card](https://huggingface.co/Qwen/Qwen3.5-4B). Qwen3-4B-Instruct-2507 69.6. — [card](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507)
- (V) Long-context: AA-LCR 57.0 (4B) and 63.0 (9B); LongBench v2 50.0 (4B) and 55.2 (9B). — [Qwen3.5-4B card](https://huggingface.co/Qwen/Qwen3.5-4B)

### Inferences
- Models still gain across generations at the same size (Qwen3-4B-2507 to Qwen3.5-4B: MMLU-Pro 69.6 to 79.1, IFEval 83.4 to 89.8), but these cards compare thinking-enabled settings against non-thinking ones, so part of the jump may come from the mode.

### Gaps
- No hallucination (e.g. Vectara HHEM, SimpleQA, FaithBench) data for sub-9B open models. Gemma 3/4, Llama 3.2, SmolLM3 and Ministral numbers not retrieved. Artificial Analysis was not consulted.

## Effect of disabling thinking mode

### Takeaway
For structured extraction, thinking adds latency and can break parsers while giving little accuracy gain. The one controlled study found no F1 difference. Defaults matter: Qwen3.5 thinks by default and must be told enable_thinking false. Runtime bugs can disable schema constraints when thinking is off.

### Cited Findings
- (V) Qwen3.5 operates in thinking mode by default. Disable it with enable_thinking: False through chat_template_kwargs (vLLM/SGLang). — [Qwen3.5-4B card](https://huggingface.co/Qwen/Qwen3.5-4B)
- (I) Nothink and Think fine-tune templates differ by <0.004 F1 on extraction; Qwen3.5-4B no-thinking gets 96.60 F1 with a JSON-only prompt. — [arXiv 2606.08051](https://arxiv.org/html/2606.08051v1)
- (I) Ollama think=false with format silently ignored the schema (Apr 2026, gemma4 / earlier qwen3.5). — [ollama#15260](https://github.com/ollama/ollama/issues/15260)
- (Opinion, low quality) Blogs advise think: false for strict JSON. — [Citium Tech](https://www.citiumtech.com/insights/reasoning-vs-non-reasoning-models), [Serverman](https://www.serverman.co.uk/ai/ollama/ollama-thinking-mode/)
- Granite 4.2 also uses enable_thinking=False (search snippet only, unverified).

### Inferences
- Run non-thinking with a schema-constrained decoder, and test the exact runtime/flag combination.

### Gaps
- No controlled non-thinking vs thinking comparison on BFCL or IFEval for the same sub-9B model.

## Saturated or unreliable benchmarks

### Takeaway
IFEval (above ~85), GSM8K and BFCL simple/non-live categories are near ceiling. BFCL v4 overall is self-reported on aggregators. Structured-output suites are small, so model differences are mostly noise at the top.

### Cited Findings
- All BFCL-V4 entries on llm-stats are self-reported, with zero verified. — [llm-stats](https://llm-stats.com/benchmarks/bfcl-v4)
- Qwen-4B scored 100% native validity and accuracy on the 14-task suite (ceiling effect). — [arXiv 2609.23742](https://arxiv.org/html/2609.23742v1)
- Aggregators (benchlm, benchmarklist, Ertas, Intuz) can disagree with model cards, so prefer primary sources. Example: Ertas "high 80s" BFCL v4 vs the card's 50.3 for Qwen3.5-4B. — [Ertas](https://www.ertas.ai/blog/on-device-tool-calling-2026-qwen3-gemma4-phi4)

### Gaps
- Contamination analyses for IFEval/BFCL were not searched.

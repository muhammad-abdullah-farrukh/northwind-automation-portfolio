# leads_test labels: who labelled them and why

Labelled on 2026-10-19 by Claude, at the owner's request, **before any model run on these 16 leads**. The labels apply
the written ideal-client rubric in `prompts/lead_icp_v1.md`: size 11–200, an offered service, budget $2k+, a start within
about 3 months, a company email and a concrete problem. Spam means a sales pitch or an adversarial or meaningless message,
not a genuine enquiry. Because the labeller also wrote the prompt, this slice is not an independent test (DECISIONS D29 amendment).

| Lead | Label | Reason |
|---|---|---|
| N01 | hot | e-commerce 51–200, $5k–10k, Zapier/n8n, within 1 month, concrete problem |
| N02 | hot | fintech 11–50, $10k+, AI automation, ASAP, concrete, budget approved |
| N03 | warm | clinics 11–50, $2k–5k, CRM, 1–3 months, but the need is not defined yet |
| N04 | cold | solo consultant, free-mail address, under $1k, just exploring |
| N05 | cold | 1000+ bank, 3+ months, generic procurement request: outside the size and timeline fit |
| N06 | cold | student thesis, free-mail address, under $1k |
| N07 | hot | logistics 51–200, $2k–5k, Zapier/n8n, within 1 month, concrete |
| N08 | spam | SEO backlink sales pitch |
| N09 | warm | real estate, 12 staff, concrete, but a $1k–2k budget |
| N10 | cold | native app built from scratch: not a service Northwind offers |
| N11 | spam | crypto offer, disposable email, link-stuffed |
| N12 | warm | travel 51–200, $5k–10k, concrete, but starting in 3+ months |
| N13 | warm | small charity, $1k–2k, concrete and soon |
| N14 | warm | SaaS 11–50, $2k–5k, but "just exploring" with no problem described |
| N15 | spam | prompt-injection attempt asking for a personal Instagram: not a genuine business lead |
| N16 | hot | education, about 200 staff, $10k+, within 1 month, concrete (website unreachable, so enrichment is empty) |

---
name: model-rot
description: Find AI model IDs (Claude, GPT/o-series, Gemini, Groq, Mistral, Cloudflare Workers AI @cf/…, Amazon Bedrock IDs incl. us./eu. profiles, embeddings, TTS, image models), GitHub Copilot model names pinned in .prompt.md/.agent.md/.chatmode.md files, and retired APIs (e.g. OpenAI Assistants API) in code, configs and docs, and check them against the providers' official deprecation pages, parsed live: retired, retiring on a date, silently aliased, or no date. Use when an LLM call fails with model_not_found / 404, before shipping defaults, when a user asks whether their models are deprecated, or for periodic dependency hygiene in AI apps.
---

```bash
python3 <this-skill-dir>/scripts/modelrot.py <path>
python3 <this-skill-dir>/scripts/modelrot.py --lookup <model-id> ...
```
For each retired or retiring hit, propose the provider's recommended replacement (in the report). Warn that replacement models can differ in parameters and behavior, so tests should run after swapping. For silently aliased Gemini models, explain that requests already go to (and bill as) the replacement.

# model-rot

> v0.1. Standard library only. Read-only.

**Find AI model IDs and APIs in your code that providers have retired, or are about to.**

Providers retire models on published schedules, and retired IDs fail hard (HTTP 404 / `model_not_found`). Shipped products keep stale defaults in configs, docs and example files. Open issues in large projects show it: [OpenMetadata#36757](https://github.com/open-metadata/OpenMetadata/issues/36757) and [IBM/mcp-context-forge#7375](https://github.com/IBM/mcp-context-forge/issues/7375) default to a retired Claude model, and [Flowise#6698](https://github.com/FlowiseAI/Flowise/issues/6698) depends on the shut-down Assistants API.

**What's different:** model-rot **parses the providers' own deprecation pages live** (cached 24 h) instead of shipping a hand-made list. Hand-made lists rot: on 2026-11-17, an existing scanner's registry still listed `gpt-3.5-turbo` (retired 2026-10-23) and `gpt-5` (retiring 2026-12-11) as *active*.

| Provider | Official source parsed |
|---|---|
| Anthropic | [model deprecations](https://platform.claude.com/docs/en/about-claude/model-deprecations) (Markdown) <!-- evergreen --> |
| OpenAI | [deprecations](https://developers.openai.com/api/docs/deprecations) (HTML tables, including API sunsets like the Assistants API) <!-- evergreen --> |
| Google Gemini | [deprecations](https://aistudio.google.com/docs/deprecations) (Markdown export) <!-- evergreen --> |

Every hit gets one of four states:
- **retired**: requests fail now;
- **retiring on DATE**: days left, plus the provider's recommended replacement;
- **silently aliased**: requests are routed to a different model (Gemini does this), so you're running and paying for a model you didn't choose;
- **no date announced**.

```bash
python3 modelrot.py path/to/app              # exit 1 on retired / aliased / retiring within --days (default 60)
python3 modelrot.py --lookup gpt-5 claude-sonnet-4-5-20250929 gemini-2.5-pro
python3 modelrot.py path/to/app --no-docs --days 30
```

It understands Bedrock (`us.anthropic.claude-…-v1:0`) and Vertex (`claude-…@2025…`) forms, and notes that those platforms keep their own schedules. Display labels like `GPT-4` are ignored, since API IDs are lowercase.

Validated on 2026-11-17: OpenMetadata → `conf/openmetadata.yaml:705` `claude-3-5-sonnet-20240620`, retired 2025-10-28 (the bug in its open issue). mcp-context-forge → 52 retired references across code, admin UI and docs.

## Limits
- Anthropic, OpenAI and Google only, for now. Parsers are per page format; other providers can be added. Checked 2026-11-17: Alibaba Model Studio (百炼) publishes its retirement *policy* as a table ([模型下线](https://help.aliyun.com/zh/model-studio/model-depreciation): 30 days' notice for snapshots, 3 months for main models), but the retired-model lists are separate prose announcements (aliyun.com/notice/…), too fragile to parse reliably. No official deprecation page was found for DeepSeek or Zhipu.
- IDs built at runtime (`f"claude-{size}"`, environment variables) aren't visible.
- If a provider redesigns its page, parsing can break. The report shows row counts per source, so a sudden drop to 0 is visible.

## Tests
`python3 -m unittest discover tests`, offline, with fixture copies of all three page formats.

MIT license. Not affiliated with Anthropic, OpenAI or Google.

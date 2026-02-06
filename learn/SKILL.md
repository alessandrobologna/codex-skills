---
name: learn
description: Research a user-specified topic with current authoritative sources and package the findings as a reusable topic-kb skill (for example, kinesis-kb). Use when a user asks to learn about a topic, build a knowledge-base skill, or convert web research into reusable guidance.
---

# Learn

## Objective

Create a topic-specific skill folder that captures durable, source-backed knowledge other agents can reuse later.

## Inputs

- Capture the topic from the user request.
- Capture the output root. Default to `skills/` in the current workspace if the user does not specify another path.
- Capture depth as `quick` (5-8 sources) or `deep` (10-20 sources). Default to `deep` for technical topics.

## Workflow

1. Define scope and skill name.
- Normalize the topic into a slug and append `-kb`.
- Example: `Amazon Kinesis` -> `kinesis-kb`.
- Keep scope narrow enough to be useful (service-level or domain-level), not broad like "cloud".

2. Research with high-quality sources.
- Use current, authoritative sources first: official docs, standards, primary vendor docs.
- Add secondary sources only for context.
- Record URLs and access dates while researching.
- Read `references/research-rubric.md` before collecting sources.

3. Scaffold the target skill.
- Run:
```bash
python3 scripts/scaffold_topic_kb.py "TOPIC" --out skills
```
- Use `--dry-run` first when path or naming is uncertain.

4. Fill the generated knowledge sections.
- Edit the generated `SKILL.md` and replace placeholders with concise, practical guidance.
- Prefer operationally useful content: architecture patterns, pitfalls, troubleshooting, decision criteria, and API caveats.
- Keep statements grounded in cited sources. If uncertain, mark uncertainty explicitly.

5. Add and verify references.
- Populate `references/sources.md` with the source list used to build the KB.
- Include publication date when available and access date for each source.
- Add a "Last verified" date in generated `SKILL.md`.

6. Validate and report.
- Validate generated skills with:
```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/.system/skill-creator/scripts/quick_validate.py" skills/TOPIC-kb
```
- Report created files, validation status, and key coverage areas.

## Output Contract

Create this structure:

```text
<output-root>/<topic>-kb/
  SKILL.md
  agents/openai.yaml
  references/sources.md
```

Generated skill quality bar:
- Include enough detail for direct problem-solving, not just definitions.
- Include pitfalls and troubleshooting guidance.
- Include source-backed recommendations, not invented claims.
- Keep content compact and scan-friendly.

## Resources

- `scripts/scaffold_topic_kb.py`: Create a topic-kb skill skeleton with valid frontmatter and agent metadata.
- `references/research-rubric.md`: Apply source-quality and synthesis rules while researching.

## Example Invocation

- "Use the learn skill on Amazon Kinesis and create `kinesis-kb` in `skills/`."
- "Research OpenTelemetry collectors deeply and produce `opentelemetry-kb` with citations."

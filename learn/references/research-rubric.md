# Research Rubric

Use this rubric while collecting material for a generated `topic-kb` skill.

## Source Priority

1. Prefer official product documentation, standards, RFCs, and maintainer-authored references.
2. Prefer current sources over old sources when behavior may have changed.
3. Use vendor blogs, incident writeups, and community posts as secondary support.
4. Avoid uncited summaries and low-signal listicles.

## Coverage Targets

- `quick` depth: 5-8 sources, with at least 3 primary sources.
- `deep` depth: 10-20 sources, with at least 6 primary sources.
- Include at least one source for each area:
  - Core concepts
  - Architecture patterns
  - API behavior and limits
  - Operations and troubleshooting

## Evidence Logging

Capture claims while researching to avoid citation drift.

| Claim | Source URL | Confidence | Notes |
| --- | --- | --- | --- |
| [Throughput limit behavior] | [https://...] | [High/Med/Low] | [Any caveats] |

## Synthesis Rules

- Separate facts from inferences; label inferred guidance explicitly.
- Preserve important caveats, version constraints, and region constraints.
- Prefer actionable statements over textbook definitions.
- Keep generated KB sections concise and directly useful in implementation.

## Freshness Rules

- Include "Last verified" date in generated `SKILL.md`.
- Record access date for every source in `references/sources.md`.
- Re-check unstable facts (limits, pricing, release status) before finalizing output.

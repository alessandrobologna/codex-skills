#!/usr/bin/env python3
"""
Scaffold a topic-specific knowledge base skill.

Examples:
  python3 scripts/scaffold_topic_kb.py "Amazon Kinesis" --out skills
  python3 scripts/scaffold_topic_kb.py "OpenTelemetry" --out skills --dry-run
"""

import argparse
import re
import sys
from datetime import date
from pathlib import Path

MAX_NAME_LENGTH = 64
MIN_SHORT_DESCRIPTION = 25
MAX_SHORT_DESCRIPTION = 64
PROVIDER_PREFIXES = (
    "amazon ",
    "aws ",
    "google cloud ",
    "gcp ",
    "microsoft ",
    "azure ",
    "oracle ",
    "ibm ",
)


def normalize_spaces(value: str) -> str:
    return " ".join(value.strip().split())


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return re.sub(r"-{2,}", "-", slug)


def drop_provider_prefix(topic: str) -> str:
    lowered = topic.lower()
    for prefix in PROVIDER_PREFIXES:
        if lowered.startswith(prefix):
            return topic[len(prefix) :].strip()
    return topic


def derive_skill_name(topic: str, explicit_name: str | None) -> str:
    if explicit_name:
        base = slugify(explicit_name)
    else:
        preferred = drop_provider_prefix(topic)
        base = slugify(preferred) or slugify(topic)

    if not base:
        raise ValueError("Unable to derive a valid skill name from the topic.")

    if not base.endswith("-kb"):
        base = f"{base}-kb"

    if len(base) > MAX_NAME_LENGTH:
        raise ValueError(
            f"Derived skill name '{base}' is too long ({len(base)} characters). "
            f"Maximum is {MAX_NAME_LENGTH}."
        )

    if not re.match(r"^[a-z0-9-]+$", base):
        raise ValueError(
            f"Derived skill name '{base}' contains invalid characters. "
            "Use lowercase letters, digits, and hyphens only."
        )

    return base


def yaml_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def short_description_for(topic: str) -> str:
    description = f"Help with {topic} architecture and operations"
    if len(description) > MAX_SHORT_DESCRIPTION:
        description = f"{topic} knowledge base workflows"
    if len(description) > MAX_SHORT_DESCRIPTION:
        suffix = " KB workflows"
        max_topic_len = MAX_SHORT_DESCRIPTION - len(suffix)
        trimmed_topic = topic[:max_topic_len].rstrip()
        description = f"{trimmed_topic}{suffix}"
    if len(description) < MIN_SHORT_DESCRIPTION:
        description = "Topic knowledge base workflows"
    return description


def build_skill_md(skill_name: str, topic: str, today: str) -> str:
    description = (
        f"Knowledge base for {topic}. Use when requests involve {topic} concepts, architecture, "
        f"APIs, implementation patterns, operations, troubleshooting, or best practices."
    )
    return f"""---
name: {skill_name}
description: {yaml_quote(description)}
---

# {topic} Knowledge Base

## Scope

- [Summarize what this KB covers in 2-4 bullets.]
- [State what is intentionally out of scope.]

## Quick Facts

- [State the service or topic purpose.]
- [State core primitives or building blocks.]
- [State key constraints or limits.]

## Core Concepts

- [Concept 1]: [Explain in one concise paragraph.]
- [Concept 2]: [Explain in one concise paragraph.]
- [Concept 3]: [Explain in one concise paragraph.]

## Architecture and Implementation Patterns

- [Pattern name]: [When to use it, why, tradeoffs.]
- [Pattern name]: [When to avoid it.]

## API and Integration Notes

- [Important API behavior, defaults, quotas, or compatibility notes.]
- [SDK/CLI behavior that often surprises users.]

## Operations and Reliability

- [Monitoring and alerting guidance.]
- [Backups, replay, recovery, or rollback considerations.]
- [Security and IAM guidance.]

## Pitfalls and Troubleshooting

- [Common failure mode]: [Symptoms], [Root cause], [Fix].
- [Common failure mode]: [Symptoms], [Root cause], [Fix].

## Decision Guide

- If [constraint], choose [option] because [reason].
- If [constraint], avoid [option] because [reason].

## References

- Last verified: {today}
- Keep full references in `references/sources.md`.
"""


def build_openai_yaml(topic: str) -> str:
    display_name = f"{topic} KB"
    short_description = short_description_for(topic)
    default_prompt = f"Use this knowledge base to answer practical questions about {topic}."
    return "\n".join(
        [
            "interface:",
            f"  display_name: {yaml_quote(display_name)}",
            f"  short_description: {yaml_quote(short_description)}",
            f"  default_prompt: {yaml_quote(default_prompt)}",
            "",
        ]
    )


def build_sources_md(topic: str, today: str) -> str:
    return f"""# {topic} Sources

Record sources used to build this KB.

## Quality Mix

- Prefer primary vendor documentation and standards.
- Add secondary sources only when they provide operational context.
- Include at least one troubleshooting source when available.

## Source Log

| Claim Area | Source | Type | Published | Accessed | Notes |
| --- | --- | --- | --- | --- | --- |
| [Example: throughput limits] | [Title](https://example.com) | [Primary/Secondary] | [YYYY-MM-DD or unknown] | {today} | [What this source supports] |

## Change Notes

- {today}: Initial KB scaffold created.
"""


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Scaffold a topic-specific KB skill.")
    parser.add_argument("topic", help="Topic name, for example: Amazon Kinesis")
    parser.add_argument("--out", default="skills", help="Output root for generated skill")
    parser.add_argument(
        "--name",
        help="Optional explicit skill name. '-kb' is appended when missing.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite files when the target skill already exists.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned paths without writing files.",
    )
    args = parser.parse_args()

    topic = normalize_spaces(args.topic)
    if not topic:
        print("[ERROR] Topic must not be empty.")
        return 1

    try:
        skill_name = derive_skill_name(topic, args.name)
    except ValueError as exc:
        print(f"[ERROR] {exc}")
        return 1

    output_root = Path(args.out).expanduser().resolve()
    skill_dir = output_root / skill_name
    today = date.today().isoformat()

    files = {
        skill_dir / "SKILL.md": build_skill_md(skill_name, topic, today),
        skill_dir / "agents/openai.yaml": build_openai_yaml(topic),
        skill_dir / "references/sources.md": build_sources_md(topic, today),
    }

    if args.dry_run:
        print("[DRY RUN] Planned files:")
        for path in files:
            print(f"  - {path}")
        return 0

    if skill_dir.exists() and not args.force:
        print(
            f"[ERROR] Target skill already exists: {skill_dir}\n"
            "Use --force to overwrite generated files."
        )
        return 1

    for path, content in files.items():
        if path.exists() and not args.force:
            print(
                f"[ERROR] File already exists: {path}\n"
                "Use --force to overwrite generated files."
            )
            return 1

    for path, content in files.items():
        write_file(path, content)

    print(f"[OK] Generated skill: {skill_name}")
    print(f"[OK] Location: {skill_dir}")
    print("[OK] Files:")
    for path in files:
        print(f"  - {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

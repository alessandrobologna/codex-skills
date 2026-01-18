#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MANAGED_BEGIN = "<!-- waylog-summary:begin -->"
MANAGED_END = "<!-- waylog-summary:end -->"

JOURNAL_BEGIN = "<!-- waylog-journal:begin -->"
JOURNAL_END = "<!-- waylog-journal:end -->"
JOURNAL_META_RE = re.compile(
    r"^<!--\s*waylog-journal-meta:\s*sessions_sha256=(?P<sha256>[0-9a-f]{64})\s*-->$"
)
WAYLOG_REPO_URL = "https://github.com/shayne-snap/waylog-cli"

MANUAL_BEGIN = "<!-- waylog-manual:begin -->"
MANUAL_END = "<!-- waylog-manual:end -->"

ENTRY_END = "<!-- waylog-entry:end -->"

ENTRY_META_RE = re.compile(r"^<!--\s*waylog-entry:\s*(?P<body>.*?)\s*-->$")

FALLBACK_HIGHLIGHT = "Summary generation failed (see stderr)."


SUMMARY_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "project_relevance": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "label": {"type": "string", "enum": ["related", "unrelated", "unclear"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "reason": {"type": "string"},
                "touched_areas": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["label", "confidence", "reason", "touched_areas"],
        },
        "highlights": {"type": "array", "items": {"type": "string"}},
        "decisions": {"type": "array", "items": {"type": "string"}},
        "implementation_details": {"type": "array", "items": {"type": "string"}},
        "open_questions": {"type": "array", "items": {"type": "string"}},
        "security_notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "project_relevance",
        "highlights",
        "decisions",
        "implementation_details",
        "open_questions",
        "security_notes",
    ],
}

JOURNAL_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "properties": {"journal_markdown": {"type": "string"}},
    "required": ["journal_markdown"],
}


REDACTIONS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
            re.MULTILINE,
        ),
        "[REDACTED_PRIVATE_KEY]",
    ),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "[REDACTED_AWS_ACCESS_KEY_ID]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "[REDACTED_SLACK_TOKEN]"),
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
        "[REDACTED_JWT]",
    ),
    (
        re.compile(
            r"(?i)\b(api[_-]?key|token|secret|password|passwd|passphrase)\b\s*[:=]\s*([^\s,;]+)"
        ),
        r"\1=[REDACTED]",
    ),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[REDACTED_EMAIL]"),
]


@dataclass(frozen=True)
class HistorySession:
    rel_path: str
    abs_path: Path
    provider: str
    started_at: str
    updated_at: str
    message_count: str
    title: str
    content: str


@dataclass(frozen=True)
class ExistingEntry:
    rel_path: str
    sha256: str
    updated_at: str
    status: str
    block: str


def eprint(*args: object) -> None:
    print(*args, file=sys.stderr)


def format_waylog_install_help() -> str:
    return "\n".join(
        [
            "WayLog CLI (`waylog`) was not found on your PATH.",
            "",
            "Install it (macOS/Homebrew):",
            "  brew install shayne-snap/tap/waylog",
            "",
            "Install it (Rust/Cargo):",
            "  cargo install waylog",
            "",
            f"More info: {WAYLOG_REPO_URL}",
        ]
    )


def find_repo_root(start: Path) -> Path:
    for candidate in [start, *start.parents]:
        if (candidate / ".waylog" / "history").is_dir():
            return candidate
    raise FileNotFoundError("Could not find `.waylog/history` in current directory or parents.")


def find_git_root(start: Path) -> Path | None:
    for candidate in [start, *start.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            fm_lines = lines[1:i]
            rest = "\n".join(lines[i + 1 :])
            fm: dict[str, str] = {}
            for line in fm_lines:
                if not line.strip() or line.strip().startswith("#") or ":" not in line:
                    continue
                key, value = line.split(":", 1)
                fm[key.strip()] = value.strip()
            return fm, rest
    return {}, text


def extract_title(body: str) -> str:
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return "(untitled)"


def parse_started_at_from_filename(name: str) -> str:
    # Expected: YYYY-MM-DD_HH-MM-SSZ-...
    m = re.match(r"^(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})-(\d{2})Z", name)
    if not m:
        return ""
    date, hh, mm, ss = m.groups()
    return f"{date} {hh}:{mm}:{ss}Z"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def sanitize_text(text: str) -> str:
    sanitized = text
    sanitized = re.sub(r"/Users/[^/]+/", "/Users/<user>/", sanitized)
    for pattern, repl in REDACTIONS:
        sanitized = pattern.sub(repl, sanitized)
    return sanitized


def detect_sensitive_categories(text: str) -> list[str]:
    categories: list[str] = []
    checks: list[tuple[str, re.Pattern[str]]] = [
        ("private_key", REDACTIONS[0][0]),
        ("api_key", REDACTIONS[1][0]),
        ("aws_access_key_id", REDACTIONS[2][0]),
        ("github_token", REDACTIONS[3][0]),
        ("slack_token", REDACTIONS[4][0]),
        ("jwt", REDACTIONS[5][0]),
        ("credential_kv", REDACTIONS[6][0]),
        ("email", REDACTIONS[7][0]),
    ]
    for name, pattern in checks:
        if pattern.search(text):
            categories.append(name)
    return categories


def parse_history_session(repo_root: Path, path: Path, max_chars: int | None) -> HistorySession:
    raw = path.read_text(encoding="utf-8", errors="replace")
    fm, body = parse_front_matter(raw)

    title = extract_title(body)

    content = raw
    if max_chars is not None and max_chars > 0 and len(content) > max_chars:
        content = content[-max_chars:]
        content = f"[...truncated to last {max_chars} chars...]\n\n{content}"

    rel_path = str(path.relative_to(repo_root).as_posix())
    started_at = fm.get("started_at") or parse_started_at_from_filename(path.name) or ""

    return HistorySession(
        rel_path=rel_path,
        abs_path=path,
        provider=fm.get("provider", ""),
        started_at=started_at,
        updated_at=fm.get("updated_at", ""),
        message_count=fm.get("message_count", ""),
        title=title,
        content=content,
    )


def extract_between(text: str, begin: str, end: str) -> tuple[str, str, str] | None:
    if begin not in text or end not in text:
        return None
    before, rest = text.split(begin, 1)
    middle, after = rest.split(end, 1)
    return before, middle, after


def extract_between_optional(text: str, begin: str, end: str) -> tuple[str, str, str]:
    extracted = extract_between(text, begin, end)
    if extracted is None:
        return text, "", ""
    return extracted


def extract_manual_body(text: str) -> str:
    extracted = extract_between(text, MANUAL_BEGIN, MANUAL_END)
    if extracted is None:
        return ""
    return extracted[1].strip("\n")


def extract_journal_sessions_sha(text: str) -> str | None:
    extracted = extract_between(text, JOURNAL_BEGIN, JOURNAL_END)
    if extracted is None:
        return None
    body = extracted[1].splitlines()
    for line in body:
        m = JOURNAL_META_RE.match(line.strip())
        if m:
            return m.group("sha256")
    return None


def parse_entry_meta(line: str) -> dict[str, str] | None:
    m = ENTRY_META_RE.match(line.strip())
    if not m:
        return None
    body = m.group("body").strip()
    # Body is expected to be key=value pairs separated by spaces.
    meta: dict[str, str] = {}
    for token in body.split():
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        meta[key] = value
    if "file" not in meta or "sha256" not in meta:
        return None
    return meta


def parse_existing_entries(managed_body: str) -> dict[str, ExistingEntry]:
    entries: dict[str, ExistingEntry] = {}
    lines = managed_body.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].startswith("## "):
            header_line = lines[i]
            if i + 1 < len(lines):
                meta = parse_entry_meta(lines[i + 1])
                if meta:
                    rel_path = meta.get("file", "")
                    sha = meta.get("sha256", "")
                    updated_at = meta.get("updated_at", "")
                    block_lines = [header_line, lines[i + 1]]
                    i += 2
                    while i < len(lines):
                        block_lines.append(lines[i])
                        if lines[i].strip() == ENTRY_END:
                            i += 1
                            break
                        i += 1
                    block = "\n".join(block_lines)
                    status = meta.get("status", "")
                    if not status:
                        # Backwards-compat: treat older fallback entries as retriable.
                        status = "error" if FALLBACK_HIGHLIGHT in block else "ok"
                    entries[rel_path] = ExistingEntry(
                        rel_path=rel_path,
                        sha256=sha,
                        updated_at=updated_at,
                        status=status,
                        block=block,
                    )
                    continue
        i += 1
    return entries


def json_load_loose(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(text[start : end + 1])


def list_codex_mcp_servers(codex_bin: str) -> list[dict[str, Any]]:
    try:
        proc = subprocess.run(
            [codex_bin, "mcp", "list", "--json"],
            text=True,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        eprint(f"[warn] codex binary not found: {codex_bin!r}")
        return []

    if proc.returncode != 0:
        eprint("[warn] `codex mcp list --json` failed; continuing without MCP overrides.")
        return []

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        eprint("[warn] Failed to parse `codex mcp list --json` output; continuing without MCP overrides.")
        return []

    if not isinstance(data, list):
        return []

    servers: list[dict[str, Any]] = []
    for item in data:
        if isinstance(item, dict):
            servers.append(item)
    return servers


def build_codex_mcp_disable_overrides(
    servers: list[dict[str, Any]],
    *,
    only_enabled: bool,
) -> list[str]:
    overrides: list[str] = []
    for server in servers:
        name = server.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        if only_enabled and not bool(server.get("enabled")):
            continue
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            eprint(f"[warn] Skipping MCP server with unsupported name: {name!r}")
            continue
        overrides.append(f"mcp_servers.{name}.enabled=false")
    return overrides


def run_codex_summary(
    *,
    repo_root: Path,
    codex_bin: str,
    model: str | None,
    reasoning_effort: str | None,
    history_persistence: str,
    codex_cd: Path | None,
    codex_config: list[str],
    schema_path: Path,
    prompt: str,
) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile(mode="w+", encoding="utf-8", delete=False) as out:
        out_path = Path(out.name)

    cmd: list[str] = [codex_bin]
    if model:
        cmd.extend(["-m", model])
    cmd.extend(["-c", f'history.persistence="{history_persistence}"'])
    if reasoning_effort:
        cmd.extend(["-c", f'model_reasoning_effort="{reasoning_effort}"'])
    for cfg in codex_config:
        cmd.extend(["-c", cfg])
    if codex_cd is not None:
        cmd.extend(["--cd", str(codex_cd)])
    cmd.extend(
        [
            "-a",
            "never",
            "-s",
            "read-only",
            "exec",
            "--skip-git-repo-check",
            "--color",
            "never",
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(out_path),
            "-",
        ]
    )

    try:
        proc = subprocess.run(
            cmd,
            input=prompt,
            text=True,
            cwd=str(codex_cd or repo_root),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"codex exec failed (exit {proc.returncode}). stderr:\n{proc.stderr.strip()}"
            )
        content = out_path.read_text(encoding="utf-8", errors="replace").strip()
        data = json_load_loose(content)
        return data
    finally:
        try:
            out_path.unlink(missing_ok=True)
        except Exception:
            pass


def run_codex_journal(
    *,
    repo_root: Path,
    codex_bin: str,
    model: str | None,
    reasoning_effort: str | None,
    history_persistence: str,
    codex_cd: Path | None,
    codex_config: list[str],
    schema_path: Path,
    prompt: str,
) -> str:
    data = run_codex_summary(
        repo_root=repo_root,
        codex_bin=codex_bin,
        model=model,
        reasoning_effort=reasoning_effort,
        history_persistence=history_persistence,
        codex_cd=codex_cd,
        codex_config=codex_config,
        schema_path=schema_path,
        prompt=prompt,
    )
    journal = data.get("journal_markdown")
    if not isinstance(journal, str):
        raise RuntimeError("Journal output missing `journal_markdown` string.")
    return journal


def make_prompt(repo_root: Path, session: HistorySession, sensitive_categories: list[str]) -> str:
    cat_note = ", ".join(sensitive_categories) if sensitive_categories else "none detected"
    return "\n".join(
        [
            "You are summarizing an AI chat transcript from `.waylog/history/*.md`.",
            "",
            "Goal: produce a concise journal entry of important decisions and implementation details.",
            "",
            "This summary is specifically for the current repository:",
            f"- repo_name: {repo_root.name}",
            f"- repo_root: {sanitize_text(str(repo_root))}",
            "",
            "First determine whether this session is related to this repository's code/spec/docs/tests.",
            "Set `project_relevance` accordingly:",
            "- label: related | unrelated | unclear",
            "- confidence: 0..1",
            "- reason: short explanation (no secrets/PII)",
            "- touched_areas: short tags like spec|db|peer_server|cli|web|tests|docs|mcp|packaging",
            "",
            "Hard requirements:",
            "- Do NOT include secrets, credentials, tokens, API keys, passwords, private keys, or PII.",
            "- If the transcript contains sensitive strings, mention only that it was present and was redacted.",
            "- Do not quote long passages; do not copy raw logs into the summary.",
            "- Return JSON ONLY (no Markdown fences), matching the provided output schema.",
            "",
            "Session metadata:",
            f"- file: {session.rel_path}",
            f"- provider: {session.provider or '(unknown)'}",
            f"- started_at: {session.started_at or '(unknown)'}",
            f"- updated_at: {session.updated_at or '(unknown)'}",
            f"- message_count: {session.message_count or '(unknown)'}",
            f"- title: {session.title or '(unknown)'}",
            f"- sensitive_strings_detected_in_source: {cat_note}",
            "",
            "If the session is unrelated, keep the other arrays empty (or at most 1 short highlight).",
            "",
            "Transcript:",
            session.content,
            "",
        ]
    )


def render_entry(
    session: HistorySession,
    sha: str,
    summary: dict[str, Any],
    *,
    status: str,
    model: str | None,
    reasoning_effort: str | None,
) -> str:
    started = session.started_at or session.updated_at or ""
    provider = session.provider or "unknown"
    title = sanitize_text(session.title or "(untitled)")
    header = f"## {started} — {provider} — {title}"

    project_relevance = summary.get("project_relevance")
    relevance_label: str | None = None
    relevance_confidence: float | None = None
    relevance_reason: str | None = None
    relevance_areas: list[str] = []
    if isinstance(project_relevance, dict):
        label = project_relevance.get("label")
        if isinstance(label, str) and label.strip():
            relevance_label = label.strip()
        confidence = project_relevance.get("confidence")
        if isinstance(confidence, (int, float)):
            relevance_confidence = float(confidence)
        reason = project_relevance.get("reason")
        if isinstance(reason, str) and reason.strip():
            relevance_reason = reason.strip()
        areas = project_relevance.get("touched_areas")
        if isinstance(areas, list):
            relevance_areas = [str(a).strip() for a in areas if str(a).strip()]

    meta_parts: list[str] = [
        f"file={session.rel_path}",
        f"sha256={sha}",
        f"updated_at={session.updated_at or ''}",
        f"status={status}",
    ]
    if relevance_label:
        meta_parts.append(f"relevance={relevance_label}")
    if relevance_confidence is not None:
        meta_parts.append(f"relevance_confidence={relevance_confidence:.2f}")
    if model:
        meta_parts.append(f"model={model}")
    if reasoning_effort:
        meta_parts.append(f"reasoning_effort={reasoning_effort}")
    meta = f"<!-- waylog-entry: {' '.join(meta_parts)} -->"

    def bullets(items: Any) -> list[str]:
        if not isinstance(items, list):
            return []
        out: list[str] = []
        for item in items:
            if isinstance(item, str) and item.strip():
                out.append(f"- {sanitize_text(item.strip())}")
        return out

    lines: list[str] = [header, meta]
    lines.append(f"- Source: `{session.rel_path}`")
    if session.updated_at:
        lines.append(f"- Updated: {session.updated_at}")
    if session.message_count:
        lines.append(f"- Messages: {session.message_count}")
    if relevance_label:
        if relevance_confidence is not None:
            lines.append(f"- Relevance: {relevance_label} (confidence {relevance_confidence:.2f})")
        else:
            lines.append(f"- Relevance: {relevance_label}")
    if relevance_reason and relevance_label in {"unrelated", "unclear"}:
        lines.append(f"- Relevance Reason: {sanitize_text(relevance_reason)}")
    if relevance_areas and relevance_label == "related":
        lines.append(f"- Areas: {', '.join(sanitize_text(a) for a in relevance_areas[:12])}")
    sections: list[tuple[str, str]] = [
        ("Highlights", "highlights"),
        ("Decisions", "decisions"),
        ("Implementation", "implementation_details"),
        ("Open Questions", "open_questions"),
        ("Security", "security_notes"),
    ]
    for label, key in sections:
        b = bullets(summary.get(key))
        if b:
            lines.append(f"**{label}**")
            lines.extend(b)
    lines.append(ENTRY_END)
    return "\n".join(lines)


def build_default_sessions_file() -> str:
    return "\n".join(
        [
            "# Waylog Sessions",
            "",
            "Internal, auto-generated per-session summaries (sanitized).",
            "",
            f"{MANAGED_BEGIN}",
            f"{MANAGED_END}",
            "",
        ]
    )


def build_default_journal_file(manual_body: str = "") -> str:
    lines: list[str] = [
        "# Waylog Summary",
        "",
        "Condensed journal of project decisions and implementation evolution (sanitized).",
        "",
        f"{JOURNAL_BEGIN}",
        f"{JOURNAL_END}",
        "",
        "## Manual Notes",
        f"{MANUAL_BEGIN}",
    ]
    if manual_body:
        lines.append(manual_body)
    lines.extend([f"{MANUAL_END}", ""])
    return "\n".join(lines)


def write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", delete=False, dir=str(path.parent)
    ) as tmp:
        tmp_path = Path(tmp.name)
        tmp.write(content)
        tmp.write("" if content.endswith("\n") else "\n")
    tmp_path.replace(path)


def render_summary(before: str, after: str, history_order: list[str], blocks: dict[str, str]) -> str:
    body_blocks = [blocks[rel_path] for rel_path in history_order if rel_path in blocks]
    new_managed_body = "\n\n".join(body_blocks).strip()
    return (
        before
        + MANAGED_BEGIN
        + "\n"
        + (new_managed_body + "\n" if new_managed_body else "")
        + MANAGED_END
        + after
    )


def render_journal_file(journal_body: str, *, sessions_sha: str, previous_text: str | None) -> str:
    manual_body = extract_manual_body(previous_text or "")
    base = build_default_journal_file(manual_body=manual_body)
    before, _, after = extract_between_optional(base, JOURNAL_BEGIN, JOURNAL_END)

    managed_lines: list[str] = [
        f"<!-- waylog-journal-meta: sessions_sha256={sessions_sha} -->",
        journal_body.strip(),
    ]
    managed = "\n".join([line for line in managed_lines if line.strip()]).strip()
    return before + JOURNAL_BEGIN + "\n" + (managed + "\n" if managed else "") + JOURNAL_END + after


def parse_session_block_for_journal(block: str) -> dict[str, Any] | None:
    lines = block.splitlines()
    if not lines or not lines[0].startswith("## "):
        return None

    header = lines[0].removeprefix("## ").strip()
    started_at = header
    provider = ""
    title = ""
    parts = header.split(" — ", 2)
    if len(parts) == 3:
        started_at, provider, title = parts

    meta: dict[str, str] | None = None
    if len(lines) > 1:
        meta = parse_entry_meta(lines[1])

    relevance_label = meta.get("relevance") if meta else ""
    relevance_confidence: float | None = None
    if meta and "relevance_confidence" in meta:
        try:
            relevance_confidence = float(meta["relevance_confidence"])
        except ValueError:
            relevance_confidence = None
    relevance_reason = ""
    relevance_areas: list[str] = []

    section: str | None = None
    collected: dict[str, list[str]] = {
        "highlights": [],
        "decisions": [],
        "implementation_details": [],
        "open_questions": [],
        "security_notes": [],
    }
    section_map = {
        "Highlights": "highlights",
        "Decisions": "decisions",
        "Implementation": "implementation_details",
        "Open Questions": "open_questions",
        "Security": "security_notes",
    }

    for line in lines[2:]:
        if line.strip() == ENTRY_END:
            break
        if line.startswith("- Relevance:"):
            value = line.removeprefix("- Relevance:").strip()
            if value:
                relevance_label = value.split("(", 1)[0].strip()
            continue
        if line.startswith("- Relevance Reason:"):
            relevance_reason = line.removeprefix("- Relevance Reason:").strip()
            continue
        if line.startswith("- Areas:"):
            value = line.removeprefix("- Areas:").strip()
            if value:
                relevance_areas = [v.strip() for v in value.split(",") if v.strip()]
            continue
        if line.startswith("**") and line.endswith("**"):
            key = line.strip("*")
            section = section_map.get(key)
            continue
        if section and line.startswith("- "):
            collected[section].append(line[2:].strip())

    # Keep prompts bounded; the journal step should dedupe/condense.
    def cap(items: list[str], n: int = 25) -> list[str]:
        out = [sanitize_text(s) for s in items if s.strip()]
        return out[:n]

    obj: dict[str, Any] = {
        "started_at": started_at,
        "provider": provider or (meta.get("provider") if meta else "") or "",
        "title": sanitize_text(title) if title else "",
        "file": meta.get("file") if meta else "",
        "status": meta.get("status") if meta else "",
        "relevance_label": sanitize_text(relevance_label) if relevance_label else "",
        "relevance_confidence": relevance_confidence,
        "relevance_reason": sanitize_text(relevance_reason) if relevance_reason else "",
        "areas": [sanitize_text(a) for a in relevance_areas[:12]],
        "highlights": cap(collected["highlights"], 25),
        "decisions": cap(collected["decisions"], 25),
        "implementation_details": cap(collected["implementation_details"], 25),
        "open_questions": cap(collected["open_questions"], 15),
        "security_notes": cap(collected["security_notes"], 10),
    }
    return obj


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Summarize .waylog/history into .waylog-journal/summary.md"
    )
    parser.add_argument("--history-dir", default=None, help="Path to .waylog/history (default: auto)")
    parser.add_argument(
        "--sessions-file",
        default=None,
        help="Path to .waylog-journal/sessions.md (default: auto)",
    )
    parser.add_argument(
        "--journal-file",
        "--summary-file",
        default=None,
        help="Path to .waylog-journal/summary.md (default: auto)",
    )
    parser.add_argument(
        "--codex-bin",
        default=os.environ.get("CODEX_BIN", "codex"),
        help="Path to codex executable (default: codex)",
    )
    parser.add_argument(
        "--codex-history-persistence",
        choices=["save-all", "none"],
        default="none",
        help='Codex history persistence for these runs (default: none; avoids polluting waylog via Codex sessions)',
    )
    parser.add_argument(
        "--codex-cd",
        default=None,
        help="Run Codex with `--cd` set to this directory (default: temp dir)",
    )
    parser.add_argument(
        "--codex-mcp",
        choices=["disable-all", "inherit"],
        default="disable-all",
        help="MCP server behavior for Codex runs (default: disable-all)",
    )
    parser.add_argument(
        "--codex-config",
        action="append",
        default=[],
        help="Extra `codex -c` config overrides (repeatable)",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("CODEX_MODEL"),
        help="Override Codex model (default: use Codex config / profile)",
    )
    parser.add_argument(
        "--reasoning-effort",
        default=os.environ.get("CODEX_REASONING_EFFORT"),
        help='Override `model_reasoning_effort` (e.g. low|medium|high|xhigh; default: use Codex config)',
    )
    parser.add_argument(
        "--no-prompt",
        action="store_true",
        help="Do not prompt for missing model/reasoning settings (use Codex defaults instead)",
    )
    parser.add_argument(
        "--no-journal",
        action="store_true",
        help="Only update per-session summaries; do not generate the condensed journal",
    )
    parser.add_argument(
        "--force-journal",
        action="store_true",
        help="Regenerate the condensed journal even if per-session summaries are unchanged",
    )
    parser.add_argument("--force", action="store_true", help="Regenerate all entries")
    parser.add_argument("--dry-run", action="store_true", help="Compute changes but do not write")
    parser.add_argument(
        "--max-chars",
        type=int,
        default=200_000,
        help="Max chars per transcript sent to the model (default: 200000)",
    )
    args = parser.parse_args(argv)

    cwd = Path.cwd()
    if args.history_dir:
        history_dir = Path(args.history_dir).expanduser()
        if history_dir.name == "history" and history_dir.parent.name == ".waylog":
            repo_root = history_dir.parent.parent
        else:
            repo_root = find_git_root(cwd) or cwd
    else:
        try:
            repo_root = find_repo_root(cwd)
        except FileNotFoundError:
            repo_root = find_git_root(cwd) or cwd
        history_dir = repo_root / ".waylog" / "history"

    default_journal_dir = repo_root / ".waylog-journal"
    default_sessions_file = default_journal_dir / "sessions.md"
    default_journal_file = default_journal_dir / "summary.md"

    sessions_file = Path(args.sessions_file) if args.sessions_file else default_sessions_file
    journal_file = Path(args.journal_file) if args.journal_file else default_journal_file

    if not history_dir.is_dir():
        if shutil.which("waylog") is None:
            eprint(format_waylog_install_help())
            eprint("")
            eprint("Then run `waylog pull` in your repo to populate `.waylog/history/`.")
        else:
            eprint(f"Missing history dir: {history_dir}")
            eprint("Try running `waylog pull` in your repo to populate `.waylog/history/`.")
        return 2

    if shutil.which("waylog") is None and not any(history_dir.glob("*.md")):
        eprint(format_waylog_install_help())
        eprint("")
        eprint("This project has an empty `.waylog/history/` directory; run `waylog pull` to recover history.")

    sessions_text = (
        sessions_file.read_text(encoding="utf-8", errors="replace") if sessions_file.exists() else ""
    )
    if sessions_text and extract_between(sessions_text, MANAGED_BEGIN, MANAGED_END) is None:
        eprint(f"{sessions_file} exists but is missing managed markers; refusing to overwrite.")
        eprint("Add markers or move the file aside, then re-run.")
        return 2

    if not sessions_text:
        sessions_text = build_default_sessions_file()

    before, managed_body, after = extract_between(sessions_text, MANAGED_BEGIN, MANAGED_END) or ("", "", "")
    existing_entries = parse_existing_entries(managed_body)

    history_files = sorted(history_dir.glob("*.md"), key=lambda p: p.name)

    updates: list[str] = []
    kept: int = 0

    for path in history_files:
        session = parse_history_session(repo_root, path, args.max_chars)
        sha = sha256_file(path)
        existing = existing_entries.get(session.rel_path)
        if existing and existing.sha256 == sha and existing.status == "ok" and not args.force:
            kept += 1
        else:
            updates.append(session.rel_path)

    if args.dry_run:
        eprint(f"Would update {len(updates)} entries; keep {kept} unchanged.")
        for p in updates:
            eprint(f"- {p}")
        if not args.no_journal:
            # Best-effort signal for journal regeneration.
            sessions_sha = sha256_text(managed_body.strip())
            existing_journal_text = (
                journal_file.read_text(encoding="utf-8", errors="replace") if journal_file.exists() else ""
            )
            journal_sha = extract_journal_sessions_sha(existing_journal_text)
            if args.force_journal or sessions_sha != (journal_sha or ""):
                eprint("Would regenerate journal.")
            else:
                eprint("Journal up-to-date.")
        return 0

    eprint(f"History files: {len(history_files)}. To update: {len(updates)}. Unchanged: {kept}.")

    model = args.model
    reasoning_effort = args.reasoning_effort
    if updates and not args.no_prompt and sys.stdin.isatty():
        if not model:
            entered = input("Codex model (blank = use default): ").strip()
            model = entered or None
        if not reasoning_effort:
            entered = input(
                "Reasoning effort (blank = use default; e.g. low|medium|high|xhigh): "
            ).strip()
            reasoning_effort = entered or None
    if updates:
        eprint(
            "Codex settings: "
            + (f"model={model}" if model else "model=(default)")
            + ", "
            + (f"reasoning_effort={reasoning_effort}" if reasoning_effort else "reasoning_effort=(default)")
        )

    with tempfile.TemporaryDirectory() as td:
        codex_config: list[str] = []
        if args.codex_mcp == "disable-all":
            servers = list_codex_mcp_servers(args.codex_bin)
            codex_config.extend(build_codex_mcp_disable_overrides(servers, only_enabled=False))
        codex_config.extend([str(cfg) for cfg in (args.codex_config or []) if str(cfg).strip()])

        codex_cd = (
            Path(args.codex_cd).expanduser().resolve() if args.codex_cd else Path(td) / "codex-cd"
        )
        codex_cd.mkdir(parents=True, exist_ok=True)

        summary_schema_path = Path(td) / "waylog_summary_schema.json"
        summary_schema_path.write_text(json.dumps(SUMMARY_SCHEMA, indent=2), encoding="utf-8")

        journal_schema_path = Path(td) / "waylog_journal_schema.json"
        journal_schema_path.write_text(json.dumps(JOURNAL_SCHEMA, indent=2), encoding="utf-8")

        history_order: list[str] = [
            str(path.relative_to(repo_root).as_posix()) for path in history_files
        ]
        blocks: dict[str, str] = {rel: entry.block for rel, entry in existing_entries.items()}

        completed: int = 0
        try:
            for path in history_files:
                session = parse_history_session(repo_root, path, args.max_chars)
                sha = sha256_file(path)
                existing = existing_entries.get(session.rel_path)
                if existing and existing.sha256 == sha and existing.status == "ok" and not args.force:
                    continue

                completed += 1
                eprint(f"[{completed}/{len(updates)}] Summarizing {session.rel_path}")
                sensitive_categories = detect_sensitive_categories(
                    path.read_text(encoding="utf-8", errors="replace")
                )
                prompt = make_prompt(repo_root, session, sensitive_categories)

                status = "ok"
                try:
                    data = run_codex_summary(
                        repo_root=repo_root,
                        codex_bin=args.codex_bin,
                        model=model,
                        reasoning_effort=reasoning_effort,
                        history_persistence=args.codex_history_persistence,
                        codex_cd=codex_cd,
                        codex_config=codex_config,
                        schema_path=summary_schema_path,
                        prompt=prompt,
                    )
                except Exception as exc:
                    eprint(f"[warn] Failed to summarize {session.rel_path}: {exc}")
                    status = "error"
                    data = {
                        "project_relevance": {
                            "label": "unclear",
                            "confidence": 0.0,
                            "reason": "Summary generation failed.",
                            "touched_areas": [],
                        },
                        "highlights": [FALLBACK_HIGHLIGHT],
                        "decisions": [],
                        "implementation_details": [],
                        "open_questions": [],
                        "security_notes": ["No sensitive data included in this entry."],
                    }

                blocks[session.rel_path] = render_entry(
                    session,
                    sha,
                    data,
                    status=status,
                    model=model,
                    reasoning_effort=reasoning_effort,
                )

                # Incremental, resumable writes: safe to interrupt and re-run.
                write_atomic(sessions_file, render_summary(before, after, history_order, blocks))
        except KeyboardInterrupt:
            eprint("Interrupted; partial progress is saved. Re-run to continue.")
            return 130

        sessions_body = "\n\n".join([blocks[rel_path] for rel_path in history_order if rel_path in blocks]).strip()
        sessions_sha = sha256_text(sessions_body)
        if updates:
            eprint(f"Updated {sessions_file} ({len(updates)} updated, {kept} unchanged).")
        else:
            eprint(f"No session updates needed ({sessions_file}).")

        if not args.no_journal:
            existing_journal_text = (
                journal_file.read_text(encoding="utf-8", errors="replace") if journal_file.exists() else ""
            )
            journal_sha = extract_journal_sessions_sha(existing_journal_text)
            needs_journal = args.force_journal or (sessions_sha != (journal_sha or ""))
            if needs_journal:
                eprint("Generating condensed journal...")
                if not args.no_prompt and sys.stdin.isatty():
                    if not model:
                        entered = input("Codex model (blank = use default): ").strip()
                        model = entered or None
                    if not reasoning_effort:
                        entered = input(
                            "Reasoning effort (blank = use default; e.g. low|medium|high|xhigh): "
                        ).strip()
                        reasoning_effort = entered or None
                prompt = "\n".join(
                    [
                        f"You are maintaining a concise engineering journal for the repository `{repo_root.name}`.",
                        "",
                        "Input: a list of per-session summaries from `.waylog/history/*.md`.",
                        "Goal: output a usable, low-noise history of the project's evolution (decisions + implementation changes).",
                        "",
                        "Rules:",
                        "- Preserve chronological order.",
                        "- Focus only on items that affected the code/spec/docs/tests of this repository.",
                        "- Drop sessions labeled `relevance_label=unrelated` unless they clearly impacted this repo anyway.",
                        "- Remove noise: greetings, unrelated math, unrelated projects/topics, duplicated bullets, and repetitive security boilerplate.",
                        "- Prefer milestones and deltas (what changed + why) over step-by-step narration.",
                        "- Keep it compact (think: a changelog + decisions log).",
                        "- Do NOT include secrets, credentials, tokens, API keys, passwords, private keys, or PII. If something was redacted, say 'redacted' without details.",
                        "",
                        "Produce markdown with dated sections (`## YYYY-MM-DD`) and bullets under each date.",
                        "Optional: prefix bullets with area tags like `[spec]`, `[db]`, `[cli]`, `[web]`, `[docs]`, `[tests]`.",
                        "",
                        "Per-session summaries (JSON, sanitized):",
                        json.dumps(
                            [
                                parsed
                                for rel in history_order
                                if rel in blocks
                                and (parsed := parse_session_block_for_journal(blocks[rel])) is not None
                            ],
                            ensure_ascii=False,
                        ),
                        "",
                    ]
                )
                journal_body = run_codex_journal(
                    repo_root=repo_root,
                    codex_bin=args.codex_bin,
                    model=model,
                    reasoning_effort=reasoning_effort,
                    history_persistence=args.codex_history_persistence,
                    codex_cd=codex_cd,
                    codex_config=codex_config,
                    schema_path=journal_schema_path,
                    prompt=prompt,
                )
                journal_body = sanitize_text(journal_body)
                new_journal_text = render_journal_file(
                    journal_body, sessions_sha=sessions_sha, previous_text=existing_journal_text
                )
                write_atomic(journal_file, new_journal_text)
                eprint(f"Updated {journal_file}.")
            else:
                eprint(f"Journal up-to-date ({journal_file}).")
        else:
            eprint("Skipped journal generation (--no-journal).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

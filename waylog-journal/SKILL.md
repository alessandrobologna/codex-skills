---
name: waylog-journal
description: Summarize `.waylog/history/*.md` into a sanitized per-session cache + a condensed, chronological `.waylog-journal/summary.md` journal.
---

# Waylog Journal

Keep a running, security-sanitized journal of important decisions and implementation details by
summarizing `.waylog/history/*.md` into a per-session cache (`.waylog-journal/sessions.md`) and a
condensed journal (`.waylog-journal/summary.md`).

## Quick start

From the project root (or any subdirectory inside it):

```bash
python3 ~/.codex/skills/waylog-journal/scripts/waylog_journal.py
```

## Prerequisites

To collect/pull transcripts into `.waylog/history/`, install WayLog CLI (`waylog`):

```bash
brew install shayne-snap/tap/waylog
# or
cargo install waylog
```

See: https://github.com/shayne-snap/waylog-cli

Useful flags:

- `--dry-run` (see what would change without calling the model)
- `--force` (regenerate everything)
- `--codex-history-persistence save-all|none` (default: `none` to avoid writing Codex history)
- `--codex-cd <path>` (overrides Codex `--cd`; default: temp dir)
- `--model <name>` (override default Codex model)
- `--reasoning-effort <level>` (override `model_reasoning_effort`)
- `--no-prompt` (never ask; always use Codex defaults unless flags/env are set)
- `--no-journal` (skip the condensed journal step)
- `--force-journal` (regenerate the journal even if unchanged)

## What to do when this skill is active

1. If the user didn’t specify `--model` / `--reasoning-effort`, ask them what to use (or confirm using
   their Codex defaults).
1. Run the script (it invokes `codex exec` once per changed history file, plus one optional pass to
   generate the condensed journal).
1. Open `.waylog-journal/summary.md` and sanity-check for:
   - Chronological order preserved
   - Only important decisions/implementation details captured
   - No secrets/credentials/PII (everything sensitive must be redacted)
1. Validate the journal against the repo (quick final pass):
   - Skim `git log --oneline --decorate -n 100` for major milestones and date alignment
   - Spot-check key claims with `rg` (e.g. tool names, file names, feature keywords)
   - If the journal contains claims that don’t match the codebase or git history, re-run with
     `--force-journal` (and optionally `--force`) using a higher reasoning effort.

## Guidelines

- Do not include secrets (API keys, tokens, passwords, private URLs, private keys) or PII in
  `.waylog-journal/summary.md`. If something sensitive appears in a log, mention it only as “redacted”.
- Keep summaries short and focused: decisions, implementation details, and any unresolved TODOs.
- Preserve chronological order based on the `.waylog/history/*.md` timestamps.
- The script tries to classify whether each session is `related`/`unrelated` to the current repo; the
  condensed journal should exclude unrelated sessions (e.g., ad-hoc math questions started in the
  project directory).
- Update incrementally: do not regenerate unchanged entries unless asked.
- Do not hand-edit the managed journal section between `<!-- waylog-journal:begin -->` / `<!-- waylog-journal:end -->`;
  add human notes in the “Manual Notes” section or regenerate via the script.
- By default, the script runs Codex with `history.persistence=none` and a temp working root (`--cd`) to reduce the
  chance that `waylog pull` ingests these summarization runs. Set `--codex-history-persistence save-all` if you
  explicitly want to keep Codex history.
- The script writes `.waylog-journal/sessions.md` incrementally after each updated entry, so it’s safe
  to interrupt and re-run; completed entries are skipped based on per-file `sha256`.
- Expect model usage/cost: `codex exec` runs once per changed history file, plus (by default) one
  additional `codex exec` to generate the condensed journal if the sessions changed.

## Examples (user prompts that should trigger this skill)

- “Update the waylog journal”
- “Summarize `.waylog/history` into `.waylog-journal/summary.md`”
- “Refresh the project decisions journal from the latest sessions”

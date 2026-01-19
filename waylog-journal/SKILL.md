---
name: waylog-journal
description: Summarize `.waylog/history/*.md` into a sanitized per-session cache + a condensed, chronological `.waylog-journal/summary.md` journal.
---

# Waylog Journal

Keep a running, security-sanitized journal of important decisions and implementation details by
summarizing `.waylog/history/*.md` into a per-session cache (`.waylog-journal/sessions.md`) and a
condensed journal (`.waylog-journal/summary.md`).

## Important: sandbox network

This skill runs a Python script that spawns `codex exec` subprocesses. If you run it *from inside Codex*, those
subprocesses inherit Codex’s command sandbox. If outbound network is disabled there, the skill cannot call the model
and will (at best) produce placeholders.

When the skill is invoked, **always request outbound network access for the command sandbox** before running the
script (or instruct the user how to enable it).

## Quick start

From the project root (or any subdirectory inside it):

```bash
python3 ~/.codex/skills/waylog-journal/scripts/waylog_journal.py
```

Recommended fast pass (initial per-session summaries):

```bash
python3 ~/.codex/skills/waylog-journal/scripts/waylog_journal.py \
  --model gpt-5.1-codex-mini \
  --reasoning-effort low
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
- `--codex-profile <name>` (pass through to child `codex` runs as `--profile`; useful for local/offline profiles)
- `--codex-oss` / `--codex-local-provider lmstudio|ollama|ollama-chat` (run child `codex` via local OSS provider)
- `--codex-home-mode inherit|temp` (default: `inherit`; use `temp` to isolate `CODEX_HOME` for sandboxed runs)
- `--codex-home <path>` (explicit `CODEX_HOME` for child `codex` runs; overrides `--codex-home-mode`)
- `--codex-history-persistence save-all|none` (default: `none` to avoid writing Codex history)
- `--codex-cd <path>` (overrides Codex `--cd`; default: temp dir)
- `--codex-mcp disable-all|inherit` (default: `disable-all` to avoid MCP tool usage during summarization)
- `--codex-config <key=value>` (repeatable; passed through as `codex -c ...`)
- `--codex-retries <n>` / `--codex-retry-backoff-sec <sec>` (retry transient Codex/network failures)
- `--model <name>` (override default Codex model)
- `--reasoning-effort <level>` (override `model_reasoning_effort`)
- `--no-prompt` (never ask; always use Codex defaults unless flags/env are set)
- `--no-journal` (skip the condensed journal step)
- `--force-journal` (regenerate the journal even if unchanged)

## What to do when this skill is active

Keep it simple: don’t create a multi-step plan unless the user asks; don’t run `--dry-run` unless you’re debugging.

1. **Request sandbox network access** (required when running via Codex command execution). If it’s not already enabled:
   - One-off (start Codex with): `codex -c 'sandbox_workspace_write.network_access=true'`
   - Or set in `~/.codex/config.toml`:

     ```toml
     sandbox_mode = "workspace-write"

     [sandbox_workspace_write]
     network_access = true
     ```

   If the user can’t/doesn’t want to enable this, stop and tell them to run the script directly in their shell
   (outside Codex), because it won’t work in a network-disabled sandbox.
1. If the user didn’t specify `--model` / `--reasoning-effort`, ask what to use (suggest `gpt-5.1-codex-mini` + `low`).
1. Run the script (it invokes `codex exec` once per changed history file, plus one optional pass for the journal).
1. Sanity-check `.waylog-journal/summary.md` for chronology, relevance filtering, and redaction.
1. If output is wrong, **re-run the script** with `--force` / `--force-journal` (don’t hand-edit managed sections).

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
- Do not “fix up” placeholder/failed runs by hand-editing `.waylog-journal/sessions.md` metadata (`status=...`,
  `sha256=...`, etc.). Fix the underlying issue (usually sandbox network access) and re-run the script.
- By default, the script runs Codex with `history.persistence=none` and a temp working root (`--cd`) to reduce the
  chance that `waylog pull` ingests these summarization runs.
- By default, the script runs child `codex` processes with your normal `CODEX_HOME`. Set `--codex-home-mode temp`
  to isolate `CODEX_HOME` (useful if `~/.codex/sessions` is not writable in a sandbox, or if you want to avoid
  writing Codex session artifacts).
- Set `--codex-history-persistence save-all` if you explicitly want to keep Codex history.
- By default, the script disables MCP servers for these runs (`--codex-mcp disable-all`) to avoid tool usage and
  external API calls. Set `--codex-mcp inherit` to keep Codex MCP settings.
- If Codex cannot write session files under the configured `CODEX_HOME`, the script retries with an isolated temp
  `CODEX_HOME` (seeded from your existing Codex auth/config when available).
- If outbound network access is blocked **by the Codex command sandbox**, enable it via
  `sandbox_workspace_write.network_access=true` (otherwise neither hosted models nor localhost OSS providers can work
  from inside the sandbox).
- If outbound network access is blocked by environment policy/firewall (but localhost works), use a local Codex
  profile/provider (e.g. `--codex-profile gptoss-profile` or `--codex-oss --codex-local-provider lmstudio`).
- The script writes `.waylog-journal/sessions.md` incrementally after each updated entry, so it’s safe
  to interrupt and re-run; completed entries are skipped based on per-file `sha256`.
- Expect model usage/cost: `codex exec` runs once per changed history file, plus (by default) one
  additional `codex exec` to generate the condensed journal if the sessions changed.

## Troubleshooting

- `401 Unauthorized` / “Missing bearer…”: Codex is not logged in in this environment. Run `codex login status`, then `codex login` (or `printenv OPENAI_API_KEY | codex login --with-api-key`).
- Network errors (e.g. “stream disconnected”): Re-run, consider `--codex-retries`, and consider lowering `--max-chars`.
- Sandbox blocked network (DNS/connect errors from inside Codex “workspace-write”): enable outbound network access for
  sandboxed commands via config (security-sensitive; applies to all commands run in the sandbox):

  ```toml
  sandbox_mode = "workspace-write"

  [sandbox_workspace_write]
  network_access = true
  ```

  Or start Codex with a one-off override:

  ```bash
  codex -c 'sandbox_workspace_write.network_access=true'
  ```

## Examples (user prompts that should trigger this skill)

- “Update the waylog journal”
- “Summarize `.waylog/history` into `.waylog-journal/summary.md`”
- “Refresh the project decisions journal from the latest sessions”

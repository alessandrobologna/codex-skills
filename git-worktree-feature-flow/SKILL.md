---
name: git-worktree-feature-flow
description: Create a feature branch in a Git worktree, work independently, then merge back and clean up safely.
---

# Git Worktree Feature Flow

Use this skill when the user wants an isolated working directory for a feature (via `git worktree`), then to merge that branch back into a target branch and clean up the worktree.

## Examples (user prompts)
- "Create a worktree for `feature/foo` off `main`."
- "Spin up a worktree for my change, put it in `../wts/feature-foo`."
- "Merge my worktree branch back into `main` with a squash merge, then clean up."
- "Finish the worktree for `feature/foo` but keep the branch around."

## Quick flow

1) Start: create a feature worktree
- Ask for `branch` name (required).
- Optional: ask for `base` ref (default: current branch).
- Run `scripts/worktree-start.sh`.

2) Work: user edits/commits in the worktree directory.

3) Finish: merge + cleanup
- Ask for merge `strategy`: `merge` (default), `squash`, or `ff-only`.
- Optional: ask for `into` target branch (default: detected repo default branch, usually `main`).
- Run `scripts/worktree-finish.sh`.

## Commands (scripts)

### Start a worktree

```bash
$HOME/.codex/skills/git-worktree-feature-flow/scripts/worktree-start.sh --branch feature/my-change
```

Common options:
- `--base <ref>`: base branch/ref to branch from (default: current branch)
- `--path <dir>`: where to place the worktree (default: sibling `.worktrees/<repo>/<branch>`)
  - If `--path` is relative, it’s interpreted relative to the repo root.
- `--yes`: do not prompt

### Finish (merge back and clean up)

```bash
$HOME/.codex/skills/git-worktree-feature-flow/scripts/worktree-finish.sh --branch feature/my-change
```

Common options:
- `--into <branch>`: target branch to merge into (default: detected default branch)
- `--strategy merge|squash|ff-only`: merge strategy (default: `merge`)
- `--no-delete-branch`: keep the feature branch after merging
- `--keep-worktree`: keep the worktree directory after merging
- `--yes`: do not prompt

Notes:
- `--keep-worktree` implies you should also pass `--no-delete-branch` (you can’t delete a branch that’s still checked out in a worktree).
- For `--strategy squash`, the script creates a squash commit automatically and may force-delete the feature branch after committing (use `--no-delete-branch` to keep it).

## Agent guidelines

- Prefer the scripts in `scripts/` over manually typing long `git worktree` commands.
- Confirm the user’s intended `branch`, `base`, and merge `strategy` before making changes.
- Be conservative:
  - Refuse to proceed if the feature worktree has uncommitted changes unless the user explicitly wants to continue.
  - Refuse to proceed if the target worktree (where the merge happens) is dirty.
  - If cleaning up, don’t run the finish step from inside the feature worktree directory.
- After finishing, summarize:
  - where the worktree lived,
  - what merge strategy was used,
  - whether the branch/worktree were deleted.

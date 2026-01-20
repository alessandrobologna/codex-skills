#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_lib.sh
source "$SCRIPT_DIR/_lib.sh"

usage() {
  cat <<'EOF'
Merge a feature branch back into a target branch and optionally clean up the worktree.

Usage:
  worktree-finish.sh --branch <name> [--into <branch>] [--strategy merge|squash|ff-only]
                    [--repo <path>] [--no-delete-branch] [--keep-worktree] [--yes]

Options:
  --branch, -b         Feature branch name (required).
  --into               Target branch (default: detected default branch).
  --strategy           merge (default), squash, or ff-only.
  --repo               Any path inside the target repo (default: cwd).
  --no-delete-branch   Keep the feature branch after merge.
  --keep-worktree      Keep the feature worktree directory after merge.
  --yes, -y            Do not prompt.
EOF
}

branch=""
into=""
strategy="merge"
repo="."
delete_branch=1
remove_worktree=1
yes=0
squash_committed=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --branch|-b) branch="${2:-}"; shift 2 ;;
    --into) into="${2:-}"; shift 2 ;;
    --strategy) strategy="${2:-}"; shift 2 ;;
    --repo) repo="${2:-}"; shift 2 ;;
    --no-delete-branch) delete_branch=0; shift ;;
    --keep-worktree) remove_worktree=0; shift ;;
    --yes|-y) yes=1; shift ;;
    --help|-h) usage; exit 0 ;;
    *) die "Unknown arg: $1 (use --help)" ;;
  esac
done

[[ -n "$branch" ]] || die "Missing --branch (use --help)"
case "$strategy" in
  merge|squash|ff-only) ;;
  *) die "Invalid --strategy: $strategy (use merge|squash|ff-only)" ;;
esac

repo_root="$(require_git_repo "$repo")" || die "Not a git repo: $repo"

git -C "$repo_root" show-ref --verify --quiet "refs/heads/$branch" || die "Branch not found: $branch"

if [[ -z "$into" ]]; then
  into="$(detect_default_branch "$repo_root")"
fi
[[ "$branch" != "$into" ]] || die "--branch and --into must differ (got: $branch)"

feature_path=""
if worktree_path_for_branch "$repo_root" "$branch" >/dev/null; then
  feature_path="$(worktree_path_for_branch "$repo_root" "$branch")"
  ensure_clean_or_die "$feature_path" "Feature worktree"
else
  warn "No worktree found for branch '$branch'; will merge branch anyway."
fi

if [[ "$remove_worktree" -eq 0 && "$delete_branch" -eq 1 && -n "$feature_path" ]]; then
  die "Cannot delete branch while keeping its worktree; use --no-delete-branch or omit --keep-worktree."
fi

target_path="$repo_root"
if worktree_path_for_branch "$repo_root" "$into" >/dev/null; then
  target_path="$(worktree_path_for_branch "$repo_root" "$into")"
fi

ensure_clean_or_die "$target_path" "Target worktree"

info "Repo:     $repo_root"
info "Branch:   $branch"
info "Into:     $into"
info "Strategy: $strategy"
info "Target:   $target_path"
if [[ -n "$feature_path" ]]; then
  info "Feature:  $feature_path"
fi

if [[ "$remove_worktree" -eq 1 && -n "$feature_path" ]]; then
  cwd="$(pwd -P)"
  feature_abs="$(cd "$feature_path" && pwd -P)"
  case "$cwd/" in
    "$feature_abs/"*) die "Current directory is inside the feature worktree; cd out or pass --keep-worktree." ;;
  esac
fi

if [[ "$yes" -ne 1 ]] && ! confirm "Merge and clean up?"; then
  info "Canceled."
  exit 1
fi

git -C "$target_path" switch "$into"

case "$strategy" in
  merge)
    git -C "$target_path" merge "$branch"
    ;;
  ff-only)
    git -C "$target_path" merge --ff-only "$branch"
    ;;
  squash)
    git -C "$target_path" merge --squash "$branch"
    if git -C "$target_path" diff --cached --quiet; then
      info "No changes to commit after squash; branch may already be merged."
    else
      git -C "$target_path" commit -m "Squash merge '$branch' into '$into'"
      squash_committed=1
    fi
    ;;
esac

if [[ "$remove_worktree" -eq 1 && -n "$feature_path" ]]; then
  if [[ "$feature_path" == "$target_path" ]]; then
    warn "Feature worktree equals target worktree; refusing to remove: $feature_path"
  else
    git -C "$target_path" worktree remove "$feature_path"
  fi
fi

if [[ "$delete_branch" -eq 1 ]]; then
  if [[ "$strategy" == "squash" ]]; then
    if [[ "$squash_committed" -eq 1 ]]; then
      git -C "$target_path" branch -D "$branch"
    else
      if ! git -C "$target_path" branch -d "$branch"; then
        warn "Branch is not fully merged (squash produced no commit); keeping: $branch"
      fi
    fi
  else
    git -C "$target_path" branch -d "$branch"
  fi
fi

git -C "$target_path" worktree prune

info "Done."

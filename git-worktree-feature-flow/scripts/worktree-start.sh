#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_lib.sh
source "$SCRIPT_DIR/_lib.sh"

usage() {
  cat <<'EOF'
Create (or attach) a feature branch worktree.

Usage:
  worktree-start.sh --branch <name> [--base <ref>] [--path <dir>] [--repo <path>] [--yes]

Options:
  --branch, -b   Branch name (required).
  --base         Base ref to branch from (default: current branch).
  --path, -p     Worktree path (default: sibling .worktrees/<repo>/<branch>).
                If relative, it is interpreted relative to the repo root.
  --repo         Any path inside the target repo (default: cwd).
  --yes, -y      Do not prompt.
EOF
}

branch=""
base=""
path=""
repo="."
yes=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --branch|-b) branch="${2:-}"; shift 2 ;;
    --base) base="${2:-}"; shift 2 ;;
    --path|-p) path="${2:-}"; shift 2 ;;
    --repo) repo="${2:-}"; shift 2 ;;
    --yes|-y) yes=1; shift ;;
    --help|-h) usage; exit 0 ;;
    *) die "Unknown arg: $1 (use --help)" ;;
  esac
done

[[ -n "$branch" ]] || die "Missing --branch (use --help)"

repo_root="$(require_git_repo "$repo")" || die "Not a git repo: $repo"

if [[ -z "$base" ]]; then
  base="$(git -C "$repo_root" rev-parse --abbrev-ref HEAD)"
  [[ "$base" != "HEAD" ]] || base="$(detect_default_branch "$repo_root")"
fi

if [[ -z "$path" ]]; then
  repo_name="$(basename "$repo_root")"
  branch_dir="$(branch_slug "$branch")"
  path="$(cd "$repo_root/.." && pwd)/.worktrees/$repo_name/$branch_dir"
elif [[ "$path" != /* ]]; then
  path="$repo_root/$path"
fi

if worktree_path_for_branch "$repo_root" "$branch" >/dev/null; then
  existing_path="$(worktree_path_for_branch "$repo_root" "$branch")"
  info "Branch already has a worktree: $existing_path"
  exit 0
fi

info "Repo:   $repo_root"
info "Branch: $branch"
info "Base:   $base"
info "Path:   $path"

if [[ "$yes" -ne 1 ]] && ! confirm "Create worktree?"; then
  info "Canceled."
  exit 1
fi

mkdir -p "$(dirname "$path")"

if git -C "$repo_root" show-ref --verify --quiet "refs/heads/$branch"; then
  info "Branch exists; adding worktree without creating a new branch."
  git -C "$repo_root" worktree add "$path" "$branch"
else
  git -C "$repo_root" worktree add -b "$branch" "$path" "$base"
fi

info "Created worktree: $path"
info "Next: cd \"$path\""

#!/usr/bin/env bash
set -euo pipefail

die() {
  echo "error: $*" >&2
  exit 1
}

warn() {
  echo "warn: $*" >&2
}

info() {
  echo "info: $*"
}

confirm() {
  local prompt="${1:-Proceed?}"
  local reply
  read -r -p "$prompt [y/N] " reply || true
  [[ "$reply" == "y" || "$reply" == "Y" ]]
}

require_git_repo() {
  local repo_hint="${1:-.}"
  git -C "$repo_hint" rev-parse --show-toplevel 2>/dev/null
}

detect_default_branch() {
  local repo_root="$1"

  local origin_head
  origin_head="$(git -C "$repo_root" symbolic-ref --quiet refs/remotes/origin/HEAD 2>/dev/null || true)"
  if [[ -n "$origin_head" ]]; then
    echo "${origin_head#refs/remotes/origin/}"
    return 0
  fi

  if git -C "$repo_root" show-ref --verify --quiet refs/heads/main; then
    echo "main"
    return 0
  fi

  if git -C "$repo_root" show-ref --verify --quiet refs/heads/master; then
    echo "master"
    return 0
  fi

  local current
  current="$(git -C "$repo_root" rev-parse --abbrev-ref HEAD)"
  if [[ "$current" != "HEAD" ]]; then
    echo "$current"
    return 0
  fi

  die "Could not detect default branch; pass --into/--base explicitly."
}

worktree_path_for_branch() {
  local repo_root="$1"
  local branch="$2"
  local needle="refs/heads/$branch"

  local current_path=""
  local current_branch=""
  local line=""

  while IFS= read -r line; do
    case "$line" in
      worktree\ *)
        current_path="${line#worktree }"
        current_branch=""
        ;;
      branch\ *)
        current_branch="${line#branch }"
        ;;
    esac

    if [[ -n "$current_path" && "$current_branch" == "$needle" ]]; then
      echo "$current_path"
      return 0
    fi
  done < <(git -C "$repo_root" worktree list --porcelain)

  return 1
}

branch_slug() {
  local branch="$1"
  branch="${branch//\//__}"
  branch="${branch// /_}"
  echo "$branch"
}

ensure_clean_or_die() {
  local dir="$1"
  local label="$2"
  if [[ -n "$(git -C "$dir" status --porcelain)" ]]; then
    die "$label has uncommitted changes: $dir"
  fi
}


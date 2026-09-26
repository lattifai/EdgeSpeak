#!/usr/bin/env bash
# Build the `claude-directory` branch that Anthropic's Claude plugin directory tracks.
#
# The branch is generated from a committed source ref (default: main) using an allowlist,
# so files added to main never leak into the directory listing by accident. It holds one
# plugin at the repository root: the directory manifest and icon, the directory README, the license,
# and the six core skills. The script commits locally and never pushes; pushing the branch
# publishes a new directory version.
#
# Usage: scripts/build-directory-branch.sh [source-ref]
set -euo pipefail

SOURCE_REF="${1:-main}"
BRANCH="claude-directory"
CORE_SKILLS=(
  edgespeak-transcribe
  edgespeak-align
  edgespeak-segment
  edgespeak-karaoke
  edgespeak-name-speakers
  edgespeak-translate
)
BANNED_TERMS='broadcast|yt-download|yt-dlp|youtube|text-to-speech|(^|[^a-z])dub|voice clon'

fail() { echo "error: $*" >&2; exit 1; }

# Fail when the grep command matches (exit 0); also fail when grep itself errors (exit >= 2),
# so an unreadable tree never passes an assertion silently.
assert_no_match() {
  local message="$1"; shift
  local output status=0
  output="$("$@")" || status=$?
  if [ "$status" -eq 0 ]; then
    printf '%s\n' "$output" >&2
    fail "$message"
  elif [ "$status" -ne 1 ]; then
    fail "grep exited with status $status while checking: $message"
  fi
}

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"
SOURCE_SHA="$(git rev-parse --verify "${SOURCE_REF}^{commit}")" || fail "unknown source ref: $SOURCE_REF"
command -v claude >/dev/null || fail "the claude CLI is required for 'claude plugin validate'"

# Build on top of the published branch: refresh origin's copy first and refuse to append to a
# local branch that is missing published commits, so the later push stays a fast-forward.
if git remote get-url origin >/dev/null 2>&1; then
  git fetch --quiet origin "+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH" 2>/dev/null || true
fi
if git show-ref --verify --quiet "refs/heads/$BRANCH" &&
   git show-ref --verify --quiet "refs/remotes/origin/$BRANCH" &&
   ! git merge-base --is-ancestor "origin/$BRANCH" "$BRANCH"; then
  fail "local $BRANCH is missing commits from origin/$BRANCH; reset it to origin/$BRANCH after checking nothing local would be lost"
fi

WORKTREE="$(mktemp -d "${TMPDIR:-/tmp}/claude-directory.XXXXXX")"
cleanup() { git worktree remove --force "$WORKTREE" >/dev/null 2>&1 || rm -rf "$WORKTREE"; }
trap cleanup EXIT

if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
  git worktree add --quiet "$WORKTREE" "$BRANCH"
elif git show-ref --verify --quiet "refs/remotes/origin/$BRANCH"; then
  git worktree add --quiet -b "$BRANCH" "$WORKTREE" "origin/$BRANCH"
else
  git worktree add --quiet --detach "$WORKTREE" "$SOURCE_SHA"
  git -C "$WORKTREE" checkout --quiet --orphan "$BRANCH"
fi

# Start from an empty tree, then copy only the allowlisted paths from the committed source.
find "$WORKTREE" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
mkdir -p "$WORKTREE/.claude-plugin"
git show "$SOURCE_SHA:directory-listing/plugin.json" > "$WORKTREE/.claude-plugin/plugin.json"
git show "$SOURCE_SHA:directory-listing/icon.svg" > "$WORKTREE/.claude-plugin/icon.svg"
git show "$SOURCE_SHA:directory-listing/README.md" > "$WORKTREE/README.md"
git show "$SOURCE_SHA:directory-listing/README.zh-CN.md" > "$WORKTREE/README.zh-CN.md"
git show "$SOURCE_SHA:skills/LICENSE" > "$WORKTREE/LICENSE"
skill_paths=()
for skill in "${CORE_SKILLS[@]}"; do skill_paths+=("skills/$skill"); done
git archive "$SOURCE_SHA" "${skill_paths[@]}" | tar -x -C "$WORKTREE"

# Assertions: nothing from the excluded skills, no installer pipes in skills, exactly six skills.
# A linked worktree's .git is a file, so exclude it both as a directory and as a file.
assert_no_match "excluded-skill terms found in the directory tree" \
  grep -rniE --exclude-dir=.git --exclude=.git "$BANNED_TERMS" "$WORKTREE"
assert_no_match "installer pipe found in a skill" \
  grep -rnE 'curl -fsSL.*\|[[:space:]]*sh' "$WORKTREE/skills"
skill_count="$(find "$WORKTREE/skills" -name SKILL.md | wc -l | tr -d ' ')"
[ "$skill_count" = "${#CORE_SKILLS[@]}" ] || fail "expected ${#CORE_SKILLS[@]} SKILL.md files, found $skill_count"
if [ -n "$(find "$WORKTREE" -name .DS_Store -print -quit)" ]; then fail ".DS_Store found"; fi
claude plugin validate "$WORKTREE" || fail "claude plugin validate failed"

git -C "$WORKTREE" add -A
if git -C "$WORKTREE" diff --cached --quiet; then
  echo "$BRANCH is already up to date with $SOURCE_REF ($SOURCE_SHA)."
  exit 0
fi
git -C "$WORKTREE" commit --quiet -m "chore: build the Claude directory listing from ${SOURCE_SHA:0:12}"
echo "Committed $(git rev-parse --short "$BRANCH") on $BRANCH from $SOURCE_REF ($SOURCE_SHA)."
echo "Not pushed. Publishing a directory version is: git push origin $BRANCH"

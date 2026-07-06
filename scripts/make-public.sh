#!/usr/bin/env bash
# Build the public, MIT-licensed `apex-harness` repo from this (private) `apex` repo.
#
# It copies the harness code (lib/ mcp/ skills/ commands/ .claude/hooks +
# .claude/settings.json, templates/ tests/ scripts/paper_metrics.py
# docs/paper-ase2026/), drops in the open-source meta files from
# scripts/apex-harness-skel/, runs a light sanitisation pass, and then scans the
# result for secrets / personal absolute paths and reports.
#
# It does NOT touch git and does NOT push. You review the tree, then:
#     cd <target> && python3 -m venv .venv && . .venv/bin/activate
#     pip install -e ".[dev]" && pytest          # expect 620 passed
#     git init && git add -A && git commit -m "chore: initial public release of APEX harness"
#     gh repo create vjrivmon/apex-harness --public --source . --remote origin --push
#
# Usage:
#     scripts/make-public.sh [TARGET_DIR] [--force] [--verify]
#       TARGET_DIR : default ~/RoadToDevOps/apex-harness
#       --force    : overwrite TARGET_DIR if it already exists
#       --verify   : after building, create a venv, pip install, and run pytest
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKEL="$REPO/scripts/apex-harness-skel"
TARGET="${1:-$HOME/RoadToDevOps/apex-harness}"
shift || true
FORCE=0; VERIFY=0
for a in "$@"; do
  case "$a" in
    --force) FORCE=1 ;;
    --verify) VERIFY=1 ;;
    *) echo "unknown arg: $a" >&2; exit 2 ;;
  esac
done

[ -d "$SKEL" ] || { echo "missing skeleton dir: $SKEL" >&2; exit 1; }

if [ -e "$TARGET" ]; then
  if [ "$FORCE" = "1" ]; then
    echo ">> wiping existing $TARGET"
    rm -rf "$TARGET"
  else
    echo "target already exists: $TARGET  (pass --force to overwrite)" >&2
    exit 1
  fi
fi
mkdir -p "$TARGET"

# --- common rsync excludes (cruft / runtime state / venv / vcs) ---------------
EX=(
  --exclude '__pycache__/' --exclude '*.pyc' --exclude '.pytest_cache/'
  --exclude '.mypy_cache/' --exclude '.ruff_cache/' --exclude '.venv/'
  --exclude '*.egg-info/' --exclude '.git/' --exclude '*.db' --exclude '*.sqlite'
  --exclude '*.db-shm' --exclude '*.db-wal' --exclude '.DS_Store' --exclude '*.log'
)

copy() {  # copy() SRC_REL [DST_REL]
  local src="$REPO/$1" dst="$TARGET/${2:-$1}"
  [ -e "$src" ] || { echo "  ! skip (missing): $1"; return 0; }
  mkdir -p "$(dirname "$dst")"
  if [ -d "$src" ]; then
    rsync -a "${EX[@]}" "$src/" "$dst/"
  else
    cp "$src" "$dst"
  fi
  echo "  + $1${2:+  ->  $2}"
}

echo ">> copying harness code into $TARGET"
copy lib
copy mcp
copy skills
copy commands
copy templates
copy tests
copy tools
copy .claude/hooks
copy .claude/settings.json
copy scripts/paper_metrics.py scripts/paper_metrics.py
copy docs/paper-ase2026 docs/paper-ase2026

# --- exclude files that carry private data even though their dir is included ---
rm -f  "$TARGET/lib/embeddings.py"                 # contains a private Tailscale IP; unused stub
rm -rf "$TARGET/docs/paper-ase2026"/{*.aux,*.bbl,*.blg,*.fls,*.fdb_latexmk,*.out,comment.cut} 2>/dev/null || true
find "$TARGET" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$TARGET" -name '*.pyc' -delete 2>/dev/null || true

# --- drop in the open-source meta files ---------------------------------------
echo ">> writing open-source meta files"
cp "$SKEL/LICENSE"          "$TARGET/LICENSE"
cp "$SKEL/README.md"        "$TARGET/README.md"
cp "$SKEL/CONTRIBUTING.md"  "$TARGET/CONTRIBUTING.md"
cp "$SKEL/CITATION.cff"     "$TARGET/CITATION.cff"
cp "$SKEL/pyproject.toml"   "$TARGET/pyproject.toml"
cp "$SKEL/CLAUDE.md"        "$TARGET/CLAUDE.md"
cp "$SKEL/gitignore"        "$TARGET/.gitignore"
for f in LICENSE README.md CONTRIBUTING.md CITATION.cff pyproject.toml CLAUDE.md .gitignore; do echo "  + $f"; done

# --- light sanitisation pass --------------------------------------------------
echo ">> sanitising absolute personal paths"
# Replace the one literal absolute path that appears in a docstring example.
if grep -rl '/home/[a-zA-Z0-9_]*/RoadToDevOps/apex/' "$TARGET" >/dev/null 2>&1; then
  grep -rlZ '/home/[a-zA-Z0-9_]*/RoadToDevOps/apex/' "$TARGET" | xargs -0 \
    sed -i 's#/home/[a-zA-Z0-9_]*/RoadToDevOps/apex/#~/path/to/apex-harness/#g'
fi
# Any remaining bare home dir -> ~
if grep -rl '/home/[a-zA-Z0-9_]*/' "$TARGET" >/dev/null 2>&1; then
  grep -rlZ '/home/[a-zA-Z0-9_]*/' "$TARGET" | xargs -0 \
    sed -i 's#/home/[a-zA-Z0-9_]*/#~/#g'
fi

# --- secrets / PII scan -------------------------------------------------------
echo ">> scanning for secrets / private addresses / personal handles"
PATTERNS='sk-ant-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{30,}|gho_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|-----BEGIN [A-Z ]*PRIVATE KEY-----|xox[baprs]-[A-Za-z0-9-]+|\b10\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\b|\b192\.168\.[0-9]{1,3}\.[0-9]{1,3}\b|\b100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.[0-9]{1,3}\.[0-9]{1,3}\b|/home/[a-zA-Z0-9_]+/|vicenterivasmonferrer'
HITS="$(grep -rInE "$PATTERNS" "$TARGET" 2>/dev/null || true)"
if [ -n "$HITS" ]; then
  echo "!! POTENTIAL ISSUES FOUND -- review before publishing:"
  echo "$HITS" | sed 's/^/   /'
else
  echo "   clean (no obvious secrets, private IPs, home paths, or personal handles)."
fi

# --- summary ------------------------------------------------------------------
N_PY=$(find "$TARGET" -name '*.py' | wc -l | tr -d ' ')
N_SKILL=$(find "$TARGET/skills" -maxdepth 1 -mindepth 1 -type d | wc -l | tr -d ' ')
N_HOOK=$(find "$TARGET/.claude/hooks" -name '*.py' | wc -l | tr -d ' ')
N_TEST=$(find "$TARGET/tests" -name 'test_*.py' | wc -l | tr -d ' ')
N_ALL=$(find "$TARGET" -type f | wc -l | tr -d ' ')
echo
echo ">> built $TARGET"
echo "   files: $N_ALL   python: $N_PY   skills: $N_SKILL   hooks: $N_HOOK   test files: $N_TEST"
echo
if [ "$VERIFY" = "1" ]; then
  echo ">> verifying (venv + pip install + pytest) ..."
  ( cd "$TARGET"
    python3 -m venv .venv
    . .venv/bin/activate
    pip install -q -e ".[dev]"
    pytest )
  echo ">> pytest OK"
fi
cat <<EOF
Next steps (you do these after reviewing the tree):
  cd "$TARGET"
  python3 -m venv .venv && . .venv/bin/activate
  pip install -e ".[dev]" && pytest          # expect 620 passed
  git init && git add -A && git commit -m "chore: initial public release of APEX harness"
  gh repo create vjrivmon/apex-harness --public --description "A self-improving harness for LLM coding agents across the software lifecycle" --source . --remote origin --push
EOF

#!/usr/bin/env bash
#
# scripts/check-public-firewall.sh
#
# Pre-publish scan for personal / internal markers in committed-or-
# staged content. Implements the rule in CLAUDE.md
# § INTERNAL-DOCS-STAY-INTERNAL.
#
# Usage:
#   scripts/check-public-firewall.sh                # scan working tree
#   scripts/check-public-firewall.sh --staged       # scan git index
#   scripts/check-public-firewall.sh --ref REF      # scan one commit's tree
#
# Exits non-zero on any match. Suitable for git pre-commit hooks and CI.

set -euo pipefail

MODE="working"
REF=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --staged) MODE="staged"; shift ;;
        --ref)    MODE="ref"; REF="$2"; shift 2 ;;
        -h|--help)
            sed -n 's/^# \{0,1\}//p' "$0" | head -20
            exit 0
            ;;
        *) echo "unknown flag: $1" >&2; exit 2 ;;
    esac
done

# Public file scope = everything except local-only paths (matches the
# .gitignore intent for internal coordination).
EXCLUDES=(
    ':(exclude)notes/**'
    ':(exclude)memory/**'
    ':(exclude)WORKING.md'
    ':(exclude)CLAUDE.md'
    ':(exclude)AGENTS.md'
    ':(exclude)GEMINI.md'
    ':(exclude).venv/**'
    ':(exclude).cache/**'
    ':(exclude)models/**'
    ':(exclude)tests/fixtures/cassettes/**'
    # The script itself defines the patterns it scans for, so it
    # cannot scan itself without false-positives.
    ':(exclude)scripts/check-public-firewall.sh'
)

# Patterns considered leaks. Extend deliberately; over-eager additions
# create false-positives that erode trust in the scan.
PATTERNS=(
    # Personal identifiers
    'Aakash'
    'aakash'
    # Specific INTERNAL corpus counts from project-personal-corpus-state.
    # Every plausible shape: digits-with-comma, K-suffix, etc.
    '29,?937'
    '14,?939'
    '614,?9[0-9]{2}'
    '620,?[0-9]{3}'
    '620[Kk]'
    '614[Kk]'
    '858 notes'
    '9,?477'
    # Phrases that signal a private-corpus reference even without numbers.
    'personal Zotero library'
    'personal corpus'
    # Banned engineering jargon per feedback-no-load-bearing-jargon.
    'load-bearing'
)

case "$MODE" in
    staged)   FILES=$(git diff --cached --name-only -- "${EXCLUDES[@]}") ;;
    ref)      FILES=$(git diff-tree --no-commit-id --name-only -r "$REF" -- "${EXCLUDES[@]}") ;;
    working)  FILES=$(git ls-files -- "${EXCLUDES[@]}") ;;
esac

if [[ -z "$FILES" ]]; then
    echo "leak-scan: no files in scope; clean."
    exit 0
fi

FAIL=0
for pattern in "${PATTERNS[@]}"; do
    while IFS= read -r file; do
        [[ -z "$file" || ! -f "$file" ]] && continue
        if grep -nE "$pattern" "$file" >/dev/null 2>&1; then
            echo "leak-scan: FAIL — pattern '$pattern' in $file:"
            grep -nE "$pattern" "$file" | head -5 | sed 's/^/    /'
            FAIL=1
        fi
    done <<<"$FILES"
done

# Also scan commit messages on the staged commit when running --staged.
if [[ "$MODE" == "staged" ]]; then
    MSG="$(git diff --cached --name-only -- "${EXCLUDES[@]}" 2>&1 | head -1)"
    # Pre-commit message isn't available here; the commit-msg hook
    # handles that. Skip silently.
    :
fi

# Scan the most recent commit's message when running --ref.
if [[ "$MODE" == "ref" && -n "$REF" ]]; then
    for pattern in "${PATTERNS[@]}"; do
        if git log -1 --format=%B "$REF" | grep -E "$pattern" >/dev/null 2>&1; then
            echo "leak-scan: FAIL — pattern '$pattern' in commit message of $REF:"
            git log -1 --format=%B "$REF" | grep -nE "$pattern" | head -5 | sed 's/^/    /'
            FAIL=1
        fi
    done
fi

if [[ "$FAIL" -eq 1 ]]; then
    echo
    echo "leak-scan: aborting. Fix the listed leaks, or add the pattern"
    echo "to scripts/check-public-firewall.sh::EXCLUDES if it is a"
    echo "legitimate token (e.g. a public-domain author name)."
    exit 1
fi
echo "leak-scan: clean. ${#PATTERNS[@]} patterns checked across $(wc -l <<<"$FILES" | tr -d ' ') files."

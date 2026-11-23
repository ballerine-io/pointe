#!/bin/bash
# Run Pointe's five focused security reviews with Claude Code, read-only, and write one report per area.
#
#   tools/security_review.sh                      # all five areas, against HEAD
#   tools/security_review.sh --ref v1.21.1        # against a tag or commit
#   tools/security_review.sh --model <id> network-pairing web-page
#
# Each review runs `claude -p` in a clean, detached checkout of the commit (so uncommitted work is not reviewed), with
# only read tools allowed: Read, Grep, Glob, and `git log`, `git show`, `rg`, `ls` through Bash. The model cannot edit,
# run tests or reach the network through a tool. Reports go to .security-reviews/<date>/<area>.md (gitignored): they
# can describe unfixed issues, so they stay private until triaged. What is published goes in docs/security/reviews/
# (see the README there).
#
# Options:
#   --model ID   the model (default: $POINTE_REVIEW_MODEL, else claude-mythos-5-2)
#   --ref REF    the commit to review (default: HEAD)
#   --out DIR    where reports go (default: .security-reviews/<date>)
#   AREA ...     any of: network-pairing approvals-voice secrets-supply web-page apple-apps (default: all, in parallel)
#
# CLAUDE_CONFIG_DIR is passed through, so a second Claude Code account works:
#   CLAUDE_CONFIG_DIR=~/.claude-2 tools/security_review.sh
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
MODEL=${POINTE_REVIEW_MODEL:-claude-mythos-5-2}
REF=HEAD
DATE=$(date +%Y-%m-%d)
OUT=""
AREAS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --model) MODEL=$2; shift 2 ;;
    --ref) REF=$2; shift 2 ;;
    --out) OUT=$2; shift 2 ;;
    -h|--help) sed -n '2,23p' "$0"; exit 0 ;;
    -*) echo "unknown option: $1" >&2; exit 2 ;;
    *) AREAS+=("$1"); shift ;;
  esac
done

focus() {
  case "$1" in
    network-pairing) echo "Network exposure and authentication: the local HTTP server on 127.0.0.1 (origin/CSRF/DNS-rebinding/CORS checks, token handling), the TLS phone listener and certificate pinning, pairing (QR secret, invites, rotate/off), multi-machine hub/node links, remote session tokens, anything reachable from the LAN or a VPN." ;;
    approvals-voice) echo "Approval and voice safety: what a spoken word or a tap can approve or send, the permission-hook relay and hold logic, read-back binding, voice lock/owner binding, meeting mode and night shift rails, prompt injection from session transcripts or meeting audio into the brain that could cause an unwanted send/approval, attach-by-voice joining sessions." ;;
    secrets-supply) echo "Secrets and supply chain: Keychain usage and naming, how keys reach processes (env, argv, logs), logging/redaction, crash/debug output, the install path (uv, link-pointe, ~/.local/bin), plugin hooks, GitHub Actions pinning, dependency lock, the egress allowlist vs real outbound hosts, openai_url." ;;
    web-page) echo "The web page the daemon serves (ui.html and its JS): XSS through session names/transcripts/meeting notes, unsafe HTML insertion, message/event handling, clickjacking, service-worker or storage of secrets, the phone browser path." ;;
    apple-apps) echo "The iOS and macOS apps (apple/PointeKit, ios/, macos/): certificate pinning and pairing storage, Keychain/UserDefaults usage, URL schemes and deep links, Face ID/Touch ID gates, local network permissions, the Mac app's daemon start, AppleScript/automation, entitlements." ;;
    *) return 1 ;;
  esac
}

[ ${#AREAS[@]} -eq 0 ] && AREAS=(network-pairing approvals-voice secrets-supply web-page apple-apps)
for a in "${AREAS[@]}"; do focus "$a" >/dev/null || { echo "unknown area: $a" >&2; exit 2; }; done
command -v claude >/dev/null || { echo "claude (Claude Code) is not on PATH" >&2; exit 1; }

SHA=$(git -C "$ROOT" rev-parse --verify "$REF^{commit}")
[ -n "$OUT" ] || OUT="$ROOT/.security-reviews/$DATE"
mkdir -p "$OUT"
OUT=$(cd "$OUT" && pwd)

TREE=$(mktemp -d "${TMPDIR:-/tmp}/pointe-review.XXXXXX")
cleanup() { git -C "$ROOT" worktree remove --force "$TREE" >/dev/null 2>&1 || rm -rf "$TREE"; }
trap cleanup EXIT
git -C "$ROOT" worktree add --detach --quiet "$TREE" "$SHA"

review() {
  local area=$1 prompt
  prompt="You are performing a security review of Pointe, an open-source voice layer for coding agents (Python daemon serving a local web page and a TLS listener for paired phones, Claude Code/Codex/OpenCode adapters, permission-approval relay, iOS and macOS apps in Swift). Read SECURITY.md, docs/security/, docs/harnesses.md and docs/multi-machine.md first for the intended threat model. FOCUS: $(focus "$area")
Read the actual code. Report only real, specific issues with file:line evidence, an exploit scenario, severity (critical/high/medium/low/info) using CVSS-style reasoning, and a concrete fix. Also list what you checked and found sound, and any assumptions. Do not modify files. Output markdown with sections: Summary, Findings (one subsection each: title, severity, location, scenario, fix), Checked and sound, Not covered."
  {
    printf '<!-- %s review of %s by %s on %s -->\n\n' "$area" "$SHA" "$MODEL" "$DATE"
    (cd "$TREE" && claude -p "$prompt" --model "$MODEL" --permission-mode default \
      --allowedTools "Read" "Grep" "Glob" "Bash(git log:*)" "Bash(git show:*)" "Bash(rg:*)" "Bash(ls:*)" \
      --output-format text)
  } > "$OUT/$area.md" 2> "$OUT/$area.err"
}

echo "Reviewing $SHA with $MODEL: ${AREAS[*]}"
pids=()
for a in "${AREAS[@]}"; do review "$a" & pids+=($!); done
status=0
for i in "${!pids[@]}"; do
  if wait "${pids[$i]}"; then echo "  ${AREAS[$i]}: $OUT/${AREAS[$i]}.md"
  else echo "  ${AREAS[$i]}: failed, see $OUT/${AREAS[$i]}.err" >&2; status=1; fi
done
exit $status

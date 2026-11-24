#!/usr/bin/env bash
# The end-to-end suites in parallel, each on its own isolated daemon, port and sample repo.
set -uo pipefail
cd "$(dirname "$0")/../.."
OUT=/tmp/cv-e2e && mkdir -p "$OUT" /tmp/cv-state-single /tmp/cv-state-multi /tmp/cv-state-echo
limit() { perl -e 'alarm shift; exec @ARGV' 1500 "$@"; }  # a hung suite must not block for hours
CLAUDE_VOICE_STATE=/tmp/cv-state-single CLAUDE_VOICE_DAEMON_PORT=7862 \
  limit uv run python -u -I tests/e2e/scenarios.py brain >"$OUT/single.log" 2>&1 &
CLAUDE_VOICE_STATE=/tmp/cv-state-multi CLAUDE_VOICE_DAEMON_PORT=7863 \
  limit uv run python -u -I tests/e2e/multi_session.py >"$OUT/multi.log" 2>&1 &
CLAUDE_VOICE_STATE=/tmp/cv-state-echo CLAUDE_VOICE_DAEMON_PORT=7864 \
  limit uv run python -u -I tests/e2e/echo.py >"$OUT/echo.log" 2>&1 &
wait
grep -hE "^(PASS|FAIL|SKIP)|passed" "$OUT/single.log" "$OUT/multi.log" "$OUT/echo.log"

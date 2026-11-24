#!/usr/bin/env bash
# A Linux node in Docker, three times: with lsof, with only ss, and with neither (the hook reads /proc).
# The checkout is mounted read-only; the fake hub runs inside the container. Usage: tests/e2e/linux_node/run.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
for tool in lsof ss none; do
  echo "== Linux node, port tool: $tool"
  docker build -q -t "pointe-linux-node:$tool" --build-arg PORT_TOOL="$tool" -f "$ROOT/tests/e2e/linux_node/Dockerfile" "$ROOT" >/dev/null
  docker run --rm -v "$ROOT:/pointe:ro" "pointe-linux-node:$tool"
done

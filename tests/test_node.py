"""What a node (another machine whose sessions the hub voices) may load: no Pipecat, no model, no vendor SDK.

Run in a fresh interpreter, since this suite's own process has long since imported the daemon."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The modules a node runs on (docs/design/multi-machine.md, "Why not run the node's logic inside daemon.py"), with
# every harness adapter loaded, as the node's registry loads them.
NODE_IMPORTS = """
import json, sys
import nodelink, sessions, guards, readout, harnesses
harnesses.names()
readout.mask("ANTHROPIC_API_KEY=sk-ant-0123456789abcdef")
import aiohttp, fastapi, uvicorn, websockets
print(json.dumps(sorted(sys.modules)))
"""

FORBIDDEN = ("pipecat", "onnxruntime", "sherpa_onnx", "anthropic", "google", "openai", "numpy", "torch")


def test_a_node_imports_nothing_that_loads_a_model_or_a_vendor_sdk(tmp_path):
    out = subprocess.run([sys.executable, "-c", NODE_IMPORTS], cwd=ROOT, capture_output=True, text=True, timeout=60,
                         env={"CLAUDE_VOICE_STATE": str(tmp_path), "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, out.stderr
    loaded = json.loads(out.stdout.splitlines()[-1])
    assert not [m for m in loaded if m.split(".")[0] in FORBIDDEN]

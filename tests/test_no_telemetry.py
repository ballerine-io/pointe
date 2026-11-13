"""No onnxruntime telemetry, in any setup: every module of Pointe that can load onnxruntime (directly, or through Silero,
the voice lock, kokoro-onnx or faster-whisper) must have set ORT_DISABLE_TELEMETRY first (no_telemetry.py)."""

import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ORT_BACKED = ("onnxruntime", "sherpa_onnx", "kokoro_onnx", "faster_whisper")
ORT_NAMES = re.compile(r"\b(onnxruntime|sherpa_onnx|kokoro_onnx|faster_whisper|pipecat\.audio\.vad\.silero|"
                       r"pipecat\.services\.kokoro|pipecat\.services\.whisper)\b")
MODULES = sorted([*ROOT.glob("*.py"), *ROOT.glob("harnesses/*.py"), *ROOT.glob("bench/*.py")])

# Run in a fresh interpreter without the variable: a finder records any ORT-backed import made while it is unset, then
# the module is imported by path under another name, so its `if __name__ == "__main__"` block does not run.
PROBE = r"""
import importlib.util, os, sys
bad = []
class Watch:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in {names} and os.environ.get("ORT_DISABLE_TELEMETRY") != "1":
            bad.append(name)
        return None
sys.meta_path.insert(0, Watch())
path = sys.argv[1]
sys.path[:0] = [os.path.dirname(path), {root!r}, os.path.join({root!r}, "bench"), os.path.join({root!r}, "harnesses")]
name = "probe_" + os.path.basename(path)[:-3]
try:
    spec = importlib.util.spec_from_file_location(name, path)
    sys.modules[name] = module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
except BaseException as e:  # a missing extra or a script that needs arguments: what it imported before still counts
    pass
# Most loads come later, inside a call (Silero, the voice lock): a process that imported a module of Pointe that can
# reach onnxruntime must still have the variable set when that happens.
ours = {os.path.abspath(f) for f in {paths}}
if any(os.path.abspath(getattr(m, "__file__", None) or "") in ours for m in list(sys.modules.values())) or path in ours:
    try:
        import onnxruntime
    except ImportError:
        pass
print("ORT-WITHOUT-GUARD " + ",".join(bad) if bad else "ok")
""".replace("{names}", repr(set(ORT_BACKED))).replace("{root!r}", repr(str(ROOT))).replace(
    "{paths}", repr({str(m) for m in MODULES if m.name != "no_telemetry.py" and ORT_NAMES.search(m.read_text())}))


def probe(path: Path, state: Path) -> str:
    env = {k: v for k, v in os.environ.items() if k != "ORT_DISABLE_TELEMETRY"}
    env.update(CLAUDE_VOICE_STATE=str(state), HF_HUB_OFFLINE="1")
    got = subprocess.run([sys.executable, "-c", PROBE, str(path)], capture_output=True, text=True, env=env, timeout=120,
                         cwd=state)
    return got.stdout.strip().splitlines()[-1] if got.stdout.strip() else f"no output: {got.stderr[-300:]}"


def test_no_module_loads_onnxruntime_before_the_variable_is_set(tmp_path):
    (tmp_path / "token").write_text("test-token")
    with ThreadPoolExecutor(8) as pool:
        results = dict(zip(MODULES, pool.map(lambda m: probe(m, tmp_path), MODULES)))
    bad = {str(m.relative_to(ROOT)): r for m, r in results.items() if r.startswith("ORT-WITHOUT-GUARD")}
    assert not bad, bad
    assert results[ROOT / "daemon.py"] == "ok"


@pytest.mark.parametrize("path", [m for m in MODULES if m.name != "no_telemetry.py" and ORT_NAMES.search(m.read_text())], ids=lambda p: p.name)
def test_a_module_that_names_onnxruntime_imports_the_guard_first(path):
    """Lazy imports inside functions are covered too: the guard runs when the module itself is imported."""
    source = path.read_text()
    guard = re.search(r"^import no_telemetry\b", source, re.M)
    assert guard and guard.start() < ORT_NAMES.search(source).start(), f"{path.name}: import no_telemetry first"


@pytest.mark.parametrize("launcher", ["voice-daemon", "pointe", "voice-doctor", "claude-voice"])
def test_the_launchers_export_it_for_every_child_process(launcher):
    assert 'export ORT_DISABLE_TELEMETRY="${ORT_DISABLE_TELEMETRY:-1}"' in (ROOT / "bin" / launcher).read_text()


def test_the_guard_sets_it():
    env = {k: v for k, v in os.environ.items() if k != "ORT_DISABLE_TELEMETRY"}
    got = subprocess.run([sys.executable, "-c", "import no_telemetry, os; print(os.environ['ORT_DISABLE_TELEMETRY'])"],
                         capture_output=True, text=True, env=env, cwd=ROOT)
    assert got.stdout.strip() == "1"

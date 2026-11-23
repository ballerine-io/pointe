"""Vendor keys reach the daemon only: every program a Pointe module starts gets an environment without them
(childenv.child_env), and a key read from the Keychain never enters this process's environment at all."""

import ast
import asyncio
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import childenv  # noqa: E402
import vendors  # noqa: E402
from harnesses import claude_code  # noqa: E402

# What the plugin runs: the top-level modules and the harness adapters. bench/, demo/, evals/, tools/, ios/ and macos/
# are run by a maintainer by hand and read their own keys.
SHIPPED = sorted([*ROOT.glob("*.py"), *ROOT.glob("harnesses/*.py")])
SPAWNS = {("subprocess", n) for n in ("run", "Popen", "call", "check_call", "check_output", "getoutput", "getstatusoutput")}
SPAWNS |= {("asyncio", "create_subprocess_exec"), ("asyncio", "create_subprocess_shell")}
SPAWNS |= {("os", n) for n in ("system", "popen", "execv", "execve", "execvp", "execvpe", "execl", "execle", "execlp",
                               "execlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe", "posix_spawn", "posix_spawnp")}
BUILDERS = {"child_env", "_env"}  # _env: claude_code's, built on child_env (tested below)
# Programs that start the daemon: it reads keys from the environment it is given (Linux, CI, a shell's exports).
NEEDS_KEYS = {("keys.py", "restart"), ("harnesses/join.py", "main")}
# Scripts that run on macOS's own python3, standard library only (tests/test_apps.py), and never import vendors: they hold
# no key from the Keychain, only the environment the person's shell gave them, which their children get as before.
OWN_ENV = {"apps.py", "uninstall.py"}
SECRET = "sk-test-keychain-0123456789abcdef"


def _spawn(call: ast.Call) -> bool:
    f = call.func
    return isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and (f.value.id, f.attr) in SPAWNS


def _built(node: ast.AST | None) -> bool:
    return node is not None and any(isinstance(c, ast.Call) and getattr(c.func, "id", getattr(c.func, "attr", None)) in BUILDERS
                                    for c in ast.walk(node))


def _env_of(call: ast.Call) -> ast.AST | None:
    env = next((k.value for k in call.keywords if k.arg == "env"), None)
    if env is None and call.func.attr in ("execve", "execvpe", "spawnve", "spawnvpe") and len(call.args) >= 3:
        env = call.args[-1]
    return env


def _spawns_without_child_env() -> list[str]:
    bad = []
    for path in SHIPPED:
        tree = ast.parse(path.read_text())
        name = str(path.relative_to(ROOT))
        if name in OWN_ENV:
            assert "import vendors" not in path.read_text(), name
            continue
        for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            assigned = {t.id: n.value for n in ast.walk(fn) if isinstance(n, ast.Assign)
                        for t in n.targets if isinstance(t, ast.Name)}
            for call in [c for c in ast.walk(fn) if isinstance(c, ast.Call) and _spawn(c)]:
                env = _env_of(call)
                if isinstance(env, ast.Name):
                    env = assigned.get(env.id)
                if not _built(env) and (name, fn.name) not in NEEDS_KEYS:
                    bad.append(f"{name}:{call.lineno} in {fn.name}()")
    return sorted(set(bad))


def test_every_program_a_pointe_module_starts_gets_an_environment_without_the_keys():
    bad = _spawns_without_child_env()
    assert not bad, "pass env=childenv.child_env(...) (or NEEDS_KEYS, with a reason):\n" + "\n".join(bad)


def test_the_check_sees_a_spawn_without_the_helper(tmp_path, monkeypatch):
    """The test above would pass on a tree it cannot read: show it a spawn it must refuse, and one it must accept."""
    (tmp_path / "bad.py").write_text("import subprocess\ndef f():\n    subprocess.run(['git', 'status'])\n")
    (tmp_path / "ok.py").write_text("import subprocess, childenv\ndef f():\n    env = childenv.child_env(A='1')\n"
                                    "    subprocess.run(['git'], env=env)\n")
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    monkeypatch.setattr(sys.modules[__name__], "SHIPPED", [tmp_path / "bad.py", tmp_path / "ok.py"])
    assert _spawns_without_child_env() == ["bad.py:3 in f()"]


def test_every_env_builder_strips_the_keys():
    for path in SHIPPED:
        for fn in ast.walk(ast.parse(path.read_text())):
            if isinstance(fn, ast.FunctionDef) and fn.name == "_env":
                assert _built(ast.Module(body=fn.body, type_ignores=[])) or "child_env" in ast.unparse(fn), path


def test_the_helper_knows_every_key_pointe_reads():
    assert childenv.KEY_ENVS == vendors.KEY_ENVS


def _keychain(monkeypatch):
    """A Keychain that holds an OpenAI key, without touching the real one."""
    monkeypatch.setattr(vendors.subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(
        argv, 0, stdout=SECRET + "\n" if "pointe.openai-api-key" in argv else "", stderr=""))
    monkeypatch.setattr(vendors, "_found", {}, raising=False)


def test_a_keychain_key_stays_out_of_the_environment_and_is_still_masked(monkeypatch):
    import readout

    for env in vendors.KEY_ENVS:
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv("CLAUDE_VOICE_LOCAL_ONLY", "0")
    _keychain(monkeypatch)
    assert vendors.key("openai") == SECRET
    assert SECRET not in os.environ.values(), "a child started any way at all would inherit it"
    assert vendors.key("openai") == SECRET, "read once, kept in memory"
    assert SECRET not in readout.mask(f"the key is {SECRET}")


def test_the_claude_fork_and_the_roster_get_no_vendor_key(monkeypatch, tmp_path):
    for env in vendors.KEY_ENVS:
        monkeypatch.setenv(env, f"from-the-shell-{env}")
    monkeypatch.setenv("CLAUDE_VOICE_LOCAL_ONLY", "0")
    monkeypatch.delenv("OPENAI_API_KEY")
    _keychain(monkeypatch)
    assert vendors.key("openai") == SECRET
    seen = []

    class Proc:
        returncode = 0

        async def communicate(self):
            return b'{"result": "fine"}', b""

    async def fake_exec(*argv, env=None, **kw):
        seen.append((argv, env))
        return Proc()

    monkeypatch.setattr(claude_code.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(claude_code.shutil, "which", lambda name: "/usr/local/bin/claude")
    session = SimpleNamespace(id="s-1", cwd=str(tmp_path), home="", transcript=str(tmp_path / "none.jsonl"), name="api")
    assert asyncio.run(claude_code.ClaudeCode().side_question(session, "what changed?")) == "fine"
    asyncio.run(claude_code._agents_raw(""))
    assert [argv[1] for argv, _ in seen] == ["-p", "agents"]
    for argv, env in seen:
        assert env is not None and not (vendors.KEY_ENVS & env.keys()), argv[:2]
        assert not any(SECRET in v or v.startswith("from-the-shell-") for v in env.values()), argv[:2]

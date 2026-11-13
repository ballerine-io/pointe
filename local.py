"""Fully local mode: ears, mouth and text models on this Mac, with no key, so nothing leaves it.

    pointe local            download what is missing (sizes first, then progress), start the text-model server, turn it on
    pointe local status     what is on disk, whether the server answers, and its memory
    pointe local start|stop the text-model server (the daemon starts it when needed; `pointe stop` stops it)
    pointe local voice      "Voice stays on your Mac": ears and mouth here, text models in the cloud (they get text only)
    pointe local off        back to the vendors chosen before (from either)

Ears are Whisper (mlx-whisper) and the mouth is Kokoro, inside the daemon. Text models (brain, reader, gate) are one model
served by mlx-lm's OpenAI-compatible server, from its own uv environment under the state dir, as this user, on loopback.
What was chosen and why, with the measurements: docs/features/local.md and docs/features/voice-stays-local.md.
"""

import contextlib
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # run as a script in isolated mode (-I)
import vendors  # noqa: E402

TEXT_MODEL = "mlx-community/gemma-4-26b-a4b-it-4bit"  # Apache-2.0; why: docs/features/local.md
EARS_MODEL = vendors.LOCAL_EARS_MODEL
MOUTH = "local:kokoro:af_heart"
MLX_LM = "mlx-lm==0.32.2"
MIN_RAM_GB = 32  # the text model took 17 GB while it ran (footprint), plus the daemon and macOS
# Thinking off: with it on, a reply waits for hundreds of hidden tokens.
SERVER_ARGS = ["--chat-template-args", json.dumps({"enable_thinking": False})]
LOCAL_KEYS = ("brain", "reader", "checker", "ears", "mouth", "local_only", "local_url", "voice_local")
VOICE_MOUTH = vendors.LOCAL_MOUTH
VOICE_MODEL = "mlx-community/Kokoro-82M-bf16"  # Kokoro on MLX, for VOICE_MOUTH; kokoro_mlx.MODEL


def state() -> Path:
    return Path(os.environ.get("CLAUDE_VOICE_STATE", Path.home() / ".claude-voice"))


def home() -> Path:
    return state() / "local"


def port() -> int:
    """The environment, else the port `pointe local` chose (so the daemon restarts the server where it was), else 7869."""
    if os.environ.get("CLAUDE_VOICE_LOCAL_PORT"):
        return int(os.environ["CLAUDE_VOICE_LOCAL_PORT"])
    configured = urllib.parse.urlsplit(vendors.config().get("local_url", ""))
    return configured.port if configured.hostname == "127.0.0.1" and configured.port else 7869


def url() -> str:
    return f"http://127.0.0.1:{port()}/v1"


def model() -> str:
    """The text model in use: the one in config.json when local mode is on, else the default."""
    brain = vendors.config().get("brain", "")
    return brain.split(":", 1)[1] if brain.startswith(f"{vendors.LOCAL}:") else TEXT_MODEL


# ---------- config.json ----------

def _config_path() -> Path:
    return state() / "config.json"


def _save_before() -> dict:
    """The choice a local setup replaces, kept once (not over by a second local setup), for `pointe local off`."""
    saved, current = home() / "config.before-local.json", vendors.config()
    if not current.get("local_only") and not current.get("voice_local"):
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_text(json.dumps(current, indent=2))
    return current


def write_config(text_model: str = TEXT_MODEL) -> None:
    """Every role local and no key read. The choice it replaces is kept, once, for `pointe local off`."""
    path, current = _config_path(), _save_before()
    current.pop("voice_local", None)
    current.update(brain=f"local:{text_model}", reader=f"local:{text_model}", checker=f"local:{text_model}",
                   ears="local", mouth=MOUTH, local_only=True, local_url=url())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=2) + "\n")


def write_voice_config() -> None:
    """Voice stays on your Mac: ears and mouth local, the text roles as they were (cloud ones: a local text model chosen
    by fully local mode goes back to the vendors' order)."""
    path, current = _config_path(), _save_before()
    for role in ("brain", "reader", "checker"):
        if str(current.get(role, "")).startswith(f"{vendors.LOCAL}:"):
            current.pop(role)
    for gone in ("local_only", "local_url"):
        current.pop(gone, None)
    current.update(ears=vendors.LOCAL, mouth=VOICE_MOUTH, voice_local=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=2) + "\n")


def restore_config() -> None:
    saved = home() / "config.before-local.json"
    if saved.exists():
        restored = json.loads(saved.read_text())
        saved.unlink()
    else:
        restored = {k: v for k, v in vendors.config().items() if k not in LOCAL_KEYS}
    _config_path().write_text(json.dumps(restored, indent=2) + "\n")


def on() -> bool:
    return vendors.local_only()


# ---------- what is on disk ----------

def cached_bytes(repo: str) -> int:
    """Bytes of a Hugging Face model already downloaded, 0 if any of it is missing."""
    try:
        from huggingface_hub import snapshot_download

        folder = Path(snapshot_download(repo, local_files_only=True))
    except Exception:
        return 0
    return sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())


def voice_on() -> bool:
    return vendors.voice_local() and not vendors.local_only()


def kokoro_bytes() -> int:
    try:
        from pipecat.services.kokoro.tts import KOKORO_CACHE_DIR
    except ImportError:  # the local extra is not installed (pointe local installs it): nothing downloaded
        return 0

    files = [KOKORO_CACHE_DIR / "kokoro-v1.0.onnx", KOKORO_CACHE_DIR / "voices-v1.0.bin"]
    return sum(f.stat().st_size for f in files) if all(f.exists() for f in files) else 0


def server_bin() -> Path:
    return home() / "mlx-lm" / "bin" / "mlx_lm.server"


def gb(n: int) -> str:
    return f"{n / 1e9:.1f} GB"


def remote_size(repo: str) -> int | None:
    try:
        from huggingface_hub import HfApi

        info = HfApi().model_info(repo, files_metadata=True)
        return sum(s.size or 0 for s in info.siblings or [])
    except Exception:
        return None


# ---------- the text-model server ----------

def _pid() -> int | None:
    try:
        pid = int((home() / "server.pid").read_text())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


def answering(base: str | None = None) -> bool:
    """Whether the text-model server at `base` (by default the one config.json names) lists its models."""
    base = base or vendors.config().get("local_url") or url()
    try:
        with urllib.request.urlopen(f"{base}/models", timeout=2) as r:
            return r.status == 200
    except OSError:
        return False


def memory(pid: int) -> str:
    """The process's footprint as macOS counts it. Not ps's RSS: the model's weights are GPU memory, which RSS leaves out."""
    got = subprocess.run(["footprint", str(pid)], capture_output=True, text=True)
    found = re.search(r"Footprint: ([\d.]+ [KMG]B)", got.stdout)
    return found.group(1) if found else "unknown"


def start(text_model: str | None = None, quiet: bool = False) -> bool:
    """Start the server if nothing answers, load the model with one tiny request, and return once it replies."""
    text_model = text_model or model()
    if answering(url()):
        return True
    if not server_bin().exists():
        print("The local text-model server is not installed. Run: pointe local", file=sys.stderr)
        return False
    log = home() / "server.log"
    with log.open("w") as out:
        proc = subprocess.Popen([str(server_bin()), "--model", text_model, "--host", "127.0.0.1", "--port", str(port()),
                                 *SERVER_ARGS], stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                start_new_session=True,  # outlives the shell that started it, as the daemon does
                                # Offline: the model is on disk, and loading it by name would ask the Hub about it.
                                env={**{k: v for k, v in os.environ.items() if k not in vendors.KEY_ENVS}, "HF_HUB_OFFLINE": "1"})
    (home() / "server.pid").write_text(str(proc.pid))
    if not quiet:
        print(f"Starting the text model on {url()} (loading about {gb(cached_bytes(text_model))} into memory)...", flush=True)
    began = time.time()
    while time.time() - began < 600:
        if proc.poll() is not None:
            print(f"The text-model server stopped. Its log: {log}", file=sys.stderr)
            return False
        if answering(url()) and _warm(text_model):
            if not quiet:
                print(f"Text model ready in {time.time() - began:.0f} s.", flush=True)
            return True
        time.sleep(1)
    print(f"The text-model server did not answer in 10 minutes. Its log: {log}", file=sys.stderr)
    return False


def _warm(text_model: str) -> bool:
    """The server loads the model on the first request: done here, so the first thing the user says does not wait for it."""
    body = json.dumps({"model": text_model, "messages": [{"role": "user", "content": "Say ok."}], "max_tokens": 4}).encode()
    request = urllib.request.Request(f"{url()}/chat/completions", data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=600) as r:
            return r.status == 200
    except OSError:
        return False


def stop() -> None:
    pid = _pid()
    if pid:
        os.kill(pid, signal.SIGTERM)
        for _ in range(40):
            if _pid() is None:
                break
            time.sleep(0.25)
        else:
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)
    (home() / "server.pid").unlink(missing_ok=True)


# ---------- install ----------

def supported(text_model: str = TEXT_MODEL) -> str | None:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        return ("The one-step local mode needs an Apple-silicon Mac. Elsewhere, set each role to local by hand and run "
                "an OpenAI-compatible server such as Ollama: see docs/features/local.md.")
    ram = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout.strip() or 0) / 2**30
    if ram < MIN_RAM_GB and text_model == TEXT_MODEL:  # a model chosen by hand is the user's call
        return (f"This Mac has {ram:.0f} GB of memory; the local text model needs {MIN_RAM_GB} GB or more. "
                f"A smaller model can be chosen with: pointe local --model <mlx-community model>, unmeasured.")
    return None


def supported_voice() -> str | None:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        return (f"{vendors.VOICE_LOCAL} needs an Apple-silicon Mac (its voice runs on MLX). Elsewhere, set ears and "
                "mouth to local by hand: see docs/features/local.md.")
    return None


def install_voice() -> int:
    """Voice stays on your Mac: download Whisper and Kokoro (MLX), check a text model has a key, turn it on."""
    if why := supported_voice():
        print(why)
        return 1
    if not any(vendors.key(v) for v in ("anthropic", "gemini", "openai")):
        print(f"{vendors.VOICE_LOCAL} keeps the brain in the cloud, so it needs one text key, best Anthropic's: "
              "pointe key anthropic (a Gemini key also works: pointe key gemini). Then run pointe local voice again.")
        return 1
    from huggingface_hub import snapshot_download  # the local extra: after the checks, which need nothing installed

    wanted = [("Speech to text, Whisper large-v3-turbo (MIT)", EARS_MODEL), ("Voice, Kokoro-82M on MLX (Apache-2.0)", VOICE_MODEL)]
    print(f"{vendors.VOICE_LOCAL}: your speech is heard and spoken on this Mac. The brain, the reader and the gate get "
          "text only.\n\nTo download (once):")
    for label, repo in wanted:
        have = cached_bytes(repo)
        print(f"  {label}: {gb(have or remote_size(repo) or 0)}{', already here' if have else ''}")
    for label, repo in wanted:
        if not cached_bytes(repo):
            print(f"Downloading {label}...", flush=True)
            snapshot_download(repo)
    write_voice_config()
    print("Loading the voice once (about 20 s the first time)...", flush=True)
    import kokoro_mlx

    kokoro_mlx.warm()
    print(f"\n{vendors.VOICE_LOCAL} is on. Restart the voice to use it: pointe stop, then /pointe:voice. "
          "Use headphones. Back to your vendors: pointe local off.")
    return 0


def install(text_model: str = TEXT_MODEL) -> int:
    from huggingface_hub import snapshot_download

    if why := supported(text_model):
        print(why)
        return 1
    wanted = [("Speech to text, Whisper large-v3-turbo (MIT)", EARS_MODEL), (f"Text model, {text_model}", text_model)]
    print("Fully local: no keys, and nothing leaves this Mac.\n\nTo download (once):")
    total = 0
    for label, repo in wanted:
        have = cached_bytes(repo)
        size = have or remote_size(repo) or 0
        total += 0 if have else size
        print(f"  {label}: {gb(size)}{', already here' if have else ''}")
    kokoro = kokoro_bytes()
    print(f"  Voice, Kokoro v1.0 (Apache-2.0): 0.3 GB{', already here' if kokoro else ''}")
    print(f"  Text-model server, {MLX_LM} (MIT), in its own environment: about 0.4 GB"
          f"{', already here' if server_bin().exists() else ''}")
    free = shutil.disk_usage(Path.home()).free
    print(f"About {gb(total + (0 if kokoro else 340_000_000) + (0 if server_bin().exists() else 400_000_000))} to download; "
          f"{gb(free)} free on this disk.\n", flush=True)

    if not server_bin().exists():
        print(f"Installing {MLX_LM}...", flush=True)
        env_dir = home() / "mlx-lm"
        subprocess.run(["uv", "venv", "--quiet", "--python", "3.12", str(env_dir)], check=True)
        subprocess.run(["uv", "pip", "install", "--quiet", "--python", str(env_dir / "bin" / "python"), MLX_LM], check=True)
    for label, repo in wanted:
        if not cached_bytes(repo):
            print(f"Downloading {label}...", flush=True)
            snapshot_download(repo)
    if not kokoro:
        print("Downloading the voice...", flush=True)
        from pipecat.services.kokoro.tts import KOKORO_CACHE_DIR, _ensure_model_files

        _ensure_model_files(KOKORO_CACHE_DIR / "kokoro-v1.0.onnx", KOKORO_CACHE_DIR / "voices-v1.0.bin")
    write_config(text_model)
    if not start(text_model):
        return 1
    print("\nFully local mode is on. Every model runs on this Mac and no key is read."
          "\nRestart the voice to use it: pointe stop, then /pointe:voice. Back to your vendors: pointe local off.")
    return 0


# ---------- status ----------

def status_lines() -> list[str]:
    text_model = model()
    if voice_on():
        lines = [f"{vendors.VOICE_LOCAL}: on (ears and mouth here; text models get text only; off: pointe local off)"]
        for label, repo in (("ears", EARS_MODEL), ("mouth", VOICE_MODEL)):
            size = cached_bytes(repo)
            lines.append(f"  {label:6} {repo}: {gb(size) + ' on disk' if size else 'not downloaded (pointe local voice)'}")
        return lines
    lines = [f"Fully local mode: {'on' if on() else 'off'}" + ("" if on() else " (turn it on: pointe local)")]
    for label, size in (("ears", cached_bytes(EARS_MODEL)), ("mouth", kokoro_bytes()), ("text", cached_bytes(text_model))):
        name = {"ears": EARS_MODEL, "mouth": "Kokoro v1.0", "text": text_model}[label]
        lines.append(f"  {label:6} {name}: {gb(size) + ' on disk' if size else 'not downloaded (pointe local)'}")
    if on():
        configured = vendors.config().get("local_url") or url()
        if answering(configured):
            pid = _pid() if configured == url() else None
            lines.append(f"  server {configured}: answering" + (f", {memory(pid)} of memory" if pid else ""))
        else:
            lines.append(f"  server {configured}: not running (the daemon starts it; or: pointe local start)")
    return lines


def main(argv: list[str]) -> int:
    command = argv[0] if argv and not argv[0].startswith("-") else "install"
    text_model = argv[argv.index("--model") + 1] if "--model" in argv else TEXT_MODEL
    if command == "install":
        return install(text_model)
    if command == "voice":
        return install_voice()
    if command == "status":
        print("\n".join(status_lines()))
        return 0
    if command in ("start", "ensure"):  # ensure: quiet, for bin/voice-daemon
        return 0 if start(quiet=command == "ensure") else 1
    if command == "stop":
        stop()
        return 0
    if command == "off":
        restore_config()
        stop()
        print("Local mode is off. Restart the voice to use your vendors: pointe stop, then /pointe:voice.")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    from loguru import logger

    logger.remove()  # pipecat logs a banner when imported: this is a command for people, not a log
    sys.exit(main(sys.argv[1:]))

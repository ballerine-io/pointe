"""Which vendor does what. Any one of several keys is enough to run; what we run ourselves comes from bench/results.

    CLAUDE_VOICE_BRAIN=vendor:model   decides what to say and which tools to call
    CLAUDE_VOICE_READER=vendor:model  reads whole sessions and reports; CLAUDE_VOICE_CHECKER=vendor:model is the fast gate
    CLAUDE_VOICE_EARS=vendor          speech to text
    CLAUDE_VOICE_MOUTH=vendor:model[:voice]   text to speech

Or the same names, in lower case, in ~/.claude-voice/config.json. "local" runs Whisper, Kokoro and any OpenAI-compatible server. CLAUDE_VOICE_OPENAI_URL (or "openai_url") points the OpenAI text models at another host, such as Azure OpenAI. bin/voice-doctor shows what runs. Unset, each role takes the first vendor in its order whose key exists. Keys come from the environment or, on macOS, the
Keychain item named here, and reach this process only when a role in use needs them.
"""

import no_telemetry  # noqa: F401  (first: before anything loads onnxruntime)
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

import assets
import childenv
import setups

KEYS = {
    "gemini": ("GOOGLE_API_KEY", "pointe.gemini-api-key"),
    "openai": ("OPENAI_API_KEY", "pointe.openai-api-key"),
    "anthropic": ("ANTHROPIC_API_KEY", "pointe.anthropic-api-key"),
    "soniox": ("SONIOX_API_KEY", "pointe.soniox-api-key"),
    "elevenlabs": ("ELEVENLABS_API_KEY", "pointe.elevenlabs-api-key"),
}
# The names before 1.20.0. Still read, after Pointe's own, so a key saved then keeps working; never written or deleted
# here, because another tool may keep an item of the same name. Not for OpenAI with openai_url set: that key goes to a
# host the person chose, and `openai-api-key` may be another tool's key for OpenAI itself (openai_url came after 1.20.0).
LEGACY_ITEMS = {vendor: item.removeprefix("pointe.") for vendor, (_, item) in KEYS.items()}
ENV_ALIASES = {"gemini": "GEMINI_API_KEY"}  # Google documents both names
LOCAL = "local"  # needs no key: Whisper and Kokoro on this machine, and an OpenAI-compatible server for text models
LOCAL_URL = "http://localhost:11434/v1"  # Ollama; CLAUDE_VOICE_LOCAL_URL or "local_url" points it at mlx-lm, LM Studio, vLLM...
# Every Soniox real-time stream: the ears, the echo guard's mirror, meeting ears and the benches. v6 because Soniox
# removes stt-rt-v5 on 2026-12-15 (its models page); v5 against v6: docs/benchmarks.md.
SONIOX_RT_MODEL = "stt-rt-v6"
LOCAL_EARS_MODEL = "mlx-community/whisper-large-v3-turbo"  # why: bench/results/local.md; its commit: assets.HF_MODELS
LOCAL_EARS_MODEL_CT2 = "deepdml/faster-whisper-large-v3-turbo-ct2"  # the same model for faster-whisper, off Apple silicon
KEY_ENVS = {env for env, _ in KEYS.values()} | set(ENV_ALIASES.values()) | {"CLAUDE_VOICE_LOCAL_KEY"}
# Read by the vendor SDKs when a client is built (Anthropic 2.6, openai 3.42, google-genai 2.34), and each sends the key
# and session content to another host than the vendor's own API, or adds a gateway's credential to every request: the
# egress list (docs/security/egress-allowlist.txt) would not hold. A person sets them for Claude Code, not for Pointe, so
# they are taken out of this process's environment at import and handed back only to the Claude Code it starts
# (harnesses/claude_code._env). The clients below also name their host outright.
SDK_ROUTING_ENVS = ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_CUSTOM_HEADERS", "OPENAI_BASE_URL",
                    "OPENAI_CUSTOM_HEADERS", "OPENAI_ADMIN_KEY", "GOOGLE_GEMINI_BASE_URL", "GOOGLE_VERTEX_BASE_URL",
                    "GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_GENAI_USE_ENTERPRISE")
FOR_CLAUDE_CODE = {name: os.environ.pop(name) for name in SDK_ROUTING_ENVS if name in os.environ}
ANTHROPIC_URL = "https://api.anthropic.com"
OPENAI_URL = "https://api.openai.com/v1"
GEMINI_URL = "https://generativelanguage.googleapis.com/"
# Keys read from the Keychain, in this process's memory only: never in os.environ, so nothing it starts inherits one.
# vendor -> (the item it came from, the key)
_found: dict[str, tuple[str, str]] = {}
# First available wins. The order is the result of bench/results; see README, "Benchmarks".
BRAIN_ORDER = ["anthropic:claude-sonnet-5-5", "gemini:gemini-3.8-flash", "openai:gpt-6-sol"]
BRAIN_FALLBACK = {"gemini:gemini-3.8-flash": "gemini:gemini-3.6-flash", "anthropic:claude-sonnet-5-5": "anthropic:claude-haiku-5-5",
                  "openai:gpt-6-sol": "openai:gpt-6.1-terra"}
READER_ORDER = ["anthropic:claude-sonnet-5-5", "gemini:gemini-3.8-flash", "openai:gpt-6-sol"]
CHECKER_ORDER = ["gemini:gemini-3.5-flash-lite", "anthropic:claude-haiku-5-5", "openai:gpt-5.6-luna"]
EARS_ORDER = ["soniox", "gemini", "openai", "elevenlabs"]
MOUTH_ORDER = ["elevenlabs:eleven_v4_turbo", "gemini:gemini-3.8-flash-lite-tts", "soniox:tts-rt-v2", "openai:gpt-4o-mini-tts"]


def local_only() -> bool:
    """Fully local mode (`pointe local`): no key is read, so no role, mirror or meeting can reach a vendor."""
    return os.environ.get("CLAUDE_VOICE_LOCAL_ONLY", "").lower() in ("1", "true") or config().get("local_only") is True


VOICE_LOCAL = "Voice stays on your Mac"  # the setup's name, as /pointe:setup and the doctor show it
LOCAL_MOUTH = "local:kokoro-mlx:af_heart"  # why: docs/features/voice-stays-local.md
AUDIO_ONLY = ("soniox", "elevenlabs")  # vendors whose only use here is audio: their keys are not read when the voice stays local


class CloudAudioRefused(RuntimeError):
    """Audio was about to go to a vendor while the voice stays on this Mac."""


def voice_local() -> bool:
    """Ears, mouth and every other audio path on this Mac; text models may still be in the cloud (`pointe local voice`).
    Fully local mode is this too."""
    return (os.environ.get("CLAUDE_VOICE_VOICE_LOCAL", "").lower() in ("1", "true") or config().get("voice_local") is True
            or local_only())


def refuse_cloud_audio(what: str) -> None:
    """The one check every path that would stream audio to a vendor passes first: the call, the mirror, meeting ears."""
    if voice_local():
        raise CloudAudioRefused(f"{VOICE_LOCAL}: {what} would send audio to a vendor, so it is off")


def key(vendor: str) -> str | None:
    if local_only() or (vendor in AUDIO_ONLY and voice_local()):
        return None
    return _stored(vendor)


def saved(vendor: str) -> bool:
    """Whether the key is in the environment or the Keychain, whatever the setup in use reads: a switch away from Fully
    local, which reads none, still finds the Anthropic key saved before."""
    return _stored(vendor, keep=False) is not None


def _stored(vendor: str, keep: bool = True) -> str | None:
    env, item = KEYS[vendor]
    value = os.environ.get(env) or os.environ.get(ENV_ALIASES.get(vendor, ""))
    if value:
        return value
    names = (item,) if vendor == "openai" and openai_url() else (item, LEGACY_ITEMS[vendor])
    if _found.get(vendor, ("",))[0] in names:
        return _found[vendor][1]
    for name in names:
        try:
            got = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", name, "-w"], capture_output=True,
                                 text=True, timeout=5, env=childenv.child_env())
        except (OSError, subprocess.TimeoutExpired):
            return None
        if not got.returncode and got.stdout.strip():
            if not keep:
                return got.stdout.strip()
            _found[vendor] = (name, got.stdout.strip())
            return _found[vendor][1]
    return None


def known_keys() -> list[str]:
    """Every key value this process holds, from its environment or the Keychain: what a log line or a mask must hide."""
    return [v for v in [*(os.environ.get(env, "") for env in KEY_ENVS), *(v for _, v in _found.values())] if v]


_clients: dict[str, object] = {}


def _gemini():
    # Kept alive: a client that is garbage collected during a call closes the connection under it.
    from google import genai

    from google.genai import types

    # One attempt: the library's own retries turned an out-of-quota 429 into a silent wait past every timeout, so the
    # vendor fallback never saw it. A refusal now surfaces at once and the next vendor answers.
    return _clients.setdefault("gemini", genai.Client(api_key=key("gemini"), vertexai=False, http_options=types.HttpOptions(
        base_url=GEMINI_URL, retry_options=types.HttpRetryOptions(attempts=1))))


def _anthropic():
    import anthropic

    return _clients.setdefault("anthropic", anthropic.AsyncAnthropic(api_key=key("anthropic"), base_url=ANTHROPIC_URL))


def openai_url() -> str | None:
    """Another host for the OpenAI text models (Azure OpenAI, or any server that speaks OpenAI's API):
    CLAUDE_VOICE_OPENAI_URL or "openai_url". The OpenAI key then belongs to that host. docs/features/openai-url.md"""
    url = os.environ.get("CLAUDE_VOICE_OPENAI_URL") or config().get("openai_url")
    if not url:
        return None
    if not str(url).startswith("https://"):
        raise SystemExit(f"openai_url={url}: it must start with https://, because the OpenAI key is sent there")
    return str(url)


def refuse_openai_audio(what: str) -> None:
    """With openai_url set, the OpenAI key is another host's: OpenAI's own audio services would send it to OpenAI."""
    if openai_url():
        raise SystemExit(f"{what}: openai_url is set, so the OpenAI key runs text models only "
                         "(brain, reader, checker). Choose another vendor for ears and mouth.")


def _openai():
    from openai import AsyncOpenAI

    return _clients.setdefault("openai", AsyncOpenAI(api_key=key("openai"), base_url=openai_url() or OPENAI_URL))


def warm(choices: list[str]) -> None:
    """Load each vendor's library and build its client before the first call: done lazily, mid-call, the imports and the
    client setup froze the daemon for up to two seconds right after the user spoke. Run it in a thread."""
    build = {"gemini": _gemini, "anthropic": _anthropic, "openai": _openai}
    for vendor in {c.split(":")[0] for c in choices if c}:
        try:
            if vendor in build and has(vendor):
                build[vendor]()
                if vendor == "gemini":  # its request types build their schemas on first use
                    from google.genai import types

                    types.GenerateContentConfig(temperature=0.0, system_instruction="x")
        except Exception as e:
            logger.info(f"warming {vendor} skipped: {type(e).__name__}")


_local_refused: str | None = None  # why Pointe's own text-model port is not to be used now (local.recheck), else None


def _local():
    from openai import AsyncOpenAI

    if _local_refused:
        raise ConnectionError(_local_refused)

    url = os.environ.get("CLAUDE_VOICE_LOCAL_URL") or config().get("local_url") or LOCAL_URL
    return _clients.setdefault(LOCAL, AsyncOpenAI(base_url=url,
                                                  api_key=os.environ.get("CLAUDE_VOICE_LOCAL_KEY", "none")))


def has(vendor: str) -> bool:
    return vendor == LOCAL or key(vendor) is not None


def config() -> dict:
    """~/.claude-voice/config.json, for a choice that should outlast a shell: {"brain": "openai:gpt-6-sol", "mouth": ...}."""
    path = Path(os.environ.get("CLAUDE_VOICE_STATE", Path.home() / ".claude-voice")) / "config.json"
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as e:
        raise SystemExit(f"{path} cannot be read: {e}") from e


def pick(env: str, order: list[str]) -> str:
    """The environment wins, then config.json, then the first vendor in the order that has a key."""
    wanted = os.environ.get(env) or config().get(env.removeprefix("CLAUDE_VOICE_").lower())
    if env in ("CLAUDE_VOICE_EARS", "CLAUDE_VOICE_MOUTH") and voice_local():
        if wanted and wanted != "auto" and wanted.split(":")[0] != LOCAL:
            raise SystemExit(f"{env}={wanted}: {VOICE_LOCAL} is on, so ears and mouth run only on this Mac. "
                             "Turn it off with: pointe local off")
        if not wanted or wanted == "auto":
            return LOCAL if env == "CLAUDE_VOICE_EARS" else LOCAL_MOUTH
    if env in ("CLAUDE_VOICE_EARS", "CLAUDE_VOICE_MOUTH") and openai_url():
        if wanted and wanted.split(":")[0] == "openai":
            refuse_openai_audio(f"{env}={wanted}")
        order = [c for c in order if c.split(":")[0] != "openai"]
    if wanted and wanted != "auto":
        if wanted.split(":")[0] not in {*KEYS, LOCAL}:
            raise SystemExit(f"{env}={wanted}: unknown vendor. Choose from: {', '.join([*KEYS, LOCAL])}")
        if local_only() and wanted.split(":")[0] != LOCAL:
            raise SystemExit(f"{env}={wanted}: fully local mode is on, so only local models run. "
                             "Turn it off with: pointe local off")
        if not has(wanted.split(":")[0]):
            raise SystemExit(f"{env}={wanted} needs a key: {missing_key_help(wanted.split(':')[0])}")
        return wanted
    chosen = setups.chosen(config())
    if chosen is not None and chosen.local != "all":
        allowed = {*chosen.keys, *chosen.optional}
        order = [c for c in order if c.split(":")[0] in allowed]
        for choice in order:
            if has(choice.split(":")[0]):
                return choice
        need = next(c.split(":")[0] for c in order if c.split(":")[0] in chosen.keys)
        raise SystemExit(f"{env}: the setup {chosen.name} needs its {NAMES[need]} key: {missing_key_help(need)}. "
                         "Another setup: pointe setup")
    for choice in order:
        if has(choice.split(":")[0]):
            return choice
    raise SystemExit(f"{env}: no key found for any of {order}. {missing_key_help(order[0].split(':')[0])}")


def missing_key_help(vendor: str) -> str:
    env, item = KEYS[vendor]
    return f"save one with pointe key {vendor} (it goes to the Keychain item {item}), or set {env}"


@dataclass
class Setup:
    brain: str = ""
    reader: str = ""
    checker: str = ""
    ears: str = ""
    mouth: str = ""
    notes: list[str] = field(default_factory=list)


def resolve(front: str = "brain") -> Setup:
    """What will run, given the keys that exist. Fails at start, with the command to fix it, rather than mid-call."""
    if front != "brain" and voice_local():
        raise SystemExit(f"CLAUDE_VOICE_FRONT={front}: a realtime model hears the audio itself, and {VOICE_LOCAL} is on. "
                         "Unset CLAUDE_VOICE_FRONT, or turn the setup off with: pointe local off")
    s = Setup(reader=pick("CLAUDE_VOICE_READER", READER_ORDER), checker=pick("CLAUDE_VOICE_CHECKER", CHECKER_ORDER))
    if front == "brain":
        s.brain = pick("CLAUDE_VOICE_BRAIN", BRAIN_ORDER)
        s.mouth = pick("CLAUDE_VOICE_MOUTH", MOUTH_ORDER)
    s.ears = pick("CLAUDE_VOICE_EARS", EARS_ORDER)
    if s.ears != "soniox":
        s.notes.append("Use headphones: on speakers Pointe can hear itself.")  # no Soniox, so no echo guard (docs/benchmarks.md)
    if voice_local() and not local_only():
        s.notes.append(f"{VOICE_LOCAL}: ears and mouth run on this Mac; the text models get text only.")
    return s


# ---------- which keys a person needs: the one answer /pointe:setup, the doctor, the docs, the page and the Mac app give ----------

ROLE_ORDERS = {"brain": BRAIN_ORDER, "reader": READER_ORDER, "checker": CHECKER_ORDER, "ears": EARS_ORDER, "mouth": MOUTH_ORDER}
# Each of these alone fills every role (tests/test_key_setup.py resolves each). Costs: docs/benchmarks.md, "Other setups".
START_KEYS = (("gemini",), ("openai",), ("soniox", "anthropic"))
WHAT_YOU_NEED = ("Any one of these is enough to start: (a) one Gemini key (free tier; about $0.70 to $0.95 a busy hour "
                 "with billing on), (b) one OpenAI key (about $0.95 a busy hour), (c) Soniox + Anthropic API keys (about "
                 "$1.20). Fastest and most accurate voice: Anthropic + Soniox + ElevenLabs (+ Gemini for the checker), "
                 "about $1 a busy hour.")
# Pointe calls the vendors' APIs with its own key: a Claude.ai login is not one (key() reads ANTHROPIC_API_KEY only).
WHY_KEYS = setups.WHY_KEYS
# The one key to suggest when a role is empty and no setup is chosen: the ears' measured lead first (docs/benchmarks.md).
FIX_ORDER = ("soniox", "anthropic", "elevenlabs", "gemini", "openai")
NAMES = {"gemini": "Gemini", "openai": "OpenAI", "anthropic": "Anthropic", "soniox": "Soniox", "elevenlabs": "ElevenLabs"}
ROLE_WORDS = {"brain": "think", "reader": "read your sessions", "checker": "check each send", "ears": "hear you",
              "mouth": "speak"}


def filled(present: set[str], voice_on_mac: bool = False, setup: "setups.Setup | None" = None) -> dict[str, str | None]:
    """Each role's vendor with only these keys and no role chosen by hand, None where no key fills it. A chosen setup
    allows only its own vendors; one that runs a role on this Mac fills it with LOCAL."""
    if setup is not None:
        present = present & {*setup.keys, *setup.optional}
        voice_on_mac = voice_on_mac or bool(setup.local)
    roles = {}
    for role, order in ROLE_ORDERS.items():
        if (voice_on_mac and role in ("ears", "mouth")) or (setup is not None and setup.local == "all"):
            roles[role] = LOCAL
        else:
            roles[role] = next((c.split(":")[0] for c in order if c.split(":")[0] in present), None)
    return roles


def _words(items: list[str], last: str = "or") -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + f" {last} " + items[-1]


def _a(name: str) -> str:
    return f"{'an' if name[0] in 'AEIOU' else 'a'} {name}"


def key_status(present: set[str], voice_on_mac: bool = False, setup: "setups.Setup | None" = None) -> dict:
    """What each key does here, and the one problem worth saying. With a setup chosen, a key it uses and that is not
    there is "needed", and every other key "optional". With none, an empty role names the single key that fills it.
    A key no role needs is "optional", never "missing"."""
    roles = filled(present, voice_on_mac, setup)
    empty = [r for r, v in roles.items() if v is None]
    if setup is not None:
        needed = [v for v in setup.keys if v not in present]
    elif empty:
        needed = ["gemini"] if not present else [next(v for v in FIX_ORDER if None not in filled(present | {v}, voice_on_mac).values())]
    else:
        needed = []
    uses = {v: [r for r, x in roles.items() if x == v] for v in KEYS}
    keys = {v: "not read" if voice_on_mac and v in AUDIO_ONLY else ("in use" if uses[v] else "not used") if v in present
            else "needed" if v in needed else "optional" for v in KEYS}  # "not read": nothing to add, the doctor's words
    head = f"Setup: {setup.name}. " if setup is not None else ""
    if setup is not None and needed:
        line = head + f"It needs {_words([_a(NAMES[v]) for v in needed], 'and')} key: pointe key {needed[0]}."
    elif not empty and not needed:
        line = head + "Every role is filled." + (" The other keys are optional: not needed with your current keys."
                                                 if "optional" in keys.values() else "")
    elif not present:
        line = f"No model key yet. {WHAT_YOU_NEED}"
    else:
        line = f"Pointe cannot {_words([ROLE_WORDS[r] for r in empty])} yet: add {_a(NAMES[needed[0]])} key."
    return {"roles": roles, "empty": empty, "fix": needed[0] if needed else None, "needed": needed, "keys": keys,
            "uses": uses, "line": line}


# ---------- text models: one call shape for the gates and the reader ----------

_EXHAUSTED: dict[str, float] = {}  # vendor -> when it last refused for quota or rate: skipped for a while
EXHAUSTED_SECS = 600


def _out_of_quota(error: Exception) -> bool:
    text = f"{type(error).__name__} {error}".lower()
    return any(sign in text for sign in ("429", "resource_exhausted", "rate_limit", "ratelimit", "quota", "insufficient_quota"))


# What each vendor says to a wrong, revoked or unpaid key (captured with made-up keys), and our own sentence for it.
_REFUSED = ("api key not valid", "invalid api key", "invalid_api_key", "incorrect api key", "invalid x-api-key",
            "invalid bearer token", "authentication_error", "key was refused")
_VENDOR_NAMES = {"gemini": "gemini", "google": "gemini", "anthropic": "anthropic", "openai": "openai", "soniox": "soniox",
                 "elevenlabs": "elevenlabs"}


def refused_key(text: str) -> str | None:
    """The vendor an error says refused its key: "" when the text does not name one, None when it is not a refused key.
    The first vendor named wins: a pipeline error starts with its service (GeminiSTTService#1 ...)."""
    low = text.lower()
    if not any(sign in low for sign in _REFUSED):
        return None
    return _named(low)


_QUOTA = ("resource_exhausted", "quota", "insufficient_quota", "billing", "credit balance")
_RATE = ("429", "rate_limit", "ratelimit", "rate limit", "too many requests")
_DOWN = re.compile(r"\b50[0234]\b|internal server error|internal error|service unavailable|bad gateway|overloaded|servererror")


def _named(low: str) -> str:
    named = [(low.find(name), vendor) for name, vendor in _VENDOR_NAMES.items() if name in low]
    return min(named)[1] if named else ""


def fault(error) -> tuple[str, str] | None:
    """A vendor failing in a way a retry of the same words will not fix: ("quota" | "rate" | "down", the vendor named in
    the error or ""). None for anything else (a refused key is refused_key's; a timeout or a dropped link is not this)."""
    text = f"{type(error).__name__} {error}" if isinstance(error, BaseException) else str(error)
    low = text.lower()
    if any(sign in low for sign in _QUOTA):
        kind = "quota"
    elif any(sign in low for sign in _RATE):
        kind = "rate"
    elif _DOWN.search(low):
        kind = "down"
    else:
        return None
    return kind, _named(low)


def fault_help(kind: str, vendor: str) -> str:
    """The page's line for a vendor fault: what happened and what to do, in words, never the library's text."""
    name = NAMES.get(vendor, "The model")
    return {"quota": f"{name}'s quota for this key is used up: turn on billing for the key, or wait until the quota "
                     f"resets. Check it with pointe key check {vendor or '<vendor>'}.",
            "rate": f"{name} is limiting how often this key may call it: wait a minute, then talk again.",
            "down": f"{name} is not answering (an error on its side). Talk again in a minute."}[kind]


def fault_spoken(kind: str, vendor: str, default: str = "") -> str:
    name = NAMES.get(vendor or default, "the model")
    return {"quota": f"My {name} quota is used up. Turn on billing for the key, or wait for it to reset.",
            "rate": f"{name} is limiting my key for a moment. Try again in a minute.",
            "down": f"{name} is not answering right now. Try again in a minute."}[kind]


def refused_help(vendor: str) -> str:
    return (f"The {vendor or 'model'} key was refused: it is wrong, revoked or out of credit. Save the right one with "
            f"pointe key {vendor or '<vendor>'}, or run /pointe:setup again.")


def refused_spoken(vendor: str, hebrew: bool = False) -> str:
    """The refused key, short enough to say aloud."""
    if hebrew:
        return f"המפתח של {vendor} נדחה. בדוק אותו עם pointe key {vendor}."
    return f"My {vendor} key was refused. Check it with pointe key {vendor}."


def _say_if_refused(vendor: str, error: Exception) -> None:
    if refused_key(f"{type(error).__name__} {error}") is not None:
        logger.error(refused_help(vendor))  # callers log only the error's type: this says which key, for the page


def _stand_in(choice: str) -> str | None:
    """The next model in the same role's order whose vendor has a key and has not just run out."""
    for order in (CHECKER_ORDER, READER_ORDER, BRAIN_ORDER):
        if choice in order:
            for other in order[order.index(choice) + 1:] + order[:order.index(choice)]:
                vendor = other.split(":")[0]
                if vendor != choice.split(":")[0] and has(vendor) and time.time() - _EXHAUSTED.get(vendor, 0) > EXHAUSTED_SECS:
                    return other
    return None


async def text(choice: str, prompt: str, system: str | None = None, json_reply: bool = False, thinking: str | None = None,
               max_tokens: int | None = None, temperature: float = 0.0) -> str:
    """One completion. `thinking` is low, medium or high, or None for the model's default. A vendor that refuses for quota
    or rate limits is skipped for ten minutes, and the next one in the role's order with a key answers instead."""
    vendor, model = choice.split(":", 1)
    if time.time() - _EXHAUSTED.get(vendor, 0) < EXHAUSTED_SECS and (other := _stand_in(choice)):
        vendor, model = other.split(":", 1)
    try:
        return await _TEXT[vendor](model, prompt, system, json_reply, thinking, max_tokens, temperature)
    except Exception as error:
        _say_if_refused(vendor, error)
        if not _out_of_quota(error):
            raise
        _EXHAUSTED[vendor] = time.time()
        other = _stand_in(f"{vendor}:{model}")
        if other is None:
            raise
        logger.warning(f"{vendor} is out of quota or rate limited; {other} answers for ten minutes")
        o_vendor, o_model = other.split(":", 1)
        return await _TEXT[o_vendor](o_model, prompt, system, json_reply, thinking, max_tokens, temperature)


async def _gemini_text(model, prompt, system, json_reply, thinking, max_tokens, temperature) -> str:
    from google.genai import types

    resp = await _gemini().aio.models.generate_content(
        model=model, contents=prompt,
        config=types.GenerateContentConfig(
            temperature=temperature, system_instruction=system, max_output_tokens=max_tokens,
            response_mime_type="application/json" if json_reply else None,
            thinking_config=types.ThinkingConfig(thinking_level=thinking) if thinking else None))
    return resp.text or ""


async def _anthropic_text(model, prompt, system, json_reply, thinking, max_tokens, temperature) -> str:
    import anthropic

    system = (system or "") + ("\nReply with JSON only." if json_reply else "")
    extra = {"output_config": {"effort": thinking}} if thinking else {}
    resp = await _anthropic().messages.create(model=model, max_tokens=max(max_tokens or 0, 8000), system=system or anthropic.NOT_GIVEN,
                                        messages=[{"role": "user", "content": prompt}], **extra)
    return "".join(b.text for b in resp.content if b.type == "text")


async def _openai_text(model, prompt, system, json_reply, thinking, max_tokens, temperature) -> str:
    # OpenAI refuses json_object unless the messages contain the word "json".
    system = ((system or "") + ("\nReply with JSON only." if json_reply else "")).strip()
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    extra = {"response_format": {"type": "json_object"}} if json_reply else {}
    if thinking:
        extra["reasoning_effort"] = thinking
    resp = await _openai().chat.completions.create(model=model, messages=messages, **extra)
    return resp.choices[0].message.content or ""


async def _local_text(model, prompt, system, json_reply, thinking, max_tokens, temperature) -> str:
    system = ((system or "") + ("\nReply with JSON only." if json_reply else "")).strip()
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    extra = {"max_tokens": max_tokens} if max_tokens else {}
    resp = await _local().chat.completions.create(model=model, messages=messages, temperature=temperature, reasoning_effort="low",
                                                  **extra)
    return resp.choices[0].message.content or ""


_TEXT = {"gemini": _gemini_text, "anthropic": _anthropic_text, "openai": _openai_text, LOCAL: _local_text}


# ---------- the brain's one model step ----------

@dataclass
class Step:
    calls: list[dict]  # {"id", "name", "args"}
    raw: object = None  # the vendor's own message, replayed as it came (thought signatures, thinking blocks)
    said: str = ""  # plain text, where a vendor answers without a tool
    usage: dict = field(default_factory=dict)
    vendor: str = ""  # whose raw message this is: only that vendor gets it replayed


def _schema(tool: dict) -> dict:
    return {"type": "object", "properties": tool["properties"], "required": tool["required"]}


async def _gemini_step(model: str, system: str, messages: list[dict], tools: list[dict]) -> Step:
    from google.genai import types

    contents = []
    for m in messages:
        if m["role"] == "user":
            contents.append(types.Content(role="user", parts=[types.Part(text=m["content"])]))
        elif m["role"] == "assistant":
            contents.append(m.get("raw") or types.Content(role="model", parts=[
                types.Part(function_call=types.FunctionCall(id=c["id"], name=c["name"], args=c["args"])) for c in m["calls"]]
                or [types.Part(text=m.get("said") or "")]))
        else:
            contents.append(types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
                id=r["id"], name=r["name"], response={"result": r["result"]})) for r in m["results"]]))
    config = types.GenerateContentConfig(
        system_instruction=system, temperature=0.3,
        tools=[types.Tool(function_declarations=[types.FunctionDeclaration(
            name=t["name"], description=t["description"], parameters_json_schema=_schema(t)) for t in tools])],
        tool_config=types.ToolConfig(function_calling_config=types.FunctionCallingConfig(mode="ANY")),  # no text: reasoning has nowhere to leak
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        thinking_config=types.ThinkingConfig(thinking_level=os.environ.get("CLAUDE_VOICE_BRAIN_THINKING", "low")))
    resp = await _gemini().aio.models.generate_content(model=model, contents=contents, config=config)
    content = resp.candidates[0].content if resp.candidates else None
    calls = [{"id": p.function_call.id or f"c{i}", "name": p.function_call.name, "args": dict(p.function_call.args or {})}
             for i, p in enumerate((content.parts or []) if content else []) if p.function_call]
    u = resp.usage_metadata
    return Step(calls, content, usage={"context": getattr(u, "prompt_token_count", 0) or 0,
                                       "reply": getattr(u, "candidates_token_count", 0) or 0})


_TEXT_VALUE = re.compile(r'"text"\s*:\s*"')


def partial_text(fragment: str) -> str:
    """The words of a speak call whose JSON is still being written ('{"text": "Use the first o'): the value of "text"
    as far as it has come. An escape cut in half at the end waits for its other half."""
    opened = _TEXT_VALUE.search(fragment)
    if not opened:
        return ""
    body, i, end = fragment[opened.end():], 0, 0
    while i < len(body) and body[i] != '"':
        step = 1 if body[i] != "\\" else 6 if body[i + 1:i + 2] == "u" else 2
        if i + step > len(body):
            break
        i += step
        end = i
    try:
        said = json.loads(f'"{body[:end]}"', strict=False)
    except ValueError:
        return ""
    return said[:-1] if said and "\ud800" <= said[-1] <= "\udbff" else said  # half of a pair (an emoji as two escapes)


async def _anthropic_stream(request: dict, heard) -> object:
    """The same request, read as it is written. `heard` is told the words of the reply so far each time they grow, when
    the reply is a speak call and the first thing the model writes: text before a speak call is not spoken, and a tool
    called first may change what is true by the time the words are said. It is also told once, with nothing, when the
    first piece of anything arrives. The speak tool's input streams as it is written (eager_input_streaming), so the
    API does not check it: the caller reads `text` as a string or as nothing."""
    request = {**request, "tools": [{**t, "eager_input_streaming": True} if t["name"] == "speak" else t
                                    for t in request["tools"]]}
    reply, written, said = None, "", ""  # the index of the block that is the reply; None until the first block that says
    async with _anthropic().messages.stream(**request) as stream:
        async for event in stream:
            if event.type == "content_block_start":
                block = event.content_block
                if reply is None and block.type not in ("thinking", "redacted_thinking"):
                    reply = event.index if block.type == "tool_use" and block.name == "speak" else -1
                    if reply < 0:
                        logger.info(f"reply not read as it is written: {getattr(block, 'name', None) or block.type} came first")
                heard(said)
            elif event.type == "content_block_delta" and event.index == reply and event.delta.type == "input_json_delta":
                written += event.delta.partial_json
                now = partial_text(written)
                if now != said:
                    said = now
                    heard(said)
        return await stream.get_final_message()


async def _anthropic_step(model: str, system: str, messages: list[dict], tools: list[dict], heard=None) -> Step:
    converted = []
    for m in messages:
        if m["role"] == "user":
            converted.append({"role": "user", "content": m["content"]})
        elif m["role"] == "assistant":
            converted.append({"role": "assistant", "content": m.get("raw") or m.get("said") or [
                {"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["args"]} for c in m["calls"]]})
        else:
            converted.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": r["id"], "content": json.dumps(r["result"], ensure_ascii=False)}
                for r in m["results"]]})
    # Forced tool choice is refused on the newest models: `speak` is required by the prompt, and text counts as speech.
    # Two cache points: the marker on the system block keeps tools and prompt cached whatever the history does; the
    # top-level marker is the automatic one, placed by the API on the last block, so each step reads the steps before it.
    request = dict(
        model=model, max_tokens=4000, system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        tools=[{"name": t["name"], "description": t["description"], "input_schema": _schema(t)} for t in tools],
        messages=converted, output_config={"effort": os.environ.get("CLAUDE_VOICE_BRAIN_THINKING", "low")},
        cache_control={"type": "ephemeral"})
    resp = await (_anthropic().messages.create(**request) if heard is None else _anthropic_stream(request, heard))
    calls = [{"id": b.id, "name": b.name, "args": dict(b.input) if isinstance(b.input, dict) else {}}
             for b in resp.content if b.type == "tool_use"]
    said = "".join(b.text for b in resp.content if b.type == "text").strip()
    u = resp.usage
    read, written = u.cache_read_input_tokens or 0, u.cache_creation_input_tokens or 0
    # input_tokens is the uncached remainder only: the whole prompt is the sum of the three
    return Step(calls, resp.content, said, {"context": u.input_tokens + read + written, "cached": read, "reply": u.output_tokens})


async def _openai_step(model: str, system: str, messages: list[dict], tools: list[dict]) -> Step:
    # The Responses API: current models refuse function tools with reasoning on chat completions. store=False keeps session
    # content out of OpenAI's stored responses, so reasoning has to travel with the request, encrypted.
    items: list[dict] = []
    for m in messages:
        if m["role"] == "user":
            items.append({"role": "user", "content": m["content"]})
        elif m["role"] == "assistant":
            if m.get("raw"):
                items += m["raw"]
            elif m["calls"]:
                items += [{"type": "function_call", "call_id": c["id"], "name": c["name"], "arguments": json.dumps(c["args"])}
                          for c in m["calls"]]
            else:
                items.append({"role": "assistant", "content": m.get("said", "")})
        else:
            items += [{"type": "function_call_output", "call_id": r["id"], "output": json.dumps(r["result"], ensure_ascii=False)}
                      for r in m["results"]]
    resp = await _openai().responses.create(
        model=model, instructions=system, input=items, tool_choice="required", store=False,
        include=["reasoning.encrypted_content"], reasoning={"effort": os.environ.get("CLAUDE_VOICE_BRAIN_THINKING", "low")},
        tools=[{"type": "function", "name": t["name"], "description": t["description"], "parameters": _schema(t), "strict": False}
               for t in tools])
    calls = [{"id": o.call_id, "name": o.name, "args": json.loads(o.arguments or "{}")}
             for o in resp.output if o.type == "function_call"]
    return Step(calls, [o.model_dump(exclude_none=True) for o in resp.output], resp.output_text or "",
                {"context": resp.usage.input_tokens, "reply": resp.usage.output_tokens})


async def _local_step(model: str, system: str, messages: list[dict], tools: list[dict]) -> Step:
    # Chat completions: what every OpenAI-compatible server speaks. A server that ignores tool_choice answers in text, which counts as speech.
    converted: list[dict] = [{"role": "system", "content": system}]
    for m in messages:
        if m["role"] == "user":
            converted.append({"role": "user", "content": m["content"]})
        elif m["role"] == "assistant":
            calls = [{"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": json.dumps(c["args"])}}
                     for c in m["calls"]]
            converted.append({"role": "assistant", "content": m.get("said", ""), **({"tool_calls": calls} if calls else {})})
        else:
            converted += [{"role": "tool", "tool_call_id": r["id"], "content": json.dumps(r["result"], ensure_ascii=False)}
                          for r in m["results"]]
    resp = await _local().chat.completions.create(
        model=model, messages=converted, tool_choice="required", temperature=0.3,
        reasoning_effort=os.environ.get("CLAUDE_VOICE_BRAIN_THINKING", "low"),
        tools=[{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": _schema(t)}}
               for t in tools])
    message = resp.choices[0].message
    calls = [{"id": c.id or f"c{i}", "name": c.function.name, "args": json.loads(c.function.arguments or "{}")}
             for i, c in enumerate(message.tool_calls or [])]
    u = resp.usage
    return Step(calls, None, (message.content or "").strip(), {"context": u.prompt_tokens if u else 0, "reply": u.completion_tokens if u else 0})


_STEP = {"gemini": _gemini_step, "anthropic": _anthropic_step, "openai": _openai_step, LOCAL: _local_step}
STREAMS = {"anthropic"}  # vendors whose step can be read as it is written (`heard`); the others answer whole


def _as_text_where_foreign(messages: list[dict], vendor: str) -> list[dict]:
    """Turns another vendor took become plain text: its tool calls need that vendor's own signatures (Gemini refuses a
    call without its thought_signature), so they are told, not replayed."""
    out, foreign = [], set()
    for m in messages:
        if m["role"] == "assistant" and m.get("vendor", vendor) != vendor:
            calls = "; ".join(f"{c['name']}({json.dumps(c['args'], ensure_ascii=False)})" for c in m["calls"])
            said = " ".join(filter(None, [m.get("said") or "", f"[I called: {calls}]" if calls else ""]))
            out.append({"role": "assistant", "calls": [], "said": said or "[no reply]", "raw": None})
            foreign |= {c["id"] for c in m["calls"]}
        elif m["role"] == "tool" and all(r["id"] in foreign for r in m["results"]):
            results = "; ".join(f"{r['name']}: {json.dumps(r['result'], ensure_ascii=False)}" for r in m["results"])
            out.append({"role": "user", "content": f"[results of those calls] {results}"})
        else:
            out.append(m)
    return out


async def step(choice: str, system: str, messages: list[dict], tools: list[dict], heard=None) -> Step:
    """One model step. `heard(text)`, when given and the vendor streams, is called as the reply's speak call is written
    (see _anthropic_stream); the step returned is the same either way."""
    vendor, model = choice.split(":", 1)
    # After a handover (quota), earlier turns came from another vendor: their raw form means nothing here, so they go
    # in the neutral form, as calls and text.
    try:
        more = {"heard": heard} if heard is not None and vendor in STREAMS else {}
        result = await _STEP[vendor](model, system, _as_text_where_foreign(messages, vendor), tools, **more)
    except Exception as error:
        _say_if_refused(vendor, error)
        raise
    result.vendor = vendor
    return result


# ---------- ears and mouth ----------

DEFAULT_ELEVENLABS_VOICE = "cjVigY5qzO86Huf0OWal"  # Eric
DEFAULT_GEMINI_VOICE = "Charon"


GEMINI_PHRASES = 100  # adaptation phrases sent to Gemini's ears: the session names and the dictionary come first


def build_ears(vendor: str, terms: list[str]):
    """A speech-to-text service in the pipeline. Soniox and Gemini take the vocabulary hints (session names, the user's
    dictionary): without them Free start heard "docs" as "Dox" and "shop" as "Sharp" (QA round 2)."""
    from pipecat.transcriptions.language import Language

    if vendor != LOCAL and voice_local():
        raise SystemExit(f"CLAUDE_VOICE_EARS={vendor}: {VOICE_LOCAL} is on, so the ears run only on this Mac")

    if vendor == "soniox":
        from pipecat.services.soniox.stt import SonioxContextObject, SonioxSTTService

        return SonioxSTTService(
            api_key=key("soniox"),
            should_interrupt=False,  # SonioxEars decides barge-in, by words
            vad_force_turn_endpoint=False,  # Soniox endpointing: 0.31 s p50 in the benchmark
            settings=SonioxSTTService.Settings(model=SONIOX_RT_MODEL,  # pipecat's own default is stt-rt-v5
                                               language_hints=[Language.EN, Language.HE],
                                               endpoint_sensitivity=float(os.environ.get("CLAUDE_VOICE_ENDPOINT", "-0.5")),
                                               max_endpoint_delay_ms=2500,  # patient: a pause to think ends no turn
                                               context=SonioxContextObject(terms=terms)))
    if vendor == "gemini":
        from pipecat.services.google.gemini_live.stt import GeminiSTTService

        return GeminiSTTService(api_key=key("gemini"),
                                settings=GeminiSTTService.Settings(adaptation_phrases=list(terms)[:GEMINI_PHRASES] or None))
    if vendor == "openai":
        refuse_openai_audio("CLAUDE_VOICE_EARS=openai")
        from pipecat.services.openai.stt import OpenAIRealtimeSTTService

        return OpenAIRealtimeSTTService(api_key=key("openai"))
    if vendor == "elevenlabs":
        from pipecat.services.elevenlabs.stt import ElevenLabsRealtimeSTTService

        return ElevenLabsRealtimeSTTService(api_key=key("elevenlabs"))
    if vendor == LOCAL:
        return _local_ears()
    raise SystemExit(f"CLAUDE_VOICE_EARS: unknown vendor {vendor}")


def _local_ears():
    """Whisper on this machine: MLX on Apple silicon, faster-whisper elsewhere. Needs: uv sync --extra local (bin/voice-daemon does it)."""
    import platform

    if platform.system() == "Darwin" and platform.machine() == "arm64":
        return _mlx_ears()
    from pipecat.services.whisper.stt import WhisperSTTService

    # A folder, not a repository name: faster-whisper would otherwise read the repository at `main`.
    return WhisperSTTService(settings=WhisperSTTService.Settings(model=assets.snapshot(LOCAL_EARS_MODEL_CT2), language=None))


def whisper_text(result: dict) -> str:
    """The words of an mlx-whisper result, without the segments Whisper likely made up: pipecat's MLX filters."""
    return " ".join(s.get("text", "").strip() for s in result.get("segments", [])
                    if s.get("compression_ratio") != 0.5555555555555556 and s.get("no_speech_prob", 0.0) < 0.6).strip()


def _mlx_ears():
    """pipecat's WhisperSTTServiceMLX, without its module, which imports faster-whisper first: the local extra installs
    only mlx-whisper on Apple silicon. Language is detected per utterance."""
    import asyncio

    import numpy as np
    from pipecat.frames.frames import ErrorFrame, TranscriptionFrame
    from pipecat.services.settings import STTSettings
    from pipecat.services.stt_service import SegmentedSTTService
    from pipecat.utils.time import time_now_iso8601

    try:  # a path, not a repo name: mlx-whisper asks the Hugging Face Hub about a repo name once per daemon
        path = assets.snapshot(LOCAL_EARS_MODEL, local_files_only=True)
    except Exception:
        path = None  # not downloaded yet: fetched at the pinned commit on the first utterance, as mlx-whisper would at `main`

    class MLXWhisperEars(SegmentedSTTService):
        model_path = path

        async def run_stt(self, audio: bytes):
            import mlx_whisper

            samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
            await self.start_processing_metrics()
            try:
                if self.model_path is None:
                    self.model_path = await asyncio.to_thread(assets.snapshot, LOCAL_EARS_MODEL)
                result = await asyncio.to_thread(mlx_whisper.transcribe, samples, path_or_hf_repo=self.model_path,
                                                 temperature=0.0, language=None)
            except Exception as e:
                yield ErrorFrame(error=f"local ears: {type(e).__name__}: {e}")
                return
            await self.stop_processing_metrics()
            if text := whisper_text(result):
                yield TranscriptionFrame(text, self._user_id, time_now_iso8601(), None)

    return MLXWhisperEars(settings=STTSettings(model=LOCAL_EARS_MODEL, language=None))


def build_mouth(choice: str, rate: int, http):
    """A text-to-speech service in the pipeline, at the transport's output rate."""
    vendor, model, *rest = choice.split(":") + [""]
    voice = rest[0] if rest and rest[0] else None
    if vendor != LOCAL and voice_local():
        raise SystemExit(f"CLAUDE_VOICE_MOUTH={choice}: {VOICE_LOCAL} is on, so the mouth runs only on this Mac")
    if vendor == "elevenlabs":
        # HTTP streaming: eleven_v4_turbo, which speaks Hebrew, is refused on the WebSocket endpoint (HTTP 400).
        from pipecat.services.elevenlabs.tts import ElevenLabsHttpTTSService

        return ElevenLabsHttpTTSService(api_key=key("elevenlabs"), aiohttp_session=http, sample_rate=rate,
                                        settings=ElevenLabsHttpTTSService.Settings(voice=voice or DEFAULT_ELEVENLABS_VOICE, model=model))
    if vendor == "gemini":
        from pipecat.services.google.tts import GeminiTTSService

        return GeminiTTSService(api_key=key("gemini"), sample_rate=rate,
                                settings=GeminiTTSService.Settings(voice=voice or DEFAULT_GEMINI_VOICE, model=model))
    if vendor == "openai":
        refuse_openai_audio(f"CLAUDE_VOICE_MOUTH={choice}")
        from pipecat.services.openai.tts import OpenAITTSService

        return OpenAITTSService(api_key=key("openai"), sample_rate=rate,
                                settings=OpenAITTSService.Settings(voice=voice or "ash", model=model))
    if vendor == "soniox":
        from pipecat.services.soniox.tts import SonioxTTSService

        return SonioxTTSService(api_key=key("soniox"), sample_rate=rate)
    if vendor == LOCAL and model == "kokoro-mlx":
        import kokoro_mlx

        return kokoro_mlx.KokoroMLXTTSService(sample_rate=rate, voice=voice or kokoro_mlx.DEFAULT_VOICE)
    if vendor == LOCAL:
        from pipecat.services.kokoro.tts import KokoroTTSService

        model_file, voices_file = assets.ensure_kokoro()  # verified by hash first: Pipecat's own download has none
        return KokoroTTSService(sample_rate=rate, model_path=str(model_file), voices_path=str(voices_file),
                                settings=KokoroTTSService.Settings(voice=voice or "af_heart"))
    raise SystemExit(f"CLAUDE_VOICE_MOUTH: unknown vendor {vendor}")

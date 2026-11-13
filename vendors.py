"""Which vendor does what. Any one of several keys is enough to run; what we run ourselves comes from bench/results.

    CLAUDE_VOICE_BRAIN=vendor:model   decides what to say and which tools to call
    CLAUDE_VOICE_READER=vendor:model  reads whole sessions and reports; CLAUDE_VOICE_CHECKER=vendor:model is the fast gate
    CLAUDE_VOICE_EARS=vendor          speech to text
    CLAUDE_VOICE_MOUTH=vendor:model[:voice]   text to speech

Or the same names, in lower case, in ~/.claude-voice/config.json. "local" runs Whisper, Kokoro and any OpenAI-compatible server. bin/voice-doctor shows what runs. Unset, each role takes the first vendor in its order whose key exists. Keys come from the environment or, on macOS, the
Keychain item named here, and reach this process only when a role in use needs them.
"""

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

KEYS = {
    "gemini": ("GOOGLE_API_KEY", "gemini-api-key"),
    "openai": ("OPENAI_API_KEY", "openai-api-key"),
    "anthropic": ("ANTHROPIC_API_KEY", "anthropic-api-key"),
    "soniox": ("SONIOX_API_KEY", "soniox-api-key"),
    "elevenlabs": ("ELEVENLABS_API_KEY", "elevenlabs-api-key"),
}
ENV_ALIASES = {"gemini": "GEMINI_API_KEY"}  # Google documents both names
LOCAL = "local"  # needs no key: Whisper and Kokoro on this machine, and an OpenAI-compatible server for text models
LOCAL_URL = "http://localhost:11434/v1"  # Ollama; CLAUDE_VOICE_LOCAL_URL or "local_url" points it at mlx-lm, LM Studio, vLLM...
LOCAL_EARS_MODEL = "mlx-community/whisper-large-v3-turbo"  # why: bench/results/local.md
KEY_ENVS = {env for env, _ in KEYS.values()} | set(ENV_ALIASES.values()) | {"CLAUDE_VOICE_LOCAL_KEY"}
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


def key(vendor: str) -> str | None:
    if local_only():
        return None
    env, item = KEYS[vendor]
    value = os.environ.get(env) or os.environ.get(ENV_ALIASES.get(vendor, ""))
    if value:
        return value
    try:
        got = subprocess.run(["security", "find-generic-password", "-s", item, "-w"], capture_output=True, text=True,
                             timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if not got.returncode and got.stdout.strip():
        os.environ[env] = got.stdout.strip()
        return os.environ[env]
    return None


_clients: dict[str, object] = {}


def _gemini():
    # Kept alive: a client that is garbage collected during a call closes the connection under it.
    from google import genai

    from google.genai import types

    # One attempt: the library's own retries turned an out-of-quota 429 into a silent wait past every timeout, so the
    # vendor fallback never saw it. A refusal now surfaces at once and the next vendor answers.
    return _clients.setdefault("gemini", genai.Client(api_key=key("gemini"), http_options=types.HttpOptions(
        retry_options=types.HttpRetryOptions(attempts=1))))


def _anthropic():
    import anthropic

    return _clients.setdefault("anthropic", anthropic.AsyncAnthropic(api_key=key("anthropic")))


def _openai():
    from openai import AsyncOpenAI

    return _clients.setdefault("openai", AsyncOpenAI(api_key=key("openai")))


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


def _local():
    from openai import AsyncOpenAI

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
    if wanted and wanted != "auto":
        if wanted.split(":")[0] not in {*KEYS, LOCAL}:
            raise SystemExit(f"{env}={wanted}: unknown vendor. Choose from: {', '.join([*KEYS, LOCAL])}")
        if local_only() and wanted.split(":")[0] != LOCAL:
            raise SystemExit(f"{env}={wanted}: fully local mode is on, so only local models run. "
                             "Turn it off with: pointe local off")
        if not has(wanted.split(":")[0]):
            raise SystemExit(f"{env}={wanted} needs a key: {missing_key_help(wanted.split(':')[0])}")
        return wanted
    for choice in order:
        if has(choice.split(":")[0]):
            return choice
    raise SystemExit(f"{env}: no key found for any of {order}. {missing_key_help(order[0].split(':')[0])}")


def missing_key_help(vendor: str) -> str:
    env, item = KEYS[vendor]
    return f"set {env}, or on macOS: security add-generic-password -U -s {item} -a \"$USER\" -w"


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
    s = Setup(reader=pick("CLAUDE_VOICE_READER", READER_ORDER), checker=pick("CLAUDE_VOICE_CHECKER", CHECKER_ORDER))
    if front == "brain":
        s.brain = pick("CLAUDE_VOICE_BRAIN", BRAIN_ORDER)
        s.mouth = pick("CLAUDE_VOICE_MOUTH", MOUTH_ORDER)
    s.ears = pick("CLAUDE_VOICE_EARS", EARS_ORDER)
    if s.ears != "soniox":
        s.notes.append("Without Soniox the echo guard has no mirror stream: use headphones or browser echo cancellation.")
    return s


# ---------- text models: one call shape for the gates and the reader ----------

_EXHAUSTED: dict[str, float] = {}  # vendor -> when it last refused for quota or rate: skipped for a while
EXHAUSTED_SECS = 600


def _out_of_quota(error: Exception) -> bool:
    text = f"{type(error).__name__} {error}".lower()
    return any(sign in text for sign in ("429", "resource_exhausted", "rate_limit", "ratelimit", "quota", "insufficient_quota"))


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


async def _anthropic_step(model: str, system: str, messages: list[dict], tools: list[dict]) -> Step:
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
    resp = await _anthropic().messages.create(
        model=model, max_tokens=4000, system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        tools=[{"name": t["name"], "description": t["description"], "input_schema": _schema(t)} for t in tools],
        messages=converted, output_config={"effort": os.environ.get("CLAUDE_VOICE_BRAIN_THINKING", "low")})
    calls = [{"id": b.id, "name": b.name, "args": dict(b.input or {})} for b in resp.content if b.type == "tool_use"]
    said = "".join(b.text for b in resp.content if b.type == "text").strip()
    return Step(calls, resp.content, said, {"context": resp.usage.input_tokens + (resp.usage.cache_read_input_tokens or 0),
                                            "reply": resp.usage.output_tokens})


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


async def step(choice: str, system: str, messages: list[dict], tools: list[dict]) -> Step:
    vendor, model = choice.split(":", 1)
    # After a handover (quota), earlier turns came from another vendor: their raw form means nothing here, so they go
    # in the neutral form, as calls and text.
    result = await _STEP[vendor](model, system, _as_text_where_foreign(messages, vendor), tools)
    result.vendor = vendor
    return result


# ---------- ears and mouth ----------

DEFAULT_ELEVENLABS_VOICE = "cjVigY5qzO86Huf0OWal"  # Eric
DEFAULT_GEMINI_VOICE = "Charon"


def build_ears(vendor: str, terms: list[str]):
    """A speech-to-text service in the pipeline. Only Soniox takes vocabulary hints."""
    from pipecat.transcriptions.language import Language

    if vendor == "soniox":
        from pipecat.services.soniox.stt import SonioxContextObject, SonioxSTTService

        return SonioxSTTService(
            api_key=key("soniox"),
            should_interrupt=False,  # SonioxEars decides barge-in, by words
            vad_force_turn_endpoint=False,  # Soniox endpointing: 0.31 s p50 in the benchmark
            settings=SonioxSTTService.Settings(language_hints=[Language.EN, Language.HE],
                                               endpoint_sensitivity=float(os.environ.get("CLAUDE_VOICE_ENDPOINT", "-0.5")),
                                               max_endpoint_delay_ms=2500,  # patient: a pause to think ends no turn
                                               context=SonioxContextObject(terms=terms)))
    if vendor == "gemini":
        from pipecat.services.google.gemini_live.stt import GeminiSTTService

        return GeminiSTTService(api_key=key("gemini"))
    if vendor == "openai":
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
    from pipecat.services.whisper.stt import Model, WhisperSTTService

    return WhisperSTTService(settings=WhisperSTTService.Settings(model=Model.LARGE_V3_TURBO, language=None))


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
        from huggingface_hub import snapshot_download

        path = snapshot_download(LOCAL_EARS_MODEL, local_files_only=True)
    except Exception:
        path = LOCAL_EARS_MODEL  # not downloaded yet: mlx-whisper fetches it on the first utterance

    class MLXWhisperEars(SegmentedSTTService):
        model_path = path

        async def run_stt(self, audio: bytes):
            import mlx_whisper

            samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
            await self.start_processing_metrics()
            try:
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
        from pipecat.services.openai.tts import OpenAITTSService

        return OpenAITTSService(api_key=key("openai"), sample_rate=rate,
                                settings=OpenAITTSService.Settings(voice=voice or "ash", model=model))
    if vendor == "soniox":
        from pipecat.services.soniox.tts import SonioxTTSService

        return SonioxTTSService(api_key=key("soniox"), sample_rate=rate)
    if vendor == LOCAL:
        from pipecat.services.kokoro.tts import KokoroTTSService

        return KokoroTTSService(sample_rate=rate, settings=KokoroTTSService.Settings(voice=voice or "af_heart"))
    raise SystemExit(f"CLAUDE_VOICE_MOUTH: unknown vendor {vendor}")

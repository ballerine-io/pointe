"""Model judges for the agents proof: does the conversation in a transcript read naturally? Two judges from two vendors
read bench/agents/live.py's transcript.md and answer a fixed rubric as JSON. No human raters.

    python3 bench/agents/judge.py <evidence folder>

The keys are read from the macOS Keychain by this process alone. Writes judge.json beside the transcript.
"""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[0:0] = [str(ROOT / "pointe")]

RUBRIC = """You are judging a voice assistant's conversation transcript. The assistant ("Pointe") is a voice layer: the
user talks to it, and it passes requests to AI agents ("openclaw" and "hermes", agents built on agent frameworks) and
reads their replies back. Lines in _[brackets]_ are the test harness's own notes about what it did (the call hanging up,
a new call opening); they are not part of the conversation. The user's words were typed as text in place of speech.

Judge only the assistant's lines. Score each criterion 1 (poor) to 5 (excellent), with one sentence of evidence:
- natural: reads like a sharp colleague on a call: short spoken sentences, no robotic filler, no lists read aloud
- faithful: reports what the agents said without inventing or dropping facts
- routing_clear: it is always clear which agent a request went to and which agent a reply came from
- async_clear: a reply that arrived later, or while the user was away, is introduced clearly and not confusingly
- consent_clear: a relay between agents and a command approval are asked plainly, and a no is respected and confirmed
Then: "verdict": "natural" if the conversation reads naturally overall (average 3.5 or more and no criterion under 3),
else "unnatural"; and "worst_moment": the single assistant line that reads worst, quoted, and why.
Answer with JSON only: {"natural": {"score": n, "evidence": "..."}, ..., "verdict": "...", "worst_moment": "..."}"""


def keychain(item: str) -> str:
    return subprocess.run(["/usr/bin/security", "find-generic-password", "-s", item, "-w"], capture_output=True,
                          text=True).stdout.strip()


async def claude(transcript: str) -> tuple[dict, dict]:
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=keychain("anthropic-api-key"))
    r = await client.messages.create(model="claude-sonnet-5-5", max_tokens=1500, system=RUBRIC,
                                     messages=[{"role": "user", "content": transcript}])
    text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
    return _json(text), {"in": r.usage.input_tokens, "out": r.usage.output_tokens, "model": "claude-sonnet-5-5"}


async def gemini(transcript: str) -> tuple[dict, dict]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=keychain("gemini-api-key"))
    r = await client.aio.models.generate_content(model="gemini-3.8-flash", contents=transcript, config=types.GenerateContentConfig(
        system_instruction=RUBRIC, response_mime_type="application/json"))
    u = r.usage_metadata
    return _json(r.text), {"in": u.prompt_token_count, "out": (u.candidates_token_count or 0) + (u.thoughts_token_count or 0),
                           "model": "gemini-3.8-flash"}


def _json(text: str) -> dict:
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(text[text.find("{"):text.rfind("}") + 1])


async def main(folder: Path) -> None:
    transcript = (folder / "transcript.md").read_text()
    out = {}
    for name, judge in (("claude", claude), ("gemini", gemini)):
        try:
            verdict, usage = await judge(transcript)
            out[name] = {"verdict": verdict, "usage": usage}
        except Exception as e:
            out[name] = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
    (folder / "judge.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1])))

"""The voice call minus the audio: the real daemon code and the real voice model, driven by text.

    sim.py serve --scenario evals/scenarios/x.json --sock /tmp/x.sock     (run in the background; prints "ready")
         [--front brain|live]  who decides what to say: the brain (brain.py), or Gemini Live as a whole
    sim.py --sock /tmp/x.sock user "what you say"                         one spoken turn; prints what came back
    sim.py --sock /tmp/x.sock final --file reply.md [--session NAME]      Claude Code ends its turn with this message
    sim.py --sock /tmp/x.sock wrote|typed --text "..." [--session NAME]   Claude Code text mid-turn | the user typed
    sim.py --sock /tmp/x.sock tool --text "Bash: run the tests"           Claude Code ran a tool
    sim.py --sock /tmp/x.sock wait | show | stop

What is real: INSTRUCTIONS and the tools, every gate and router, the transcript follower, feed, the session reader
and any other model call the daemon makes. What is not: audio, speech recognition, barge-in timing, and Claude Code
(the tester plays it; a delegation is recorded, not delivered). State lives in a temp dir, never ~/.claude-voice.

A scenario is {"mode": "orchestrator"|"session", "sessions": [{"name", "cwd", "active": bool,
"history": [{"role": "user"|"assistant", "text", "compact": bool}]}]}. Output is JSON: events since the last command.
"""

import argparse
import asyncio
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SETTLE_SECS = 3.0
TURN_TIMEOUT_SECS = 60.0


class SimInjector:
    """The FeedInjector's interface without audio: speech the model is asked for waits for its turn to end."""

    def __init__(self, sim):
        self.sim, self.bot_started_at, self.responded_at = sim, 0.0, 0.0
        self.queue: list[str] = []

    @property
    def holding(self) -> bool:
        return bool(self.queue)

    async def inject(self, text: str, respond: bool) -> None:
        self.sim.event("feed", text=text, respond=respond)
        if respond:
            self.queue.append(text)
            self.sim.kick()
        else:
            await self.sim.append(text)


class Sim:
    def __init__(self, scenario: dict, tmp: Path):
        import daemon as d

        self.d, self.tmp, self.events = d, tmp, []
        self.live = None
        self.speaking = False
        self.last_activity = time.time()
        self.buffer = ""
        self.sessions = {}
        self.delegations = []
        self.tools_running = 0
        if hasattr(d, "_digest_turn"):  # a report is being written: the model is about to speak
            digest = d._digest_turn

            async def counted(*args):
                self.tools_running += 1
                try:
                    return await digest(*args)
                finally:
                    self.tools_running -= 1
                    self.last_activity = time.time()

            d._digest_turn = counted
        from sessions import Session

        d.REGISTRY.path = None
        d.REGISTRY.sessions = {}
        d.REGISTRY.mode = scenario.get("mode", "orchestrator")
        for i, spec in enumerate(scenario["sessions"]):
            path = tmp / f"s{i}.jsonl"
            with path.open("w") as f:
                for entry in spec.get("history", []):
                    f.write(json.dumps(self._entry(entry)) + "\n")
            session = Session(id=f"s{i}", name=spec["name"], cwd=spec.get("cwd", "/tmp/repo"), pid=os.getpid(),
                              transcript=str(path))
            d.REGISTRY.sessions[session.id] = session
            self.sessions[spec["name"]] = session
            if spec.get("active") or i == 0:
                d.REGISTRY.active_id = session.id

        async def recorded_dispatch(target, message):
            from sessions import voice_message

            self.delegations.append({"to": target.name, "message": message})
            self.write(target, self._entry({"role": "user", "text": voice_message(message)}))
            self.event("delegated", to=target.name, message=message)
            target.busy = True
            return True

        d._dispatch = recorded_dispatch
        self.injector = SimInjector(self)

    @staticmethod
    def _entry(e: dict) -> dict:
        if e["role"] == "user":
            entry = {"type": "user", "message": {"role": "user", "content": e["text"]}}
            if e.get("compact"):
                entry["isCompactSummary"] = True
            return entry
        return {"type": "assistant", "message": {"role": "assistant", "stop_reason": e.get("stop", "end_turn"),
                                                 "content": [{"type": "text", "text": e["text"]}]}}

    def event(self, kind: str, **fields) -> None:
        self.last_activity = time.time()
        self.events.append({"kind": kind, **fields})

    def kick(self) -> None:
        asyncio.create_task(self._pump())

    async def _pump(self) -> None:
        if self.speaking or not self.injector.queue:
            return
        self.injector.queue.sort(key=self.d._feed_priority)
        text = self.injector.queue.pop(0)
        self.speaking = True
        self.injector.responded_at = time.time()
        await self.live.send_realtime_input(text=text)

    async def append(self, text: str) -> None:
        from google.genai import types

        await self.live.send_client_content(
            turns=[types.Content(role="user", parts=[types.Part(text=text)])], turn_complete=False)

    def config(self):
        from google.genai import types

        declarations = []
        for tool in self.d.TOOLS.standard_tools:
            declarations.append(types.FunctionDeclaration(
                name=tool.name, description=tool.description,
                parameters_json_schema={"type": "object", "properties": tool.properties, "required": tool.required}))
        return types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO], system_instruction=self.d.INSTRUCTIONS,
            tools=[types.Tool(function_declarations=declarations)],
            output_audio_transcription=types.AudioTranscriptionConfig(),
            history_config=types.HistoryConfig(initial_history_in_client_content=True),
            context_window_compression=types.ContextWindowCompressionConfig(sliding_window=types.SlidingWindow()))

    async def run(self, sock_path: str) -> None:
        from google import genai
        from google.genai import types
        from sessions import follow_transcript

        d = self.d
        client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
        d.state.http = None
        async with client.aio.live.connect(model=d.MODEL or "models/gemini-3.8-live", config=self.config()) as live:
            self.live = live
            d.state.context = None
            d.state.conn = d.Connection(injector=self.injector, voice=None, runner=None, workers={})
            now = time.time()
            d.state.connected_at = d.state.last_delegation_at = d.state.last_switch_at = now
            receiver = asyncio.create_task(self._receive())
            asyncio.create_task(self._keepalive())
            for session in self.sessions.values():
                asyncio.create_task(follow_transcript(session, d.feed, lambda: None))
            if hasattr(d, "_start_briefs"):
                d._start_briefs()
            opening = d._opening_context()
            self.event("opening", messages=[m["content"] for m in opening])
            self.speaking = True
            await live.send_client_content(
                turns=[types.Content(role="user", parts=[types.Part(text=m["content"])]) for m in opening],
                turn_complete=True)
            await live.send_realtime_input(text=" ")
            server = await asyncio.start_unix_server(self._client, path=sock_path)
            print("ready", flush=True)
            async with server:
                self.done = asyncio.Event()
                await self.done.wait()
            receiver.cancel()

    async def _keepalive(self) -> None:
        """A real call streams audio; without any input Gemini closes an idle session after a few minutes."""
        from google.genai import types

        silence = types.Blob(data=b"\0" * 3200, mime_type="audio/pcm;rate=16000")
        while True:
            await asyncio.sleep(20)
            await self.live.send_realtime_input(audio=silence)

    async def _receive(self) -> None:
        d = self.d
        while True:
            async for msg in self.live.receive():
                self.last_activity = time.time()
                if msg.tool_call:
                    asyncio.create_task(self._tools(msg.tool_call.function_calls))
                content = msg.server_content
                if not content:
                    continue
                if content.output_transcription and content.output_transcription.text:
                    self.speaking = True
                    self.buffer += content.output_transcription.text
                if content.turn_complete:
                    if self.buffer.strip():
                        d._remember("assistant", self.buffer)
                        self.event("bot", text=self.buffer.strip())
                    self.buffer, self.speaking = "", False
                    self.kick()

    async def _tools(self, calls) -> None:
        from google.genai import types

        handlers = {t.name: t.handler for t in self.d.TOOLS.standard_tools}
        responses = []
        self.tools_running += 1
        for call in calls:
            outcome = {}

            class Params:
                arguments = dict(call.args or {})

                @staticmethod
                async def result_callback(result, *a, **k):
                    outcome["result"] = result

            await handlers[call.name](Params)
            self.event("tool", name=call.name, args=dict(call.args or {}), result=outcome.get("result"))
            responses.append(types.FunctionResponse(id=call.id, name=call.name,
                                                    response={"result": outcome.get("result")}))
        self.tools_running -= 1
        self.last_activity = time.time()
        await self.live.send_tool_response(function_responses=responses)

    async def settle(self, secs: float = SETTLE_SECS) -> None:
        deadline = time.time() + TURN_TIMEOUT_SECS
        while time.time() < deadline:
            await asyncio.sleep(0.25)
            if not self.speaking and not self.tools_running and not self.injector.queue and time.time() - self.last_activity >= secs:
                return
        self.event("timeout", note="the model did not settle")

    def drain(self) -> list[dict]:
        out, self.events = self.events, []
        return out

    def write(self, session, entry: dict) -> None:
        with Path(session.transcript).open("a") as f:
            f.write(json.dumps(entry) + "\n")

    async def _client(self, reader, writer) -> None:
        cmd = json.loads(await reader.readline())
        result = await self.handle(cmd)
        writer.write(json.dumps(result, ensure_ascii=False).encode() + b"\n")
        await writer.drain()
        writer.close()

    async def handle(self, cmd: dict) -> dict:
        d, op = self.d, cmd["op"]
        session = self.sessions.get(cmd.get("session")) or d.REGISTRY.active
        if op == "user":
            await d.on_user_utterance(cmd["text"])
            self.speaking = True
            await self.live.send_realtime_input(text=cmd["text"])
        elif op == "final":
            self.write(session, self._entry({"role": "assistant", "text": cmd["text"]}))
        elif op == "wrote":
            self.write(session, self._entry({"role": "assistant", "text": cmd["text"], "stop": None}))
        elif op == "typed":
            self.write(session, self._entry({"role": "user", "text": cmd["text"]}))
        elif op == "tool":
            name, _, detail = cmd["text"].partition(":")
            self.write(session, {"type": "assistant", "message": {"role": "assistant", "stop_reason": "tool_use", "content": [
                {"type": "tool_use", "name": name.strip(), "input": {"description": detail.strip()}}]}})
        elif op == "stop":
            self.done.set()
            return {"stopped": True}
        elif op == "show":
            return {"active": d.REGISTRY.active.name if d.REGISTRY.active else None, "mode": d.REGISTRY.mode,
                    "delegations": self.delegations, "conversation": d.state.conversation,
                    "needs": {s.name: s.needs for s in self.sessions.values()}}
        await asyncio.sleep(1.0)  # the follower polls the transcript
        await self.settle()
        return {"events": self.drain()}


class BrainSim(Sim):
    """The call with the real Brain, as the daemon runs it, and no audio. Replies carry the whole turn's latency in ms."""

    def __init__(self, scenario, tmp):
        self.ms = 0
        super().__init__(scenario, tmp)
        d = self.d

        async def speak(text: str) -> None:
            text = d._spoken_names(text)
            d._remember("assistant", text)
            self.event("bot", text=text, ms=int((time.time() - self.turn_started) * 1000))

        self.brain = d.make_brain(speak)
        given = self.brain.on_usage

        def usage(u: dict) -> None:
            self.ms = u.get("ms", 0)
            given(u)

        self.brain.on_usage = usage
        self.brain.on_tool = lambda name, args, result: self.event("tool", name=name, args=args, result=result)
        self.turn_started = time.time()

    async def _pump(self) -> None:
        if self.speaking or not self.injector.queue:
            return
        self.injector.queue.sort(key=self.d._feed_priority)
        await self.turn(self.injector.queue.pop(0))

    async def append(self, text: str) -> None:
        self.brain.append(text)

    async def turn(self, text: str | None) -> None:
        self.speaking = True
        self.turn_started = time.time()
        try:
            await self.brain.turn(text)
        finally:
            self.speaking = False
            self.last_activity = time.time()
        self.kick()

    async def send_realtime_input(self, text: str) -> None:  # what handle() calls for a spoken turn
        await self.turn(text)

    async def run(self, sock_path: str) -> None:
        from sessions import follow_transcript

        d = self.d
        d.state.conn = d.Connection(injector=self.injector, voice=None, runner=None, workers={})
        d.state.connected_at = d.state.last_delegation_at = d.state.last_switch_at = time.time()
        for session in self.sessions.values():
            asyncio.create_task(follow_transcript(session, d.feed, lambda: None))
        d._start_briefs()
        opening = d._opening_context()
        self.event("opening", messages=[m["content"] for m in opening])
        for m in opening[:-1]:
            self.brain.append(m["content"])
        greeting = d.fixed_greeting()
        if greeting:
            self.brain.append(opening[-1]["content"])
            d._remember("assistant", greeting)
            self.event("bot", text=greeting, ms=0)
        else:
            await self.turn(opening[-1]["content"])
        self.live = self
        server = await asyncio.start_unix_server(self._client, path=sock_path)
        print("ready", flush=True)
        async with server:
            self.done = asyncio.Event()
            await self.done.wait()


def serve(args) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="voice-sim-"))
    (tmp / "token").write_text("sim")
    os.environ["CLAUDE_VOICE_STATE"] = str(tmp)
    os.environ.setdefault("GOOGLE_API_KEY", subprocess.run(
        ["security", "find-generic-password", "-s", "gemini-api-key-paid", "-w"],
        capture_output=True, text=True, check=True).stdout.strip())
    scenario = json.loads(Path(args.scenario).read_text())

    async def main():
        sim = Sim(scenario, tmp) if args.front == "live" else BrainSim(scenario, tmp)
        await sim.run(args.sock)

    asyncio.run(main())


def call(args) -> None:
    text = args.text
    if getattr(args, "file", None):
        text = Path(args.file).read_text()
    s = socket.socket(socket.AF_UNIX)
    s.connect(args.sock)
    s.sendall(json.dumps({"op": args.op, "text": text, "session": args.session}).encode() + b"\n")
    data = b""
    while chunk := s.recv(65536):
        data += chunk
    if not data.strip():
        sys.exit("the simulated call ended (the model connection closed): start a new serve")
    print(json.dumps(json.loads(data), ensure_ascii=False, indent=1))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--sock")
    sub = p.add_subparsers(dest="op", required=True)
    serve_p = sub.add_parser("serve")
    serve_p.add_argument("--scenario", required=True)
    serve_p.add_argument("--sock", required=True, dest="sock")
    serve_p.add_argument("--front", default="brain", choices=["live", "brain"])
    for op in ("user", "final", "wrote", "typed", "tool", "wait", "show", "stop"):
        c = sub.add_parser(op)
        c.add_argument("positional", nargs="?")
        c.add_argument("--text")
        c.add_argument("--file")
        c.add_argument("--session")
    args = p.parse_args()
    if args.op == "serve":
        serve(args)
    else:
        args.text = args.text or args.positional
        call(args)


if __name__ == "__main__":
    main()

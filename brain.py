"""Decides what to say. A text model with the session's tools; speech is a tool call, so reasoning has nowhere to go and
code can check a reply before anyone hears it. No audio here: the daemon hands it words and speaks what comes back."""

import asyncio
import json
import re
import time
from collections.abc import Awaitable, Callable
from types import SimpleNamespace

from loguru import logger

import vendors
from brief import unsupported_in

SPEAK = {"name": "speak",
         "description": "Say this to the user. It is the only way to reach them, and it ends your turn. Only what they "
         "should hear: never reasoning, notes about rules, or tool names. Empty text means stay silent, which is the "
         "right reply to a plain acknowledgment such as okay or thanks.",
         "properties": {"text": {"type": "string"}}, "required": ["text"]}
MAX_STEPS = 6
MAX_MESSAGES = 400  # a long call is trimmed from the front; the notes carry what the oldest turns held
FILLER_AFTER_SECS = 4.5  # silence past this says "one sec"; the model's p95 is under it, so it is rare
STEP_TIMEOUT_SECS = 8.0  # past this the fast model answers: p95 is 2.3 s, and stalls of 20 s were seen
_CLAIMS_SENT = re.compile(r"^on it\b|\b(?:i've|i have|i just|i) (?:asked|sent|told|instructed)\b(?! nothing| anything)|^sending\b|"
                          r"(?<!לא )שלחתי|(?<!לא )ביקשתי")
_CLAIMS_ANSWERED = re.compile(r"\b(?:denied|declined|approved|granted|applying your yes|your yes (?:was|is|has)|won't run)\b|נדחה|אושר")
_CLAIMS_CLEAR = re.compile(r"nothing (is )?(needed|open|waiting|pending)|nothing (from|for) you|don't need anything|"
                           r"אין צורך|לא צריך ממך|לא מחכה")


_UNSPEAKABLE = re.compile(r"`|(?:^|[\s(])[\w.-]*/[\w.-]+\.\w{1,5}\b|\b[\w-]+\.(?:py|ts|tsx|js|jsx|go|rb|rs|json|yaml|yml|sql|sh|md|html|css)\b")
_BACKSTAGE = re.compile(r"\bmy notes\b|\bthe notes\b|\bthe feed\b|\bthe transcript\b|\bin the history\b|\bsession history\b|\bthe system\b|\bthe gate\b|\bthe checker\b|\btool (?:call|result)\b|\blist_sessions\b|\bask_about_session\b|\bsend_to_claude_code\b")
# A question that hands the conversation back with nothing in it. The user knows they can talk.
_EMPTY_CLOSER = re.compile(r"(?:^|(?<=[.!?…]))\s*(?:(?:so,?\s*)?what(?:'s| is| would you like| do you want)(?: to)?(?: do| tackle| work on)?(?: our)?(?: the)?(?: next)?(?: move| step)?(?: next)?|"
                           r"(?:is there )?anything else(?: i can do)?|let me know[^.!?]*|how can i help[^.!?]*|מה הלאה|מה הצעד הבא[^.!?]*|"
                           r"עוד משהו|מה תרצה לעשות[^.!?]*)[.!?…]*\s*$", re.I)


def plain(said: str) -> str:
    """Markdown has no sound: bullets and bold become plain sentences."""
    said = re.sub(r"\*\*|__", "", said)
    return re.sub(r"(?m)^\s*(?:[-*•]|\d+[.)])\s+", "", said).strip()


def without_repeat(said: str, previous: str) -> str:
    """The same closing list on reply after reply is a nag: a last sentence that repeats the last reply's is dropped."""
    parts = re.split(r"(?<=[.!?…])\s+", said.strip())
    last = re.split(r"(?<=[.!?…])\s+", previous.strip())[-1] if previous else ""
    if len(parts) < 2 or not last:
        return said
    a, b = set(re.findall(r"\w+", parts[-1].lower())), set(re.findall(r"\w+", last.lower()))
    return " ".join(parts[:-1]) if a and len(a & b) / len(a | b) > 0.6 else said


_STOP = set("the a an and or but so to of in on at for with is are was were be been it its this that these those you your "
             "i me my we our they their he she his her not no yes do does did have has had will would can could should "
             "just still now then there here what which who how why when also only about from as by if than".split())
REPEAT_WINDOW_SECS = 90.0


def _content(text: str) -> set[str]:
    return {w for w in re.findall(r"\w+", text.lower()) if w not in _STOP and len(w) > 1}


def without_recent_repeats(said: str, recent: list[str], asked: str) -> str:
    """Sentences the voice already said in the last minute and a half are cut, unless the user's latest words ask about
    them: on a real call it warned three times that an answer had not arrived, and apologised twice in one breath."""
    asked_words = _content(asked)
    kept = []
    for sentence in re.split(r"(?<=[.!?…])\s+", said.strip()):
        words = _content(sentence)
        repeated = len(words) >= 3 and any(len(words & _content(old)) / len(words) >= 0.7 for old in recent)
        if not repeated or (asked_words and len(words & asked_words) >= 2):
            kept.append(sentence)
    return " ".join(kept)


def without_closer(said: str) -> str:
    return _EMPTY_CLOSER.sub("", said).strip()


class Brain:
    def __init__(self, choice: str, instructions: str, tools: list, context: Callable[[], str],
                 speak: Callable[[str], Awaitable[None]], filler: Callable[[], Awaitable[None]] | None = None,
                 has_open: Callable[[], str | None] | None = None, sent_lately: Callable[[], bool] | None = None,
                 on_usage: Callable[[dict], None] | None = None, fallback: str | None = None,
                 on_tool: Callable[[str, dict, object], None] | None = None,
                 may_stay_silent: Callable[[], bool] | None = None,
                 language_problem: Callable[[str], str | None] | None = None):
        self.language_problem = language_problem or (lambda _s: None)
        self.translate: Callable[[str], Awaitable[str]] | None = None
        self._last_spoken = ""
        self._recent_spoken: list[tuple[float, str]] = []  # (when, what) the voice said lately
        self._answered_user = False  # the user's latest words already got a spoken reply
        self.may_stay_silent = may_stay_silent or (lambda: True)
        self.fallback, self.on_tool = fallback, on_tool or (lambda *_a: None)
        self.choice, self.instructions, self.tools = choice, instructions, tools
        self.context, self.speak, self.filler = context, speak, filler
        self.has_open, self.sent_lately = has_open or (lambda: None), sent_lately or (lambda: False)
        self.permission_pending = lambda: False
        self.on_usage = on_usage or (lambda _u: None)
        self.messages: list[dict] = []
        self._lock = asyncio.Lock()
        self._current: asyncio.Task | None = None
        self._given = ""
        self._tools_running = False
        self._waiting: list[str] = []
        self._generation = 0  # moves on when the user talks: a turn from an older one must not speak

    def append(self, text: str) -> None:
        if not (text and text.strip()):
            return
        if self._tools_running:  # between a tool call and its result nothing may be added: vendors refuse that history
            self._waiting.append(text)
        else:
            self.messages.append({"role": "user", "content": text})
        if not text.lstrip().startswith("["):  # the user's own words, not session news
            self._answered_user = False

    @property
    def busy(self) -> bool:
        return self._lock.locked()

    def interrupt(self) -> None:
        """The user started talking: whatever was about to be said is stale."""
        self._generation += 1
        if self._current:
            self._current.cancel()

    def _user_named(self, word: str) -> bool:
        """The user's own last words, not session news (which arrives bracketed), used this word."""
        last = next((m["content"] for m in reversed(self.messages)
                     if m["role"] == "user" and isinstance(m.get("content"), str) and not m["content"].startswith("[")), "")
        return bool(re.search(rf"\b{re.escape(word)}\b", last.lower()))

    def speech_problem(self, said: str, sent: bool, refused: bool = False) -> str | None:
        """Why this reply must not be spoken as it is. Each one is a harm the user could act on."""
        lowered = said.lower()
        if not said and not self.may_stay_silent():
            return "The user is waiting for an answer: say something."
        if said and self.may_stay_silent() and len(said.split()) > 10:
            return "They only acknowledged. Speak empty text, or a few words at most."
        if not sent and (refused or not self.sent_lately()) and _CLAIMS_SENT.search(lowered):
            return ("You say you sent something, and nothing was sent. Call send_to_claude_code and speak its result, or "
                    "say that you did not send it.")
        if re.search(r"typed? .{0,40}terminal", lowered) and not re.search(r"merg|post|publish|delet|drop", lowered):
            return "Only a merge, a post to people outside or a delete needs typing. Do not say this one does."
        if _UNSPEAKABLE.search(said):
            return "That has a path or code in it. Say what it means in plain words, without file names or backticks."
        backstage = _BACKSTAGE.search(lowered)
        if backstage and not self._user_named(backstage.group(0).split()[-1]):  # "what's in the notes?" may get "the notes say"
            return "Do not mention notes, the feed, transcripts or tools. Say what you know, or that you do not know."
        wrong_language = self.language_problem(said)
        if wrong_language:
            return wrong_language
        if self.permission_pending() and _CLAIMS_ANSWERED.search(lowered):
            return "That has not happened. Only a [permission answered] message says it was answered. Put the question again."
        needs = self.has_open()
        if needs and _CLAIMS_CLEAR.search(lowered):
            return f"That is false; these are open, so say them, most urgent first:\n{needs}"
        known = " ".join(json.dumps({k: v for k, v in m.items() if k != "raw"}, ensure_ascii=False, default=str)
                         for m in self.messages if m["role"] != "assistant")  # its own words prove nothing
        made_up = unsupported_in(said, known)
        if made_up:
            return f"These are in nothing you were told, so do not state them: {made_up}."
        return None

    def _repair(self) -> None:
        """After a refused history, keep what was said and drop vendor state and any unanswered call."""
        kept = []
        for i, m in enumerate(self.messages):
            if m["role"] == "assistant" and m.get("calls"):
                answered = i + 1 < len(self.messages) and self.messages[i + 1]["role"] == "tool"
                if not answered:
                    continue
            kept.append({k: v for k, v in m.items() if k != "raw"})
        self.messages = kept
        self._tools_running = False

    def _trim(self) -> None:
        if len(self.messages) <= MAX_MESSAGES:
            return
        cut = len(self.messages) - MAX_MESSAGES
        while cut < len(self.messages) and self.messages[cut]["role"] != "user":
            cut += 1
        self.messages = [{k: v for k, v in m.items() if k != "raw"} for m in self.messages[cut:]]  # vendors refuse edited replays

    async def turn(self, text: str | None = None) -> None:
        """One reply: tools as needed, then speech. A turn that is interrupted leaves a valid history behind."""
        generation = self._generation
        if text is not None:
            self.append(text)
        async with self._lock:
            if generation != self._generation:
                return  # the words stay in the history; the turn that follows answers them
            await self._run(generation)

    async def _run(self, generation: int) -> None:
        decls = [SPEAK] + [{"name": t.name, "description": t.description, "properties": t.properties,
                            "required": t.required} for t in self.tools]
        sent, retries, filled, refused = False, 0, False, False
        for _ in range(MAX_STEPS):
            self._trim()
            now = self.context()
            if now != self._given:  # appended, never edited: vendors cache the prefix, and some refuse an edited one
                self.append(now)
                self._given = now
            started = time.time()
            try:
                step, filled = await self._step(decls, filled)
            except asyncio.CancelledError:
                if generation != self._generation:
                    return
                raise
            except Exception as e:
                logger.error(f"brain failed: {type(e).__name__}: {str(e)[:200]}")
                self._repair()
                await self.speak("I lost my connection to the model for a moment. Say that again?")
                return
            finally:
                self._current = None
            if generation != self._generation:
                return
            ms = int((time.time() - started) * 1000)
            self.on_usage({**step.usage, "ms": ms})
            calls = step.calls
            if not calls and step.said:  # a vendor without forced tool use answered in plain text
                calls = [{"id": "text", "name": "speak", "args": {"text": step.said}, "plain": True}]
            if not calls:
                await self.speak("Sorry, I lost that. Say it again?")
                return
            real = [c for c in calls if not c.get("plain")]
            if real:
                self.messages.append({"role": "assistant", "calls": real, "raw": step.raw, "vendor": step.vendor})
                self._tools_running = True
            results, done = {}, False
            for call in [c for c in calls if c["name"] != "speak"]:  # speech last: it may report what the tools did
                result, filled = await self._tool(call, filled)
                results[call["id"]] = result
                sent = sent or (call["name"] == "send_to_claude_code" and "sent_to" in (result or {}))
                refused = refused or (call["name"] == "send_to_claude_code" and "error" in (result or {}))
            for call in [c for c in calls if c["name"] == "speak"]:
                said = plain(str(call["args"].get("text", "")))
                problem = self.speech_problem(said, sent, refused) if retries < 2 else None
                if problem:
                    retries += 1
                    logger.info(f"speech refused: {said!r}: {problem[:160]}")
                    results[call["id"]] = {"error": f"Not spoken. {problem}"}
                elif generation != self._generation:
                    results[call["id"]] = {"interrupted": True}
                    done = True
                else:
                    if call.get("plain"):
                        self.messages.append({"role": "assistant", "calls": [], "said": said, "raw": step.raw, "vendor": step.vendor})
                    said = without_repeat(without_closer(said), self._last_spoken)
                    now = time.time()
                    self._recent_spoken = [(t, x) for t, x in self._recent_spoken if now - t < REPEAT_WINDOW_SECS]
                    asked = next((m["content"] for m in reversed(self.messages) if m["role"] == "user"
                                  and isinstance(m.get("content"), str) and not m["content"].startswith("[")), "")
                    trimmed = without_recent_repeats(said, [x for _, x in self._recent_spoken], asked)
                    if trimmed != said:
                        logger.info(f"repeat cut: {said!r} -> {trimmed!r}")
                        # A first answer to new words must still say something; a second reply to the same words need not.
                        said = trimmed if (trimmed or self._answered_user) else said
                    if said and self.translate and self.language_problem(said):  # it was told twice; the user must still follow
                        said = await self.translate(said)
                        if generation != self._generation:  # the user moved on while it was translated
                            said = ""
                    if said:  # empty: the right reply to "okay, thanks" can be silence
                        self._last_spoken = said
                        self._recent_spoken.append((time.time(), said))
                        self._answered_user = True
                        await self.speak(said)
                    results[call["id"]] = "spoken"
                    done = True
            if real:
                self.messages.append({"role": "tool", "results": [
                    {"id": c["id"], "name": c["name"], "result": results.get(c["id"])} for c in real]})
            self._tools_running = False
            waiting, self._waiting = self._waiting, []
            for text in waiting:
                self.append(text)
            if done or generation != self._generation:
                return
        await self.speak("That took too many steps, so I stopped. Tell me what you need first.")

    async def _step(self, decls: list[dict], filled: bool) -> tuple[vendors.Step, bool]:
        """One model step that cannot stall the call: a filler past a few seconds, the fast model past the timeout."""
        choices = [c for c in (self.choice, self.fallback) if c]
        for choice in choices:
            self._current = asyncio.ensure_future(vendors.step(choice, self.instructions, self.messages, decls))
            try:
                done, _ = await asyncio.wait({self._current}, timeout=FILLER_AFTER_SECS if not filled else 0.001)
                if not done and self.filler and not filled:
                    filled = True
                    await self.filler()
                return await asyncio.wait_for(asyncio.shield(self._current), STEP_TIMEOUT_SECS - FILLER_AFTER_SECS), filled
            except (asyncio.TimeoutError, TimeoutError):
                self._current.cancel()
                logger.warning(f"brain {choice} took over {STEP_TIMEOUT_SECS} s")
                last = TimeoutError(f"{choice} timed out")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"brain {choice} failed: {type(e).__name__}: {str(e)[:160]}")
                last = e
                # Out of quota: the same vendor's fallback will be too, so another vendor with a key takes the step.
                if vendors._out_of_quota(e) and len(choices) < 3:
                    vendors._EXHAUSTED[choice.split(":")[0]] = time.time()
                    if other := vendors._stand_in(choice):
                        choices.append(other)
        raise last

    async def _tool(self, call: dict, filled: bool) -> tuple[object, bool]:
        tool = next((t for t in self.tools if t.name == call["name"]), None)
        if tool is None:
            return {"error": f"No tool named {call['name']}."}, filled
        outcome = {}

        async def done(result, *_a, **_k):
            outcome["result"] = result

        params = SimpleNamespace(arguments=call["args"], result_callback=done)
        # Never cancelled: a request half delivered must still be recorded as sent.
        running = asyncio.ensure_future(tool.handler(params))
        if not filled and self.filler:
            finished, _ = await asyncio.wait({running}, timeout=FILLER_AFTER_SECS)
            if not finished:
                filled = True
                await self.filler()
        await asyncio.shield(running)
        self.on_tool(call["name"], call["args"], outcome.get("result"))
        return outcome.get("result"), filled

    def get_messages(self, truncate_large_values: bool = False) -> list[dict]:
        """The history in the shape the context drawer reads."""
        out = []
        for m in self.messages:
            if m["role"] == "user":
                out.append({"role": "user", "content": m["content"]})
            elif m["role"] == "assistant":
                speech = [c["args"].get("text", "") for c in m["calls"] if c["name"] == "speak"] + ([m["said"]] if m.get("said") else [])
                if speech:
                    out.append({"role": "assistant", "content": " ".join(speech)})
                other = [c for c in m["calls"] if c["name"] != "speak"]
                if other:
                    out.append({"role": "assistant", "tool_calls": [{"id": c["id"], "type": "function", "function": {
                        "name": c["name"], "arguments": json.dumps(c["args"], ensure_ascii=False)}} for c in other]})
            else:
                out += [{"role": "tool", "tool_call_id": r["id"], "content": json.dumps(r["result"], ensure_ascii=False, default=str)}
                        for r in m["results"] if r["name"] != "speak"]
        return out

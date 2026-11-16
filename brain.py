"""Decides what to say. A text model with the session's tools; speech is a tool call, so reasoning has nowhere to go and
code can check a reply before anyone hears it. No audio here: the daemon hands it words and speaks what comes back."""

import asyncio
import json
import re
import time
from collections.abc import Awaitable, Callable
from types import SimpleNamespace

from loguru import logger

import conversation
import vendors
from brief import unsupported_in
from guards import status_intent

SPEAK = {"name": "speak",
         "description": "Say this to the user. It is the only way to reach them, and it ends your turn. Only what they "
         "should hear: never reasoning, notes about rules, or tool names. Empty text means stay silent, which is the "
         "right reply to a plain acknowledgment such as okay or thanks.",
         "properties": {"text": {"type": "string"}}, "required": ["text"]}
MAX_STEPS = 6
MAX_MESSAGES = 400  # a hard cap on count; the token budget below is what a long call runs into first
# A step's time grows with its input: on a live call 14k tokens took 2.1 s and 340k took 7.4 s (about 16 ms per 1k
# tokens over a 1.9 s floor), until both models passed the 8 s timeout. The history is held near the size where the
# model's p95 was measured, so the timeout stays a stall guard and not a ceiling the call grows into.
HISTORY_TOKENS = 24_000  # over this, before a turn, older items shrink (the system prompt and tools add about 6k)
HISTORY_AFTER_TRIM = 16_000  # a trim brings it down to this: trims come every few turns, not every step
RECENT_TOKENS = 6_000  # the newest part stays as it came: the latest report, its reply and the turns around it
CHARS_PER_TOKEN = 3.5  # a first guess, English prose; corrected from each vendor's own count (Hebrew is nearer 2)
MAX_ITEM_CHARS = 16_000  # one user message or feed item; the daemon's own caps are lower, this is the net under them
MAX_RESULT_CHARS = 8_000  # one tool result
STUB_CHARS = 240  # what an old feed item keeps: its first line says what arrived; the notes carry the rest
OLD_RESULT = "[an earlier result, dropped from the history]"
OLD_NEWS = " […cut: older news; the notes and ask_about_session have the rest]"
# A first sentence shorter than this is not said ahead of the rest: "On it." is over in half a second, and the rest then
# starts after a silence in which the call looks finished (the voice has stopped, the floor's breath starts).
EARLY_MIN_WORDS = 4
FORESEEN_SECS = 10.0  # a step started ahead of its turn (Brain.foresee) is dropped when the turn has not come by then
FILLER_AFTER_SECS = 4.5  # silence past this says "one sec"; the model's p95 is under it, so it is rare
STEP_TIMEOUT_SECS = 8.0  # past this the fast model answers: p95 is 2.3 s, and stalls of 20 s were seen
SLOW_LINE = "The model took too long to answer. Say that again?"
LOST_LINE = "I lost my connection to the model for a moment. Say that again?"
# Put before the user's own words, in what the model is sent, when they come right after a session's text or another
# line from the daemon: two user turns in a row reach a model as one, and the words then read as that text's last line.
# Added to a refusal when the reply's first sentence was said while the rest was still being written (Brain._say_first).
HEARD_FIRST = (" The user has already heard your first sentence: {!r}. Say only what comes after it, and do not say it "
               "again.")
HEARD_ROOM = " It counts in the length: you have at most {} more words, in {}, to finish the answer."
OWN_WORDS = "[the text above ends here. The user now speaks. These are their own words:]\n"
_CLAIMS_SENT = re.compile(r"^on it\b|\b(?:i've|i have|i just|i) (?:asked|sent|told|instructed)\b(?! nothing| anything)|^sending\b|"
                          r"(?<!לא )שלחתי|(?<!לא )ביקשתי")
_CLAIMS_ANSWERED = re.compile(r"\b(?:denied|declined|approved|granted|applying your yes|your (?:yes|no) (?:was|is|has|went|got|counted|did)|won't run)\b|נדחה|אושר")
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


# A question that asks the user to choose ("Which one: shop or harbor?", "Studio's or devbox's?"): its options may repeat a
# status answer, but cut, the user is left with nothing to answer.
_CHOICE = re.compile(r"^(?=.*\?\s*$).*\b(?:which|or|איזה|איזו|או)\b", re.I | re.S)


def without_recent_repeats(said: str, recent: list[str], asked: str) -> str:
    """Sentences the voice already said in the last minute and a half are cut, unless the user's latest words ask about
    them: on a real call it warned three times that an answer had not arrived, and apologised twice in one breath."""
    asked_words = _content(asked)
    kept = []
    sentences = re.split(r"(?<=[.!?…])\s+", said.strip())
    for i, sentence in enumerate(sentences):
        words = _content(sentence)
        repeated = len(words) >= 3 and any(len(words & _content(old)) / len(words) >= 0.7 for old in recent)
        # "Which one?" alone cannot be answered: the sentence before it holds the options it asks between
        offers = i + 1 < len(sentences) and sentences[i + 1].endswith("?") and len(_content(sentences[i + 1])) < 3
        if not repeated or offers or _CHOICE.search(sentence) or (asked_words and len(words & asked_words) >= 2):
            kept.append(sentence)
    return " ".join(kept)


# A last sentence that only promises to speak later, or says it is waiting. The update comes when it comes.
_PROMISE_CLOSER = re.compile(
    r"(?<=[.!?…])\s+(?:(?:and )?i(?:'ll| will) (?:let you know|tell you|read (?:it|them) out|report back|update you|come back to you|"
    r"get back to you|flag it)\b[^.!?]*|(?:still )?waiting (?:on|for) (?:its|their|the|that|an?) [^.!?]*|"
    r"(?:אני )?(?:אעדכן|אודיע|אקריא|אחזור אליך)[^.!?]*|(?:אני )?(?:מחכה|ממתין) ל[^.!?]*)[.!…]*\s*$", re.I)


def without_closer(said: str) -> str:
    said = _EMPTY_CLOSER.sub("", said).strip()
    return _PROMISE_CLOSER.sub("", said).strip()


class Reply:
    """A reply as the model writes it: the words of its speak call so far, and a wake-up each time more arrive."""

    def __init__(self, on_first: Callable[[float], None] | None = None) -> None:
        self.text, self.began, self.over = "", 0.0, False
        self.grew = asyncio.Event()
        self.on_first = on_first  # told once, when the first piece of anything arrives
        self.to: Reply | None = None

    def __call__(self, text: str, began: float = 0.0) -> None:
        if not self.began:
            self.began = began or time.time()
            if self.on_first:
                self.on_first(self.began)
        self.text = text
        self.grew.set()
        if self.to is not None:
            self.to(text, self.began)

    def follow(self, other: "Reply") -> None:
        """`other` is told what this one has heard so far, and all that comes: a step started before its turn."""
        self.to = other
        if self.began:
            other(self.text, self.began)


class Brain:
    _foreseen: SimpleNamespace | None = None  # a first model step started before its turn (foresee)

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
        self._resuming = False  # this turn answers [resume]: what it repeats was sent before but not heard
        self._answered_user = False  # the user's latest words already got a spoken reply
        self.may_stay_silent = may_stay_silent or (lambda: True)
        self.fallback, self.on_tool = fallback, on_tool or (lambda *_a: None)
        self.choice, self.instructions, self.tools = choice, instructions, tools
        self.context, self.speak, self.filler = context, speak, filler
        self.has_open, self.sent_lately = has_open or (lambda: None), sent_lately or (lambda: False)
        self.permission_pending = lambda: False
        self.terse = lambda: False  # drive mode: the user cannot look, so no "Sorry, I lost that" chatter either
        self.style_problem: Callable[[str], str | None] = lambda _s: None  # a mode's own limit (drive: length)
        # How long this turn's reply may be, from what started it and the user's latest words (conversation.limit_for).
        self.limit: Callable[[str | None, str], conversation.Limit | None] = lambda _trigger, _asked: None
        # Why a reply to the user's own words tells too much: news that is queued to be said right after it (said, asked).
        self.news_ahead: Callable[[str, str], str | None] = lambda _said, _asked: None
        # Where the time of a reply to the user's own words goes (latency.STAGES): told as each stage is reached.
        self.stage: Callable[..., None] = lambda _stage, _when=None: None
        # A reply's first sentence is said while the rest is still being written, when both are set: speak_first(first),
        # then speak_rest(rest, whole) once the whole reply passed its checks (rest may be empty). may_speak_early: not
        # in a mode with its own rules for what is said.
        self.speak_first: Callable[[str], Awaitable[None]] | None = None
        self.speak_rest: Callable[[str, str], Awaitable[None]] | None = None
        self.may_speak_early: Callable[[], bool] = lambda: True
        self.on_usage = on_usage or (lambda _u: None)
        # The sentence for a refused key, by vendor; None when it cannot be heard (the mouth uses that key too).
        self.key_refused: Callable[[str], str | None] = vendors.refused_spoken
        self._key_refusal_said = False  # one Brain per call: said once, then the page explains
        self.messages: list[dict] = []
        self._chars_per_token = CHARS_PER_TOKEN  # what the vendor last counted, so the budget holds in its tokens
        self._lock = asyncio.Lock()
        self._current: asyncio.Task | None = None
        self._given = ""
        self._tools_running = False
        self._waiting: list[str] = []
        self._generation = 0  # moves on when the user talks: a turn from an older one must not speak
        self._user_turns = 0  # turns on the user's own words, started and not finished
        self._after_user: list[tuple[str, bool]] = []  # session news that arrived meanwhile: (text, needs a reply)
        self._trigger = ""  # what started the turn now running: the user's words, or a bracketed line from the daemon
        self._view: dict | None = None  # the newest message in the history the step now with the model read: what it answers
        self._answered: dict | None = None  # the same, for the last step whose reply was spoken

    @staticmethod
    def _clipped(text: str) -> str:
        return text if len(text) <= MAX_ITEM_CHARS else text[:MAX_ITEM_CHARS].rstrip() + " […cut]"

    def _decls(self) -> list[dict]:
        return [SPEAK] + [{"name": t.name, "description": t.description, "properties": t.properties,
                           "required": t.required} for t in self.tools]

    def foresee(self, text: str) -> None:
        """The user's sentence reads finished and its settle time is running (turns.py): the model step that would
        answer it starts now, so the wait and the model's time overlap. Only the request is made. Nothing is added to
        the history, no tool runs and nothing is said until the turn is really taken; then the step is used if what it
        was sent is exactly what the turn would send now (_step), and dropped otherwise: the user said more, news
        arrived, the state changed. A dropped step costs one small request."""
        self.forget()
        if not text.strip() or self.busy or self._tools_running or self._user_turns or self._waiting:
            return
        ahead = [*self.messages, {"role": "user", "content": self._clipped(text)}]
        now = self.context()
        if now != self._given:
            ahead.append({"role": "user", "content": now})
        outgoing, decls = self._outgoing(ahead), self._decls()
        relay = Reply() if self.speak_first else None
        task = asyncio.ensure_future(vendors.step(self.choice, self.instructions, outgoing, decls,
                                                  **({"heard": relay} if relay else {})))
        task.add_done_callback(lambda t: t.cancelled() or t.exception())  # a failure is met again by the turn's own step
        self._foreseen = SimpleNamespace(choice=self.choice, outgoing=outgoing, decls=decls, task=task, relay=relay,
                                         at=time.time())

    def forget(self) -> None:
        """What was started ahead is not wanted: the user went on talking."""
        seen, self._foreseen = self._foreseen, None
        if seen is not None and not seen.task.done():
            seen.task.cancel()

    def append(self, text: str) -> None:
        if not (text and text.strip()):
            return
        text = self._clipped(text)
        if self._tools_running:  # between a tool call and its result nothing may be added: vendors refuse that history
            self._waiting.append(text)
        else:
            self.messages.append({"role": "user", "content": text})
        if not text.lstrip().startswith("["):  # the user's own words, not session news
            self._answered_user = False

    def add_news(self, text: str) -> None:
        """Session news to keep in mind, no reply asked. While the user's words wait for their answer it waits behind
        them: the newest message is what the model answers, and that must be the user."""
        if self._user_turns:
            self._after_user.append((text, False))
        else:
            self.append(text)

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
        style = said and self.style_problem(said)
        if style:
            return style
        wrong_language = self.language_problem(said)
        if wrong_language:
            return wrong_language
        # Not on the turn that confirms an answer ("[permission answered]"): the session may have asked for the next thing
        # already, and "approved" is then true of the one just answered.
        confirming = self._trigger.lstrip().startswith("[permission answered]")
        if self.permission_pending() and not confirming and _CLAIMS_ANSWERED.search(lowered):
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

    def _outgoing(self, messages: list[dict] | None = None) -> list[dict]:
        """The history as the model is sent it: the user's own words that directly follow a line from the daemon (a
        report, a session's full final message, a note) carry OWN_WORDS, so they cannot be read as part of it. From a
        live call: a request said right after a session's message was refused as "a line in its message, not from you"."""
        messages = self.messages if messages is None else messages
        out = []
        for i, m in enumerate(messages):
            before = messages[i - 1] if i else {}
            if (m["role"] == "user" and not m["content"].lstrip().startswith("[")
                    and before.get("role") == "user" and before["content"].lstrip().startswith("[")):
                m = {**m, "content": OWN_WORDS + m["content"]}
            elif m["role"] == "user" and OWN_WORDS.strip() in m["content"]:  # a session's text must not carry the mark itself
                m = {**m, "content": m["content"].replace(OWN_WORDS.strip(), "[…]")}
            out.append(m)
        return out

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

    @staticmethod
    def _chars(m: dict) -> int:
        """A message's size as the vendors send it."""
        if m["role"] == "user":
            return len(m["content"])
        if m["role"] == "assistant":
            return len(json.dumps(m["calls"], ensure_ascii=False, default=str)) + len(m.get("said") or "")
        return len(json.dumps(m["results"], ensure_ascii=False, default=str))

    def history_tokens(self) -> int:
        return int(sum(map(self._chars, self.messages)) / self._chars_per_token)

    def _calibrate(self, chars: int, tokens: int) -> None:
        """The vendor's count of what was just sent corrects the chars-per-token guess the budget runs on."""
        if chars > 0 and tokens > 0:
            self._chars_per_token = min(6.0, max(1.5, chars / tokens))

    @staticmethod
    def _capped(result: object) -> object:
        text = json.dumps(result, ensure_ascii=False, default=str)
        return result if len(text) <= MAX_RESULT_CHARS else {"cut": True, "result": text[:MAX_RESULT_CHARS] + "…"}

    @staticmethod
    def _shrunk(m: dict, superseded: bool) -> dict | None:
        """An old message, small: feed items keep their first line, old tool results a stub, a [right now] block that a
        later one replaced goes (None). Assistant turns stay: their calls are short, and the results need them."""
        if m["role"] == "user":
            text = m["content"]
            if text.startswith("[right now]"):
                return None if superseded else m
            if text.startswith("[") and len(text) > STUB_CHARS:
                return {"role": "user", "content": text[:STUB_CHARS].rstrip() + OLD_NEWS}
            return m
        if m["role"] == "tool":
            results = [r if len(json.dumps(r["result"], ensure_ascii=False, default=str)) <= STUB_CHARS
                       else {**r, "result": OLD_RESULT} for r in m["results"]]
            return m if results == m["results"] else {**m, "results": results}
        return m

    def _trim(self) -> None:
        """The history stays under its token budget. The newest turns stay as they came; before them, the oldest items
        shrink first (see _shrunk), then whole turns go from the front. Never between a call and its result: the vendors
        refuse a pending call whose turn was edited. A trim edits the replay, so vendor state (raw) goes with it."""
        if self._tools_running or (self.messages and self.messages[-1]["role"] == "tool"):
            return
        sizes = [self._chars(m) for m in self.messages]
        total = sum(sizes)
        if len(self.messages) <= MAX_MESSAGES and total / self._chars_per_token <= HISTORY_TOKENS:
            return
        goal = HISTORY_AFTER_TRIM * self._chars_per_token
        recent, tail = len(self.messages), 0
        while recent > 0 and tail + sizes[recent - 1] <= RECENT_TOKENS * self._chars_per_token:
            recent -= 1
            tail += sizes[recent]
        while recent < len(self.messages) and self.messages[recent]["role"] != "user":
            recent += 1
        recent_ids = {id(m) for m in self.messages[recent:]}
        newest_now = max((i for i, m in enumerate(self.messages)
                          if m["role"] == "user" and m["content"].startswith("[right now]")), default=-1)
        kept = []
        for i, m in enumerate(self.messages):
            stale_now = i != newest_now and m["role"] == "user" and m["content"].startswith("[right now]")
            if i < recent and (total > goal or stale_now):  # a replaced [right now] block is waste whatever the total
                small = self._shrunk(m, superseded=i != newest_now)
                total -= sizes[i] - (self._chars(small) if small else 0)
                if small is None:
                    continue
                m = small
            kept.append(m)
        cut = 0
        while cut < len(kept) and id(kept[cut]) not in recent_ids and (total > goal or len(kept) - cut > MAX_MESSAGES):
            total -= self._chars(kept[cut])
            cut += 1
        while cut < len(kept) and kept[cut]["role"] != "user":  # a history starts with the user, never a reply
            cut += 1
        before = sum(sizes)
        self.messages = [{k: v for k, v in m.items() if k != "raw"} for m in kept[cut:]]  # vendors refuse edited replays
        logger.info(f"brain history trimmed: ~{int(before / self._chars_per_token)} -> ~{self.history_tokens()} tokens, "
                    f"{len(sizes)} -> {len(self.messages)} messages")

    async def turn(self, text: str | None = None) -> None:
        """One reply: tools as needed, then speech. A turn that is interrupted leaves a valid history behind.
        The user's own words are answered first: session news (bracketed) that arrives while a turn on their words is
        waiting or running is added after that turn, then answered. From a live run: a typed request followed at once by
        a queued report was never sent, because the model answered the report, the newest message."""
        user = text is not None and not text.lstrip().startswith("[")
        if text is not None and not user and self._user_turns:
            self._after_user.append((text, True))
            return
        generation = self._generation
        if text is not None:
            self._resuming = text.startswith("[resume]")  # the daemon asks for the rest of a report talked over
        if user:
            self._user_turns += 1
        try:
            before = len(self.messages)
            if text is not None:
                self.append(text)
            mine = self.messages[-1] if len(self.messages) > before else None  # None: it waits behind a running tool
            async with self._lock:
                if generation != self._generation:
                    return  # the words stay in the history; the turn that follows answers them
                if mine is not None and not user and mine is self._answered:
                    # Two lines from the daemon back to back (the opening, then "your brain dump is still here"): the
                    # first turn's step read the history with this line as its newest message, and its reply was spoken.
                    logger.info(f"turn skipped, the reply before it already answered this: {text[:80]!r}")
                    return
                unasked = text is not None and (conversation.is_update(text) or bool(conversation.BATCH_HEAD.match(text)))
                await self._run(generation, not unasked, text)
        finally:
            if user:
                self._user_turns -= 1
        if user and not self._user_turns and self._after_user:
            held, self._after_user = self._after_user, []
            for news, reply in held:
                if reply:
                    await self.turn(news)
                else:
                    self.add_news(news)

    def _asked(self) -> str:
        """The user's own latest words, not session news (which arrives bracketed)."""
        return next((m["content"] for m in reversed(self.messages) if m["role"] == "user"
                     and isinstance(m.get("content"), str) and not m["content"].startswith("[")), "")

    async def _run(self, generation: int, user: bool = True, trigger: str | None = None) -> None:
        """`user`: this turn answers the user's words or something they just did. A turn nobody asked for (a report, a
        nudge: conversation.is_update) never says "one sec" or "say that again": the user said nothing, and may be
        thinking."""
        decls = self._decls()
        sent, retries, filled, refused, shortened = False, 0, not user, False, False
        self._trigger = trigger or ""
        own_words = trigger is not None and not trigger.lstrip().startswith("[")  # not a report, a click or a mode's line
        ahead_checked = not own_words
        early = ""  # the first sentence of the reply, once it was said while the model still wrote the rest (_say_first)
        for _ in range(MAX_STEPS):
            self._trim()
            now = self.context()
            if now != self._given:  # appended, never edited: vendors cache the prefix, and some refuse an edited one
                self.append(now)
                self._given = now
            started = time.time()
            sent_chars = sum(map(self._chars, self.messages)) + len(self.instructions) + len(json.dumps(decls, ensure_ascii=False))
            carried = bool(early)  # said in an earlier step: this one was asked for what follows it
            live = Reply(lambda at: self.stage("first_token", at)) if (
                own_words and not early and self.speak_first and self.speak_rest and self.may_speak_early()) else None
            saying = asyncio.ensure_future(self._say_first(live, generation, sent, refused, trigger)) if live else None
            try:
                step, filled = await self._step(decls, filled, live, (lambda at: self.stage("brain_sent", at)) if own_words else None)
                if live and saying:
                    live.over = True
                    live.grew.set()
                    early = await saying
            except asyncio.CancelledError:
                self._heard_only(saying, early)
                if generation != self._generation:
                    return
                raise
            except Exception as e:
                logger.error(f"brain failed: {type(e).__name__}: {str(e)[:200]}")
                self._repair()
                if self._heard_only(saying, early):  # they have an answer's first sentence: no "say that again" on top of it
                    return
                vendor = vendors.refused_key(f"{type(e).__name__} {e}")
                if vendor is not None:
                    line = None if self._key_refusal_said else self.key_refused(vendor or self.choice.split(":")[0])
                    self._key_refusal_said = True
                    if line:
                        await self.speak(line)
                    return
                # A step past the timeout is the model being slow, not a lost connection: the words must not say otherwise
                if user:
                    await self.speak(SLOW_LINE if isinstance(e, TimeoutError) else LOST_LINE)
                return
            finally:
                self._current = None
                if saying and not saying.done():
                    saying.cancel()
            if generation != self._generation:
                self._heard_only(saying, early)
                return
            ms = int((time.time() - started) * 1000)
            if own_words:
                self.stage("reply")
            self._calibrate(sent_chars, step.usage.get("context") or 0)
            self.on_usage({**step.usage, "ms": ms})
            calls = step.calls
            if not calls and step.said:  # a vendor without forced tool use answered in plain text
                calls = [{"id": "text", "name": "speak", "args": {"text": step.said}, "plain": True}]
            if not calls:
                if early:
                    self._spoke(early)
                elif user and not self.terse():
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
            speaks = [c for c in calls if c["name"] == "speak"]
            for call in speaks[:-1]:  # a draft and its rewrite in one step: one reply per turn, the last
                logger.info(f"speak dropped, a later one in the same step replaces it: {call['args'].get('text', '')!r}")
                results[call["id"]] = "replaced by your next speak call: one reply per turn"
            asked = self._asked()
            limit = self.limit(trigger, asked)
            for call in speaks[-1:]:
                said = plain(str(call["args"].get("text", "")))
                if early and not said.startswith(early):  # asked to go on from the sentence already said: checked as one reply
                    said = f"{early} {said}".strip()
                problem = self.speech_problem(said, sent, refused) if retries < 2 else None
                if not problem and not ahead_checked and retries < 2:
                    # Sent back once, with the reason: whether the user's words ask for that news is the model's call.
                    problem, ahead_checked = self.news_ahead(said, asked), True
                if not problem and not shortened and retries < 2:
                    # Over on words, sent back once: the model shortens better than a cut does. A second long one, and one
                    # over only on sentences, is cut in code below: that costs no model step before the first sound.
                    problem, shortened = conversation.retry_problem(without_closer(said), limit), True
                if problem:
                    retries += 1
                    logger.info(f"speech refused: {said!r}: {problem[:160]}")
                    # With its first sentence said, the step that follows costs the user no wait: that sentence is playing.
                    results[call["id"]] = {"error": f"Not spoken. {problem}" + self._heard_note(early, limit)}
                elif generation != self._generation:
                    if early:
                        self._spoke(early)
                    results[call["id"]] = {"interrupted": True}
                    done = True
                else:
                    if call.get("plain"):
                        self.messages.append({"role": "assistant", "calls": [], "said": said, "raw": step.raw, "vendor": step.vendor})
                    said = without_repeat(without_closer(said), self._last_spoken)
                    now = time.time()
                    self._recent_spoken = [(t, x) for t, x in self._recent_spoken if now - t < REPEAT_WINDOW_SECS]
                    # A report the user talked over comes back ([resume]): it was sent whole but heard only in part,
                    # so it is no repeat. The answer to a status question ("what's going on everywhere") asks for the
                    # state again, so it is said whole; only that answer: the turns after it are filtered as ever.
                    whole = self._resuming or (not self._answered_user and status_intent(asked))
                    trimmed = said if whole else without_recent_repeats(said, [x for _, x in self._recent_spoken], asked)
                    if trimmed != said:
                        logger.info(f"repeat cut: {said!r} -> {trimmed!r}")
                        # A first answer to new words must still say something; a second reply to the same words need not.
                        said = trimmed if (trimmed or self._answered_user) else said
                    if carried and said.startswith(early):  # sent back, it may say that sentence again in other words
                        said = f"{early} {without_recent_repeats(said[len(early):].strip(), [early], '')}".strip()
                    cut = conversation.trim(said, limit)
                    if cut != said:
                        logger.info(f"length cut: {len(said.split())} -> {len(cut.split())} words")
                        said = cut
                    if early:  # what follows the sentence already said; a reply the filters changed from its start has none
                        rest = said[len(early):].strip() if said.startswith(early) else ""
                        if not said.startswith(early):
                            logger.info(f"the rest of the reply dropped, it no longer follows its first sentence: {said!r}")
                        said = f"{early} {rest}".strip()
                        self._spoke(said)
                        await self.speak_rest(rest, said)
                        results[call["id"]] = "spoken"
                        done = True
                        continue
                    if said and self.translate and self.language_problem(said):  # it was told twice; the user must still follow
                        said = await self.translate(said)
                        if generation != self._generation:  # the user moved on while it was translated
                            said = ""
                    if said:  # empty: the right reply to "okay, thanks" can be silence
                        self._spoke(said)
                        if own_words:
                            self.stage("checked")
                        await self.speak(said)
                    results[call["id"]] = "spoken"
                    done = True
            if real:
                self.messages.append({"role": "tool", "results": [
                    {"id": c["id"], "name": c["name"], "result": self._capped(results.get(c["id"]))} for c in real]})
            self._tools_running = False
            waiting, self._waiting = self._waiting, []
            for text in waiting:
                self.append(text)
            if done or generation != self._generation:
                return
        if early:
            self._spoke(early)
        elif user:
            await self.speak("That took too many steps, so I stopped. Tell me what you need first.")

    @staticmethod
    def _heard_note(early: str, limit: conversation.Limit | None) -> str:
        """For a reply sent back after its first sentence was said: what was heard, and the room that is left. From a
        live run: told only its limit, the model wrote a second sentence as long as before, and the cut took it all."""
        if not early:
            return ""
        if limit is None:
            return HEARD_FIRST.format(early)
        sentences = max(limit.sentences - 1, 1)
        return HEARD_FIRST.format(early) + HEARD_ROOM.format(
            max(limit.words - conversation.count_words(early), 5), "one sentence" if sentences == 1 else f"{sentences} sentences")

    def _spoke(self, said: str) -> None:
        self._last_spoken = said
        self._recent_spoken.append((time.time(), said))
        self._answered_user = True
        self._answered = self._view

    def _heard_only(self, saying: asyncio.Task | None, carried: str = "") -> str:
        """A reply ended (the user spoke, the model failed) after its first sentence was said: the history keeps what
        the user heard, or the next reply would say it again. `carried`: said in an earlier step, so the history has it
        already, in that step's result."""
        early = saying.result() if saying and saying.done() and not saying.cancelled() and not saying.exception() else ""
        if early and not carried:
            self.messages.append({"role": "assistant", "calls": [], "said": early})
        if early or carried:
            self._spoke(early or carried)
        return early or carried

    async def _say_first(self, live: Reply, generation: int, sent: bool, refused: bool, trigger: str | None) -> str:
        """Says the first sentence of a reply while the model still writes the rest, and returns it; "" when it waits for
        the whole reply. Every check a reply passes is put to the sentence as if it were the whole reply (a claim, a
        path, a made-up fact, news that is queued, the user's language, a repeat, the length), so nothing is heard that
        would have been sent back. The rest follows once the whole reply passed the same checks (_run)."""
        while not (first := conversation.first_sentence(plain(live.text))) and not live.over:
            live.grew.clear()
            await live.grew.wait()
        if not first or live.over or generation != self._generation:
            return ""  # one sentence, or all of it is here already: the whole reply is checked and said as ever
        self.stage("first_sentence")
        asked = self._asked()
        limit = self.limit(trigger, asked)
        if limit is None or self.may_stay_silent() or conversation.count_words(first) < EARLY_MIN_WORDS:
            return ""
        now = time.time()
        recent = [x for t, x in self._recent_spoken if now - t < REPEAT_WINDOW_SECS]
        whole = self._resuming or (not self._answered_user and status_intent(asked))
        if (self.speech_problem(first, sent, refused) or self.news_ahead(first, asked) or without_closer(first) != first
                or conversation.trim(first, limit) != first
                or not (whole or without_recent_repeats(first, recent, asked) == first)):
            logger.info("first sentence not said ahead: it waits for the whole reply's checks")
            return ""
        self.stage("checked")
        await self.speak_first(first)
        return first

    async def _step(self, decls: list[dict], filled: bool, live: Reply | None = None,
                    on_sent: Callable[[float], None] | None = None) -> tuple[vendors.Step, bool]:
        """One model step that cannot stall the call: a filler past a few seconds, the fast model past the timeout.
        `live` is told the reply as it is written, by a vendor that streams. `on_sent`: when the request left, which is
        before now for a step started ahead of its turn (foresee)."""
        choices = [c for c in (self.choice, self.fallback) if c]

        async def read(choice: str) -> vendors.Step:
            # Noted when the step reads the history, not when it was asked for: a line appended in between is in its view.
            self._view = next((m for m in reversed(self.messages) if m["role"] == "user" and m["content"] != self._given), None)
            outgoing = self._outgoing()
            seen, self._foreseen = self._foreseen, None
            if seen is not None:
                failed = seen.task.done() and (seen.task.cancelled() or seen.task.exception() is not None)
                if (not failed and seen.choice == choice and time.time() - seen.at < FORESEEN_SECS and seen.decls == decls
                        and seen.outgoing == outgoing):
                    logger.info(f"brain step was started {time.time() - seen.at:.2f} s ahead of its turn")
                    if on_sent:
                        on_sent(seen.at)
                    if live is not None and seen.relay is not None:
                        seen.relay.follow(live)
                    return await seen.task
                seen.task.cancel()
            if on_sent:
                on_sent(time.time())
            return await vendors.step(choice, self.instructions, outgoing, decls, **({"heard": live} if live else {}))

        for choice in choices:
            self._current = asyncio.ensure_future(read(choice))
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
        try:
            await asyncio.shield(running)
        except Exception as e:  # a call left without a result makes every vendor refuse the history from then on
            logger.error(f"tool {call['name']} failed: {type(e).__name__}: {str(e)[:160]}")
            outcome.setdefault("result", {"error": f"Not delivered: {call['name']} failed ({type(e).__name__}). Tell the "
                                                   f"user it did not go through."})
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

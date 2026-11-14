"""Brain dump: the user dumps their thoughts, Pointe stays quiet and keeps every word, then structures them into a prompt
(goal, context, constraints, open questions, in the user's own words) for review, and sends it to a session only when
told to. This module holds the rules: what starts and ends a dump, what counts in review, the record, the structuring
call and its guard, the prompt text, and the file that keeps a dump across a dropped call or a daemon restart.
daemon.py runs it (docs/design/brain-dump.md).

Rules enforced here, each with a test in tests/test_brain_dump.py:
- Nothing said while dumping reaches the voice model or a session; only the structured prompt does, on an explicit send.
- The prompt is the user's words: an item whose words are not mostly theirs is dropped (`invented`); when the model
  fails, the raw thoughts are the prompt.
- A dump is written to disk on every change and loaded at start, so it outlives the call and the daemon.
"""

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from guards import listen_intent, over_intent
from readout import mask

MAX_THOUGHTS = 600  # about an hour of talking at a thought per few seconds
MAX_CHARS = 60_000  # past it the oldest thoughts go, and the record says how many
THOUGHT_CHARS = 2000
PROMPT_CHARS = 12_000
SECTIONS = (("goal", "Goal"), ("context", "Context"), ("constraints", "Constraints"), ("open_questions", "Open questions"))
STATES = ("dumping", "structuring", "review")

# The page's and the app's words (ui.html DUMP_COPY, ios/Pointe/BrainDump.swift BrainDumpCopy): the three must not drift.
COPY = {
    "button": "Brain dump",
    "done": "Done",
    "title": "Brain dump",
    "lede": "Talk freely. Nothing is sent until you say so.",
    "empty": "Start talking. Every thought lands here.",
    "hint": "When you're done: tap Done, or say “done” or “over to you”.",
    "structuring": "Structuring your thoughts…",
    "reviewTitle": "Your brain dump, structured",
    "reviewLede": "In your words. Edit it, add more, or send it to a session.",
    "reviewHint": "Or say “send it to …”, “add more”, “read it back” or “discard”.",
    "addMore": "Add more",
    "discard": "Discard",
    "discardSure": "Discard the dump?",
    "send": "Send to",
    "sent": "Sent to",
    "fallback": "Pointe could not structure it; this is what you said.",
    "resumed": "Still here from earlier.",
    "state": "Brain dump",
    "review": "Review",
}

# What starts one: every brainstorm phrase (guards.listen_intent) and the new name. A whole short utterance only.
_START = re.compile(r"^\W*(?:(?:ok(?:ay)?|so|hey|pointe)\W+)*(?:(?:start |begin |open )?(?:a |my )?brain ?dump(?: mode)?|"
                    r"let me (?:just )?dump(?: (?:my|some) thoughts)?|dump mode|(?:i (?:need|want) to )?dump my thoughts)\W*$", re.I)
# What ends one: every old hand-off phrase (guards.over_intent) and plain "done". "Send that to X" ends it too, with X
# preselected; the send itself waits for review (daemon).
_DONE = re.compile(r"^\W*(?:(?:ok(?:ay)?|so|right|alright|and)\W+)*(?:done|i'?m done|all done|that'?s (?:all|my dump|the dump)|"
                   r"structure (?:it|that|this|them)|wrap (?:it|that) up|make (?:it|that) a prompt|סיימתי|זהו|תסדר את זה)\W*$", re.I)
_SEND_TO = re.compile(r"^\W*(?:(?:ok(?:ay)?|so|right|alright|and|yes|yeah)\W+)*(?:send|ship|give|pass) (?:it|that|this|the dump|the prompt)"
                      r"(?: (?:over|on|out))?(?: to (?P<to>[\w./ -]+?))?\W*$|^\W*(?:תשלח|שלח) את זה(?: ל(?P<to_he>[\w./ -]+?))?\W*$", re.I)
_MORE = re.compile(r"^\W*(?:(?:ok(?:ay)?|so|wait|no|hold on|actually)\W+)*(?:add more|more|not yet|one more thing|keep going|"
                   r"let me add(?: something| more)?|i(?:'ve| have) got more|עוד|רגע, עוד|עוד משהו)\W*$", re.I)
_DISCARD = re.compile(r"^\W*(?:(?:ok(?:ay)?|so|no|actually)\W+)*(?:discard(?: (?:it|that|this|the dump))?|forget (?:it|that|this|the dump)|"
                      r"scrap (?:it|that|this)|throw (?:it|that) (?:away|out)|drop (?:it|that|the dump)|never mind|"
                      r"תמחק את זה|תשכח מזה|עזוב)\W*$", re.I)
_READ = re.compile(r"^\W*(?:(?:ok(?:ay)?|so|please)\W+)*(?:read (?:it|that|the prompt)(?: back| out| to me| aloud)?|"
                   r"what did you (?:get|make)|תקריא(?: את זה)?)\W*$", re.I)


def _lower(text: str) -> str:
    return (text or "").strip().lower()


def start_intent(text: str) -> bool:
    """"Brain dump", "just listen", "let me think out loud": a whole short utterance."""
    return listen_intent(text) or bool(_START.match(_lower(text)))


def done_intent(text: str) -> bool:
    """"Done", "over to you", "what do you think", "send that to X": a whole short utterance."""
    return over_intent(text) or bool(_DONE.match(_lower(text)))


def send_target(text: str) -> str | None:
    """"Send it to billing" names where it goes; "send it" (no name) is the empty string; None when it is not a send."""
    found = _SEND_TO.match(_lower(text))
    if not found:
        return None
    return (found.group("to") or found.group("to_he") or "").strip()


def discard_intent(text: str) -> bool:
    """"Discard", "forget it", "never mind": a whole short utterance, while dumping or in review."""
    return bool(_DISCARD.match(_lower(text)))


def review_intent(text: str) -> str | None:
    """What the user asks in review: send | more | discard | read, else None (ordinary speech)."""
    lowered = _lower(text)
    if send_target(text) is not None:
        return "send"
    if _MORE.match(lowered):
        return "more"
    if _DISCARD.match(lowered):
        return "discard"
    if _READ.match(lowered):
        return "read"
    return None


def strip_start(text: str) -> str:
    """The words after the start phrase, when the user ran straight on: "Brain dump. The checkout is slow." keeps the
    thought. Fewer than three words is the phrase's own tail ("just listen, okay")."""
    rest = re.sub(r"^\W*(?:(?:ok(?:ay)?|so|hey|pointe)\W+)*(?:brain ?dump(?: mode)?|dump mode|let me (?:just )?dump(?: my thoughts)?|"
                  r"just listen|listen mode|monologue(?: mode)?|let me (?:just )?(?:think(?: (?:out )?loud| aloud)?|talk)|"
                  r"i(?:'m| am) (?:just )?thinking (?:out )?loud|רק תקשיב|תקשיב רגע|תן לי לחשוב(?: בקול)?|אני חושב בקול)\W*", "",
                  text or "", flags=re.I)
    return rest if len(rest.split()) >= 3 else ""


# ---------- the record ----------

@dataclass
class Thought:
    text: str
    at: float


@dataclass
class Dump:
    id: str = field(default_factory=lambda: f"d{int(time.time() * 1000)}")
    since: float = field(default_factory=time.time)
    state: str = "dumping"
    thoughts: list[Thought] = field(default_factory=list)
    dropped: int = 0  # thoughts that fell out of the window (MAX_CHARS)
    structured: int = 0  # how many thoughts the prompt covers; "add more" folds the rest in at the next done
    prompt: dict | None = None  # {goal, context, constraints, open_questions, text} once structured
    target: str | None = None  # the session named for the send, when one was
    problem: str | None = None  # why the last action was refused, for the screen
    resumed: bool = False  # came back from the file after a dropped call or a restart
    fallback: bool = False  # the model could not structure it: the prompt is the raw thoughts

    def add(self, text: str) -> Thought | None:
        text = re.sub(r"\s+", " ", text or "").strip()[:THOUGHT_CHARS]
        if not text:
            return None
        thought = Thought(text, time.time())
        self.thoughts.append(thought)
        while (len(self.thoughts) > MAX_THOUGHTS or sum(len(t.text) for t in self.thoughts) > MAX_CHARS) and len(self.thoughts) > 1:
            self.thoughts.pop(0)
            self.dropped += 1
        return thought

    @property
    def said(self) -> str:
        return " ".join(t.text for t in self.thoughts)

    @property
    def text(self) -> str:
        """What a send delivers: the edited or structured prompt, else the raw thoughts."""
        return (self.prompt or {}).get("text") or render({"context": [t.text for t in self.thoughts]})

    def status(self) -> dict:
        return {"id": self.id, "state": self.state, "since": self.since,
                "thoughts": [asdict(t) for t in self.thoughts], "dropped": self.dropped,
                "prompt": self.prompt, "target": self.target, "problem": self.problem, "resumed": self.resumed,
                "fallback": self.fallback}

    def compat(self) -> dict:
        """The old status field, for an app that still reads `monologue`."""
        return {"since": self.since, "said": self.said[-600:]}


# ---------- the file ----------

def save(path: Path, dump: Dump | None) -> None:
    """Every change goes to disk, so a dropped call or a restart loses nothing. None removes the file."""
    if dump is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(dump), ensure_ascii=False))
    tmp.replace(path)


def load(path: Path) -> Dump | None:
    """The dump left by the last run, marked resumed; a structuring that was cut comes back as dumping."""
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    try:
        dump = Dump(**{**raw, "thoughts": [Thought(**t) for t in raw.get("thoughts", [])]})
    except TypeError:
        return None
    if dump.state not in STATES or (not dump.thoughts and dump.prompt is None):
        return None
    if dump.state == "structuring":
        dump.state = "dumping"
    dump.resumed, dump.problem = True, None
    return dump


# ---------- structuring ----------

SYSTEM = ("You turn someone's spoken thoughts into a structured brief for a coding agent. Use only their words: quote or "
          "lightly trim each thought, keep their language, fix nothing but obvious speech fillers. Never add a requirement, "
          "an assumption, a solution or a fact they did not say. Group each thought under one key: goal (what they want, "
          "one line, empty string if they never said), context (what is going on, what they observed), constraints (what "
          "must or must not happen), open_questions (what they are unsure about). A thought that fits nowhere goes to "
          "context. Reply with JSON only: {\"goal\": string, \"context\": [strings], \"constraints\": [strings], "
          "\"open_questions\": [strings]}.")


def structure_prompt(thoughts: list[str], existing: str = "") -> str:
    body = "\n".join(f"- {t}" for t in thoughts)
    if existing:
        return (f"An earlier structured brief, already reviewed:\n{existing}\n\nNew thoughts to fold in, in order:\n{body}\n\n"
                "Return the whole brief again with the new thoughts placed; keep the existing lines as they are.")
    return f"The thoughts, in order:\n{body}"


_STOP = set("the a an and or but of to in on for with is are was were be it this that we you i they he she at by as from "
            "so if then than just like really maybe also about my our your its not no yes do does did have has had will "
            "would can could should what which who how why when there here".split())


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[\w']+", (text or "").lower()) if w not in _STOP and len(w) > 1}


def invented(item: str, said: str) -> bool:
    """An item whose content words are not mostly in what the user said: the model added something. Short items (one or
    two content words) pass when any word is theirs."""
    words = _words(item)
    if not words:
        return True
    theirs = _words(said)
    hit = len(words & theirs) / len(words)
    return hit < (0.5 if len(words) > 2 else 0.01)


def parse(reply: str, said: str) -> dict:
    """The model's JSON as the four sections, each item checked against the user's words. Raises on no JSON."""
    text = reply.strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\s*|\s*```$", "", text)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("not an object")
    out: dict = {}
    for key, _ in SECTIONS:
        value = data.get(key, "" if key == "goal" else [])
        items = [value] if isinstance(value, str) else [str(v) for v in (value or []) if isinstance(v, (str, int, float))]
        items = [mask(re.sub(r"\s+", " ", i).strip()) for i in items]
        items = [i for i in items if i and not invented(i, said)]
        out[key] = (items[0] if items else "") if key == "goal" else items
    if not out["goal"] and not any(out[k] for k, _ in SECTIONS[1:]):
        raise ValueError("nothing survived")
    return out


def render(sections: dict) -> str:
    """The prompt as it is shown and sent: a heading per section, the user's items under it. Empty sections are left out,
    except Goal, which says so."""
    lines = ["Brain dump from the user, in their own words, structured; nothing added:"]
    goal = (sections.get("goal") or "").strip()
    lines.append(f"Goal: {goal}" if goal else "Goal: (not stated)")
    for key, label in SECTIONS[1:]:
        items = [i for i in (sections.get(key) or []) if str(i).strip()]
        if items:
            lines.append(f"{label}:")
            lines += [f"- {i}" for i in items]
    return "\n".join(lines)[:PROMPT_CHARS]


def structured(sections: dict) -> dict:
    """The prompt field: the sections and their text."""
    return {**{k: sections.get(k, "" if k == "goal" else []) for k, _ in SECTIONS}, "text": render(sections)}


def fallback(thoughts: list[str]) -> dict:
    """The model failed or is not there: what the user said, under Context, still a prompt."""
    return {"goal": "", "context": list(thoughts), "constraints": [], "open_questions": [],
            "text": render({"context": thoughts})}


def edited(text: str) -> dict:
    """The user rewrote the text: the text is the prompt; the sections are no longer separately known."""
    text = (text or "").strip()[:PROMPT_CHARS]
    return {"goal": "", "context": [], "constraints": [], "open_questions": [], "text": text}


# ---------- what the voice is told ----------

def review_line(dump: Dump) -> str:
    n = len(dump.thoughts)
    fell = f" The {dump.dropped} oldest thought(s) fell off the end; the rest is here." if dump.dropped else ""
    how = ("Pointe could not structure it, so the prompt is their words as said." if dump.fallback else
           "It is structured on their screen.")
    return (f"[brain dump ready] The user dumped {n} thought(s) and said done. {how}{fell} Say, in one short sentence in "
            "their language: their brain dump is ready to review; they can send it, add more, or discard. Nothing was "
            "sent. Do not summarise or repeat it; do not call any tool.")


def read_line(dump: Dump) -> str:
    return (f"[read the brain dump back] Read this to the user, word for word, nothing added, then stop:\n{dump.text}\n"
            "[end of the dump] Do not call any tool.")


def sent_line(dump: Dump, session: str) -> str:
    return (f"[brain dump sent] The user's reviewed brain dump went to {session}, word for word, by their explicit send. "
            "Say so in one short sentence in their language; do not repeat it, do not call any tool.")


def resumed_line(dump: Dump) -> str:
    n = len(dump.thoughts)
    if dump.state == "review":
        return (f"[brain dump still here] A brain dump from earlier ({n} thought(s)) is structured and waiting for review on "
                "their screen. Say in one short sentence: it is still here; they can send it, add more, or discard. Do not "
                "repeat it; do not call any tool.")
    return (f"[brain dump still here] The user was dumping thoughts ({n} so far) when the call ended, and the dump is still "
            "on. Say in one short sentence: their brain dump is still here; keep going, say done, or discard. Then stay "
            "quiet. Do not call any tool.")


def sent_header(session: str) -> str:
    return f"[from the user, by voice: their brain dump, structured for {session}]"

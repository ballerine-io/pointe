"""Night shift (docs/design/night-shift.md): the user gives tasks for their sessions in the evening, Pointe keeps the
sessions moving while they sleep, and the morning briefing leads with what was decided without them.

The rules live here, in code: what the user's words ask for (the sessions and the tasks are spans of what they said,
never a model's arguments), the only messages a shift may send (fixed templates around the user's task), what a
session's report means, what happens next, the caps, the ledger and the morning report. No Pipecat and no HTTP here;
daemon.py carries the actions out.

Nothing in this module answers a permission request, and nothing in it can: a request is recorded, word for word, as
Blocked, and waits for the user.
"""

import json
import os
import re
import secrets
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import readout

HOURS = 8.0  # a shift ends after this long
MAX_HOURS = 12.0
MESSAGES = 40  # messages a shift may send to sessions
MAX_MESSAGES = 200
FOLLOWUPS = 3  # per task, after its brief
MAX_FRONTS = 8
MAX_TASKS = 5  # per session
MAX_TASK_CHARS = 2000
HISTORY = 7
CONFIRM_SECS = 60.0  # how long a read-back can still be answered yes
WORDS_PER_SEC = 2.8  # about how fast the voice says a read-back: the minute for a yes starts when it has been said
STALL_SECS = 600.0  # a task in flight, the session idle, and no report for this long: one status follow-up
PARK_SECS = 12 * 3600.0  # how long a shift session's approval request is held for the user
START_WAIT_SECS = 150.0  # a new session on the plan that has not joined by then is Blocked

RULE = "I approve nothing: a session that needs approval waits for you."
THIS_MAC_ONLY = "A night shift runs sessions on this Mac only in this version."

# ---------- the only messages a shift sends ----------

REPORT_BLOCK = """NIGHT REPORT
STATUS: done | blocked | working
DONE: what you finished, with the proof (commit, pull request, test output)
BLOCKED: what waits, and on whom
DECIDED: the question -> what you chose -> what changes if the user chooses otherwise"""

_LIMITS = ("Do nothing destructive or outward-facing that the task does not ask for. If a step needs the user's "
           "approval, a credential or a decision only they can make, do not work around it: list it under BLOCKED and "
           "move to the other parts of the task.")

TEMPLATES = {
    "task": ("[Night shift. The user is away until morning and left this task before leaving.]\nTask: {task}\n\n"
             "Rules for tonight:\n- Keep going on anything that is not blocked. Do not stop to ask a question: choose "
             "the most defensible answer, write it down under DECIDED, and carry on.\n- " + _LIMITS + "\n- End your "
             "turn with this report, with exactly these labels, one item per line (leave out a label with nothing "
             "under it):\n" + REPORT_BLOCK),
    "continue": ("[Night shift. The user is still away.] Keep going on the task: {task}\n" + _LIMITS + "\nWhen you "
                 "stop, end with the NIGHT REPORT block (STATUS, DONE, BLOCKED, DECIDED)."),
    "decide": ("[Night shift. The user is away until morning and cannot answer.] Do not wait for an answer. Choose the "
               "most defensible option yourself and keep going on the task: {task}\nWrite each choice as a line "
               "\"DECIDED: the question -> what you chose -> what changes if the user chooses otherwise\". If it is a "
               "decision only the user can make, or it needs their approval, do not take it: list it under BLOCKED and "
               "do the rest. " + _LIMITS + "\nEnd with the NIGHT REPORT block (STATUS, DONE, BLOCKED, DECIDED)."),
    "report": ("[Night shift. The user is away until morning.] Say where the task stands: {task}\nIf there is more you "
               "can do without the user, do it first. " + _LIMITS + "\nThen end with this report, with exactly these "
               "labels, one item per line:\n" + REPORT_BLOCK),
    "status": ("[Night shift. The user is away until morning.] Nothing has come from you for a while on the task: "
               "{task}\nIf you are done, say so. If you wait on something, list it under BLOCKED and do the rest. "
               + _LIMITS + "\nEnd with this report, with exactly these labels, one item per line:\n" + REPORT_BLOCK),
}


def message(kind: str, task: str) -> str:
    """The text a shift sends: a fixed template around the user's own task. There is no other way to make one."""
    return TEMPLATES[kind].replace("{task}", task)


# ---------- what the user's words ask for ----------

_OPENER = re.compile(
    r"^\W*(?:(?:ok(?:ay)?|hey|so|and|pointe|please|alright)\W+)*"
    r"(?:(?:for\s+|on\s+)?(?:the\s+)?(?:night\s*shift)(?:\s+(?:tonight|plan|is|for\s+tonight))*"
    r"|(?:start|run|begin|do|set\s+up)\s+(?:a|the|tonight'?s)\s+night\s*shift(?:\s+(?:tonight|with|where))?"
    r"|(?:for\s+)?tonight|overnight|over\s+the\s+night|while\s+i\s+sleep"
    r"|הלילה|משמרת\s+לילה|למשמרת\s+הלילה)(?![\w'])\W*", re.I)
_STOP = re.compile(
    r"^\W*(?:(?:ok(?:ay)?|hey|so|pointe|please|no)\W+)*(?:stop|end|cancel|abort|halt|kill|call\s+off)\s+"
    r"(?:the\s+|tonight'?s\s+|this\s+)?(?:night\s*shift|shift)\W*(?:please|now)?\W*$"
    r"|^\W*(?:עצור|תעצור|תעצרי|בטל|תבטל|תבטלי|הפסק|תפסיק)\s+את\s+(?:משמרת\s+הלילה|המשמרת)\W*$", re.I)
_APPROVE = re.compile(r"\b(?:approve|allow|authori[sz]e|unblock|release|green\s*light|let)\b|(?<!\w)(?:אשר|תאשר|תאשרי|שחרר|תשחרר)(?!\w)", re.I)
_TELLS = re.compile(r"\b(?:tell|ask|remind|instruct)\b|(?<!\w)(?:תגיד|תגידי|תבקש|תבקשי)(?!\w)", re.I)
_TOKEN = re.compile(r"[^\W_]+(?:['’\-][^\W_]+)*|[,.;:!?]")
_SEPS = {",", ".", ";", ":", "!", "?"}
_JOINS = {"and", "then", "also", "plus", "next", "after", "that", "finally", "ו", "ואז", "וגם", "גם"}
_LEADS = {"tell", "ask", "have", "let", "get", "make", "תגיד", "תבקש"}
_ARTICLES = {"the", "my", "our"}
_TASK_LEAD = re.compile(r"^\W*(?:(?:session|agent)\b\W*)?(?:(?:to|should|shall|will|can|must|has\s+to|needs\s+to|"
                        r"is\s+going\s+to|please|ש)\b\W*)*", re.I)
_START_TASK = re.compile(r"^\W*(?:(?:called|named)\s+[\w-]+\W*)?(?:(?:to|and|that\s+(?:will|should)|which\s+(?:will|should)|"
                         r"and\s+(?:have|tell|ask)\s+it\s+to|כדי\s+ל?|ש)\b\W*)+", re.I)


def shift_intent(text: str) -> str | None:
    """"Tonight: billing finishes the retry work", "night shift: ...": the words after the opening, or None. Only an
    utterance that opens with it: "what did the night shift do" is not one."""
    m = _OPENER.match(text or "")
    return text[m.end():].strip() if m else None


def stop_intent(text: str) -> bool:
    """A whole short utterance: "stop the night shift". A stop needs no read-back and counts from any voice."""
    return bool(_STOP.match(text or ""))


def release_intent(text: str, waiting: list) -> object | None:
    """"Approve billing's push": the one waiting session these words name, or None. It approves nothing: the daemon
    reads that session's exact request out, and only the yes after it counts. "Tell billing to approve the PR" is a
    send."""
    from sessions import _hears

    said = text or ""
    if not _APPROVE.search(said) or _TELLS.search(said):
        return None
    tokens = [t.lower() for t in re.findall(r"[^\W_]+", said.replace("'s", " ").replace("’s", " "))]
    found = [s for s in waiting if any(all(any(_hears(w, t) for t in tokens) for w in words) for words in _said_words(s.name))]
    return found[0] if len(found) == 1 else None


@dataclass
class Item:
    """One line of a plan: a session on the voice and its task, or a new session to start and its task."""
    task: str
    session_id: str = ""
    name: str = ""
    start: dict | None = None  # {harness, folder, name}: checked by the daemon exactly as New session is

    def view(self) -> dict:
        return {"session": self.name, "task": self.task, "new": bool(self.start),
                "harness": (self.start or {}).get("harness")}


@dataclass
class Plan:
    items: list[Item] = field(default_factory=list)
    problem: str = ""  # fixed words for the user: the one thing to ask before any read-back


def _toks(text: str) -> list[tuple[str, int, int]]:
    return [(m.group(0).lower(), m.start(), m.end()) for m in _TOKEN.finditer(text)]


def _said_words(name: str) -> list[list[str]]:
    """The ways a session's name is said: all of its words, or only the ones that tell it apart ("billing" for
    billing/main: nobody says the branch). A name with no such word has only the first way."""
    from sessions import _distinctive, _name_words

    words = _name_words(name)
    told = [w for w in words if _distinctive(w)]
    return [w for w in (words, told) if w] if told != words else ([words] if words else [])


def _name_at(tokens: list[tuple[str, int, int]], i: int, sessions: list) -> tuple[list, int]:
    """The sessions whose name is said from token i, and how many tokens it took. The longest name wins; two sessions
    heard in the same words are both returned: a tie, never a guess."""
    from sessions import _hears

    best, size = [], 0
    for s in sessions:
        for words in _said_words(s.name):
            if i + len(words) > len(tokens) or not all(_hears(w, tokens[i + k][0]) for k, w in enumerate(words)):
                continue
            if len(words) > size:
                best, size = [s], len(words)
            elif len(words) == size and s not in best:
                best.append(s)
            break
    return best, size


def plan_request(text: str, sessions: list, places: list[tuple[str, str]] = (), machines: list[str] = (),
                 here: str = "", here_folder: str | None = None) -> Plan | None:
    """The night's plan, from the user's own words; None if they did not ask for a night shift.

    An item starts where a session's name (or a request for a new session) stands at the head of a clause and runs to
    the next head; its task is the words in between, as said. Anything unclear is a `problem`, never a guess.
    """
    from guards import start_request

    rest = shift_intent(text)
    if rest is None:
        return None
    tokens = _toks(rest)
    heads: list[tuple[int, int, int, object]] = []  # (clause start, name start token, tokens after it, session | "start")
    i, at_head = 0, True
    while i < len(tokens):
        word = tokens[i][0]
        if word in _SEPS or word in _JOINS:
            at_head, i = True, i + 1
            continue
        if at_head:
            j = i
            if tokens[j][0] in _LEADS and j + 1 < len(tokens):
                j += 1
            if tokens[j][0] in _ARTICLES and j + 1 < len(tokens):
                j += 1
            named, size = _name_at(tokens, j, sessions)
            clause_end = next((tokens[k][1] for k in range(i, len(tokens)) if tokens[k][0] in {";", ".", "!", "?"}), len(rest))
            if j == i and start_request(rest[tokens[i][1]:clause_end], list(places), list(machines), here, here_folder) is not None:
                heads.append((i, i, i, "start"))
            elif named:
                heads.append((i, j, j + size, named))
                i = j + size
                at_head = False
                continue
        at_head = False
        i += 1
    if not heads:
        return Plan(problem="Not started. Ask which session does what tonight: the user named no session that is on "
                            "the voice. A task goes to a session by its name, as in \"tonight: billing fixes the retry "
                            "tests\".")
    items: list[Item] = []
    for n, (first, _, after, who) in enumerate(heads):
        end = tokens[heads[n + 1][0]][1] if n + 1 < len(heads) else len(rest)
        if who == "start":
            clause = rest[tokens[first][1]:end]
            ask = start_request(clause, list(places), list(machines), here, here_folder)
            if ask.machine:
                return Plan(problem=f"Not started. {THIS_MAC_ONLY}")
            if ask.harnesses:
                return Plan(problem="Not started. One new session per item: ask which agent it should be.")
            if ask.ties:
                return Plan(problem="Not started. The words for the new session fit more than one folder: ask which.")
            if ask.folder is None:
                return Plan(problem="Not started. Ask where the new session should start: the user named no folder "
                                    "they already work in.")
            task = _task_of_start(clause, ask.folder, places)
            if not task:
                return Plan(problem="Not started. Ask what the new session should do tonight.")
            items.append(Item(task=task, start={"harness": ask.harness, "folder": ask.folder, "name": ask.name}))
            continue
        if len(who) > 1:
            return Plan(problem="Not started. Those words fit more than one session: ask which, "
                                + " or ".join(s.name for s in who) + ".")
        session = who[0]
        if getattr(session, "machine", ""):
            return Plan(problem=f"Not started. {session.name} runs on another machine. {THIS_MAC_ONLY}")
        begin = tokens[after][1] if after < len(tokens) else len(rest)
        task = _clean_task(rest[begin:end]) if begin < end else ""
        if not task:
            return Plan(problem=f"Not started. Ask what {session.name} should do tonight.")
        items.append(Item(task=task, session_id=session.id, name=session.name))
    return Plan(items=items, problem=limits_problem(items) or "")


def _clean_task(raw: str) -> str:
    task = _TASK_LEAD.sub("", raw.replace("’", "'"), count=1) if not raw.lstrip().startswith("'s") else raw.lstrip()[2:]
    task = re.sub(r"[\s,;:.]*(?:\b(?:and|then|also|plus)\b)?[\s,;:.]*$", "", task, flags=re.I).strip()
    return task if re.search(r"\w", task) else ""


def _task_of_start(clause: str, folder: str, places) -> str:
    """What a new session is to do: the words after its place ("... in shop to fix the flaky test")."""
    from sessions import _hears, _name_words

    tokens = _toks(clause)
    at = max((end for word, _, end in tokens if word in ("session", "agent", "thread", "here", "סשן")), default=0)
    for label, path in places:
        if path != folder:
            continue
        words = _name_words(label)
        for i in range(len(tokens) - len(words) + 1):
            if words and all(_hears(w, tokens[i + k][0]) for k, w in enumerate(words)):
                at = max(at, tokens[i + len(words) - 1][2])
    rest = clause[at:]
    m = _START_TASK.match(rest)
    return _clean_task(rest[m.end():]) if m else ""


def limits_problem(items: list[Item]) -> str | None:
    """Why a plan is too large or empty, in fixed words, or None."""
    if not items:
        return "A night shift needs at least one task."
    fronts: dict[str, int] = {}
    for n, item in enumerate(items):
        key = item.session_id or f"new:{n}"
        fronts[key] = fronts.get(key, 0) + 1
        if not item.task.strip() or len(item.task) > MAX_TASK_CHARS:
            return f"Each task needs words, at most {MAX_TASK_CHARS} characters."
    if len(fronts) > MAX_FRONTS:
        return f"A night shift takes at most {MAX_FRONTS} sessions."
    if max(fronts.values()) > MAX_TASKS:
        return f"A session takes at most {MAX_TASKS} tasks a night."
    return None


def valid_hours(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 < value <= MAX_HOURS


def valid_messages(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= MAX_MESSAGES


def said_hours(hours: float) -> str:
    if hours < 1:
        return f"{max(1, round(hours * 60))} minutes"
    whole = round(hours, 1)
    return f"{int(whole) if whole == int(whole) else whole} hour{'s' if whole != 1 else ''}"


def read_back(items: list[dict], hours: float, messages: int) -> str:
    """Exactly what a yes will start: `items` are {session, task, new, agent, folder} with names already final."""
    lines = []
    for it in items:
        who = (f"A new {it['agent']} session in {it['folder']}, named {it['session']}" if it.get("new") else it["session"])
        lines.append(f"{who}: {it['task'].rstrip('.')}.")
    return (f"Night shift. {' '.join(lines)} Up to {said_hours(hours)} and {messages} messages. {RULE} Start? "
            f"Say yes or tap.")


# ---------- what a session's report says ----------

_LABEL = re.compile(r"^[\s>*#\-•`_]*(STATUS|DONE|BLOCKED|DECIDED)\b[\s*_`]*[:\-–][\s*_`]*(.*)$", re.I)
_NOTHING = re.compile(r"^\W*(?:(?:none|nothing|n/?a|no|not applicable|-+)?\W*$|(?:nothing|none|no\s+blockers?|not\s+blocked)\b)", re.I)
_COMMIT = re.compile(r"\b(?:commit(?:ted)?(?:\s+(?:as|is|hash|sha|id))?|sha|hash)\b[^\n]{0,24}?\b([0-9a-f]{7,40})\b", re.I)
_PR_URL = re.compile(r"https://[\w.-]+/[\w.-]+/[\w.-]+/(?:pull|merge_requests)/\d+")
_PR_NUM = re.compile(r"\b(?:PR|pull request)\s*#?\s*(\d{1,6})\b", re.I)
_ARROW = re.compile(r"\s*(?:->|→|=>|—>)\s*")


@dataclass
class Outcome:
    status: str = "unclear"  # done | blocked | working | asks | unclear
    done: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    decided: list[tuple[str, str, str]] = field(default_factory=list)  # question, choice, what changes otherwise
    question: str = ""
    commit: str = ""
    pr: str = ""
    last_line: str = ""


def read_report(final: str, digest: dict | None = None) -> Outcome:
    """What a finished turn says about its task. The session's own NIGHT REPORT block decides; without one, a question
    to the user (the report digest says it waits, or its last lines ask) is `asks`; anything else is `unclear`. A
    commit or pull request is taken from the message by a regex, never from a model's summary of it."""
    final = final or ""
    lines = [ln.rstrip() for ln in final.splitlines()]
    out = Outcome(last_line=next((ln.strip() for ln in reversed(lines) if ln.strip()), "")[:300])
    marker = max((i for i, ln in enumerate(lines) if re.search(r"night\s+report", ln, re.I)), default=-1)
    status, current = "", None
    for ln in lines[marker + 1:] if marker >= 0 else lines:
        m = _LABEL.match(ln)
        if m:
            current, value = m.group(1).upper(), m.group(2).strip().strip("*_`").strip()
        elif current and ln.strip() and re.match(r"^\s+\S|^\s*[-•*]\s", ln):
            value = re.sub(r"^\s*[-•*]\s*", "", ln).strip()  # a wrapped or bulleted line under the label
        else:
            current = None if not ln.strip() else current
            continue
        if not value or _NOTHING.match(value):
            continue
        if current == "STATUS":
            status = next((w for w in ("done", "blocked", "working") if re.search(rf"\b{w}\b", value, re.I)), status)
        elif current == "DONE":
            out.done.append(value[:400])
        elif current == "BLOCKED":
            out.blocked.append(value[:400])
        elif current == "DECIDED":
            parts = [p.strip() for p in _ARROW.split(value, maxsplit=2)] + ["", ""]
            out.decided.append((parts[0][:300], parts[1][:300], parts[2][:300]))
    if marker >= 0 or status:
        out.status = status or ("blocked" if out.blocked and not out.done else "done" if out.done else "unclear")
    if out.status == "unclear":
        tail = "\n".join(ln for ln in lines if ln.strip())[-400:]
        waits = bool(digest and (digest.get("waiting") or digest.get("questions")))
        if waits or tail.rstrip().endswith("?"):
            out.status = "asks"
            asked = [str(q) for q in (digest or {}).get("questions") or []]
            out.question = (asked[0] if asked else str((digest or {}).get("need") or "") or
                            next((ln.strip() for ln in reversed(lines) if ln.strip().endswith("?")), out.last_line))[:300]
    proof = "\n".join(out.done) or final
    if m := (_COMMIT.search(proof) or _COMMIT.search(final)):
        out.commit = m.group(1)
    if m := (_PR_URL.search(proof) or _PR_URL.search(final)):
        out.pr = m.group(0)
    elif m := (_PR_NUM.search(proof) or _PR_NUM.search(final)):
        out.pr = f"#{m.group(1)}"
    return out


# ---------- the shift ----------

@dataclass
class Task:
    text: str
    state: str = "queued"  # queued | working | done | blocked | parked
    followups: int = 0
    sent_at: float = 0.0
    reported_at: float = 0.0


@dataclass
class Front:
    """One session on the shift and its queue."""
    session: str
    session_id: str = ""
    harness: str = "claude-code"
    start_id: str = ""  # a new session the shift started: not on the voice until it joins
    state: str = "working"  # starting | working | waiting | parked | finished
    tasks: list[Task] = field(default_factory=list)
    current: int = -1
    nudged_at: float = 0.0
    waiting_on: str = ""  # the request id (or "terminal") its Blocked entry was written for

    def task(self) -> Task | None:
        return self.tasks[self.current] if 0 <= self.current < len(self.tasks) else None

    def view(self) -> dict:
        task = self.task()
        return {"session": self.session, "harness": self.harness, "state": self.state,
                "task": task.text if task and task.state == "working" else "",
                "done": sum(t.state == "done" for t in self.tasks), "total": len(self.tasks)}


@dataclass
class Entry:
    id: str
    kind: str  # done | blocked | decided | asked
    session: str
    task: str
    at: float
    text: str = ""
    proof: str = ""
    commit: str = ""
    pr: str = ""
    waits_on: str = ""
    request: str = ""  # an approval request, word for word as its card shows it (masked)
    request_id: str = ""
    question: str = ""
    choice: str = ""
    otherwise: str = ""
    resolved: str = ""
    resolved_at: float = 0.0


def _m(text) -> str:
    return readout.mask(str(text or "")).strip()


@dataclass
class Shift:
    id: str
    at: float
    ends_at: float
    hours: float = HOURS
    messages: int = MESSAGES
    followups: int = FOLLOWUPS
    notify: bool = False
    how: str = "voice"
    sent: int = 0
    ended: float = 0.0
    why: str = ""  # complete | hours | messages | stopped
    fronts: list[Front] = field(default_factory=list)
    entries: list[Entry] = field(default_factory=list)

    # ----- reading it -----

    @property
    def on(self) -> bool:
        return not self.ended

    def front_of(self, session_id: str) -> Front | None:
        return next((f for f in self.fronts if f.session_id and f.session_id == session_id), None)

    def can_send(self) -> bool:
        return self.on and self.sent < self.messages

    def open_entries(self, session: str, kinds=("blocked", "asked")) -> list[Entry]:
        return [e for e in self.entries if e.session == session and e.kind in kinds and not e.resolved]

    def ledger(self) -> dict:
        """The four buckets, as the screens show them. In flight is the tasks being worked on now."""
        flight = [{"session": f.session, "task": t.text, "since": t.sent_at, "followups": t.followups}
                  for f in self.fronts for t in f.tasks if t.state == "working"]
        waiting = [{"session": f.session, "task": t.text} for f in self.fronts for t in f.tasks if t.state == "queued"]
        by = {k: [asdict(e) for e in self.entries if e.kind == k] for k in ("done", "blocked", "decided", "asked")}
        return {"done": by["done"], "in_flight": flight, "blocked": by["blocked"], "decided": by["decided"],
                "asked": by["asked"], "not_started": waiting}

    def summary(self) -> dict:
        tasks = [t for f in self.fronts for t in f.tasks]
        return {"on": self.on, "id": self.id, "at": self.at, "ends_at": self.ends_at, "ended": self.ended or None,
                "why": self.why, "sent": self.sent, "budget": self.messages, "hours": self.hours, "notify": self.notify,
                "tasks": len(tasks), "done": sum(t.state == "done" for t in tasks),
                "in_flight": sum(t.state == "working" for t in tasks),
                "blocked": len([e for e in self.entries if e.kind == "blocked" and not e.resolved]),
                "decided": sum(e.kind == "decided" for e in self.entries),
                "asked": len([e for e in self.entries if e.kind == "asked" and not e.resolved]),
                "fronts": [f.view() for f in self.fronts]}

    def to_dict(self) -> dict:
        return asdict(self)

    def view(self) -> dict:
        return {**self.summary(), "ledger": self.ledger(), "how": self.how, "morning": morning(self)}

    @staticmethod
    def from_dict(d: dict) -> "Shift":
        fronts = [Front(**{**f, "tasks": [Task(**t) for t in f.get("tasks") or []]}) for f in d.get("fronts") or []]
        return Shift(**{**d, "fronts": fronts, "entries": [Entry(**e) for e in d.get("entries") or []]})

    # ----- writing the ledger -----

    def _add(self, kind: str, front: Front, now: float, **fields) -> Entry:
        task = front.task()
        entry = Entry(id=secrets.token_hex(4), kind=kind, session=front.session, task=task.text if task else "", at=now,
                      **{k: _m(v) for k, v in fields.items()})
        self.entries.append(entry)
        return entry

    def _park_task(self, front: Front, state: str, now: float) -> None:
        task = front.task()
        if task and task.state == "working":
            task.state, task.reported_at = state, now

    # ----- the loop: each returns the kind of message to send next, or None -----

    def next_task(self, front: Front, now: float) -> str | None:
        """Jump to the front's next queued task. None when there is none (the front is finished, or parked if anything
        of its is blocked) or when the budget is spent (its tasks stay queued)."""
        nxt = next((i for i, t in enumerate(front.tasks) if t.state == "queued"), None)
        if nxt is None:
            front.current = -1
            front.state = "parked" if any(t.state in ("blocked", "parked") for t in front.tasks) else "finished"
            return None
        if not self.can_send():
            front.current, front.state = -1, "parked"
            return None
        front.current, front.state = nxt, "working"
        return "task"

    def followup(self, front: Front, kind: str, now: float, why: str = "") -> str | None:
        """One more fixed message on the task in flight, within the caps; past them the task is parked as Blocked and
        the front jumps to its next one."""
        task = front.task()
        if task is None:
            return None
        if task.followups >= self.followups:
            self._add("blocked", front, now, text=f"Did not finish in {self.followups} follow-ups.",
                      waits_on=why or "you: look at where it stopped")
            self._park_task(front, "parked", now)
            return self.next_task(front, now)
        if not self.can_send():
            return None
        task.followups += 1
        return kind

    def report(self, front: Front, outcome: Outcome, now: float) -> str | None:
        """A turn of the task in flight ended. Records what it said and returns what to send next."""
        task = front.task()
        if task is None or task.state != "working":
            return None
        task.reported_at = now
        front.nudged_at = 0.0
        if outcome.decided:  # the session took the call itself: its line replaces the question it had asked
            self.entries = [e for e in self.entries if not (e.kind == "asked" and e.session == front.session
                                                            and e.task == task.text and not e.resolved)]
        for question, choice, otherwise in outcome.decided:
            self._add("decided", front, now, question=question, choice=choice, otherwise=otherwise,
                      text=" -> ".join(p for p in (question, choice, otherwise) if p))
        for what in outcome.blocked:
            self._add("blocked", front, now, text=what, waits_on=what)
        if outcome.status == "done":
            self._add("done", front, now, text="; ".join(outcome.done) or outcome.last_line,
                      proof="; ".join(outcome.done) or outcome.last_line, commit=outcome.commit, pr=outcome.pr)
            task.state = "done"
            return self.next_task(front, now)
        if outcome.status == "blocked":
            if not outcome.blocked:
                self._add("blocked", front, now, text=outcome.last_line, waits_on="you")
            task.state = "blocked"
            return self.next_task(front, now)
        if outcome.status == "working":
            return self.followup(front, "continue", now, "you: it kept stopping before the task was done")
        if outcome.status == "asks":
            if not any(e.question == _m(outcome.question) for e in self.open_entries(front.session, ("asked",))):
                self._add("asked", front, now, question=outcome.question, text=outcome.question,
                          choice="", otherwise="")
            return self.followup(front, "decide", now, f"you: it asks \"{outcome.question}\"")
        return self.followup(front, "report", now, f"you: it gave no report; its last words: {outcome.last_line}")

    def tick(self, front: Front, now: float, present: bool, busy: bool = False, request_id: str = "", request: str = "",
             terminal_wait: str = "", stall_secs: float = STALL_SECS) -> str | None:
        """Between turns: what the keeper saw of this front. Returns a message kind to send, or None."""
        if front.state in ("finished", "parked", "starting"):
            return None
        if not present:
            self._add("blocked", front, now, text="The session closed.", waits_on="you: start it again")
            self._park_task(front, "blocked", now)
            for t in front.tasks:
                t.state = "parked" if t.state == "queued" else t.state
            front.current, front.state = -1, "parked"
            return None
        waits = request_id or ("terminal" if terminal_wait else "")
        if waits:
            if front.waiting_on != waits:
                front.waiting_on, front.state = waits, "waiting"
                self._add("blocked", front, now, request=request, request_id=request_id,
                          text="Waits for your approval." if request_id else f"Waits at {terminal_wait}.",
                          waits_on="your approval" if request_id else f"you: answer {terminal_wait}")
            return None
        if front.state == "waiting":  # answered at its own prompt, or the request went away: it works again
            self.answered(front.session_id, front.waiting_on, "", now)
        task = front.task()
        if task is None or task.state != "working" or busy:
            return None
        quiet_since = max(task.sent_at, task.reported_at, front.nudged_at)
        if now - quiet_since >= stall_secs:
            front.nudged_at = now
            return self.followup(front, "status", now, "you: it went quiet")
        return None

    def sent_to(self, front: Front, kind: str, now: float) -> None:
        self.sent += 1
        task = front.task()
        if task is not None:
            task.sent_at = now
            if kind == "task":
                task.state = "working"

    def not_delivered(self, front: Front, why: str, now: float) -> None:
        self._add("blocked", front, now, text=f"Pointe's message did not reach it. {why}".strip(),
                  waits_on="you: check that session")
        self._park_task(front, "parked", now)
        front.current, front.state = -1, "parked"

    def not_started(self, front: Front, why: str, now: float) -> None:
        front.current = 0 if front.tasks else -1
        self._add("blocked", front, now, text=f"The new session did not start. {why}".strip(), waits_on="you")
        for t in front.tasks:
            t.state = "parked"
        front.current, front.state = -1, "parked"

    def answered(self, session_id: str, request_id: str, verdict: str, now: float) -> bool:
        """The user answered a request the shift had parked (a yes after its read-out, a tap, or at its terminal). The
        entry says so and the front works again. Never called with a verdict of Pointe's own."""
        front = self.front_of(session_id)
        if front is None or not front.waiting_on or (request_id and front.waiting_on not in (request_id, "terminal")):
            return False
        word = {"allow": "approved by you", "deny": "denied by you"}.get(verdict, "answered at its own prompt")
        for e in self.entries:
            if e.kind == "blocked" and e.session == front.session and not e.resolved and \
                    (e.request_id == front.waiting_on or (front.waiting_on == "terminal" and not e.request_id and "Waits at" in e.text)):
                e.resolved, e.resolved_at = word, now
        front.waiting_on = ""
        if front.state == "waiting":
            front.state = "working"
            if (task := front.task()) is not None:
                task.reported_at = now  # the stall clock starts again from the answer
        return True

    def user_said(self, session: str, words: str, now: float) -> int:
        """The user sent that session something: its open questions and blockers (not approvals) are answered."""
        n = 0
        for e in self.open_entries(session):
            if e.request_id or e.text.startswith("Waits at"):
                continue
            e.resolved, e.resolved_at = f"answered by you: {_m(words)[:200]}", now
            n += 1
        return n

    def over(self, now: float) -> str | None:
        """Why the shift ends now, or None."""
        if not self.on:
            return None
        if now >= self.ends_at:
            return "hours"
        states = {f.state for f in self.fronts}
        if states <= {"finished", "parked"}:
            return "complete"
        if self.sent >= self.messages and not any(t.state == "working" for f in self.fronts for t in f.tasks) \
                and "starting" not in states:
            return "messages"
        return None

    def end(self, why: str, now: float) -> None:
        if self.on:
            self.ended, self.why = now, why


def new_shift(fronts: list[Front], hours: float, messages: int, notify: bool, how: str, now: float) -> Shift:
    return Shift(id=secrets.token_hex(4), at=now, ends_at=now + hours * 3600, hours=hours, messages=messages,
                 notify=notify, how=how, fronts=fronts)


# ---------- the morning ----------

_ENDS = {"complete": "everything it could do is done", "hours": "it ran out of hours",
         "messages": "it used its message budget", "stopped": "you stopped it", "": "it is still running"}


def _clock(t: float) -> str:
    return time.strftime("%H:%M", time.localtime(t))


SAID_WORDS = 30  # of each thing a session wrote, in the spoken report: the whole of it is on the screen


def _end(text: str, words: int = SAID_WORDS) -> str:
    """A session's words as the morning report says them: cut to a length the voice can say, ending in a full stop
    unless they already end in one or in a question or exclamation mark."""
    from briefing import cap_words

    text = cap_words(text.strip(), words).rstrip(".").strip()
    return text if text[-1:] in ("?", "!") else f"{text}."


def _n(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def morning(shift: Shift, now: float | None = None) -> list[dict]:
    """The morning report, in code and in this order: the headline, the decisions made without the user, the questions
    waiting on them, then done, blocked and still in flight. Each part is {kind, title, text}; `text` is spoken. An
    approval is named, never quoted: the exact request is on the screen and in the read-out that asks for the yes."""
    s = shift.summary()
    until = f"to {_clock(shift.ended)}" if shift.ended else "and still running"
    decided = [e for e in shift.entries if e.kind == "decided"]
    asked = [e for e in shift.entries if e.kind == "asked" and not e.resolved]
    done = [e for e in shift.entries if e.kind == "done"]
    blocked = [e for e in shift.entries if e.kind == "blocked" and not e.resolved]
    flight = shift.ledger()["in_flight"]
    waiting = shift.ledger()["not_started"]
    head = (f"Night shift, {_clock(shift.at)} {until}: {s['done']} of {_n(s['tasks'], 'task')} done, {len(blocked)} blocked; "
            f"{_ENDS.get(shift.why, shift.why)}. {_n(len(decided), 'decision')} made without you, "
            f"{_n(len(asked), 'question')} waiting on you.")
    parts = [{"kind": "headline", "title": "Night shift", "text": head}]
    if decided:
        lines = [f"{e.session}: {_end(e.question or e.text)} It chose: {_end(e.choice or 'not said')}"
                 + (f" If you want otherwise: {_end(e.otherwise)}" if e.otherwise else "") for e in decided]
        parts.append({"kind": "decided", "title": "Decisions made without you", "text":
                      "Decisions made without you. " + " ".join(lines)})
    if asked:
        parts.append({"kind": "asked", "title": "Questions waiting on you", "text": "Questions waiting on you. "
                      + " ".join(f"{e.session} asks: {e.question or e.text}" for e in asked)})
    if done:
        parts.append({"kind": "done", "title": "Done", "text": "Done. "
                      + " ".join(f"{e.session}: {_end(e.proof or e.text)}" for e in done)})
    if blocked:
        lines = [f"{e.session} waits for your approval; say \"approve {e.session}\" to hear the request." if e.request_id
                 else f"{e.session}: {_end(e.text)}" for e in blocked]
        parts.append({"kind": "blocked", "title": "Blocked", "text": "Blocked. " + " ".join(lines)})
    if flight or waiting:
        lines = [f"{x['session']} is still working on: {x['task'].rstrip('.')}." for x in flight]
        lines += [f"{x['session']} did not start: {x['task'].rstrip('.')}." for x in waiting]
        parts.append({"kind": "in_flight", "title": "Still in flight", "text": "Still in flight. " + " ".join(lines)})
    return parts


def written(shift: Shift) -> str:
    return "\n\n".join(p["text"] for p in morning(shift))


# ---------- the store ----------

class Store:
    """The last seven shifts, the running one last: STATE/night-shifts.json, 0600 (it holds what sessions did, masked).
    A damaged file is an empty history."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.items: list[Shift] = []
        try:
            self.items = [Shift.from_dict(d) for d in json.loads(path.read_text()).get("items") or []][-HISTORY:]
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            pass

    def save(self) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"items": [s.to_dict() for s in self.items]}, f, ensure_ascii=False)
        os.replace(tmp, self.path)

    def add(self, shift: Shift) -> None:
        self.items = (self.items + [shift])[-HISTORY:]
        self.save()

    @property
    def current(self) -> Shift | None:
        return self.items[-1] if self.items and self.items[-1].on else None

    @property
    def latest(self) -> Shift | None:
        return self.items[-1] if self.items else None

    def get(self, shift_id: str) -> Shift | None:
        return next((s for s in self.items if s.id == shift_id), None)

    def since(self, t: float) -> Shift | None:
        """The shift a briefing that starts at `t` leads with: the newest one that ran after it."""
        return next((s for s in reversed(self.items) if (s.ended or float("inf")) >= t), None)

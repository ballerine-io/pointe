"""A big fleet, kept small for the voice: the rules, with no daemon state in them (docs/design/people-and-machines.md,
"A big fleet"). The daemon gathers the facts of each session into a Row and calls these; every rule here has a test in
tests/test_fleet_scale.py.

Three tiers. Every session is in exactly one at a time:
  focus       the active session, the thread, sessions that wait on the user, urgent ones, those sent to with no
              report yet, and those named or asked about lately. At most FOCUS_MAX. A session gets here by an event,
              never by a model's choice, and leaves FOCUS_SECS after its last one.
  background  the rest. Counted per machine.
  quiet       background sessions the person marked quiet, and by default every one past the RECENT_PER_MACHINE most
              recent on its machine. No reading-model call for it until it needs the user, is named or is asked
              about. Recent is by its activity when it joined and by the person's words since, never by its own work
              (daemon._fleet_recent).

The budget: "what needs me" is at most BUDGET_TOKENS at any fleet size (fit). Routing sees at most CANDIDATES_MAX
sessions (candidates). Background reports past REPORTS_PER_MIN lines a minute are held for the screen (plan_speech).

Off unless POINTE_FLEET=on, until the fleet benchmark has measured it (bench/fleet): off, the daemon tells the brain,
routes and reports as it did before.
"""

import math
import os
import re
from dataclasses import dataclass

FOCUS_MAX = 12
RECENT_PER_MACHINE = 20
FOCUS_SECS = 600.0  # named, asked about or sent to this long ago: back to the background
BUDGET_TOKENS = 1800
CHARS_PER_TOKEN = 3.5  # brain.CHARS_PER_TOKEN, the repo's first guess for English prose; stricter than 4
CANDIDATES_MAX = 8
LEXICAL_FIRST = 4  # places kept for the best lexical matches before the focus tier fills the rest
SCORE_FLOOR = 1.5
LIST_ROWS = 20
REPORTS_PER_MIN = 4  # background report lines spoken in a minute; the rest are held
COALESCE_OVER = 2  # more background reports than this waiting: one line per machine
NAMES_IN_A_LINE = 3
WAITS_MARK = " Waits on the user for:"

FOCUS, BACKGROUND, QUIET = "focus", "background", "quiet"


def enabled() -> bool:
    return os.environ.get("POINTE_FLEET", "off").strip().lower() in ("on", "1", "true", "yes")


def tokens(text: str) -> int:
    """The estimate the budget is held in: characters over CHARS_PER_TOKEN, rounded up."""
    return math.ceil(len(text) / CHARS_PER_TOKEN)


# ---------- tiers ----------

@dataclass(frozen=True)
class Row:
    """What the tiers need to know of a session. All of it comes from the daemon's records and the machine's signals."""
    id: str
    name: str
    machine: str = ""  # "" is this machine
    owner: str = ""  # "" is mine
    active: bool = False
    thread: bool = False
    needs: bool = False  # it waits on the user: a prompt, a question
    urgent: bool = False
    awaiting: bool = False  # sent to, and no report back yet
    touched_at: float = 0.0  # when it was last named, asked about or sent to
    active_at: float = 0.0  # when its record last moved
    working: bool = False
    online: bool = True
    marked_quiet: bool = False


def _focus_rank(r: Row, now: float) -> int | None:
    if r.active:
        return 0
    if r.thread:
        return 1
    if r.needs:
        return 2 if r.urgent else 3
    if r.awaiting:
        return 4
    if r.touched_at and now - r.touched_at < FOCUS_SECS:
        return 5
    return None


def tiers(rows: list[Row], now: float) -> dict[str, str]:
    """Each session's tier, by id. A session that needs the user and found no place in focus stays in the background,
    never quiet: it is named in the block's "more need you" line."""
    ranked = sorted(((rank, -r.touched_at, r.name, r.id) for r in rows if (rank := _focus_rank(r, now)) is not None))
    focus = {sid for *_, sid in ranked[:FOCUS_MAX]}
    out = {sid: FOCUS for sid in focus}
    by_machine: dict[str, list[Row]] = {}
    for r in rows:
        if r.id not in focus:
            by_machine.setdefault(r.machine, []).append(r)
    for rest in by_machine.values():
        rest.sort(key=lambda r: (-r.active_at, r.name, r.id))
        for i, r in enumerate(rest):
            out[r.id] = QUIET if (r.marked_quiet or i >= RECENT_PER_MACHINE) and not r.needs else BACKGROUND
    return out


# ---------- the block ----------

@dataclass(frozen=True)
class MachineLine:
    name: str
    label: str  # "this Mac", "Linux, 23 ms", "offline since 10:40"
    total: int
    working: int
    needs: int
    more: bool  # it also has sessions in focus, listed above

    def text(self) -> str:
        idle = self.total - self.working
        need = "none need you" if not self.needs else f"{self.needs} need{'s' if self.needs == 1 else ''} you"
        what = f"{self.total} more" if self.more else f"{self.total} session{'' if self.total == 1 else 's'}"
        where = f"{clip(self.name, 40)} ({self.label})" if self.label else clip(self.name, 40)
        return f"- {where}: {what}, {self.working} working, {idle} idle, {need}"


def machine_lines(rows: list[Row], tier: dict[str, str], labels: dict[str, tuple[str, str]]) -> list[MachineLine]:
    """One line per machine for the sessions out of focus. `labels` gives each machine its spoken name and facts.
    Machines where somebody needs the user first, then the largest."""
    out = []
    for machine in {r.machine for r in rows}:
        here = [r for r in rows if r.machine == machine]
        rest = [r for r in here if tier[r.id] != FOCUS]
        if rest:
            name, label = labels.get(machine, (machine, ""))
            out.append(MachineLine(name, label, len(rest), sum(r.working for r in rest), sum(r.needs for r in rest),
                                   len(rest) < len(here)))
    return sorted(out, key=lambda m: (-m.needs, -m.total, m.name))


def more_need(rows: list[Row], tier: dict[str, str]) -> list[str]:
    """The sessions that need the user and are not in focus, urgent first: named in the block, never dropped."""
    return [r.name for r in sorted(rows, key=lambda r: (not r.urgent, r.name, r.id)) if r.needs and tier[r.id] != FOCUS]


def clip(text: str, chars: int) -> str:
    return text if len(text) <= chars else text[:max(1, chars - 1)] + "…"


def shorten(line: str, chars: int) -> str:
    """A session's line cut to `chars`: its notes go first, what it waits on the user for last."""
    if len(line) <= chars:
        return line
    head, mark, tail = line.partition(WAITS_MARK)
    if not mark:
        return clip(line, chars)
    tail = mark + tail
    keep = min(len(head), max(chars // 3, chars - len(tail)))
    return clip(head, keep) + clip(tail, max(1, chars - keep))


def _need_line(names: list[str], chars: int) -> str:
    """"And 4 more need you: a, b, c, d", the names it has room for and a count of the others."""
    said: list[str] = []
    for name in names[:8]:
        if len(", ".join(said + [clip(name, 40)])) > chars - 60:
            break
        said.append(clip(name, 40))
    left = len(names) - len(said)
    tail = "" if not left else f"{', and ' if said else ''}{left} other{'' if left == 1 else 's'}"
    return f"And {len(names)} more need{'s' if len(names) == 1 else ''} you: {', '.join(said)}{tail}."


REST_HEAD = ("The other sessions, by machine. None of them is listed above; list_sessions with a machine, a state or a "
             "query reads any of them:")


def fit(head: str, lines: list[str], machines: list[MachineLine] = (), needing: list[str] = (),
        budget: int = BUDGET_TOKENS) -> str:
    """The whole block, within the budget whatever the fleet's size. Nothing is cut while it fits. Over it: the
    machines past the first few become one count, then each session's line is shortened, the longest first."""
    room = int(budget * CHARS_PER_TOKEN)
    tail: list[str] = []
    if needing:
        tail.append(_need_line(list(needing), room // 8))
    if machines:
        shown, used = [], 0
        for m in machines:
            if used + len(m.text()) + 1 > room // 3:
                break
            shown.append(m)
            used += len(m.text()) + 1
        left = list(machines)[len(shown):]
        tail += [REST_HEAD] + [m.text() for m in shown]
        if left:
            needs = sum(m.needs for m in left)
            tail.append(f"- and {len(left)} more machine{'' if len(left) == 1 else 's'}: {sum(m.total for m in left)} "
                        f"sessions, {sum(m.working for m in left)} working, "
                        f"{'none need you' if not needs else f'{needs} need you'}")
    lines = list(lines)
    over = len(head) + sum(len(x) + 1 for x in lines + tail) - room
    if over > 0 and lines:
        left = room - len(head) - sum(len(x) + 1 for x in tail) - len(lines)
        cap, short = 0, sorted(len(x) for x in lines)
        for i, size in enumerate(short):  # water-filling: short lines stay whole, the long ones share what is left
            cap = max(1, (left - sum(short[:i])) // (len(short) - i))
            if size > cap:
                break
        lines = [shorten(x, cap) for x in lines]
    return clip(head + "".join("\n" + x for x in lines + tail), room)


# ---------- routing: the candidates ----------

_STOP = set("the a an and or but to of in on at for with from by into about that this these those it its is are was were be "
            "been do does did have has had can could should would will please just now then also not all any some session "
            "sessions tell ask have get make let run you your our their them they what which who how when where why there "
            "here need needs want wants going gonna thing things".split())


def words(text: str) -> set[str]:
    """The words a request or a session's record can match by: lowered, short and common ones out, a plural's s off,
    and a file name both whole and by its stem ("pricing.py": pricing.py, pricing)."""
    out = set()
    for raw in re.findall(r"[^\W_]+(?:[._-][^\W_]+)*", str(text).lower()):
        for w in {raw, *re.split(r"[._-]", raw)}:
            if len(w) > 4 and w.endswith("s") and not w.endswith("ss"):
                w = w[:-1]
            if len(w) >= 3 and w not in _STOP and not w.isdigit():
                out.add(w)
    return out


@dataclass(frozen=True)
class Doc:
    """What a session can be matched by, in words: its name; its goal, title and keywords; its file names."""
    id: str
    machine: str = ""
    name: str = ""
    about: str = ""
    files: str = ""


@dataclass(frozen=True)
class Candidate:
    id: str
    how: str  # thread | active | lexical | focus | machine | all
    score: float = 0.0


def scores(request: str, docs: list[Doc]) -> dict[str, float]:
    """A plain lexical score per session: each word of the request it has, weighted by how few sessions have it (a
    word every session has says nothing), and more for a word of its name or a file than of its notes."""
    asked = words(request)
    bags = {d.id: (words(d.name), words(d.files), words(d.about)) for d in docs}
    df: dict[str, int] = {}
    for name, files, about in bags.values():
        for w in asked & (name | files | about):
            df[w] = df.get(w, 0) + 1
    out = {}
    for sid, (name, files, about) in bags.items():
        total = 0.0
        for w in asked:
            weight = 2.0 if w in name else 1.5 if w in files else 1.0 if w in about else 0.0
            if weight:
                total += weight * math.log(1 + len(docs) / df[w])
        if total:
            out[sid] = round(total, 3)
    return out


def candidates(request: str, docs: list[Doc], thread: str | None = None, active: str | None = None,
               focus: list[str] = (), scope: list[str] | None = None,
               limit: int = CANDIDATES_MAX) -> tuple[list[Candidate], bool]:
    """Stage one of routing, in code: at most `limit` sessions for the model to pick among, and whether any of them is
    a lexical match over the floor. A machine named where the words say whom they are for (`scope`) limits them to
    that machine. Few enough sessions: all of them, as before."""
    if scope is not None:
        docs = [d for d in docs if d.machine in scope]
    known = {d.id for d in docs}
    score = scores(request, docs)
    matched = sorted((sid for sid, sc in score.items() if sc >= SCORE_FLOOR), key=lambda sid: (-score[sid], sid))
    if len(docs) <= limit:
        how = "machine" if scope is not None else "all"
        return [Candidate(d.id, how, score.get(d.id, 0.0)) for d in docs], bool(matched)
    out: dict[str, Candidate] = {}

    def take(sid: str | None, how: str) -> None:
        if sid in known and sid not in out and len(out) < limit:
            out[sid] = Candidate(sid, how, score.get(sid, 0.0))

    take(thread, "thread")
    take(active, "active")
    for sid in matched[:LEXICAL_FIRST]:
        take(sid, "lexical")
    for sid in focus:
        take(sid, "focus")
    for sid in matched[LEXICAL_FIRST:]:
        take(sid, "lexical")
    return list(out.values()), bool(matched)


# ---------- "which session?" ----------

def base_name(name: str, machine: str) -> str:
    """A session's name without the machine a collision added to it: "shop avi-box" on avi-box is shop."""
    tail = f" {machine}".lower()
    return name[:-len(tail)] if machine and name.lower().endswith(tail) and len(name) > len(tail) else name


def which_question(options: list[tuple[str, str]], here: str = "here") -> str:
    """The question for a request that fits several sessions, from (session, machine) pairs, most likely first; a
    machine of "" is this one. Up to three: the options, grouped by machine when they span machines ("on avi-box: shop
    or billing; here: shop"). More: the machine is asked for first."""
    machines = list(dict.fromkeys(m for _, m in options))
    if len(options) > NAMES_IN_A_LINE:
        if len(machines) < 2:
            return "Which session is it for?"
        named = [m or here for m in machines]
        if len({n for n, _ in options}) == 1:
            more = f" and {len(named) - 2} more" if len(named) > 3 else ""
            listed = ", ".join(named[:2]) + more if more else _listed(named)
            return f"Which machine? {options[0][0]} is on {listed}."
        return "Which machine is it for?"
    if len(machines) < 2:
        return _listed([n for n, _ in options], "or") + "?"
    if len({n for n, _ in options}) == 1:  # one name on several machines: "Shop: on avi-box or here?"
        return f"{options[0][0].capitalize()}: {_listed(['on ' + m if m else here for m in machines], 'or')}?"
    groups = []
    for m in machines:
        names = _listed([n for n, at in options if at == m], "or")
        groups.append(f"{'on ' + m if m else here}: {names}")
    line = "; ".join(groups) + "?"
    return line[0].upper() + line[1:]


def machine_answer(said: str, machines: list[str]) -> str | None:
    """The machine these words name in answer to "which machine?": every distinctive word of one machine's name, or
    "here" and "this one" for this machine (""). None when they name none, or more than one."""
    heard = set(re.findall(r"[^\W_]+", said.lower()))
    machines = list(dict.fromkeys(machines))
    hits = [m for m in machines if m and (w := set(re.findall(r"[^\W_]+", m.lower()))) and w <= heard]
    if "" in machines and re.search(r"\b(?:here|this (?:one|mac|machine|computer)|mine|my (?:mac|machine|own))\b", said, re.I):
        hits.append("")
    return hits[0] if len(hits) == 1 else None


def _listed(names: list[str], last: str = "and") -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} {last} {names[-1]}"


# ---------- list_sessions ----------

STATES = ("needs_you", "working", "idle", "offline", "quiet", "focus")


def select(rows: list[dict], machine: str = "", owner: str = "", state: str = "", query: str = "",
           limit: int = LIST_ROWS) -> tuple[list[dict], int]:
    """The rows list_sessions returns for its arguments, and how many more matched. A row is the tool's own dict, with
    "tier" beside it. `machine` and `owner` match by name without case ("me" and "mine" are the user's own); `state`
    is one of STATES; `query` keeps the rows that share a word with it, best first."""
    def same(a: str, b: str) -> bool:
        return " ".join(str(a).lower().split()) == " ".join(str(b).lower().split())

    out = [r for r in rows if not machine or same(r.get("machine", ""), machine)]
    if owner:
        mine = owner.strip().lower() in ("me", "mine", "my", "i")
        out = [r for r in out if (not r.get("owner") if mine else same(r.get("owner", ""), owner))]
    tests = {"needs_you": lambda r: bool(r.get("needs_from_user")), "working": lambda r: bool(r.get("working")),
             "idle": lambda r: not r.get("working") and not r.get("needs_from_user"),
             "offline": lambda r: not r.get("online", True), "quiet": lambda r: r.get("tier") == QUIET,
             "focus": lambda r: r.get("tier") == FOCUS}
    if state in tests:
        out = [r for r in out if tests[state](r)]
    if query:
        asked = words(query)
        hits = [(len(asked & words(f"{r.get('name', '')} {r.get('about', '')}")), r) for r in out]
        out = [r for n, r in sorted(hits, key=lambda h: -h[0]) if n]
    return out[:limit], max(0, len(out) - limit)


def overview(machines: list[tuple[str, int, int, list[str]]], here: str = "Here") -> str:
    """"What's going on everywhere", machine by machine and from the counts alone: (machine, sessions, working, the
    names that need the user). Three machines are said, those where somebody needs the user first; the rest are one
    count."""
    order = sorted(machines, key=lambda m: (not m[3], -m[1], m[0]))
    said = []
    for name, total, working, needs in order[:3]:
        need = ("none need you" if not needs else f"{_listed([clip(n, 40) for n in needs[:NAMES_IN_A_LINE]])}"
                + (f" and {len(needs) - NAMES_IN_A_LINE} more" if len(needs) > NAMES_IN_A_LINE else "")
                + f" need{'s' if len(needs) == 1 else ''} you")
        said.append(f"{'On ' + name if name else here}: {total} session{'' if total == 1 else 's'}, {working} working, {need}.")
    rest = order[3:]
    if rest:
        needs = sum(len(m[3]) for m in rest)
        said.append(f"And {len(rest)} more machine{'' if len(rest) == 1 else 's'} with {sum(m[1] for m in rest)} sessions"
                    + (f", {needs} of them need you." if needs else ", none need you."))
    return " ".join(said)


# ---------- speech ----------

APPROVAL, NEEDS, THREAD, REST = 0, 1, 2, 3  # the order things are said in


@dataclass(frozen=True)
class Report:
    """A finished turn's report that waits to be said."""
    session: str
    machine: str = ""  # its spoken name; "" is this machine
    question: bool = False  # it left a question for the user


@dataclass(frozen=True)
class Line:
    text: str  # "" for a report said as it came
    sessions: tuple[str, ...]  # the sessions the line names


_COUNT = "zero one two three four five six seven eight nine ten eleven twelve".split()


def coalesced(machine: str, reports: list[Report], several: bool) -> Line:
    """"Three on avi-box finished: tide, harbor and ferry; ferry has a question". Three names at most, those with a
    question first, and a count of the rest."""
    order = sorted(reports, key=lambda r: not r.question)
    named = order[:NAMES_IN_A_LINE]
    n = len(reports)
    count = _COUNT[n] if n < len(_COUNT) else str(n)
    where = f" on {machine}" if machine else " here" if several else ""
    more = f" and {n - len(named)} more" if n > len(named) else ""
    names = ", ".join(r.session for r in named) + more if more else _listed([r.session for r in named])
    asks = [r.session for r in named if r.question]
    asked = "" if not asks else f"; {_listed(asks)} {'has a question' if len(asks) == 1 else 'have questions'}"
    return Line(f"{count.capitalize()}{where} finished: {names}{asked}.", tuple(r.session for r in named))


def plan_speech(reports: list[Report], spoken_lately: int, several: bool = True) -> tuple[list[Line], list[Report]]:
    """What is said and what is held, of the background reports that wait: (lines, held). One or two: each as it came.
    More: one line per machine. Past REPORTS_PER_MIN lines in the minute (`spoken_lately` of them already said), the
    rest are held for the screen and the next "anything else?". A report with a question for the user is never held:
    it is said as it came. Every report is in a line or in the held list."""
    room = max(0, REPORTS_PER_MIN - spoken_lately)
    lines: list[Line] = []
    held: list[Report] = []
    if len(reports) <= COALESCE_OVER:
        groups = [[r] for r in reports]
    else:
        by: dict[str, list[Report]] = {}
        for r in reports:
            by.setdefault(r.machine, []).append(r)
        groups = sorted(by.values(), key=lambda g: (not any(r.question for r in g), -len(g), g[0].machine))
    for group in groups:
        if len(group) == 1 and (room > 0 or group[0].question):
            lines.append(Line("", (group[0].session,)))
            room -= 0 if group[0].question else 1
        elif len(group) > 1 and room > 0:
            line = coalesced(group[0].machine, group, several)
            lines.append(line)
            held += [r for r in group if r.session not in line.sessions]  # counted in the line, named on the screen
            room -= 1
        else:
            lines += [Line("", (r.session,)) for r in group if r.question]
            held += [r for r in group if not r.question]
    return lines, held


# ---------- quiet, by voice ----------

_QUIET = re.compile(r"^\W*(?:(?:please|ok(?:ay)?|pointe|and)\W+)*(?P<stop>stop keeping|don'?t keep|do not keep|no need to keep)?\s*"
                    r"(?(stop)|keep)\s+(?P<who>.+?)\s+quiet\W*$", re.I)


def quiet_intent(text: str) -> tuple[bool, str] | None:
    """"Keep tide quiet" is (True, "tide"); "stop keeping tide quiet" is (False, "tide"). A whole short utterance, so a
    request to a session ("tell tide to keep quiet about it") is none."""
    found = _QUIET.match(text.strip())
    if not found or len(text.split()) > 9 or re.search(r"\b(?:tell|ask)\b", text, re.I):
        return None
    return (not found["stop"], found["who"])

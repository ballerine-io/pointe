"""Which listed sessions a spoken description means, and the read-backs (docs/design/attach-by-voice.md).

Local first: the user's words against each session's name, title, folder, branch, first and last request and keywords.
The brain only orders a short list of close candidates, from their titles and keywords (`rank_prompt`); its answer
never joins anything by itself. Pure functions: daemon.py calls them and holds the yes.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from discovery import Found, ago

TITLES = {"claude-code": "Claude Code", "codex": "Codex", "opencode": "OpenCode"}
MOST_SPOKEN = 6  # names read out in an "all" read-back before "and N more"
MOST_CHOICES = 3  # candidates read out when the words fit several
MOST_RANKED = 8  # candidates the brain may be asked to order
CLEAR_MARGIN = 2.0  # a top score this many times the next one is a clear winner

_SPLIT = re.compile(r"[^\w]+|_")


def _stem(word: str) -> str:
    for suffix in ("ings", "ing", "ers", "er", "ies", "es", "ed", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _tokens(text: str) -> set[str]:
    return {_stem(t) for t in _SPLIT.split((text or "").lower()) if len(t) >= 2}


def _hit(word: str, tokens: set[str]) -> bool:
    w = _stem(word.lower())
    if w in tokens:
        return True
    return len(w) >= 4 and any(len(t) >= 4 and (t.startswith(w) or w.startswith(t)) for t in tokens)


def score(found: Found, words: list[str]) -> float:
    """How well the description's words fit a session: each word counts once, at the weight of the best field it is
    in (name and title 3, folder 3, branch 2, what the user asked it and its keywords 1)."""
    fields = [(_tokens(f"{found.name} {found.title}"), 3.0), (_tokens(Path(found.cwd).name), 3.0),
              (_tokens(found.branch), 2.0), (_tokens(" ".join([found.first, found.last, *found.keywords])), 1.0)]
    total = 0.0
    for word in words:
        total += max((weight for tokens, weight in fields if _hit(word, tokens)), default=0.0)
    for first, second in zip(words, words[1:]):  # "pen test" is pentest, "bill ing" billing: speech splits words
        joined = max((weight for tokens, weight in fields if _hit(first + second, tokens)), default=0.0)
        if joined > max((weight for tokens, weight in fields if _hit(first, tokens) or _hit(second, tokens)), default=0.0):
            total += joined
    return total


def _day_bounds(now: float, days_back: int) -> tuple[float, float]:
    t = time.localtime(now)
    midnight = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))
    start = midnight - days_back * 86400
    return start, start + 86400


def in_time(found: Found, when: str | None, now: float) -> bool:
    """Whether a session was last active in the spoken time. "latest" filters nothing: it orders."""
    if not when or when == "latest":
        return True
    if when == "today":
        return found.when >= _day_bounds(now, 0)[0]
    if when == "yesterday":
        a, b = _day_bounds(now, 1)
        return a <= found.when < b
    if when == "this morning":
        a, _ = _day_bounds(now, 0)
        return a <= found.when < a + 13 * 3600
    if when == "last night":
        a, _ = _day_bounds(now, 0)
        return a - 6 * 3600 <= found.when < a + 6 * 3600
    if when == "this week":
        return found.when >= now - 7 * 86400
    if when == "last week":
        return now - 14 * 86400 <= found.when < now - 5 * 86400
    return True


@dataclass
class Pick:
    """What the words pick: `kind` one (read back one), all (read back the count and names), choose (read the few
    back and ask which), rank (close candidates the brain may order first), none (nothing fits)."""

    kind: str
    items: list[Found] = field(default_factory=list)


def pick(found: list[Found], ask, now: float | None = None) -> Pick:
    """The sessions the user's words (guards.AttachAsk) mean. Sessions that cannot join are never picked."""
    now = time.time() if now is None else now
    usable = [f for f in found if f.joinable and (ask.harness is None or f.harness == ask.harness)
              and (ask.machine is None or (f.machine or "") == ask.machine) and in_time(f, ask.when, now)]
    if ask.all:
        opened = [f for f in usable if f.state == "open" and (not ask.about or score(f, ask.about) > 0)]
        return Pick("all", sorted(opened, key=lambda f: -f.when)) if opened else Pick("none")
    preferred = "recent" if ask.verb == "reopen" else "open"
    for pool in ([f for f in usable if f.state == preferred], [f for f in usable if f.state != preferred]):
        chosen = _pick_in(pool, ask, now)
        if chosen.kind != "none":
            return chosen
    return Pick("none")


def _pick_in(pool: list[Found], ask, now: float) -> Pick:
    if not pool:
        return Pick("none")
    newest = sorted(pool, key=lambda f: -f.when)
    if not ask.about:
        if len(pool) == 1 or ask.when == "latest":
            return Pick("one", newest[:1])
        return Pick("choose", newest[:MOST_CHOICES])
    scored = sorted(((score(f, ask.about), f) for f in pool), key=lambda sf: (-sf[0], -sf[1].when))
    scored = [(s, f) for s, f in scored if s > 0]
    if not scored:
        return Pick("none")
    top = scored[0][0]
    second = scored[1][0] if len(scored) > 1 else 0.0
    if second == 0 or top >= CLEAR_MARGIN * second:
        return Pick("one", [scored[0][1]])
    close = [f for s, f in scored if s >= top / CLEAR_MARGIN][:MOST_RANKED]
    return Pick("rank", close)


# ---------- the brain orders close candidates: titles and keywords only ----------

def _brief(found: Found, now: float) -> str:
    title = found.title or found.name
    words = ", ".join(found.keywords[:8])
    return f"{title} (folder {Path(found.cwd).name}, {ago(found.when, now)}{'; about: ' + words if words else ''})"[:200]


def rank_prompt(description: str, items: list[Found], now: float | None = None) -> str:
    """What the brain is shown: the user's description and, per candidate, its title, folder name, age and keywords.
    Never a transcript, a path or a request's full text."""
    now = time.time() if now is None else now
    lines = "\n".join(f"{i + 1}. {_brief(f, now)}" for i, f in enumerate(items[:MOST_RANKED]))
    return (f"Coding-agent sessions:\n{lines}\n\nThe user described one of them as: {description[:200]!r}\n\n"
            "Which session does the description mean? Answer with its number only, or 'unclear' when it could be more "
            "than one of them or none.")


def parse_rank(reply: str, count: int) -> int | None:
    found = re.fullmatch(r"\D*(\d+)\D*", (reply or "").strip())
    if not found or "unclear" in (reply or "").lower():
        return None
    n = int(found.group(1))
    return n - 1 if 1 <= n <= count else None


# ---------- answers to "which one?" ----------

_ORDINALS = {"first": 0, "one": 0, "1": 0, "1st": 0, "second": 1, "two": 1, "2": 1, "2nd": 1, "third": 2, "three": 2,
             "3": 2, "3rd": 2, "ראשון": 0, "הראשון": 0, "שני": 1, "השני": 1, "שלישי": 2, "השלישי": 2}
_BOTH = re.compile(r"\b(?:both|all(?:\s+of\s+them)?|all\s+(?:two|three)|each|every\s+one)\b|(?<!\w)(?:שניהם|כולם)(?!\w)")
_NONE = re.compile(r"\b(?:neither|none|no|nope|cancel|never\s*mind|nothing)\b|(?<!\w)(?:אף\s+אחד|לא)(?!\w)")


def choice(text: str, items: list[Found]) -> list[Found] | None:
    """The sessions an answer to "which one?" picks from the list read back: by place ("the second", "number two",
    "the last one"), "both" or "all of them", or words that fit one of them better than the rest. [] for "neither" or
    "no"; None when it does not answer."""
    lowered = (text or "").lower()
    if _BOTH.search(lowered):
        return list(items)
    lowered = re.sub(r"\bone\s+(?=(?:about|with|where|in|from|that|for|on|called|named)\b)", " ", lowered)  # "the one about X"
    said = [w for w in re.findall(r"\w+", lowered) if w in _ORDINALS and _ORDINALS[w] < len(items)]
    if len(said) > 1 and "one" in said:  # "the second one": "one" is the noun there, not the number
        said.remove("one")
    picked = {_ORDINALS[w] for w in said}
    if re.search(r"\blast\b", lowered) and items:
        picked = (picked - {0} if re.search(r"\blast\s+one\b", lowered) else picked) | {len(items) - 1}
    if len(picked) == 1:
        return [items[picked.pop()]]
    words = [w for w in re.findall(r"\w[\w-]*", lowered) if len(w) >= 3 and w not in _ORDINALS]
    scored = sorted(((score(f, words), i) for i, f in enumerate(items)), reverse=True)
    if scored and scored[0][0] > 0 and (len(scored) == 1 or scored[0][0] > scored[1][0]):
        return [items[scored[0][1]]]
    if _NONE.search(lowered):
        return []
    return None


# ---------- the read-backs, word for word ----------

def _agent(found: Found) -> str:
    return TITLES.get(found.harness, found.harness)


def _a(word: str) -> str:
    return "an" if word[:1] in "AEIOU" else "a"


def said_list(names: list[str]) -> str:
    if len(names) <= MOST_SPOKEN:
        return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    return ", ".join(names[:MOST_SPOKEN]) + f" and {len(names) - MOST_SPOKEN} more"


def _where(found: Found, here: str) -> str:
    return found.machine or here


def line_one(found: Found, here: str, now: float | None = None, speak=lambda s: s) -> str:
    """"Join pentest-recon, the Claude Code session in pentest-notes on studio?" For a recent one, the reopen and where
    it opens. No consent word ("Say yes"): heard back through the speakers, it would be a yes."""
    now = time.time() if now is None else now
    folder = speak(Path(found.cwd).name or found.cwd)
    if found.state == "open":
        line = (f"Join {speak(found.name)}, the {_agent(found)} session in {folder} on {_where(found, here)}?")
        if not found.approvals:
            line += " Its approvals stay in its terminal. Join?"
        return line
    window = " in a new terminal window" if found.harness == "claude-code" else ""
    when = ago(found.when, now)
    when = when if when.startswith("from ") else "from " + ("a moment ago" if when == "just now" else when)
    line = f"Reopen {speak(found.name)}, the {_agent(found)} session in {folder} {when},{window} on {_where(found, here)}?"
    if not found.approvals:
        line += " Its approvals will stay in its terminal. Reopen?"
    return line


def line_all(items: list[Found], here: str, harness: str | None, speak=lambda s: s) -> str:
    """"Join 3 open Claude Code sessions on studio: pentest-recon, billing and docs?" """
    agent = TITLES.get(harness or "", "")
    machines = sorted({_where(f, here) for f in items})
    where = " and ".join(machines) if len(machines) <= 2 else f"{len(machines)} machines"
    kind = f"open {agent} session" if agent else "open session"
    names = said_list([speak(f.name) for f in items])
    if len(items) == 1:
        line = f"Join the one {kind} on {where}, {names}?"
    else:
        line = f"Join {len(items)} {kind}s on {where}: {names}?"
    stay = [speak(f.name) for f in items if not f.approvals]
    if stay:
        line += (f" Approvals of {said_list(stay)} stay in {'its' if len(stay) == 1 else 'their'} terminal. "
                 + ("Join?" if len(items) == 1 else "Join them?"))
    return line


_COUNT = {2: "Two", 3: "Three"}


def line_choose(items: list[Found], here: str, now: float | None = None, speak=lambda s: s) -> str:
    """"Two sessions fit: one, pentest-recon in pentest-notes, open; two, recon in scanner, from yesterday. Which one?" """
    now = time.time() if now is None else now
    several = len({_where(f, here) for f in items}) > 1
    parts = []
    for i, f in enumerate(items):
        state = "open" if f.state == "open" else ago(f.when, now)
        on = f" on {_where(f, here)}" if several else ""
        parts.append(f"{['one', 'two', 'three'][i]}, {speak(f.name)} in {speak(Path(f.cwd).name or f.cwd)}{on}, {state}")
    line = f"{_COUNT.get(len(items), str(len(items)))} sessions fit: " + "; ".join(parts) + ". Which one?"
    if any(f.state != "open" for f in items):
        line += " A closed one reopens."
    return line

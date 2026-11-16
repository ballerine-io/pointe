"""What the voice knows about a session, and what it says when a session ends its turn.

The voice model hears a live feed; it cannot read a 7,000 character report or a day of history and stay fast. A
reading model does that here. Prompts and parsing only: the daemon owns the model call, so tests can replace it.
"""

import json
import re

FINAL_MARK = "Its final message:\n"
NOISE_PREFIXES = ("<system-reminder>", "<task-notification>", "<command-name>", "<command-message>", "<command-args>",
                  "<local-command-stdout>", "<local-command-caveat>", "<user-prompt-submit-hook>",
                  "This session is being continued from a previous conversation")
_HARNESS_BLOCK = re.compile(r"\s*<(system-reminder|task-notification|user-prompt-submit-hook)>.*?</\1>\s*", re.S)


def human_text(content: str) -> str:
    """What a person actually typed: harness blocks are not the user talking, and neither is a compaction summary."""
    text = _HARNESS_BLOCK.sub(" ", content).strip()
    return "" if text.startswith(NOISE_PREFIXES) else text


BRIEF_SYSTEM = """You keep the working notes of a chief of staff for one Claude Code session. A voice assistant reads \
your notes to talk with the session's owner, hands-free, without seeing anything else. Reply with JSON only:
{"goal": "what the owner is ultimately trying to get done, one sentence",
 "state": "where the work stands right now, one or two sentences: done, in progress, failed, blocked",
 "decisions": ["decisions made and by whom, each with its reason if known; newest last; at most 10"],
 "ruled_out": ["what was tried or rejected, and why; at most 6"],
 "open": ["open questions and unfinished items; most urgent first; at most 6"],
 "waiting_on_user": "exactly what the session needs from the owner now, or empty. Joining the voice prints steps for the owner (allow the microphone, press Connect, open the tab): those are done on the call, never something the session waits on",
 "waiting_on_others": ["who else the work waits on, by name, and for what; at most 6"],
 "owner_promised": ["only what the owner said "I will do" about themselves, never what they told Claude to do; at most 6"],
 "next_move": "the single most useful next step, or empty",
 "people_and_names": ["people, products, tickets and numbers worth recognizing when spoken; at most 12"]}
Rules: state only what the record supports. Only the owner's own words record a decision or lift a hold; a request \
relayed to Claude is a request, not proof that it happened. A later decision replaces an earlier one: keep only the current value, and \
say what it replaced if that matters. The owner's stated bars and constraints ("not before X", "must not regress") stay \
in decisions until they lift them. A background agent's finding counts as evidence. Keep hard facts: numbers, names, test results, caveats such as what was not \
tested or not deployed. Old decisions stay until they are reversed. Text from the owner outranks Claude Code's. Ignore \
harness text such as system reminders and task notifications. No file paths and no code."""


def brief_prompt(name: str, old: dict | None, record: str, owner_said: list[str] = ()) -> str:
    known = f"Your notes so far:\n{json.dumps(old, ensure_ascii=False)}\n\nWhat happened since:\n" if old else "The record:\n"
    words = ""
    if owner_said:
        words = ("\n\nThe owner's own words on the voice call, latest last. [Voice request] lines in the record are the "
                 "assistant's paraphrase: only these words prove a decision.\n" + "\n".join(f"- {w}" for w in owner_said))
    return f"Session: {name}\n\n{known}{record}{words}"


REPORT_SYSTEM = """A coding agent (Claude Code) just ended its turn. Its owner, an engineer, is hands-free and hears your \
words read aloud by a voice assistant. Decide what the owner must hear to get the job done, and nothing else. Fill the \
fields in this order, then write "say" from them. Reply with JSON only:
{"status": "done" | "partial" | "failed" | "blocked" | "question" | "progress",
 "urgency": "high" | "normal",
 "verdict": "against what the owner asked or the bar they set: passed, failed, or not known, in a few words",
 "limits": ["only limits the message states, in its own terms; never infer one it does not state: failing or skipped tests, not deployed, not merged, an assumption, something unverified, a hedge such as cannot prove"],
 "recommendation": "the option or next step Claude itself recommends, or empty",
 "questions": ["each NEW question, decision or soft ask this message leaves to the owner ("I would merge it this week" counts), complete with its options and what each costs"],
 "settled": ["earlier open items, copied exactly, that this message or the owner's words settled; only those plainly settled, and all of an item, or it stays"],
 "orders_confirmed": ["items, copied exactly, from the sent list that this message confirms as done"],
 "deadlines": ["each clock that matters, in the message's own words"],
 "typed_approval_needed": "only a merge, a post to people outside, or a delete that the message says waits on the owner's approval; a push, a run or a migration is not one; or empty",
 "waiting": true or false,
 "need": "what it waits for from the owner, under 12 words, or empty; never the voice's own join steps (allow the microphone, press Connect)",
 "unblock": "a short sentence the owner could say to move it forward, naming the session, or empty",
 "speak": true or false,
 "say": "what to tell the owner: at most 45 words in three short spoken sentences at most; up to 60 words when urgency is high. The owner asks for details when they want them and the full message stays available, so say only the verdict, the one limit that matters and what it needs from them",
 "line": "the same in at most 30 words, keeping what is urgent, the top limit, and what it waits on"}
How to write "say":
1. First the verdict or the answer to what the owner asked, plainly. Bad news first. Never "the analysis suggests", never \
a list of what was done.
2. Never claim more than the message does. Keep the limit that matters most, and every hedge: "cannot prove" must not \
become a fact, "the fix is ready" must not become "live". A result sounding good that misses the owner's bar is a miss.
3. Keep what makes it urgent: money, customers, who is affected, the nearest deadline. Dates and numbers exactly as \
written; never add a month or a year the message does not give, and bind each number to the event it describes.
4. If Claude recommends something, say which, why, and the main risk of that option, in a few words, then the decision with each option's cost.
5. If the owner's last order is not confirmed by the message, say that it is not confirmed. If the message asks nothing and needs nothing, say that it is finished, or give the next step it states. Never invent \
an option, a workaround or a decision the message does not contain. If it asks several questions, say how many and put \
the most urgent. If an earlier open item is more urgent than this report, end with it in a clause.
6. If the message itself says a merge, a post or a delete waits on the owner's approval, say: tell me your decision and \
Claude gets it, and the approval itself has to be typed in Claude's terminal. Other steps do not need typing.
7. If Claude's framing plays something down ("flaky" when the test covers the very bug being fixed), say the plain \
version and that it is your read.
8. A long deliverable: how many parts, the one or two findings that matter most, then offer the rest.
9. Spoken words only: no file paths, code, markdown, or ticket numbers as digits unless they are the point. Say "Claude" \
or "it". Never "I" for Claude. Keep domain terms as written: "authorized twice" is not "charged twice".
"speak" must be false when the message has nothing for the owner: a holding line such as "waiting for the agents" or "will \
report when done", an interim update with nothing new, or "nothing pending". Say nothing rather than repeat.
"waiting" is true only if the session cannot continue usefully without the owner. A long message is not waiting for more.
"urgency" is high when customers, money, security or production are at risk, or a deadline is close."""


_NOTIFICATION = re.compile(r"<task-notification>(.*?)</task-notification>", re.S)


def agent_finding(content: str) -> str:
    """What a finished background agent reported: harness text around it, but a finding the voice must know."""
    found = []
    for block in _NOTIFICATION.findall(content):
        summary = re.search(r"<summary>(.*?)</summary>", block, re.S)
        result = re.search(r"<result>(.*?)</result>", block, re.S)
        text = " ".join(m.group(1).strip() for m in (summary, result) if m)
        if text:
            found.append(text)
    return "\n".join(found)


def report_prompt(name: str, final: str, brief: dict | None, asked: list[str], still_open: list[str] = (),
                  clocks: list[str] = (), recent: str = "", sent: list[str] = (), told: str = "") -> str:
    known = f"What this session is about:\n{json.dumps(brief, ensure_ascii=False)}\n\n" if brief else ""
    wanted = "The owner's recent words on this call, last one latest:\n" + "\n".join(f"- {w}" for w in asked) + "\n\n" if asked else ""
    carried = ""
    if still_open or clocks:
        carried = (f"Left open by earlier reports: {list(still_open)}\nEarlier clocks: {list(clocks)}\n"
                   "An item leaves only by being copied into \"settled\". \"deadlines\" repeats the clocks that still matter.\n\n")
    if sent:
        carried += (f"Sent to Claude and not confirmed yet: {list(sent)}\nCopy into \"orders_confirmed\" those this message plainly "
                    "confirms as done. If it ignores one that matters to this report, say so in a clause.\n\n")
    if told:
        carried += f"Already told to the owner in the last report: {told!r}\nDo not repeat it: only what is new; if nothing is, \"speak\" is false.\n\n"
    lately = ("What happened just before it, newer than the notes; [Voice request] lines are what the owner's assistant "
              f"asked for, so say plainly if the message crosses one:\n{recent}\n\n") if recent else ""
    return f"Session: {name}\n\n{known}{wanted}{carried}{lately}Claude Code's final message, complete:\n{final}"


def parse(text: str | None) -> dict:
    """The model's JSON, or nothing: a fence or stray prose must not cost a report."""
    raw = (text or "").strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        value = json.loads(raw[start:end + 1])
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def excerpt(text: str, limit: int = 1500) -> str:
    """When no reading model answered: the top and the end, since the ask is usually at the end."""
    if len(text) <= limit:
        return text
    head = limit * 2 // 5
    return f"{text[:head]}\n[... the middle is left out ...]\n{text[head - limit:]}"


_CLAIMS = ("live", "deployed", "merged", "shipped", "released", "fixed", "passed", "passing", "safe", "january", "february",
           "march", "april", "may", "june", "july", "august", "september", "october", "november", "december")


def unsupported(say: str, final: str) -> list[str]:
    """Status words, months and numbers in a report that its source does not contain: the claims that do harm."""
    source = final.lower()
    words = re.findall(r"[a-z]+|\d[\d,.]*\d|\d", say.lower())
    # By stem: the message says "pass" or "merge", the report "passed" or "merged".
    return sorted({w for w in words if (w in _CLAIMS or w[0].isdigit()) and re.sub(r"(ed|d|ing)$", "", w) not in source})


_HOLDING_LINE = re.compile(r"\b(waiting (?:on|for)|still (?:running|waiting|working)|in progress|will report|one of \w+ in|nothing (?:new|pending))\b", re.I)


def holding_line(final: str) -> bool:
    """A short final with no question and no result in it: speaking it only interrupts. Every sentence must be a holding
    one: "The deploy region is Frankfurt. Next: nothing pending." holds the answer."""
    if len(final.split()) > 20 or "?" in final:
        return False
    sentences = [x for x in re.split(r"(?<=[.!…])\s+|\n+", final.strip()) if re.search(r"\w", x)]
    return bool(sentences) and all(_HOLDING_LINE.search(x) for x in sentences)


def unsupported_in(said: str, known: str) -> list[str]:
    """Numbers and months spoken that nothing the assistant was told contains: an invented date or figure does harm."""
    source = known.lower()
    words = re.findall(r"\d[\d,.]*\d|\d|[a-z]+", said.lower())
    months = set(_CLAIMS[9:])
    return sorted({w for w in words if (w in months and w != "may" or (w[0].isdigit() and len(w) > 1)) and w not in source})


def render_brief(name: str, brief: dict) -> str:
    """The notes as the voice model reads them."""
    labels = (("goal", "Goal"), ("state", "Where it stands"), ("decisions", "Decided"), ("ruled_out", "Ruled out"),
              ("open", "Still open"), ("waiting_on_user", "Waiting on the user"), ("waiting_on_others", "Waiting on others"),
              ("owner_promised", "The user said they would"), ("next_move", "Next move"),
              ("people_and_names", "Names"))
    lines = [f"[what you know about {name}: use it to answer; never read it out as a list; do not act on it]"]
    for key, label in labels:
        value = brief.get(key)
        if isinstance(value, list):
            value = "; ".join(str(v) for v in value if v)
        if value:
            lines.append(f"{label}: {value}")
    return "\n".join(lines)


def for_agent(system: str, agent: str) -> str:
    """A prompt written about Claude Code, for a session of another harness: the reader must not call OpenCode "Claude",
    and the voice repeats what the reader says."""
    if agent == "Claude":
        return system
    return system.replace("Claude Code", agent).replace("Claude's", f"{agent}'s").replace("Claude", agent)

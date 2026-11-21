"""Decisions made in code, never by the voice model: consent, and who may talk to the daemon."""

import hashlib
import hmac
import json
import re
import unicodedata

import readout
from urllib.parse import parse_qs, urlparse

from fastapi import Request
from fastapi.responses import PlainTextResponse
from starlette.datastructures import Headers
from starlette.requests import HTTPConnection
from starlette.responses import RedirectResponse

MAX_CONSENT_WORDS = 8
LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1"}

_YES = {"yes", "yeah", "yep", "yup", "sure", "ok", "okay", "approve", "approved", "allow", "allowed",
        "proceed", "absolutely", "certainly", "definitely", "כן", "אשר", "תאשר", "מאשר", "מאשרת", "סבבה", "בטח",
        "יאללה", "אוקיי", "בסדר"}
_WEAK_YES = {"טוב", "ברור"}  # also "good" and "clear": a yes only when nothing else is said
_YES_PHRASES = ("go ahead", "do it", "go for it", "sounds good", "of course", "תמשיך", "קדימה", "תעשה את זה")
# A yes despite the no word in it, but only said on its own: "why not run it on staging?" proposes something else.
_YES_DESPITE_NO = ("no problem", "no worries", "why not", "stop asking", "למה לא", "אין בעיה")
_NO = {"no", "nope", "nah", "not", "never", "deny", "denied", "reject", "don't", "dont", "stop", "cancel", "wait",
       "לא", "שלא", "אל", "תדחה", "דחה", "עצור", "בטל", "רגע"}
_CONDITION = {"don't", "dont", "אל"}  # "yes, and don't touch the migrations" adds a condition to the yes
_FILLER = {"and", "then", "please", "just", "so", "well", "it", "that", "um", "uh", "the", "את", "זה", "ו"}


def _lower(text: str) -> str:
    return text.lower().replace("\u2019", "'")


def _words(text: str) -> set[str]:
    return set(re.findall(r"[\w']+", text))


def _only_yes(lowered: str) -> bool:
    for p in _YES_PHRASES:
        lowered = lowered.replace(p, " ")
    return _words(lowered) <= _YES | _WEAK_YES | _FILLER


def consent(text: str) -> str | None:
    """'allow' / 'deny' from the user's own words; None if they did not clearly decide. No wins ties."""
    lowered = _lower(text)
    despite = [p for p in _YES_DESPITE_NO if p in lowered]
    for p in despite:
        lowered = lowered.replace(p, " ")
    words = _words(lowered)
    yes = bool(despite) or bool(words & (_YES | _WEAK_YES)) or any(p in lowered for p in _YES_PHRASES)
    no = words & _NO
    if no:
        return None if yes and no <= _CONDITION else "deny"
    if (despite or words & _WEAK_YES) and not _only_yes(lowered):
        return None
    if not despite and text.strip().endswith("?"):
        return None  # "ok, what does it do?" asks; it does not answer
    # "ok, and what about naming?" is not consent: a yes must be a short answer.
    if yes and len(re.findall(r"[\w']+", text)) <= MAX_CONSENT_WORDS:
        return "allow"
    return None


_STILL_ONLY_YES = ("you can", "run it", "with that", "right now", "now", "עכשיו")
_DISMISSALS = ("no worries", "stop asking")  # fine for a send, not for running a tool
_UNFINISHED = {"and", "so", "then", "the", "that", "well", "um", "uh", "just", "את", "ו"}
# Words a sentence never ends on: the rest is coming.
_DANGLING = {"a", "an", "the", "and", "or", "but", "so", "because", "if", "than", "between", "whether", "my", "your", "our",
             "their", "his", "um", "uh", "er", "hmm", "which", "while", "after", "before", "until", "unless", "although",
             "also", "plus", "versus", "very", "pretty", "quite", "basically", "actually",
             "של", "את", "עם", "בין", "או", "כי", "אז", "ש", "ו", "ה", "ל", "ב", "מ", "כמו", "אם",
             "אבל", "וגם", "ואז", "כאילו", "בעצם", "אחרי", "לפני", "עד", "כש", "בגלל", "למרות", "בשביל", "לגבי", "בתוך",
             "ליד", "מול", "אצל", "בלי", "כדי", "שאני", "שאתה", "שהוא", "שזה", "שהם", "אה", "אמ"}
# Words a question can end on ("what are you looking at", "what the date is"): unfinished only outside a question.
_DANGLING_OUTSIDE_QUESTIONS = {"to", "at", "of", "for", "with", "about", "from", "into", "like", "is", "are", "was", "were",
                               "when", "where", "who", "על", "גם"}
# Fillers and connectives of more than one word ("and then", "you know"): a pause after them is a pause for the rest.
_DANGLING_PHRASES = re.compile(r"\b(?:and then|i mean|you know|kind of|sort of|such as|rather than|as well as|in order to|"
                               r"as soon as|or maybe|but then)\W*$|(?:^|\W)(?:ולא רק|וגם את|זה אומר ש|מה ש)\W*$")
_QUESTION = re.compile(r"\b(what|where|who|whom|which|when|why|how|whose)\b|\?|\b(מה|איפה|מי|מתי|למה|איך|איזה)\b")


def unfinished(text: str) -> bool:
    """A sentence cut by a pause, not ended: "the difference between—", "I want to look at". Its end is still coming."""
    stripped = text.strip()
    if re.search(r"(—|–|-|…|\.\.\.|,)$", stripped):
        return True
    lowered = re.sub(r"[.!?…]+$", "", stripped.lower()).rstrip()  # Soniox closes a cut clause with a full stop too
    if _DANGLING_PHRASES.search(lowered):
        return True
    words = re.findall(r"[\w']+", lowered)
    if not words:
        return False
    before = " ".join(words[:-1])  # "it fails when" is cut; "tell me when" asks (the question word before the last)
    return words[-1] in _DANGLING or words[-1] in _DANGLING_OUTSIDE_QUESTIONS and not _QUESTION.search(before)
_ASKS_THE_USER = {"AskUserQuestion", "ExitPlanMode"}  # an answer, not an approval: "allow" would send none
_FILE_VERBS = {"Edit": "edit", "MultiEdit": "edit", "NotebookEdit": "edit", "Write": "write", "Read": "read"}


def readable_request(tool: str, tool_input: dict, cwd: str | None = None) -> str | None:
    """The words a yes approves, built here from what will run and never from the description the session's model
    wrote (readout.py says how). None when they cannot be said safely: such a request is approved only in the terminal,
    and the page and the phone show the exact text either way."""
    if tool in _ASKS_THE_USER:
        return None
    values = [v for v in tool_input.values() if isinstance(v, str)]
    if any(readout._hidden(v.replace("\n", "").replace("\t", "")) for v in values):
        return None
    path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if tool == "Bash":
        command = readout.spoken(str(tool_input.get("command") or ""), cwd)
        what = f"run: {command}" if command else ""
    elif tool in _FILE_VERBS and isinstance(path, str) and not readout._hidden(path):
        what = f"{_FILE_VERBS[tool]} {readout.place(path, cwd)}"
    else:
        return None  # other tools (web fetches, MCP calls) have arguments too varied to say safely
    if not what or readout.redact(what) is None:  # a credential is never said aloud: the tap shows it
        return None
    lowered = _lower(what)
    return None if _words(lowered) & (_YES | _WEAK_YES) or any(p in lowered for p in _YES_PHRASES) else what


def remote_readable(readable) -> str | None:
    """A node's read-out of its own request, after the cheap checks readable_request ends with: the node built it from
    the unmasked input the hub never sees, so the hub does not rebuild it from the masked preview. Anything that fails is
    unreadable: tap only."""
    if not isinstance(readable, str) or not readable.strip() or len(readable.split()) >= 25:
        return None
    if readout.redact(readable) is None or readout._hidden(readable):
        return None
    lowered = _lower(readable)
    return None if _words(lowered) & (_YES | _WEAK_YES) or any(p in lowered for p in _YES_PHRASES) else readable


_WAIT = {"wait", "רגע"}


def permission_answer(text: str) -> str | None:
    """Stricter than consent: what approves a tool call is a yes and nothing else. "Okay, tell me more" is not an answer,
    and neither is "yes, and run the linter": it comes back as None, and the request is read out again."""
    verdict = consent(text)
    if verdict == "deny" and not (_words(_lower(text)) & (_NO - _WAIT)):
        return None  # "wait, what is this?" asks first: the prompt stays open, it is not a no
    if verdict == "deny" and not (_words(_lower(strip_tasks(text))) & _NO):
        return None  # only inside a request for a session ("ask it to create denied.txt"): a new request, not a no
    if verdict != "allow":
        return verdict
    lowered = _lower(text)
    if any(p in lowered for p in _DISMISSALS):
        return None
    for p in _YES_DESPITE_NO + _STILL_ONLY_YES:
        lowered = lowered.replace(p, " ")
    last = re.findall(r"[\w']+", lowered)[-1:]
    if last and last[0] in _UNFINISHED:  # "Okay, so..." cut short by the recogniser: the rest may not be a yes
        return None
    return "allow" if _only_yes(lowered) else None


_THEN = re.compile(r"\b(?:and|then|also|plus)\b|(?<!\w)(?:ואז|וגם|גם|אחר כך)(?!\w)")


def extra_request(text: str) -> bool:
    """A yes that also asks for more: "yes, and then run the linter". "yes you can" and "go ahead and do it" do not."""
    lowered = _lower(text)
    for m in _THEN.finditer(lowered):
        rest = lowered[m.end():]
        for p in _YES_PHRASES:
            rest = rest.replace(p, " ")
        if len(_words(rest) - _YES - _WEAK_YES - _NO - _FILLER - {"also", "plus", "ואז", "וגם", "גם"}) >= 2:
            return True
    return False


_TELL = r"tell|ask|get|remind|instruct"
_TELL_HE = r"ו?(?:תגידי?|תבקשי?|תשאלי?)"
_EXPLICIT = rf"\b(?:{_TELL})\b(?!')|(?<!\w){_TELL_HE}(?!\w)"
# A second target with the verb left out, after a first task: "... and lantern to pull dev", "... ול lantern למשוך dev"
# (a Hebrew "and to" joined to a Latin session name).
_SECOND_EN = (r"\band\s+(?!(?:then|also|go|switch|move|jump|change|talk|come|head|get|back|over|work|make)\b)"
              r"(?=(?:[\w-]+\s+){1,3}?(?:to|should)\b)")
_SECOND_HE = r"(?<!\w)ו[למ](?=[\s-]*[a-z])"
_SECOND = rf"{_SECOND_EN}|{_SECOND_HE}"
_NEXT = rf"(?=(?:\band\s+)?(?:\bthen\s+)?(?:{_EXPLICIT}|{_SECOND})|$)"
# "tell X to <task>": the task says what to do, never where. It ends where the next request starts.
_TASK = re.compile(rf"(?P<head>(?:\b(?:{_TELL})\b(?!')(?!\s+(?:me|us)\b)\s+|{_SECOND_EN})\S[^;]*?)\s+"
                   rf"(?:to|that|if|whether|what|why|how|when|where|should)\b(?P<body>.*?){_NEXT}",
                   re.IGNORECASE | re.DOTALL)
# "תגיד ל X <task>": the task starts at the first infinitive (ל...) or clause (ש...) after the target.
_TASK_HE = re.compile(rf"(?P<head>(?:(?<!\w){_TELL_HE}(?!\w)(?!\s*(?:לי|לנו)(?!\w))|{_SECOND_HE})"
                      rf"[\s-]*\S+(?:\s+\S+)*?)\s+(?P<body>[לש]\w+.*?){_NEXT}", re.IGNORECASE | re.DOTALL)


def strip_tasks(text: str) -> str:
    """The words with every task body replaced by ';', so a word inside a task is not taken as routing."""
    text = _TASK.sub(lambda m: f"{m.group('head')} ; ", text)
    return _TASK_HE.sub(lambda m: f"{m.group('head')} ; ", text)


def _body_start(text: str) -> int | None:
    found = [m.start("body") for m in (_TASK.search(text), _TASK_HE.search(text)) if m]
    return min(found) if found else None


def clauses(text: str) -> list[str]:
    """'tell X to A and tell Y to B' (or '... and Y to B') as its parts; one part when there is only one.

    A verbless second target counts only after a task: "tell bluebell and lantern to pull dev" is one request.
    """
    out = []
    for part in re.split(rf"[,;]?\s*(?:\band\s+)?(?:\bthen\s+)?(?={_EXPLICIT})", text, flags=re.IGNORECASE):
        while (start := _body_start(part)) is not None and (
                second := re.compile(_SECOND, re.IGNORECASE).search(part, start)):
            out.append(part[:second.start()].rstrip(" ,"))
            part = part[second.start():]
        out.append(part)
    return [p for p in out if p.strip()] or [text]


def content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"\w+", _lower(text)) if len(w) > 2} - {"the", "and", "then", "tell", "ask", "again"}


_SWITCH = ("switch", "go to", "move to", "change to", "jump to", "back to", "talk to", "over to", "work on",
           "תעבור", "עבור ל", "תחליף", "החלף", "לך ל", "תלך ל", "חזור ל", "תחזור ל")


def switch_intent(text: str) -> bool:
    """The user asked to change sessions, not merely mentioned one ("tell X to ...")."""
    lowered = re.sub(r"\b(?:back )?to (?:me|us|you)\b", " ", _lower(strip_tasks(text)))
    return any(p in lowered for p in _SWITCH)


_CLOSE_HE = r"(?<!\w)ו?(?:תנתקי?|נתק|תורידי?|הורד|תסירי?|הסר|תסגור|תסגרי|סגור|סגרי|תוציאי?|הוצא)(?!\w)"
_CLOSE_VERB = re.compile(rf"\b(?:disconnect|unplug|detach|drop|remove|kick|close|shut|hang up on|get rid of)\b|{_CLOSE_HE}")
_TAKE_OFF = re.compile(r"\b(?:take|get|let|put)\s+(?P<obj>(?:\S+\s+){0,8}?\S+)\s+off\b")
_LEAVE = re.compile(r"\b(?:let|have|make)\s+(?P<obj>(?:\S+\s+){0,8}?\S+)\s+leave\b|"
                    r"(?P<subj>[^.;!?]+?)\s+(?:can|should|may|must|could)\s+leave\b")
# Where the words that say which sessions end: a new sentence, or another request ("..., and tell beta to ...").
_OBJECT_END = re.compile(r"[.;!?]|\b(?:and\s+)?(?:then\s+)?(?:tell|ask|switch|go|move|keep|leave|stay)\b|"
                         r"(?<!\w)ו?(?:תשאירי?|תשאירו|השאר את|השאירי|תגידי?|תבקשי?|תעבור)(?!\w)")
_FROM_VOICE = re.compile(r"\s*\b(?:from|off)\s+(?:the\s+)?(?:voice|call|line)\b.*$|\s*(?:מהקול|מהשיחה|מהווייס).*$")
_EXCEPT = re.compile(r"\b(?:except(?:\s+for)?|besides|but(?:\s+not)?|other\s+than|apart\s+from|aside\s+from|save\s+for|"
                     r"excluding|minus)\b|(?<!\w)(?:חוץ\s*מ|מלבד|פרט\s*ל|למעט|בלי)")
_ALL = re.compile(r"\b(?:all|every|everything|everyone|everybody|each)\b|(?<!\w)(?:כל|הכל|הכול|כולם|כולן)(?!\w)")
_REST = re.compile(r"\b(?:the\s+)?(?:rest|others)\b|\b(?:everything|everyone|everybody)\s+else\b|"
                   r"\bthe\s+other\s+(?:sessions|ones)\b|\ball\s+other\s+sessions\b|"
                   r"(?<!\w)(?:השאר|האחרים|האחרות|שאר הסשנים)(?!\w)")
_KEEP = re.compile(r"(?:\b(?:keep|leave)\b(?!\s+(?:the\s+)?(?:voice|call)\b)|(?<!\w)ו?(?:תשאירי?|תשאירו|השאר את|השאירי)(?!\w))"
                   rf"(?P<tail>.*?)(?=$|[.;!?]|{_CLOSE_VERB.pattern})")
_LIST = re.compile(r",|&|\b(?:and|or)\b|(?<!\w)ו-?(?=\s*\S)")
_OBJECT_FILLER = {"the", "a", "my", "these", "those", "both", "of", "session", "sessions", "one", "ones", "voice",
                  ",", "and", "or", "את", "ה", "ו", "הסשן", "הסשנים", "סשן", "סשנים"}


def disconnect_intent(text: str) -> bool:
    """The user asked to take a session off the voice, not to have a session drop something ("tell billing to drop it")."""
    lowered = _lower(strip_tasks(text))
    return bool(_CLOSE_VERB.search(lowered) or _TAKE_OFF.search(lowered) or _LEAVE.search(lowered))


class CloseAsk:
    """The sessions the user's words take off the voice. `ties`: a name two or more sessions answer to (ask which);
    `unclear`: words that ask to close but name nothing the daemon can pick (ask which); `inverse`: "all except ..."."""

    def __init__(self, close=(), keep=(), ties=(), inverse=False, unclear=False):
        self.close, self.keep, self.ties, self.inverse, self.unclear = list(close), list(keep), list(ties), inverse, unclear

    def __repr__(self):
        return (f"CloseAsk(close={[s.name for s in self.close]}, keep={[s.name for s in self.keep]}, "
                f"ties={[[s.name for s in t] for t in self.ties]}, inverse={self.inverse}, unclear={self.unclear})")


def _close_object(lowered: str) -> tuple[str, int, int] | None:
    """The words saying which sessions to close, and where they sit in `lowered`."""
    found = []
    for m in _TAKE_OFF.finditer(lowered):
        found.append((m.start(), m.group("obj"), m.start("obj"), m.end("obj")))
    for m in _LEAVE.finditer(lowered):
        group = "obj" if m.group("obj") is not None else "subj"
        found.append((m.start(), m.group(group), m.start(group), m.end(group)))
    for m in _CLOSE_VERB.finditer(lowered):
        rest = lowered[m.end():]
        end = _OBJECT_END.search(rest)
        found.append((m.start(), rest[:end.start()] if end else rest, m.end(), m.end() + (end.start() if end else len(rest))))
    if not found:
        return None
    _, obj, start, end = min(found)
    return _FROM_VOICE.sub("", obj), start, end


def _named(text: str, sessions: list) -> tuple[list, list]:
    """(sessions clearly named, ties) in a list of names: "harbor, voice, and kestrel", "harbor ו-voice"."""
    from sessions import name_groups

    named, ties = [], []
    for piece in _LIST.split(text):
        for group in name_groups(piece, sessions):
            if len(group) == 1:
                named += [s for s in group if s not in named]
            elif group not in ties:
                ties.append(group)
    return named, ties


def close_request(text: str, sessions: list) -> CloseAsk | None:
    """Which sessions the user asked to take off the voice, from their own words; None if they did not ask.

    Names are matched as everywhere else (sessions.name_groups). "All except X, Y", "close the rest" (with what to keep
    said in the same breath) and "everything" select the complement; a name two sessions answer to is a tie, never a
    guess. Words that close something inside a session ("close the issue in billing") name no session.
    """
    from sessions import name_groups

    lowered = _lower(strip_tasks(text))
    spot = _close_object(lowered)
    if spot is None:
        return None
    obj, start, end = spot
    kept, kept_ties = [], []
    for m in _KEEP.finditer(lowered):
        if not (start <= m.start() < end):
            named, ties = _named(m.group("tail"), sessions)
            kept += [s for s in named if s not in kept]
            kept_ties += ties
    cut = _EXCEPT.search(obj)
    head, tail = (obj[:cut.start()], obj[cut.end():]) if cut else (obj, "")
    if (cut and _ALL.search(head)) or _REST.search(obj) or (_ALL.search(obj) and not name_groups(obj, sessions)):
        named, ties = _named(tail, sessions)
        kept += [s for s in named if s not in kept]
        if _REST.search(obj) and not cut:  # "harbor and voice stay, close the rest": what is kept is said outside
            named, ties_out = _named(lowered[:start] + " ; " + lowered[end:], sessions)
            kept += [s for s in named if s not in kept]
            ties += ties_out
        ties += kept_ties
        if ties:
            return CloseAsk(keep=kept, ties=ties, inverse=True)
        if _REST.search(obj) and not cut and not kept:
            return CloseAsk(inverse=True, unclear=True)  # the rest of what? ask which to keep
        return CloseAsk(close=[s for s in sessions if s not in kept], keep=kept, inverse=True)
    from sessions import _tokens

    first = next((t for t in _tokens(head) if t not in _OBJECT_FILLER), "")
    if not first or not name_groups(first, sessions):
        return CloseAsk(unclear=True)  # "close it", "close the issue in billing": no session named where the close is
    named, ties = _named(head, sessions)
    if tail:
        spared, spared_ties = _named(tail, sessions)
        kept += spared
        ties += spared_ties
    close = [s for s in named if s not in kept]
    return CloseAsk(close=close, keep=kept, ties=ties, unclear=not close and not ties)


# ---------- starting a new session (docs/design/new-session.md) ----------

_HARNESS_SAID = (("codex", r"codex|קודקס"), ("opencode", r"open[\s-]*code|אופן[\s-]*קוד"), ("claude-code", r"claude(?:[\s-]*code)?|קלוד(?:[\s-]*קוד)?"))
_ANY_HARNESS = "|".join(pattern for _, pattern in _HARNESS_SAID)
_NEW_ONE = (rf"(?:(?:a|an|another|one\s+more|me|us|up)\s+)*(?:(?:new|fresh|another|second|additional)\s+)*"
            rf"(?:(?:{_ANY_HARNESS})\s+)?(?:session|agent|thread)\b(?!\s+mode)")
_START_VERB = r"(?:start|open|launch|create|begin|spin\s+up|fire\s+up|kick\s+off|bring\s+up)"
_START_HE = r"(?<!\w)ו?(?:תפתחי?|פתחי?|תתחילי?|התחל|התחילי|תריצי?|תרימי?|צור|תיצור|תיצרי)(?!\w)"
_START = re.compile(
    rf"\b{_START_VERB}\s+{_NEW_ONE}"
    rf"|\b(?:{_START_VERB}|run)\s+(?:(?:a|an|another|up)\s+)?(?:new\s+)?(?:{_ANY_HARNESS})\b(?=\s*(?:$|[.,;!?]|in\b|on\b|at\b|for\b|here\b|inside\b|called\b|named\b))"
    rf"|\b(?:new|another)\s+(?:(?:{_ANY_HARNESS})\s+)?(?:session|agent)\s+(?:in|on|for|at|here|inside|named|called)\b"
    rf"|{_START_HE}\s+(?:\S+\s+){{0,2}}?(?:סשן|סוכן|אייג'נט|{_ANY_HARNESS})")
_NAME_SAID = re.compile(r"(?:\b(?:called|named|name\s+it|call\s+it|with\s+the\s+name)|(?<!\w)(?:בשם|ותקראי?\s+לו|שנקרא))\s+(?P<name>[^.;!?,]+)")
_NAME_END = re.compile(r"\s+(?:in|on|at|for|inside|under|and)\s+|\s+(?:ב|על)(?:-|\s)")
_PLACE_BEFORE = re.compile(r"(?:\b(?:in|inside|at|under|into)\s+(?:(?:the|my)\s+)?|\b(?:folder|repo|repository|project)\s+)$")
_ON_MACHINE = re.compile(r"\bon\s+(?:(?:the|my)\s+)?(?:machine\s+)?(?P<name>[\w-]+(?:\s+[\w-]+)?)")
_HERE_MACHINE = re.compile(r"\bon\s+this\s+(?:mac|machine|computer|laptop)\b|\blocally\b")
_HERE_FOLDER = re.compile(r"\b(?:here|same\s+(?:folder|place|repo|project)|this\s+(?:folder|repo|project|one))\b|(?<!\w)(?:כאן|פה|באותה\s+תיקייה)(?!\w)")


def start_intent(text: str) -> bool:
    """The user asked for a new coding-agent session, not for a session to start something ("tell shop to start the
    server") and not for a mode ("start session mode")."""
    return bool(_START.search(_lower(strip_tasks(text))))


class StartAsk:
    """What the user's words ask to start. `harness`: the one they said, or None; `harnesses`: more than one was said
    (ask which). `folder`: the one path their words pick, or None; `ties`: the paths of several their words fit (ask
    which). `machine`: None when not said, "" for this Mac, else the machine's name. `name`: what they called it, raw."""

    def __init__(self, harness=None, harnesses=(), folder=None, ties=(), machine=None, name=None):
        self.harness, self.harnesses, self.folder, self.ties = harness, list(harnesses), folder, list(ties)
        self.machine, self.name = machine, name

    def __repr__(self):
        return (f"StartAsk(harness={self.harness}, folder={self.folder}, ties={self.ties}, machine={self.machine!r}, "
                f"name={self.name!r})")


def start_request(text: str, places: list[tuple[str, str]], machines: list[str] = (), here: str = "",
                  here_folder: str | None = None) -> StartAsk | None:
    """What the user asked to start, from their own words; None if they did not ask.

    `places` are the folders a session may start in, as (what it is called, its path): a folder's own name, and the
    name of a session running there. The folder is matched as a session's name is (sessions.name_groups), so a word two
    folders answer to is a tie and never a guess, and a path that is not in `places` cannot be said at all. `machines`
    are the other machines' names, `here` this Mac's; `here_folder` is where "here" means (the active session's).
    """
    from sessions import Session, _hears, _name_words, name_groups

    lowered = _lower(strip_tasks(text))
    if not _START.search(lowered):
        return None
    name = None
    said = _NAME_SAID.search(lowered)
    if said:
        raw = said.group("name")
        cut = _NAME_END.search(raw)
        name = (raw[:cut.start()] if cut else raw).strip(" \"'") or None
        lowered = lowered[:said.start()] + " ; " + (raw[cut.start():] if cut else "") + lowered[said.end():]
    machine = "" if _HERE_MACHINE.search(lowered) else None
    for m in _ON_MACHINE.finditer(lowered):
        heard = m.group("name").split()
        for candidate in [here, *machines]:
            words = _name_words(candidate)
            if words and len(heard) >= len(words) and all(_hears(w, h) for w, h in zip(words, heard)):
                machine = "" if candidate == here else candidate
                spoken = " ".join(heard[:len(words)])
                lowered = lowered[:m.start()] + " ; " + lowered[m.start("name") + len(spoken):]
                break
        if machine is not None:
            break
    found, spans = [], []
    for harness, pattern in _HARNESS_SAID:
        for m in re.finditer(rf"(?<![\w-])(?:{pattern})(?![\w-])", lowered):
            if any(a <= m.start() < b for a, b in spans) or _PLACE_BEFORE.search(lowered[:m.start()]):
                continue  # "in codex-tools": a folder's name, not the agent
            spans.append((m.start(), m.end()))
            if harness not in found:
                found.append(harness)
    for a, b in sorted(spans, reverse=True):
        lowered = lowered[:a] + " ; " + lowered[b:]
    stand_ins = [Session(id=str(i), name=label, cwd=path) for i, (label, path) in enumerate(places)]
    paths = []
    for group in name_groups(lowered, stand_ins):
        for s in group:
            if s.cwd not in paths:
                paths.append(s.cwd)
    if not paths and here_folder and _HERE_FOLDER.search(lowered):
        paths = [here_folder]
    ties = paths if len(paths) > 1 else []
    return StartAsk(harness=found[0] if len(found) == 1 else None, harnesses=found if len(found) > 1 else (),
                    folder=paths[0] if len(paths) == 1 else None, ties=ties, machine=machine, name=name)


def back_intent(text: str) -> bool:
    """'go back', 'the previous session': the session that was active before."""
    return bool(re.search(r"\b(?:previous|last session|last one|switch back|go back|הקודם)\b", _lower(text)))


_ORCHESTRATOR = ("orchestrator", "orchestration", "route automatically", "אורקסטרטור")
_SESSION = ("session mode", "direct mode", "focus mode", "מצב סשן")
_FOCUS = ("focus on", "only talk to", "talk only to", "pin to", "רק עם", "תתמקד ב")


def mode_intent(text: str, sessions: list | None = None) -> str | None:
    """'orchestrator' or 'session' when the user asked to change routing mode, else None.

    "Focus on X" asks for session mode only when X is a session: "focus on the failing test" is a task.
    """
    lowered = _lower(strip_tasks(text))
    if any(p in lowered for p in _ORCHESTRATOR):
        return "orchestrator"
    if any(p in lowered for p in _SESSION):
        return "session"
    from sessions import mentions

    for p in _FOCUS:
        at = lowered.find(p)
        if at >= 0 and (sessions is None or mentions(lowered[at + len(p):], sessions)):
            return "session"
    return None


_EVERYONE = r"everyone|everybody|all (?:the )?sessions|every session|all of them|all of you"
# Only where the words say who it is for: "tell everyone ...", "everyone, ...", "everyone except beta should ...".
_BROADCAST = re.compile(
    rf"\b(?:{_TELL})\s+(?:{_EVERYONE}|each session)\b"
    rf"|^\W*(?:(?:ok|okay|so|now|hey)\W+)*(?:{_EVERYONE})\s*(?:(?:on|at|in) (?:the )?[\w-]+\s*)?"  # "everyone on devbox, ..."
    rf"(?:,|should|must|needs?\b|has to|have to|except|but\b|other than)"
    rf"|\b(?:send|say|broadcast|post)\b[^.;?!]*?\bto (?:all (?:the )?sessions|every session)\b"
    rf"|(?<!\w){_TELL_HE}\s*[למ]\s*-?\s*(?:כולם|כל הסשנים)(?!\w)"
    rf"|^\W*(?:כולם|כל הסשנים)\s*(?:,|חוץ|צריכים)",
    re.IGNORECASE)


def broadcast_intent(text: str) -> bool:
    """'Tell all sessions to ...': one request for every session, not a mode change. "Fix all of them" is a task."""
    return bool(_BROADCAST.search(_lower(strip_tasks(text))))


_DISMISS_WORDS = {"later", "stop", "quiet", "enough", "nevermind", "די", "שקט", "מספיק", "עזוב", "תעזוב"}
_DISMISS_PHRASES = ("i know", "not now", "for now", "never mind", "forget it", "leave it", "shut up", "not yet",
                    "לא עכשיו", "אחר כך")


def dismiss_intent(text: str) -> bool:
    """The user waved off what the bot brought up ("I know", "later", "stop"); a task is not a dismissal."""
    lowered = _lower(strip_tasks(text))
    return bool(set(re.findall(r"[\w']+", lowered)) & _DISMISS_WORDS) or any(p in lowered for p in _DISMISS_PHRASES)


_ACK = re.compile(r"^(?:ok|okay|cool|nice|good|great|thanks|thank you|perfect|got it|understood|right|sweet|awesome|"
                  r"אוקיי|אוקי|יופי|מעולה|סבבה|תודה|טוב|הבנתי)(?:[\s,.!]+(?:ok|okay|cool|nice|good|great|thanks|thank you|"
                  r"perfect|got it|understood|right|sweet|awesome|אוקיי|אוקי|יופי|מעולה|סבבה|תודה|טוב|הבנתי))*[\s,.!]*$")
# This utterance holds the send as a whole. "Hold off on the migration" is an instruction with a constraint in it, and
# "wait, did it go live?" is a question.
_HOLD = re.compile(r"^\W*(?:(?:no,?\s+)?(?:not yet|hold off|hold on|wait)\W*(?:$|let me\b|i want\b|i need\b)|"
                   r"(?:עוד לא|חכה|רגע)\W*$)|\b(?:do not|don't) send (?:it|that|this|anything)\b|\bbefore you send\b|אל תשלח")
_STATUS = ("need me", "needs me", "need from me", "needs from me", "need to do", "waiting on me", "waiting for me",
           "on me", "anything i need", "what's left", "what is left", "still open", "open items", "where are we",
           "what's open", "everywhere", "every machine", "all machines", "all the machines", "each machine",
           "what's going on", "what is going on", "all my sessions", "all the sessions", "every session",
           "מה אני צריך", "מה נשאר", "מה פתוח", "מי מחכה", "איפה אנחנו", "מחכה לי", "מחכים לי", "בכל המכונות")


# Whole phrases: "on me" is in "turn on meeting mode". Hebrew phrases match inside words, as a prefix letter ("ומה
# נשאר") is part of the word.
_STATUS_RE = re.compile("|".join(rf"(?<![\w']){re.escape(p)}(?![\w'])" if p.isascii() else re.escape(p)
                                 for p in _STATUS))


def status_intent(text: str) -> bool:
    """A question about what is open or who needs the user: answered from the daemon's list, never from memory."""
    return bool(_STATUS_RE.search(_lower(text)))


def cut_off(text: str) -> bool:
    """Speech that plainly stops mid-thought. Only the certain cases: "it's what I asked for" ends in a preposition and is
    whole, so anything less plain is left to the checker, which reads the conversation."""
    stripped = text.strip()
    if stripped.endswith(("—", "-", "...", "…")):
        return True
    words = re.findall(r"[\w']+", _lower(stripped))
    if len(words) < 2:
        return False
    return (len(words[-1]) == 1 and bool(re.match(r"[\u0590-\u05ff]", words[-1]))) or \
        (words[-2] in ("לו", "לה", "להם") and len(words[-1]) <= 2) or words[-2:] in (["tell", "him"], ["tell", "her"])


def ack_only(text: str) -> bool:
    """Nothing but an acknowledgment ("okay nice", "thanks"): it asks for nothing unless a question was just put."""
    return bool(_ACK.match(_lower(text).strip()))


def hold_intent(text: str) -> bool:
    """The user is still deciding ("not yet", "hold off, I want to think"): nothing goes until they say so."""
    return bool(_HOLD.search(_lower(text).strip()))


_RENAME = ("rename", "call it", "call this", "name it", "name this", "call the", "שנה את השם", "תשנה את השם",
           "תקרא ל", "קרא ל")


def rename_intent(text: str) -> bool:
    lowered = text.lower()
    return any(p in lowered for p in _RENAME) or bool(re.search(r"\bcall \w+ \w+", lowered) and "call it" in lowered)


_INFER_NAME = re.compile(
    r"\b(?:infer|from (?:the )?context|you (?:choose|pick|decide)|pick (?:a|the|good|better) names?|"
    r"choose (?:a|the) names?|something (?:meaningful|better|clearer)|based on what|by what (?:it|they)|"
    r"meaningful names?|better names?)\b|לפי ההקשר|תבחר|תחליט|תמציא",
    re.IGNORECASE)


def infer_name_intent(text: str) -> bool:
    """The user asked the assistant to choose the name ("you infer it", "name them by what they do")."""
    return bool(_INFER_NAME.search(text))


def valid_name(name: str) -> bool:
    return bool(re.fullmatch(r"[\w][\w ./-]{0,38}[\w]|[\w]", name.strip()))


def _host(value: str) -> str:
    return (urlparse(f"//{value}").hostname or "").lower()


def _same_site(headers: Headers) -> bool:
    """No Origin (a script, or a same-origin GET), or exactly this address: another localhost port is another site."""
    origin = headers.get("origin")
    return origin is None or urlparse(origin).netloc.lower() == headers.get("host", "").lower()


_PAGE_HOST = re.compile(r"[0-9a-f]{16}\.localhost")


def page_host(page_key: str) -> str:
    """Cookies ignore ports, so one set on "localhost" reaches any server on any localhost port. This name is ours alone."""
    return hashlib.sha256(page_key.encode()).hexdigest()[:16] + ".localhost"


def _local_headers(headers: Headers) -> bool:
    host = _host(headers.get("host", ""))
    return (host in LOCAL_HOSTS or bool(_PAGE_HOST.fullmatch(host))) and _same_site(headers)


def is_local_request(request: Request) -> bool:
    """Blocks web pages (Origin) and DNS rebinding (Host) from reaching the daemon on 127.0.0.1."""
    return _local_headers(request.headers)


LOCAL_COOKIE = "pointe_local"
_OPEN_PATHS = {"/voice/health"}
_PHONE_PATHS = {"/voice/phone", "/voice/approve", "/voice/status", "/voice/listen", "/voice/switch", "/voice/hung-up", "/voice/disconnect", "/voice/rename", "/voice/new-session", "/voice/mode", "/voice/say", "/voice/correct", "/voice/polish", "/voice/meeting", "/voice/meeting/transcript", "/voice/notes", "/voice/prefs", "/voice/attention", "/voice/voiceprint", "/voice/artifact", "/voice/briefings", "/voice/briefings/latest", "/voice/briefings/schedule", "/voice/conflicts", "/voice/dictionary", "/voice/challenge", "/voice/drive", "/voice/dump", "/voice/hub/invite", "/voice/hub/nodes", "/voice/hub/revoke"}  # all the phone app needs; nothing else takes its key
# A node's own routes, and the phone app's pairing: each authenticates in its handler (an HMAC over the hub's nonce; a
# one-time code), so no page, phone or daemon secret is asked for. On loopback they still need local headers, and a page
# never reaches them.
_NODE_PATHS = {"/voice/node": "websocket", "/voice/node/pair": "http", "/voice/phone/pair": "http"}
_NEEDS_KEY = "Open this page with bin/voice-open, or run /pointe:voice in a Claude Code session (pointe join for other agents). It carries the key this address needs."
_NO_FRAMING = (b"content-security-policy", b"frame-ancestors 'self'")


class LocalAuth:
    """ASGI, so WebSockets are covered too. On the main listener every route needs a secret: a container or another user
    can reach loopback with any Host header it likes, and a voice call is a microphone into the user's sessions."""

    def __init__(self, app, token: str, page_key: str, remote=None, phone=None):
        self.app, self.token, self.page_key, self.remote, self.phone = app, token, page_key, remote, phone

    def _authorized(self, connection: HTTPConnection) -> bool:
        cookie = connection.cookies.get(LOCAL_COOKIE, "")
        bearer = connection.headers.get("authorization", "")
        return bool(self.page_key and self.token) and (
            hmac.compare_digest(cookie.encode(), self.page_key.encode())
            or hmac.compare_digest(bearer.encode(), f"Bearer {self.token}".encode()))

    async def _refuse(self, scope, receive, send, text: str = "forbidden") -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
        else:
            await PlainTextResponse(text, status_code=403)(scope, receive, send)

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        connection = HTTPConnection(scope)

        async def framed(message):
            if message["type"] == "http.response.start":
                message["headers"] = [*message["headers"], _NO_FRAMING]
            await send(message)

        if scope["path"] in _PHONE_PATHS:  # the phone app: its own key, on the TLS listener or from this machine
            on_tls = bool(self.remote and self.remote.on_tls_listener(scope))
            wanted = "websocket" if scope["path"] == "/voice/phone" else "http"
            who = self.phone(connection.headers.get("authorization")) if scope["type"] == wanted and self.phone else None
            if who and (on_tls or _local_headers(connection.headers)):
                scope.setdefault("state", {})["pointe_phone"] = True  # the pairing check on the TLS listener honours it
                if isinstance(who, str):
                    scope["state"]["pointe_phone_id"] = who  # which phone: Unpair ends only its call
                return await self.app(scope, receive, send)
            if scope["path"] == "/voice/phone":
                return await self._refuse(scope, receive, send)
        if scope["path"] in _NODE_PATHS:
            on_tls = bool(self.remote and self.remote.on_tls_listener(scope))
            if (scope["type"] == _NODE_PATHS[scope["path"]] and "origin" not in connection.headers
                    and (on_tls or _local_headers(connection.headers))):
                scope.setdefault("state", {})["pointe_node"] = True  # Remote.guard leaves the check to the handler
                return await self.app(scope, receive, framed if scope["type"] == "http" else send)
            return await self._refuse(scope, receive, send)
        if self.remote and self.remote.on_tls_listener(scope):
            if scope["type"] == "websocket" and not (self.remote.websocket_allowed(connection)):
                return await self._refuse(scope, receive, send)
            return await self.app(scope, receive, framed)  # http: Remote.guard decides
        if not _local_headers(connection.headers):
            return await self._refuse(scope, receive, send)
        path = scope["path"]
        if scope["type"] == "http" and path in _OPEN_PATHS:
            return await self.app(scope, receive, framed)
        offered = parse_qs(scope.get("query_string", b"").decode()).get("key", [None])[0]
        if scope["type"] == "http" and path == "/voice" and offered is not None:
            if not hmac.compare_digest(offered.encode(), self.page_key.encode()):
                return await self._refuse(scope, receive, send)
            home = page_host(self.page_key)
            if _host(connection.headers.get("host", "")) != home:
                port = connection.url.port or 80
                moved = RedirectResponse(f"http://{home}:{port}/voice?key={offered}", status_code=303)
                return await moved(scope, receive, send)
            response = RedirectResponse("/voice", status_code=303)  # the key leaves the address bar
            response.set_cookie(LOCAL_COOKIE, self.page_key, max_age=365 * 86400, httponly=True, samesite="strict")
            return await response(scope, receive, send)
        if not self._authorized(connection):
            return await self._refuse(scope, receive, send, _NEEDS_KEY if path == "/voice" else "forbidden")
        await self.app(scope, receive, framed)


# Monologue: the user thinks out loud and the bot stays silent until handed the turn. Both ends match only at the start
# of an utterance: "I'll just listen to the customer" mid-thought must not enter, and "what do you think about X" inside a
# monologue is content unless it opens the utterance.
_LISTEN = re.compile(r"^\W*(?:(?:ok(?:ay)?|so|hey)\W+)?(?:just listen|listen mode|monologue(?: mode)?|"
                     r"let me (?:just )?think(?: (?:out )?loud| aloud)?|let me (?:just )?talk|"
                     r"i(?:'m| am) (?:just )?thinking (?:out )?loud|"
                     r"רק תקשיב|תקשיב רגע|תן לי לחשוב(?: בקול)?|אני חושב בקול)\b", re.I)
_OVER = re.compile(r"^\W*(?:(?:ok(?:ay)?|so|right|alright)\W+)?(?:over to you|your turn|go ahead|what do you think|"
                   r"thoughts\?*$|i'?m done|that'?s it|done thinking|you can talk|step in|"
                   r"(?:summari[sz]e|recap|sum up) (?:that|this|it)|turn (?:that|this|it) into|"
                   r"save (?:that|this|it) as|send (?:that|this|it) to|"
                   r"מה אתה חושב|תורך|סיימתי|זהו|אתה יכול לדבר|תסכם|תשלח את זה)", re.I)


_SEND_ON = re.compile(r"^\W*(?:(?:ok(?:ay)?|so|right|alright)\W+)?send (?:that|this|it) to\b|^\W*תשלח את זה", re.I)
_STOP_ALONE = re.compile(r"^\W*(?:stop|wait|enough|רגע|די|עצור)\W*$", re.I)


def _short(text: str, words: int) -> bool:
    return len(re.findall(r"[\w']+", text)) <= words


def listen_intent(text: str) -> bool:
    """Only as a whole short utterance: "just listen to this customer call" is a request, not the mode."""
    return _short(text, 6) and bool(_LISTEN.search(_lower(text)))


def over_intent(text: str) -> bool:
    """Only as a whole short utterance, so "what do you think the customer wants" mid-thought stays content. A send
    names its target, so it may run longer; a lone "stop" or "wait" always ends it."""
    lowered = _lower(text)
    if _STOP_ALONE.match(lowered):
        return True
    if _SEND_ON.search(lowered):
        return _short(text, 16)
    return _short(text, 8) and bool(_OVER.search(lowered))


_QUOTE = re.compile(r"\b(?:exactly|word for word|verbatim|quote|read (?:me|it|out)|the full (?:thing|message|text|answer)|"
                    r"what did (?:it|he|she|they|\w+) (?:say|write|answer|reply))\b|מה בדיוק|תקריא|מילה במילה|מה הוא כתב|מה הוא אמר",
                    re.I)


def quote_intent(text: str) -> bool:
    """"What exactly did it say": answered from the record, word for word. Anything else is a question for the session."""
    return bool(_QUOTE.search(_lower(text)))


_APPROVAL = re.compile(r"\b(?:approv(?:e|es|ed|al)|authori[sz](?:e|es|ed|ation)|signed off|sign-off|green ?light)\b"
                       r"|(?<!\w)(?:מאשרת?|אישרה?|אושר|אישור|מאושר)(?!\w)")
_PERMIT = r"(?:go ahead|please|you (?:can|may)|ok(?:ay)?|now|קדימה|יאללה|סבבה)"
# Hebrew forms of the actions brief.typed_approval_needed names: imperative, future-as-imperative, infinitive.
_HE_VERBS = {"merge": "מזג|תמזג|תמזגי|למזג", "delete": "מחק|תמחק|תמחקי|למחוק", "post": "פרסם|תפרסם|תפרסמי|לפרסם",
             "remove": "מחק|תמחק|תמחקי|למחוק", "publish": "פרסם|תפרסם|תפרסמי|לפרסם", "send": "שלח|תשלח|תשלחי|לשלוח"}


def relays_approval(message: str, pending: str) -> bool:
    """Does this message pass on, or claim, the owner's approval for the action that waits on an approval typed in the
    session's terminal? Only the owner typing it counts, so the daemon refuses such a send. A question or unrelated news
    is not one."""
    text = _lower(message)
    if _APPROVAL.search(text):
        return True
    verbs = [v for v in re.findall(r"[a-z]+", _lower(pending))[:1]]
    for verb in verbs:
        stem = re.escape(verb[:-1] if verb.endswith("e") else verb)
        if re.match(rf"\s*(?:{_PERMIT}\W+(?:and\s+)?)*{stem}\w*\b", text):
            return True
        if re.search(rf"\b{_PERMIT}\W+(?:and\s+)?(?:\w+\s+){{0,2}}{stem}\w*\b", text):
            return True
        if he := _HE_VERBS.get(verb):
            if re.search(rf"(?<!\w)(?:{he})(?!\w)", text):
                return True
    return False

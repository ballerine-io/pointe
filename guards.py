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
             "their", "um", "uh",
             "של", "את", "עם", "בין", "או", "כי", "אז", "ש", "ו", "ה", "ל", "ב", "מ", "כמו", "אם"}
# Words a question can end on ("what are you looking at", "what the date is"): unfinished only outside a question.
_DANGLING_OUTSIDE_QUESTIONS = {"to", "at", "of", "for", "with", "about", "from", "into", "like", "is", "are", "was", "were",
                               "על", "גם"}
_QUESTION = re.compile(r"\b(what|where|who|whom|which|when|why|how|whose)\b|\?|\b(מה|איפה|מי|מתי|למה|איך|איזה)\b")


def unfinished(text: str) -> bool:
    """A sentence cut by a pause, not ended: "the difference between—", "I want to look at". Its end is still coming."""
    stripped = text.strip()
    if re.search(r"(—|–|-|…|\.\.\.|,)$", stripped):
        return True
    words = re.findall(r"[\w']+", stripped.lower())
    if not words:
        return False
    return words[-1] in _DANGLING or words[-1] in _DANGLING_OUTSIDE_QUESTIONS and not _QUESTION.search(stripped.lower())
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


_WAIT = {"wait", "רגע"}


def permission_answer(text: str) -> str | None:
    """Stricter than consent: what approves a tool call is a yes and nothing else. "Okay, tell me more" is not an answer,
    and neither is "yes, and run the linter": it comes back as None, and the request is read out again."""
    verdict = consent(text)
    if verdict == "deny" and not (_words(_lower(text)) & (_NO - _WAIT)):
        return None  # "wait, what is this?" asks first: the prompt stays open, it is not a no
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


_DISCONNECT = re.compile(r"\b(disconnect|unplug|detach|drop|remove|kick)\b|\b(take|let) \S+(?: \S+)? off (?:the )?(?:voice|call)\b|"
                         r"נתק|תנתק|תוריד|הורד|תסיר|הסר")


def disconnect_intent(text: str) -> bool:
    """The user asked to take a session off the voice, not to have a session drop something ("tell billing to drop it")."""
    return bool(_DISCONNECT.search(_lower(strip_tasks(text))))


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
    rf"|^\W*(?:(?:ok|okay|so|now|hey)\W+)*(?:{_EVERYONE})\s*"
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
           "what's open", "מה אני צריך", "מה נשאר", "מה פתוח", "מי מחכה", "איפה אנחנו", "מחכה לי", "מחכים לי")


def status_intent(text: str) -> bool:
    """A question about what is open or who needs the user: answered from the daemon's list, never from memory."""
    lowered = _lower(text)
    return any(p in lowered for p in _STATUS)


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
_PHONE_PATHS = {"/voice/phone", "/voice/approve", "/voice/status", "/voice/listen", "/voice/switch", "/voice/hung-up", "/voice/disconnect", "/voice/mode", "/voice/say", "/voice/correct", "/voice/polish", "/voice/meeting", "/voice/meeting/transcript", "/voice/notes", "/voice/prefs", "/voice/attention", "/voice/voiceprint", "/voice/artifact", "/voice/briefings", "/voice/briefings/latest", "/voice/briefings/schedule", "/voice/conflicts", "/voice/dictionary"}  # all the phone app needs; nothing else takes its key
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
            if (scope["type"] == wanted and self.phone and self.phone(connection.headers.get("authorization"))
                    and (on_tls or _local_headers(connection.headers))):
                scope.setdefault("state", {})["pointe_phone"] = True  # the pairing check on the TLS listener honours it
                return await self.app(scope, receive, send)
            if scope["path"] == "/voice/phone":
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

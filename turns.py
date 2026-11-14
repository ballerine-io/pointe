"""When the voice may answer (docs/design/turn-taking.md). Soniox's endpoint is a candidate for a turn end, not the
verdict: every final transcript waits for silence first, longer when the sentence reads unfinished, and a hold
("don't interrupt me") keeps the voice quiet until a release. Pure rules, so tests replay transcripts offline."""

import re
from dataclasses import dataclass

from guards import unfinished


@dataclass(frozen=True)
class Patience:
    """Seconds of silence since the user's last word before a final transcript becomes the turn."""
    complete: float  # the text reads as a whole sentence
    unfinished: float  # it ends on a dangling word, a filler or a comma (guards.unfinished)
    maximum: float  # the cap while the user keeps voicing and no whole sentence arrives


LEVELS = {
    "quick": Patience(complete=0.4, unfinished=1.5, maximum=6.0),  # about today: Soniox's own 0.3-0.5 s and no more
    "normal": Patience(complete=1.0, unfinished=3.0, maximum=10.0),
    "patient": Patience(complete=1.8, unfinished=4.5, maximum=14.0),
}
DEFAULT_LEVEL = "normal"
SHORT_LETTERS = 8  # a yes, a no, "run it", "לא עכשיו": never delayed, they answer approvals and stop the bot


def _short_answer(text: str) -> bool:
    words = re.findall(r"[\w']+", text)
    return len(words) == 1 or len(words) == 2 and sum(len(w) for w in words) <= SHORT_LETTERS


def settle(text: str, held: bool, level: str) -> float:
    """How long a final must have been followed by silence. 0 for a short answer with nothing held, and for a hold request."""
    patience = LEVELS.get(level, LEVELS[DEFAULT_LEVEL])
    if hold_intent(text):
        return 0.0  # "don't interrupt me" acts at once
    if unfinished(text):
        return patience.unfinished
    if not held and _short_answer(text):
        return 0.0
    return patience.complete


def maximum(level: str) -> float:
    return LEVELS.get(level, LEVELS[DEFAULT_LEVEL]).maximum


# ---------- hold: "don't interrupt me" ----------

HOLD_RELEASE_SILENCE_SECS = 8.0  # longer than a thinking pause, shorter than "is it still there?"; the phrase comes first
HOLD_WORDS = 10  # a hold request is short; "don't interrupt the deploy while the tests run" is content
RELEASE_WORDS = 12  # "so that is the whole plan, go ahead" ends with the release

_HOLD = re.compile(
    r"(?:\b(?:hold on|hang on|don'?t (?:interrupt|cut) me(?: off)?|do not (?:interrupt|cut) me(?: off)?|"
    r"let me (?:finish|talk|speak)(?: (?:my (?:thought|sentence|point)|talking|speaking))?|"
    r"i(?:'m| am) not (?:done|finished)(?: yet)?|not (?:done|finished) yet|wait (?:till|until) i(?:'m| am) done|"
    r"give me a (?:second|sec|minute|moment)|one (?:second|sec|moment)|just a (?:second|sec|moment))\W*$)|"
    r"(?:\b(?:don'?t|do not) interrupt\W*$)|"
    r"(?:(?:^|\W)(?:אל תפריעו? לי|אל תקטעו? אותי|(?:תן|תני|תנו) לי לסיים|(?:תן|תני|תנו) לי לדבר|(?:עוד )?לא סיימתי|חכה רגע|חכי רגע|חכה שאסיים|"
    r"רק שנייה|שנייה|רגע אחד|(?:תן|תני|תנו) לי רגע|אל תענ[היו] עדיין)\W*$)", re.I)
_RELEASE = re.compile(
    r"(?:\b(?:i(?:'m| am) (?:done|finished)|done|that'?s (?:it|all)|go ahead|over(?: to you)?|your turn|"
    r"you can (?:answer|talk|speak) now|answer now|what do you think|thoughts)\W*$)|"
    r"(?:(?:^|\W)(?:סיימתי|זה הכל|זהו|קדימה|תורך|עכשיו אתה|אתה יכול לדבר|תענה|מה אתה חושב|מה דעתך|נו)\W*$)", re.I)


def _words(text: str) -> int:
    return len(re.findall(r"[\w']+", text))


def hold_intent(text: str) -> bool:
    """A request to be left alone until further notice, as a whole short utterance ending in the phrase."""
    return _words(text) <= HOLD_WORDS and bool(_HOLD.search(text.strip()))


def before_hold(text: str) -> str:
    """The words said before the hold phrase ("I want to talk about the parser, hold on"): they are part of what is held."""
    rest = text.strip()
    while m := _HOLD.search(rest):  # "hold on, let me finish": two hold phrases, no content
        rest = rest[:m.start()].strip(" ,;:.-–—")
    return rest if _words(rest) >= 2 else ""


def release_intent(text: str) -> bool:
    """The user hands the turn back: a short utterance ending in a release phrase."""
    return _words(text) <= RELEASE_WORDS and bool(_RELEASE.search(text.strip()))


@dataclass
class Hold:
    """A hold in progress: when it began, what was said since, and when the last words came."""
    since: float
    said: list[str]
    last_at: float

    def status(self) -> dict:
        return {"since": self.since, "said": " ".join(self.said)[-600:]}

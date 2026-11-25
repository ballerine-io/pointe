"""When the voice may answer (docs/design/turn-taking.md). Soniox's endpoint is a candidate for a turn end, not the
verdict: every final transcript waits for silence first, longer when the sentence reads unfinished, shorter when
Soniox and the sound of the voice (turnsound.py) both say it ended, and a hold ("don't interrupt me") keeps the voice
quiet until a release. Pure rules, so tests replay transcripts offline."""

import re
from dataclasses import dataclass

from guards import unfinished


@dataclass(frozen=True)
class Patience:
    """Seconds of silence since the user's last word before a final transcript becomes the turn."""
    complete: float  # the text reads as a whole sentence
    unfinished: float  # it ends on a dangling word, a filler or a comma (guards.unfinished)
    maximum: float  # the cap while the user keeps voicing and no whole sentence arrives
    # A whole sentence that the other two signals also call ended: Soniox closed it itself, and the voice sounded
    # finished (turnsound.py). `agreed`: both say so. `likely`: one of them. Left out, they are `complete`.
    agreed: float = None  # type: ignore[assignment]
    likely: float = None  # type: ignore[assignment]
    # Seconds of silence after which Soniox is asked for words it still holds. Left out: so that its answer is in when
    # `complete` ends. Normal asks sooner than that: the model step starts at the final, not at the turn.
    ask: float = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        for name in ("agreed", "likely"):
            if getattr(self, name) is None:
                object.__setattr__(self, name, self.complete)


LEVELS = {
    "quick": Patience(complete=0.4, unfinished=1.5, maximum=6.0),  # about today: Soniox's own 0.3-0.5 s and no more
    # 1.3 s, from 1.0 s: on 291 recorded mid-sentence pauses of real speakers the turn was taken inside 23% of them at
    # 1.0 s and inside 10% at 1.3 s (bench/turn_rules.py; docs/design/turn-taking.md §7). The words are still asked of
    # Soniox 0.7 s after the sound, so the model reads them as soon as before, and its first sentence is seldom ready
    # before 1.3 s: a reply a model writes starts 0 to 0.1 s later. One the daemon says itself starts 0.3 s later.
    "normal": Patience(complete=1.3, unfinished=3.0, maximum=10.0, ask=0.7),
    "patient": Patience(complete=1.8, unfinished=4.5, maximum=14.0),
}
# The shorter waits tried for Normal and not shipped: on bench/turn_bench.py they took a first part that reads whole
# 0.5 or 0.8 s into its pause 94% of the time, against 0% and 15% (docs/design/turn-taking.md §6). No level uses them
# until recorded human pauses say what they cost.
CANDIDATE = Patience(complete=1.0, unfinished=3.0, maximum=10.0, agreed=0.3, likely=0.6, ask=0.7)
DEFAULT_LEVEL = "normal"
SHORT_LETTERS = 8  # a yes, a no, "run it", "לא עכשיו": never delayed, they answer approvals and stop the bot


def _short_answer(text: str) -> bool:
    words = re.findall(r"[\w']+", text)
    return len(words) == 1 or len(words) == 2 and sum(len(w) for w in words) <= SHORT_LETTERS


_STOP_WORD = re.compile(r"^\W*(?:stop|wait|enough|cancel|quiet|עצור|די|חכה|רגע)\W*$", re.I)


SOUNDS_FINISHED = 0.8  # the sound model's probability from which the voice counts as finished, and under which as
SOUNDS_OPEN = 0.2  # trailing off; between the two it says nothing (bench/turn_bench.py has the measured rates)


def settle(text: str, held: bool, level: str | Patience, answering: bool = True, endpoint: bool = False,
           sound: float | None = None) -> float:
    """How long a final must have been followed by silence. 0 for a hold request, a stop, and a short answer with nothing
    held while something waits for one (`answering`: a question, an approval, a read-back). With nothing waiting, a
    short sentence ("Okay.") may open a longer one: it settles like any other.

    A sentence that reads whole waits less when the other signals agree it ended. `endpoint`: Soniox closed the words
    itself, not on a finalize asked of it. `sound`: the probability that the voice sounded finished when it stopped
    (turnsound.score), None when it was not judged. Words that read unfinished wait the long time whatever those two
    say, a voice that trails off keeps the whole wait, and so does a sentence said in parts (`held`). The three levels
    wait the same whatever the two say (their `agreed` and `likely` are their `complete`): see CANDIDATE."""
    patience = level if isinstance(level, Patience) else LEVELS.get(level, LEVELS[DEFAULT_LEVEL])
    if hold_intent(text) or _STOP_WORD.match(text):
        return 0.0  # "don't interrupt me" and "stop" act at once
    if unfinished(text):
        return patience.unfinished
    if not held and answering and _short_answer(text):
        return 0.0
    if held or (sound is not None and sound <= SOUNDS_OPEN):
        return patience.complete
    votes = int(endpoint) + int(sound is not None and sound >= SOUNDS_FINISHED)
    return (patience.complete, patience.likely, patience.agreed)[votes]


def maximum(level: str) -> float:
    return LEVELS.get(level, LEVELS[DEFAULT_LEVEL]).maximum


# ---------- asking Soniox for words it holds ----------

FINALIZE_REPLY_SECS = 0.3  # Soniox's <fin> comes this long after a finalize (measured 0.25 to 0.34 s)
FINALIZE_MIN_SECS = 0.2  # Soniox asks for about this much silence before a finalize
FINALIZE_GAP_SECS = 2.0  # between two asks: Soniox may drop a stream asked too often


def finalize_after(level: str | Patience, sound: float | None = None) -> float:
    """Seconds of silence before the held words are asked for: so they are final when a whole sentence's settle ends,
    and no sooner. 0.7 s at Normal: on the bench it finalized 22% of clips early (0.5 s: 56%), with p90 0.76 s. When
    the voice sounded finished (`sound`, as in settle) the settle that may follow is the `likely` one, so a level whose
    `likely` is shorter asks that much sooner (CANDIDATE: 0.3 s)."""
    patience = level if isinstance(level, Patience) else LEVELS.get(level, LEVELS[DEFAULT_LEVEL])
    if sound is not None and sound >= SOUNDS_FINISHED and patience.likely < patience.complete:
        return max(FINALIZE_MIN_SECS, patience.likely - FINALIZE_REPLY_SECS)
    return patience.ask if patience.ask is not None else max(FINALIZE_MIN_SECS, patience.complete - FINALIZE_REPLY_SECS)


def finalize_due(pending: bool, voiced: bool, sound_ended: float, last_asked: float, now: float, level: str,
                 sound: float | None = None) -> bool:
    """Whether to ask Soniox for the words it has not ended yet (`finalize`). Its v6 model keeps some whole sentences open
    until about 3 s after the speech, past its own max_endpoint_delay_ms, and no turn can settle before its words are
    final (bench/results/soniox-v6.md). Asked once per silence, finalize_after(level) after the sound ended, by the voice
    detector, never by word times: those lag the audio, and a finalize while the user talks splits their words. The
    settle still decides the turn: a half sentence finalized in a pause waits like any other final."""
    return (pending and not voiced and sound_ended > last_asked and now - sound_ended >= finalize_after(level, sound)
            and now - last_asked >= FINALIZE_GAP_SECS)


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

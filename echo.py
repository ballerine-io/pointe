"""Tells the user's words apart from the bot's own voice coming back through the speakers.

Browser echo cancellation leaves a residue on laptop speakers that a VAD hears as speech and
an STT transcribes. Sound cannot tell the two apart; words can: echo repeats what the bot
just said.
"""

import re
import time
from collections import deque
from difflib import SequenceMatcher

ECHO_TAIL_SECS = 2.5  # room reverb and STT delay: echo transcripts keep arriving after the bot stops
LATE_ECHO_SECS = 8.0  # a final transcript can trail by this much; only a run of the bot's own words counts this late
BOT_MEMORY_SECS = 30.0
MIRROR_RECENT_SECS = 12.0  # the mirror trails the audio by a few seconds at most
INTERRUPT_WORDS = {"stop", "wait", "hold", "no", "enough", "quiet", "pause", "hey",
                   "רגע", "עצור", "די", "לא", "חכה", "שקט"}

ANSWER_WORDS = {"yes", "yeah", "yep", "no", "nope", "approve", "approved", "allow", "deny", "denied", "ok", "okay", "sure",
                "ahead", "כן", "לא", "תאשר", "אשר"}  # the words a yes or a no is made of


NUMBERS = {w: str(i) for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen twenty".split())}


_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
_ONES = list(NUMBERS)[:20]


def _spoken(n: int) -> list[str]:
    if n < 20:
        return [_ONES[n]]
    if n < 100:
        return [_TENS[n // 10]] + ([_ONES[n % 10]] if n % 10 else [])
    return [_ONES[n // 100], "hundred"] + (_spoken(n % 100) if n % 100 else [])


def words(text: str) -> list[str]:
    """Lowercased words, numbers below 1000 spelled out: the model writes "thirty" where the STT writes "30"."""
    out = []
    for w in re.findall(r"[\w']+", text.lower()):
        out.extend(_spoken(int(w)) if w.isascii() and w.isdigit() and int(w) < 1000 else [w])
    return out


def _like(heard: str, said: str) -> bool:
    """The STT misheard or has not finished the bot's word: "crew" for "cruel", "o" for "ocean"."""
    if heard == said:
        return True
    if heard in INTERRUPT_WORDS:
        return False  # "stop" must never pass for "storm"
    return said.startswith(heard) or (len(heard) >= 3 and SequenceMatcher(None, heard, said).ratio() >= 0.6)


class _Source:
    """One account of what the bot said. Chunks can split words, so they are joined before splitting."""

    def __init__(self):
        self.chunks: deque[tuple[float, str]] = deque()
        self.provisional = ""

    def add(self, text: str) -> None:
        now = time.time()
        self.chunks.append((now, text))
        while self.chunks and now - self.chunks[0][0] > BOT_MEMORY_SECS:
            self.chunks.popleft()

    def words(self, since: float = 0.0) -> list[str]:
        return words("".join(t for at, t in self.chunks if at >= since) + self.provisional)


class EchoGuard:
    def __init__(self):
        self._model = _Source()  # the voice model's own text: early, but written and sometimes missing
        self._mirror = _Source()  # an STT on the bot's audio: spelled the way the user's ears spell it
        self.speaking = False
        self.stopped_at = 0.0
        self._turns = (0.0, 0.0)
        self._invited: deque[tuple[float, list[str]]] = deque(maxlen=8)

    def bot_started(self) -> None:
        if not self.speaking:
            self._turns = (self._turns[1], time.time())  # (the turn before, this turn)
        self.speaking = True

    def bot_stopped(self) -> None:
        self.speaking, self.stopped_at = False, time.time()

    def bot_said(self, text: str) -> None:
        self._model.add(text)
        # 'Say "switch to billing"': when the user then says exactly that, it is them, not the echo.
        for phrase in re.findall(r"[\"“]([^\"”]{3,80})[\"”]", text):
            self._invited.append((time.time(), words(phrase)))

    def invited(self, text: str) -> bool:
        """The bot asked for these very words and has stopped talking."""
        heard = words(text)
        now = time.time()
        return not self.speaking and any(now - at < BOT_MEMORY_SECS and heard == said for at, said in self._invited)

    def mirror_heard(self, final: str, provisional: str) -> None:
        if final:
            self._mirror.add(final)
        self._mirror.provisional = provisional

    @property
    def live(self) -> bool:
        """The speakers may still be playing the bot into the mic."""
        return self.speaking or time.time() - self.stopped_at < ECHO_TAIL_SECS

    def _sources(self) -> tuple[list[str], list[str]]:
        """What can still be coming back through the speakers: the text of this turn and the one before (it is written
        before it plays), and the mirror's last few seconds. Not every word of the last half minute: against several long
        answers, near-spellings match almost anything the user says."""
        since = self._turns[0] - 1.0 if self._turns[0] else 0.0
        return self._model.words(since), self._mirror.words(time.time() - MIRROR_RECENT_SECS)

    def _bot_words(self) -> set[str]:
        model, mirror = self._sources()
        return set(model) | set(mirror)

    def _echo_mask(self, heard: list[str], fuzzy: bool = True) -> list[bool]:
        """Which heard words are the bot's. Fuzzy only while its voice may still be in the air: against a long answer,
        near-spellings match almost any sentence ("run" for "round"), and a late transcript is spelled like the mirror's."""
        like = _like if fuzzy else (lambda heard_word, said_word: heard_word == said_word)
        bot_words, bot_pairs = set(), set()
        for said in self._sources():
            bot_words.update(said)
            bot_pairs.update(zip(said, said[1:]))
        mask = [False] * len(heard)
        for i, pair in enumerate(zip(heard, heard[1:])):
            # exact, or both words a near-spelling of a pair the bot said ("his weather" for "his weathered")
            # a near-spelling counts only beside a word the bot said exactly: two near-spellings in a row ("waiting for" for
            # "waits only") are the user, who happens to use similar words
            if pair in bot_pairs or (fuzzy and any((pair[0] == a and _like(pair[1], b)) or (_like(pair[0], a) and pair[1] == b)
                                                   for a, b in bot_pairs)):
                mask[i] = mask[i + 1] = True
        # A bot word next to an echoed run is echo too (the STT misheard its neighbour). A transcript
        # of one or two words has no runs: while the bot talks its bot words count directly; after
        # it stops they do not, so a quick "yes" to "yes or no?" stays the user's.
        short = len(heard) <= 2 and self.speaking
        for i, w in enumerate(heard):
            near = (i > 0 and mask[i - 1]) or (i + 1 < len(heard) and mask[i + 1])
            if not mask[i] and (short or near) and (w in bot_words or (short and any(like(w, b) for b in bot_words))):
                mask[i] = True
        return mask

    def user_part(self, text: str) -> str:
        """The transcript minus what the bot just said; '' when nothing of the user's is left."""
        heard = words(text)
        late = time.time() - self.stopped_at > LATE_ECHO_SECS
        if not late and self._model.chunks and heard == words(self._model.chunks[-1][1]):
            return ""  # all of its last reply, and nothing else: "Four." coming back off the speakers
        if not self.live and (len(heard) < 3 or late):
            return text
        was_live = self.live
        mask = self._echo_mask(heard, fuzzy=was_live)
        rest = [w for w, m in zip(heard, mask) if not m]
        if not any(mask):
            return text
        if (not was_live and rest) or (not self.speaking and len(rest) >= 2):
            return text  # the bot has stopped: words of the user's mean it is all theirs, common word pairs included
        if not rest or (len(rest) == 1 and rest[0] not in INTERRUPT_WORDS):
            return ""  # one stray word inside an echo is a mishearing, not the user
        return " ".join(rest)

    def repeats_bot(self, text: str) -> bool:
        """These words are the bot's own recent speech coming back: every answer word in them (yes, no, approve…) sits
        in a run of two words the bot said in the last half minute, and so do at least half of them. Only for consent:
        a final can arrive after the echo tail, when user_part takes it whole ("…approve it there, or say no" once
        denied a request). A real answer brings its own words ("no, don't run the tests"), so it is not one."""
        heard = words(text)
        if len(heard) < 3:
            return False
        pairs = set()
        for said in (self._model.words(), self._mirror.words()):
            pairs.update(zip(said, said[1:]))
        mask = [False] * len(heard)
        for i, pair in enumerate(zip(heard, heard[1:])):
            if pair in pairs:
                mask[i] = mask[i + 1] = True
        answers = [m for w, m in zip(heard, mask) if w in ANSWER_WORDS]
        return bool(answers) and all(answers) and sum(mask) * 2 >= len(heard)

    def is_barge_in(self, interim: str) -> bool:
        """Live words over the bot's voice that are the user's: two in a row, or one stop word.

        In a row, because the user talks in a run while misheard echo words land scattered.
        """
        heard = words(interim)
        if not self.live:
            return len(heard) >= 2 or any(w in INTERRUPT_WORDS for w in heard)
        # The last word of a live transcript is often half heard ("c" for "cut"): if it starts a word the bot said, it
        # proves nothing yet, and must not complete a run.
        if heard and heard[-1] not in INTERRUPT_WORDS and any(b.startswith(heard[-1]) for b in self._bot_words()):
            heard = heard[:-1]
        mask = self._echo_mask(heard)
        run = best = 0
        for w, m in zip(heard, mask):
            run = 0 if m else run + 1
            best = max(best, run)
            if not m and w in INTERRUPT_WORDS:
                return True
        return best >= 2


LOUD_OVER_ECHO = 4.0  # speech this much louder than the echo floor is the user's own voice
ONSET_SECS = 1.0  # the start of each bot turn, when its echo is still arriving
MIN_SPEECH_RMS = 300  # int16 RMS; below this a "loud" frame is room noise, not a voice


class LevelGate:
    """Fast barge-in when the user's voice is clearly louder than the bot's echo.

    With headphones the echo floor is near silence, so any speech cuts in at once, as a plain VAD
    would; on loud speakers the floor is high and barge-in waits for words instead.
    """

    def __init__(self, frames_per_sec: int = 50):
        self._echo: deque[float] = deque(maxlen=frames_per_sec * 3)
        self._recent: deque[float] = deque(maxlen=max(1, frames_per_sec * 3 // 10))
        self._min_floor_frames = int(frames_per_sec * 2.5)  # the first words are no floor: words still cut in sooner
        # The speakers start a beat after the bot does, and its first echo is louder than any floor carried over from an
        # earlier turn: loudness alone does not cut a turn this young. Words still do.
        self._onset_frames = int(frames_per_sec * ONSET_SECS)
        self._turn_frames = 0
        self._was_speaking = False

    def frame(self, rms: float, bot_speaking: bool) -> None:
        self._turn_frames = self._turn_frames + 1 if bot_speaking and self._was_speaking else (1 if bot_speaking else 0)
        self._was_speaking = bot_speaking
        self._recent.append(rms)
        if bot_speaking:
            self._echo.append(rms)

    def loud(self) -> bool:
        if 0 < self._turn_frames < self._onset_frames:
            return False
        floor_frames = list(self._echo)[: -len(self._recent)]  # the onset itself is not the floor
        if len(floor_frames) < self._min_floor_frames:
            return False
        floor = sorted(floor_frames)[int(len(floor_frames) * 0.95)]  # the echo's peaks: expressive speech has quiet gaps
        now = sum(self._recent) / len(self._recent)
        return now >= MIN_SPEECH_RMS and now > floor * LOUD_OVER_ECHO

"""Thinking: the wait between the owner's last word and Pointe's reply, shown and, when it is long, heard.

Before this the screen said "Listening" through the whole wait, so heard looked the same as lost. Now the daemon's status
carries a `phase` and every screen shows it on the call's state line (the page, the iPhone, the Mac window, the Mac
bubble and menu bar), with the same words:

- "Thinking…": from the moment the turn is taken until the reply is heard, or shown when Pointe is muted. It follows
  the work, not a timer: it holds while the daemon and the model work on the owner's words or the reply's words are on
  their way to the mouth, comes back after a "One sec.", and ends by itself for a turn that gets no reply. A turn is
  open from the moment it is taken until none of that holds; news said later is not "thinking".
- "<session> is working…": a session has the owner's request and has not answered yet (progress.py keeps that watch).

Speaking… and Writing… (mute.py) come first when they hold: the phase is what is true while nothing is being said.

The waiting sound: one soft, short tone when the wait is long, so the owner knows the words were heard without looking.
Its clock is the owner's, not the pipeline's: it counts from their last word, since that is the silence they hear. It
never plays for a fast reply, never once the reply's words have gone to the mouth (so it cannot land on the reply's
first sound), and once in a turn at most. It is a plain audio frame in the call's own output, in order with the voice:
pipecat starts the bot's turn only on synthesised speech, so the echo guard, the floor and the yes window never take it
for Pointe speaking. A setting turns it off ("thinking.cue"). Never while muted (drive mode holds mute, so on the road
it plays), in whisper mode, in a meeting, or over the owner's voice.

The ladder of a slow turn: the state at once; this sound past CUE_AFTER_LAST_WORD_SECS; the spoken "One sec." the brain
already says past brain.FILLER_AFTER_SECS. A spoken acknowledgement any earlier was considered and left out: words in
the second after a question delay the answer they announce, and a filler helps only on a wait of seconds.
"""

import numpy as np

# The words, on the page (ui_thinking.html) and in both apps (ThinkingCopy), word for word.
COPY = {
    "thinking": "Thinking…",
    "working": "{session} is working…",
    "cue": "Waiting sound",
    "cue_hint": "A soft sound when Pointe needs more than a moment to answer.",
}

START_GRACE_SECS = 0.6  # a turn the daemon is done with reads as Thinking this long before the model's work on it starts
HANDED_SECS = 6.0  # words handed to the mouth that made no sound by now are not coming: the mouth's own line says why
MAX_SECS = 45.0  # a step that hangs is not "thinking" forever

CUE_AFTER_LAST_WORD_SECS = 1.8  # the silence the owner hears, from their last word
CUE_AFTER_TAKEN_SECS = 1.2  # typed words and a press have no word clock: from the turn
CUE_MIN_AFTER_TAKEN_SECS = 0.4  # words that waited long before they became the turn: not on top of it
CUE_SECS = 0.12
CUE_POLL_SECS = 0.05
_CUE_HZ, _CUE_LEVEL = 523.25, 0.1  # one C, a tenth of full scale (the chimes are a quarter)


def cue_pcm(rate: int) -> bytes:
    """The waiting sound: one soft note with its octave under a raised-cosine window, so it starts and ends at zero."""
    t = np.arange(int(rate * CUE_SECS)) / rate
    window = 0.5 - 0.5 * np.cos(2 * np.pi * t / CUE_SECS)
    wave = np.sin(2 * np.pi * _CUE_HZ * t) + 0.3 * np.sin(2 * np.pi * 2 * _CUE_HZ * t)
    return (wave / 1.3 * window * _CUE_LEVEL * 32767).astype(np.int16).tobytes()


class Wait:
    """One call's wait for a reply. Times are stamped by the daemon at the events it already has: the turn taken
    (on_user_utterance), a line on its way to the mouth (MuteOut), the first sound (BotSpeechTap) or the line shown
    instead (muted)."""

    def __init__(self) -> None:
        self.clear()

    def clear(self) -> None:
        self.open = False  # a turn of the owner's is being answered
        self.taken_at = 0.0
        self.last_word_at: float | None = None
        self.handled_at = 0.0
        self.handed_at = 0.0
        self.sound_at = 0.0
        self.cued = False
        self.turn = getattr(self, "turn", 0)  # which turn: a sound waiting for an older one is dropped

    def taken(self, now: float, last_word: float | None = None) -> None:
        """The owner's words became the turn. `last_word`: when their last word ended; None for typed words or a press."""
        self.open, self.taken_at, self.last_word_at = True, now, last_word
        self.handled_at = self.handed_at = self.sound_at = 0.0
        self.cued = False
        self.turn += 1

    def handled(self, now: float) -> None:
        """The daemon's own part of the turn is done (a yes applied, a stop sent): what follows is the model's."""
        if self.open and not self.handled_at:
            self.handled_at = now

    def handed(self, now: float) -> None:
        """A line is on its way to the mouth."""
        if self.open:
            self.handed_at = now

    def sound(self, now: float) -> None:
        """The line is heard, or shown instead of spoken."""
        if self.open:
            self.sound_at = now

    def close(self) -> None:
        """Nothing more is coming for this turn: a line said from now on is news, not its reply."""
        self.open = False

    def thinking(self, now: float, busy: bool) -> bool:
        """`busy`: work on the owner's words is running (a model step, a send)."""
        if not self.open or now - self.taken_at > MAX_SECS:
            return False
        on_its_way = self.handed_at > self.sound_at and now - self.handed_at < HANDED_SECS
        starting = not self.handed_at and not self.sound_at and (not self.handled_at or now - self.handled_at < START_GRACE_SECS)
        return busy or on_its_way or starting

    def cue_at(self) -> float | None:
        if not self.taken_at:
            return None
        if self.last_word_at is None:
            return self.taken_at + CUE_AFTER_TAKEN_SECS
        return max(self.last_word_at + CUE_AFTER_LAST_WORD_SECS, self.taken_at + CUE_MIN_AFTER_TAKEN_SECS)

    def cue_due(self, now: float, busy: bool) -> bool:
        """The sound may play now: the wait is long, work is still running, and nothing of this turn's has been said
        or handed to the mouth."""
        at = self.cue_at()
        return bool(self.open and at is not None and not self.cued and busy and not self.handed_at and not self.sound_at and now >= at
                    and now - self.taken_at <= MAX_SECS)

    def cue_played(self, now: float) -> None:
        self.cued = True


def status(wait: Wait, now: float, busy: bool, said: bool, working: tuple[str, float] | None) -> dict | None:
    """Status `phase`: what is true while nothing is being said. `said`: Pointe speaks, or just wrote a line instead;
    `working`: (name, since) of the session that has the owner's request."""
    if said:
        return None
    if wait.thinking(now, busy):
        return {"name": "thinking", "session": None, "since": round(wait.taken_at, 3)}
    if working is not None:
        return {"name": "working", "session": working[0], "since": round(working[1], 3)}
    return None

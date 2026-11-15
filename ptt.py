"""Push to talk: the daemon's input gate. With the microphone set to "ptt", audio passes only while a press holds the
gate open (plus a short tail), so nothing reaches the ears or any vendor otherwise. One exception: while a meeting is
on, the room's audio goes to the meeting stream without a press (starting a meeting took consent and shows a recording
indicator); the conversation still hears only a press. The clients stop sending too, but
this gate is the rule: the daemon is what talks to vendors. Pure state, driven by the call's PttGate with the clock.

A press is one message, as a voice message is (docs/design/push-to-talk-modes.md): what the ears hear while it is on is
kept here, shown as a draft, and sent as one turn: on release, after the tail, the ears are told the audio is over, and
the press goes as soon as no draft is left (every word final), or at FINAL_WAIT_SECS if one never becomes final."""

TAIL_SECS = 0.4  # kept after a release, so the last word is not cut; the clients send the same tail
LINK_SLACK_SECS = 0.2  # the tail's audio arrives after the release message, by up to the link's jitter
MAX_OPEN_SECS = 90.0  # a thumb on the phone in a pocket: the press ends itself
QUIET_LINK_SECS = 2.0  # open but no audio arriving: the release was lost with the link
FINAL_WAIT_SECS = 2.0  # after the finalize, the longest a draft may take to become final: only a safety net. With no
# draft left the press goes at once; Soniox's <fin> also sends it


class Ptt:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """A new call starts closed."""
        self.open = False
        self.opened_at = 0.0
        self.closed_at = 0.0
        self.closed_why = ""
        self.until = 0.0  # after a release, audio still passes until then (the tail)
        self.finalize_due = False
        self.last_audio_at = 0.0
        self.passed_bytes = 0
        self.dropped_bytes = 0
        self.room_bytes = 0  # passed for the meeting stream only, with the gate closed
        self._mode = None  # the mode last seen, to notice a switch to push to talk mid-sentence
        self.collecting = False  # a press's words are being kept: from the press until they are sent
        self.said: list[str] = []  # its final transcripts, in order
        self.live = ""  # the words being heard now, not final yet
        self.speakers: list = []  # the voice lock's verdict on each final; the weakest answers for the message
        self.own_words = False  # a final repeated the bot's own suggestion: the message answers no permission
        self.finalized = False  # the tail is over and the ears were asked for the last words
        self.final_due = 0.0  # the send goes without them then

    def press(self, now: float, collect: bool = True) -> bool:
        """True when this opened the gate; a second input pressing while it is open is not a new press. collect=False:
        no ears of Pointe's own in the call (a realtime model hears the audio and ends its own turns)."""
        if self.open:
            return False
        self.open, self.opened_at, self.last_audio_at = True, now, now
        self.closed_why, self.until, self.finalize_due = "", 0.0, False
        if collect and not self.collecting:  # pressed again before the last one was sent: the same message goes on
            self.said, self.live, self.speakers, self.own_words = [], "", [], False
        self.collecting = self.collecting or collect
        self.finalized, self.final_due = False, 0.0
        return True

    def hear(self, text: str, speaker=None, own_words: bool = False) -> None:
        """A final transcript inside the press: kept for the message, never a turn of its own."""
        self.said.append(text)
        self.speakers.append(speaker)
        self.own_words = self.own_words or own_words
        self.live = ""

    def draft(self) -> str:
        return " ".join(p for p in self.said + [self.live] if p)

    def sendable(self) -> bool:
        """Closed, and the ears were asked for the last words: the message may go."""
        return self.collecting and not self.open and self.finalized

    def take(self) -> str:
        """The message, once: everything said in the press, as one turn ("" when nothing was heard)."""
        text = " ".join(self.said).strip()
        self.collecting, self.said, self.live, self.finalized, self.final_due = False, [], "", False, 0.0
        return text

    def release(self, now: float, why: str = "released") -> bool:
        if not self.open:
            return False
        self.open, self.closed_at, self.closed_why = False, now, why
        self.until, self.finalize_due = now + TAIL_SECS + LINK_SLACK_SECS, True
        return True

    def _follow(self, mode: str, now: float) -> bool:
        """True when a setting change ended a press: a press belongs to the setting it was made in, and the clients
        forget theirs on a change, so it would otherwise stay open with no thumb on it."""
        released = self._mode is not None and mode != self._mode and self.release(now, "the microphone setting changed")
        if self._mode == "always" and mode == "ptt" and not self.open:  # the sentence under way is finished, not cut
            self.closed_at, self.closed_why = now, "switched to push to talk"
            self.until, self.finalize_due = now + TAIL_SECS + LINK_SLACK_SECS, True
        self._mode = mode
        return released

    def passes(self, mode: str, now: float) -> bool:
        self._follow(mode, now)
        return mode != "ptt" or self.open or now < self.until

    def audio(self, nbytes: int, mode: str, now: float, room: bool = False) -> bool:
        """One chunk of microphone audio arrived: True if it may go on. With room=True (a meeting is on) it always may,
        but only the meeting stream may take it unless passes() also holds."""
        self.last_audio_at = now
        ok = self.passes(mode, now)
        if ok:
            self.passed_bytes += nbytes
        elif room:
            self.room_bytes += nbytes
            return True
        else:
            self.dropped_bytes += nbytes
        return ok

    def tick(self, mode: str, now: float) -> list[str]:
        """Run often. "closed" when the gate closed by itself (closed_why says why); "finalize" once the tail is over;
        then "send" as soon as no draft is left, or "timeout" when one is still there FINAL_WAIT_SECS after the finalize."""
        events = ["closed"] if self._follow(mode, now) else []
        if mode == "ptt" and self.open:
            if now - self.opened_at > MAX_OPEN_SECS:
                self.release(now, "held too long")
                events.append("closed")
            elif now - self.last_audio_at > QUIET_LINK_SECS:
                self.release(now, "no audio")
                events.append("closed")
        if self.finalize_due and now >= self.until:
            self.finalize_due = False
            events.append("finalize")
            if self.collecting and not self.open:
                self.finalized, self.final_due = True, now + FINAL_WAIT_SECS
        if self.final_due and self.sendable() and (not self.live or now >= self.final_due):
            self.final_due = 0.0
            events.append("send" if not self.live else "timeout")  # no draft left; or the cap: what was heard goes
        return events

    def speech_began(self, now: float, mode: str) -> float:
        """When the user's words began, for the consent rules: in push to talk, at the press."""
        if mode == "ptt" and self.opened_at and (self.open or now < self.until):
            return min(self.opened_at, now)
        return now

    def status(self, mode: str, room: bool = False) -> dict:
        """room_heard: a meeting is on, so the room is heard without a press (the conversation is not)."""
        return {"mode": mode, "open": self.open, "opened_at": self.opened_at or None,
                "closed_at": self.closed_at or None, "closed_why": self.closed_why,
                "sent_bytes": self.passed_bytes, "room_heard": mode == "ptt" and room, "room_bytes": self.room_bytes,
                "draft": self.collecting}  # "hearing" is then the press's words so far, not sent yet

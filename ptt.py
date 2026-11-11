"""Push to talk: the daemon's input gate. With the microphone set to "ptt", audio passes only while a press holds the
gate open (plus a short tail), so nothing reaches the ears or any vendor otherwise. The clients stop sending too, but
this gate is the rule: the daemon is what talks to vendors. Pure state, driven by the call's PttGate with the clock."""

TAIL_SECS = 0.4  # kept after a release, so the last word is not cut; the clients send the same tail
LINK_SLACK_SECS = 0.2  # the tail's audio arrives after the release message, by up to the link's jitter
MAX_OPEN_SECS = 90.0  # a thumb on the phone in a pocket: the press ends itself
QUIET_LINK_SECS = 2.0  # open but no audio arriving: the release was lost with the link


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
        self._mode = None  # the mode last seen, to notice a switch to push to talk mid-sentence

    def press(self, now: float) -> bool:
        """True when this opened the gate; a second input pressing while it is open is not a new press."""
        if self.open:
            return False
        self.open, self.opened_at, self.last_audio_at = True, now, now
        self.closed_why, self.until, self.finalize_due = "", 0.0, False
        return True

    def release(self, now: float, why: str = "released") -> bool:
        if not self.open:
            return False
        self.open, self.closed_at, self.closed_why = False, now, why
        self.until, self.finalize_due = now + TAIL_SECS + LINK_SLACK_SECS, True
        return True

    def _follow(self, mode: str, now: float) -> None:
        if self._mode == "always" and mode == "ptt" and not self.open:  # the sentence under way is finished, not cut
            self.closed_at, self.closed_why = now, "switched to push to talk"
            self.until, self.finalize_due = now + TAIL_SECS + LINK_SLACK_SECS, True
        self._mode = mode

    def passes(self, mode: str, now: float) -> bool:
        self._follow(mode, now)
        return mode != "ptt" or self.open or now < self.until

    def audio(self, nbytes: int, mode: str, now: float) -> bool:
        """One chunk of microphone audio arrived: True if it may go on to the ears."""
        self.last_audio_at = now
        ok = self.passes(mode, now)
        if ok:
            self.passed_bytes += nbytes
        else:
            self.dropped_bytes += nbytes
        return ok

    def tick(self, mode: str, now: float) -> list[str]:
        """Run often. "closed" when the gate closed by itself (closed_why says why); "finalize" once the tail is over."""
        self._follow(mode, now)
        events = []
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
        return events

    def speech_began(self, now: float, mode: str) -> float:
        """When the user's words began, for the consent rules: in push to talk, at the press."""
        if mode == "ptt" and self.opened_at and (self.open or now < self.until):
            return min(self.opened_at, now)
        return now

    def status(self, mode: str) -> dict:
        return {"mode": mode, "open": self.open, "opened_at": self.opened_at or None,
                "closed_at": self.closed_at or None, "closed_why": self.closed_why,
                "sent_bytes": self.passed_bytes}

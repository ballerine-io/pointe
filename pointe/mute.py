"""Mute: the owner muted Pointe's voice. Every word it would say arrives as text in the conversation; the owner reads
it, and still talks or types to it. One toggle beside the call's status line on the page and in both apps; where the
status would say "Speaking…" it says "Writing…".

Each device keeps its own choice (the page in the browser, each app on its device) and tells the daemon when it calls
(`?reading=1` on the call's address) and when it changes (POST /voice/reading). Saying "stop talking, I'll read" or "talk
again" changes it for the call, and the daemon tells the device on the call ({"type": "reading", "on": ...}) so it keeps
it. The daemon's own state is the call's: `state.mute`. The wire keeps the name it had as "reading mode" (the address,
the route, the message, status `reading`), so an app built before the mute button still works on a call.

What it changes, in daemon.MuteOut and nowhere else: a line for the mouth never reaches it, so nothing is synthesised,
and the bot's turn starts and stops at once, so every rule that times the bot's speech (the yes window, the floor, the
echo guard) sees a turn of no length. Muting while Pointe speaks flushes the mouth and the speakers (MuteOut.hush) and
leaves the brain alone: the rest of that reply is written. What it does not change: approvals and read-backs. A
permission is answered by a tap or a spoken yes as always, and a read-back by its card's button or a spoken yes, under
the same rules (daemon._readback_answer): a typed yes confirms nothing, because a tap in the apps asks for Face ID or
Touch ID and a typed word must not get around that.

Drive mode holds it, as it holds whisper mode: on the road the owner cannot read, so Pointe talks until drive mode ends.
"""

import re

_LEAD = r"^\W*(?:(?:ok(?:ay)?|so|hey|pointe|please)\W+)*"
_ON = re.compile(
    _LEAD + r"(?:(?:stop|quit) talking|don'?t talk)(?:,| and|\.)? (?:i'?ll|i will|let me) read(?: it)?\W*$|"
    + _LEAD + r"(?:i'?ll|i will) read(?: it)? instead\W*$|" + _LEAD + r"i'?ll read\W*$|"
    + _LEAD + r"(?:(?:turn on |start )?reading mode(?: on)?|text only|just (?:write|text)(?: to me)?|write(?:,| and) don'?t talk)\W*$|"
    r"^\W*(?:מצב קריאה|תפסיק לדבר,? אני אקרא|אני אקרא|רק טקסט)\W*$", re.I)
_OFF = re.compile(
    _LEAD + r"(?:(?:you can )?talk (?:to me )?again|(?:you can )?speak (?:to me )?again|start talking(?: again)?|"
    r"reading mode off|(?:stop|end|exit|leave) reading(?: mode)?|back to normal(?: voice)?(?: mode)?)\W*$|"
    r"^\W*(?:תדבר שוב|דבר שוב|תדבר איתי|חזרה לרגיל|צא ממצב קריאה|בטל(?: את)? מצב קריאה)\W*$", re.I)


def intent(text: str) -> bool | None:
    """A whole short utterance that mutes Pointe (True) or unmutes it (False); None for anything else. The phrases are
    reading mode's, kept as the button's aliases."""
    text = text.strip()
    if _ON.match(text):
        return True
    if _OFF.match(text):
        return False
    return None


# The words, on the page (ui_mute.html) and in both apps (MuteCopy), word for word.
COPY = {
    "speaking": "Speaking…",
    "writing": "Writing…",
    "mute": "Mute Pointe",
    "unmute": "Unmute Pointe",
    "held": "Drive mode holds mute: Pointe talks while you drive.",
    "failed": "Mute did not change: the voice is not reachable.",
}

ON_LINE = "Muted: I'll write instead of talking. Say \"talk again\" to hear me."
OFF_LINE = "Talking again."
HELD_LINE = "Mute starts when drive mode ends. I keep talking while you drive."

RULE = ("[your voice is muted: the user reads your replies on the screen and hears nothing. Write them as you would say "
        "them, at the same length. Approvals and sends follow the usual rules. You cannot mute or unmute yourself: "
        "the user says \"stop talking, I'll read\" or \"talk again\", or taps; never say it changed.]")

WRITING_SECS = 2.0  # how long the status says "Writing…" after a line was shown instead of spoken


def status(on: bool, held: str | None, read_through: int, writing: bool = False) -> dict:
    """What every screen shows. `on`: the call's choice; `held`: a mode that suspends it ("drive"); `writing`: a line
    was just shown instead of spoken, so the status line says "Writing…"; `read_through`: the newest of Pointe's lines
    an app from before the mute button marked read (talk ids up to it are read)."""
    return {"on": on, "held": held if on else None, "read_through": read_through, "writing": writing}

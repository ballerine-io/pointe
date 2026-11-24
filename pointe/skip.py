"""Skip: the owner skips what Pointe is saying now, and Pointe goes on to the next thing that waits to be said.

One button beside the call's status line while Pointe speaks, on the page and in both apps, next to the mute button; a
key that works from any app on the Mac (the Mac app's Settings, "Skip shortcut"); and the words "skip" or "next". All
three end in daemon.skip_speech (POST /voice/skip).

What it does: the audio stops, here and on the calling device; the rest of that reply is not said, and a report cut this
way is not offered again (a barge-in's "coming back to it" is for a line the owner talked over, not one they skipped);
then the next line that waits goes after a breath, not after the quiet gap news waits for. Nothing is lost: the skipped
line's words are already in the conversation as text.

What it never does: answer anything. A skip is not a yes and not a no; a permission's read-out that was skipped is read
out again before a yes can count, by the same rule as one the owner talked over (daemon._read_out_cut_off).

A briefing keeps its own skip (one part, briefing.control_intent): while one plays, the button, the key and the words
skip its part.
"""

import re

_PHRASES = {"skip", "next", "next one", "skip it", "skip that", "skip this", "skip this one", "skip this message",
            "next message", "skip ahead", "דלג", "תדלג", "הבא", "הודעה הבאה"}


def intent(text: str) -> bool:
    """A whole short utterance that skips what is being said. "Skip the tests" or "next, run the linter" is a request."""
    said = re.sub(r"[^\w\s'֐-׿]", "", text.lower()).strip()
    said = re.sub(r"^(?:ok(?:ay)?|pointe|please|so)\s+|\s+please$", "", said).strip()
    return said in _PHRASES


# The words, on the page (ui_skip.html) and in both apps (SkipCopy), word for word.
COPY = {
    "skip": "Skip this message",
    "failed": "Skip did not reach the voice.",
}

JUST_STOPPED_SECS = 4.0  # "skip" said over a line cut that line a moment ago: it still counts as the line being said

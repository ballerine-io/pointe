"""Quick settings: the few settings changed during a day, one tap away on every surface and by voice
(docs/features/quick-settings.md).

- Reply length ("replies.length"): Brief, Concise, Detailed or Thorough. Concise is the length Pointe always had; the
  limits of each level are conversation.LENGTHS. "Tell me more" still lengthens one answer and changes nothing here.
- Speaking speed ("voice.speed"): 0.8x to 1.2x in steps of 0.1, kept per device (the Mac app, the iPhone app, the
  page): AirPods on the phone and speakers on the Mac want different speeds. A voice with no speed number (Gemini) and
  a realtime front hide the control (`speed_shown`).
- Clean up my words ("polish"): a cleaned line under each thing the user says, on the screen only.
- Whisper: whisper.py's own setting, shown in the same row.

The phrases are matched in code, on a whole short utterance, before the per-answer detail check
(conversation.wants_detail): "longer answers" changes the setting, "tell me more" one answer.
"""

import re

LEVELS = ("brief", "concise", "detailed", "thorough")
DEFAULT_LEVEL = "concise"
SPEEDS = (0.8, 0.9, 1.0, 1.1, 1.2)  # ElevenLabs stops at 1.2; every voice that takes a number takes these
SURFACES = ("mac", "iphone", "page")

# The words, on the page (ui_quick.html QUICK_COPY) and in both apps (QuickCopy), word for word.
COPY = {
    "title": "Quick settings",
    "length": "Reply length",
    "speed": "Speaking speed",
    "polish": "Clean up my words",
    "polishChip": "Clean words",
    "polishHint": "Under each thing you say, a clean version of what the voice understood",
    "whisper": "Whisper",
    "microphone": "Microphone",
    "brief": "Brief",
    "concise": "Concise",
    "detailed": "Detailed",
    "thorough": "Thorough",
    "briefHint": "One sentence: the answer only.",
    "conciseHint": "One or two short sentences.",
    "detailedHint": "The answer, then why, and the caveat that matters.",
    "thoroughHint": "Explains: what, why, how, and what to watch.",
    "slowest": "Slowest",
    "slower": "Slower",
    "normal": "Normal",
    "faster": "Faster",
    "fastest": "Fastest",
    "slowestHint": "0.8× normal speed.",
    "slowerHint": "0.9× normal speed.",
    "normalHint": "Normal speed.",
    "fasterHint": "1.1× normal speed.",
    "fastestHint": "1.2×, the voice's top speed.",
    "lengthSay": "Or say it: “be more concise”, “more detail from now on”. “Tell me more” still makes one answer longer.",
    "speedSay": "Or say it: “speak faster”, “slow down”. The next sentence takes the new speed.",
    "sheetSay": "Or say it: “be more concise”, “speak faster”, “clean up my words”, “whisper mode”.",
    "allSettings": "All settings",
}

SPEED_NAMES = dict(zip(SPEEDS, ("slowest", "slower", "normal", "faster", "fastest")))


def speed_label(speed: float) -> str:
    """"1×", "1.1×": how a chip shows a speed."""
    return f"{speed:g}×"


def valid_speeds(value) -> bool:
    """The "voice.speed" setting: a speed for each surface that set one."""
    return isinstance(value, dict) and all(k in SURFACES and not isinstance(v, bool) and isinstance(v, (int, float))
                                           and round(float(v), 1) in SPEEDS and float(v) == round(float(v), 1)
                                           for k, v in value.items())


def speed_for(speeds: dict, surface: str) -> float:
    return float(speeds.get(surface, 1.0))


def speed_shown(front: str, mouth: str) -> bool:
    """The speed control is shown: a cascaded call whose voice takes a speed. Gemini's TTS has only a style prompt, so
    its speed would be approximate; a realtime front speaks with its own voice."""
    return front == "brain" and (mouth or "").split(":")[0] in ("elevenlabs", "soniox", "openai", "local")


UP, DOWN = "up", "down"


def step(values: tuple, current, wanted):
    """`wanted` is a value of `values`, or UP / DOWN for one step from `current`, held at the ends."""
    if wanted in (UP, DOWN):
        i = values.index(current) if current in values else len(values) // 2
        return values[max(0, min(len(values) - 1, i + (1 if wanted == UP else -1)))]
    return wanted


# ---------- the phrases ----------

_LEAD = r"^\W*(?:(?:ok(?:ay)?|so|hey|pointe|please|and|alright)\W+)*"
_TAIL = r"(?:\W+(?:from now on|please|for now|going forward|from here on))*\W*$"
_HE_LEAD = r"^\W*(?:(?:טוב|אוקיי|פוינט)\W+)*"
_HE_TAIL = r"(?:\W+(?:מעכשיו|מעתה|בבקשה))*\W*$"

_LENGTH = (
    (DOWN, re.compile(_LEAD + r"(?:be (?:more )?(?:concise|brief)|be briefer|shorter (?:answers|replies)|"
                    r"keep (?:it|them|your answers|your replies) (?:shorter|short|brief)(?: from now on)?|"
                    r"less detail|(?:give me )?shorter answers)" + _TAIL, re.I)),
    (UP, re.compile(_LEAD + r"(?:be more (?:detailed|thorough)|more detail(?:s)? from now on|longer (?:answers|replies)|"
                   r"(?:give me )?more detailed (?:answers|replies))" + _TAIL, re.I)),
    (DOWN, re.compile(_HE_LEAD + r"(?:תהיה (?:יותר )?(?:תמציתי|קצר)|תהיי (?:יותר )?(?:תמציתית|קצרה)|תשובות קצרות יותר|"
                    r"פחות פירוט|תקצר|תקצרי)" + _HE_TAIL)),
    (UP, re.compile(_HE_LEAD + r"(?:תהיה (?:יותר )?(?:מפורט|יסודי)|תהיי (?:יותר )?(?:מפורטת|יסודית)|תשובות ארוכות יותר|"
                   r"יותר פירוט)" + _HE_TAIL)),
)
_LEVEL_WORDS = {"brief": "brief", "short": "brief", "concise": "concise", "detailed": "detailed", "thorough": "thorough",
                "קצרות": "brief", "תמציתיות": "concise", "מפורטות": "detailed", "יסודיות": "thorough"}
_LEVEL = re.compile(_LEAD + r"(brief|short|concise|detailed|thorough) (?:answers|replies)" + _TAIL, re.I)
_HE_LEVEL = re.compile(_HE_LEAD + r"תשובות (קצרות|תמציתיות|מפורטות|יסודיות)" + _HE_TAIL)

# "speak", "talk" or "voice" must be in it, unless the whole utterance is "slow down": "speed up the tests" is work, and
# "billing, slow down" is for a session (its name is not a lead word).
_SPEED = (
    (UP, re.compile(_LEAD + r"(?:(?:speak|talk)(?: a (?:bit|little))? (?:faster|quicker|more quickly)|faster (?:voice|speech)|"
                   r"speed up your (?:voice|speech|talking))" + _TAIL, re.I)),
    (DOWN, re.compile(_LEAD + r"(?:(?:speak|talk)(?: a (?:bit|little))? (?:slower|more slowly)|slower (?:voice|speech)|"
                    r"slow down(?: your (?:voice|speech|talking))?)" + _TAIL, re.I)),
    (1.0, re.compile(_LEAD + r"(?:(?:normal|regular|default) (?:speed|speaking speed|voice speed)|(?:speak|talk) at (?:normal|regular) speed)"
                     + _TAIL, re.I)),
    (1.2, re.compile(_LEAD + r"(?:fastest|(?:speak|talk) (?:at )?(?:the )?fastest|fastest (?:speed|voice))" + _TAIL, re.I)),
    (0.8, re.compile(_LEAD + r"(?:slowest|(?:speak|talk) (?:at )?(?:the )?slowest|slowest (?:speed|voice))" + _TAIL, re.I)),
    (UP, re.compile(_HE_LEAD + r"(?:תדברי?|דברי?) (?:מהר יותר|יותר מהר|קצת יותר מהר)" + _HE_TAIL)),
    (DOWN, re.compile(_HE_LEAD + r"(?:(?:תדברי?|דברי?) (?:לאט יותר|יותר לאט|קצת יותר לאט)|תאט|תאטי)" + _HE_TAIL)),
    (1.0, re.compile(_HE_LEAD + r"מהירות (?:רגילה|דיבור רגילה)" + _HE_TAIL)),
    (1.2, re.compile(_HE_LEAD + r"(?:תדברי? )?הכי מהר" + _HE_TAIL)),
    (0.8, re.compile(_HE_LEAD + r"(?:תדברי? )?הכי לאט" + _HE_TAIL)),
)

_POLISH = (
    (True, re.compile(_LEAD + r"(?:clean up my words|clean my words(?: up)?|clean words on|turn on clean(?:ing)? up my words)"
                      + _TAIL, re.I)),
    (False, re.compile(_LEAD + r"(?:stop cleaning(?: up)? my words|clean my words off|clean words off|don'?t clean(?: up)? my words|"
                       r"turn off clean(?:ing)? up my words)" + _TAIL, re.I)),
    (True, re.compile(_HE_LEAD + r"(?:תנקה|תנקי|נקה|נקי) את המילים שלי" + _HE_TAIL)),
    (False, re.compile(_HE_LEAD + r"(?:תפסיקי? לנקות את המילים שלי|בלי ניקוי(?: מילים)?)" + _HE_TAIL)),
)


def intent(text: str) -> tuple[str, object] | None:
    """A whole short utterance that changes a quick setting: ("replies.length", a level, UP or DOWN),
    ("voice.speed", a speed, UP or DOWN), ("polish", on). None for anything else."""
    text = (text or "").strip()
    if not text or len(text) > 80:
        return None
    for wanted, pattern in _LENGTH:
        if pattern.match(text):
            return "replies.length", wanted
    if m := (_LEVEL.match(text) or _HE_LEVEL.match(text)):
        return "replies.length", _LEVEL_WORDS[m.group(1).lower()]
    for wanted, pattern in _SPEED:
        if pattern.match(text):
            return "voice.speed", wanted
    for wanted, pattern in _POLISH:
        if pattern.match(text):
            return "polish", wanted
    return None


# ---------- what Pointe says back: four words at most ----------

_LEVEL_LINES = {"brief": ("Brief from now on.", "תשובות קצרות מעכשיו."),
                "concise": ("Concise from now on.", "תשובות תמציתיות מעכשיו."),
                "detailed": ("Detailed from now on.", "תשובות מפורטות מעכשיו."),
                "thorough": ("Thorough from now on.", "תשובות יסודיות מעכשיו.")}
_SPEED_LINES = {0.8: ("Slowest now.", "הכי לאט."), 1.0: ("Normal speed now.", "מהירות רגילה."), 1.2: ("Fastest now.", "הכי מהר.")}
_FASTER, _SLOWER = ("Faster now.", "עכשיו מהר יותר."), ("Slower now.", "עכשיו לאט יותר.")


def length_line(before: str, after: str, hebrew: bool) -> str:
    if before == after and after in ("brief", "thorough"):
        return ("כבר הכי קצר." if after == "brief" else "כבר הכי מפורט.") if hebrew else \
            ("Already at Brief." if after == "brief" else "Already at Thorough.")
    return _LEVEL_LINES[after][hebrew]


def speed_line(before: float, after: float, wanted, hebrew: bool) -> str:
    if before == after and wanted in (UP, DOWN) and after in (0.8, 1.2):
        return ("כבר הכי מהר." if after == 1.2 else "כבר הכי לאט.") if hebrew else \
            ("Already at fastest." if after == 1.2 else "Already at slowest.")
    if wanted in (UP, DOWN) and after not in _SPEED_LINES:
        return (_FASTER if after > before else _SLOWER)[hebrew]
    return _SPEED_LINES.get(after, _FASTER if after > before else _SLOWER)[hebrew]


def polish_line(on: bool, hebrew: bool) -> str:
    return ("מנקה את המילים שלך." if on else "בלי ניקוי.") if hebrew else ("Cleaning up your words." if on else "No more clean-up.")


NO_SPEED_LINE = ("Not with this voice.", "לא עם הקול הזה.")

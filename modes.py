"""What the voice may do right now. One mode at a time; a mode can only narrow what plain conversation allows.

Plain conversation is the widest: every tool, voice and tap approvals, session news spoken, nudges, permission read-outs,
free speech. Brainstorm (the user thinks out loud) and meeting mode hold things back. The invariant, tested: no mode
returns a wider approval, tool set, speech or delivery than conversation. Today's monologue machinery stays where it is
(daemon.py: _start_monologue, _end_monologue); this module names its policy so meeting mode and later modes share it.
"""

from dataclasses import dataclass

# How a permission prompt may be answered. "drive": a tap, or a spoken yes narrowed further (drive.py says how).
APPROVALS = {"voice+tap": 3, "drive": 2, "tap": 1, "none": 0}
SPEECH = {"free": 2, "on_request": 1, "never": 0}  # when the bot may talk

# What a meeting may do: read and answer, never act on a session or change routing.
READ_ONLY_TOOLS = frozenset({"speak", "list_sessions", "ask_about_session"})


@dataclass(frozen=True)
class Mode:
    name: str
    approvals: str = "voice+tap"
    tools: frozenset | None = None  # None: every tool
    holds_news: bool = False  # session news waits for the end of the mode
    nudges: bool = True  # the nudger may bring up waiting sessions
    reads_out: bool = True  # a permission request is read out
    speech: str = "free"
    sends: bool = True  # send_to_claude_code may deliver

    def allows_tool(self, name: str) -> bool:
        return self.tools is None or name in self.tools


CONVERSATION = Mode("conversation")
BRAINSTORM = Mode("brainstorm", approvals="tap", holds_news=True, nudges=False, reads_out=False, speech="never")
MEETING_LISTENING = Mode("meeting-listening", approvals="tap", tools=READ_ONLY_TOOLS, holds_news=True, nudges=False,
                         reads_out=False, speech="never", sends=False)
MEETING_PARTICIPATING = Mode("meeting-participating", approvals="tap", tools=READ_ONLY_TOOLS, holds_news=True,
                             nudges=False, reads_out=False, speech="on_request", sends=False)
DRIVE = Mode("drive", approvals="drive")  # short answers, and a yes only for what is safe from the road (drive.py)
# Devil's advocate (challenge.py): argues and looks things up, never acts. Permissions are read out and answered as in
# conversation; session reports wait for its end (daemon.FeedInjector.inject), so holds_news stays off here.
CHALLENGE = Mode("challenge", tools=READ_ONLY_TOOLS, nudges=False, sends=False)
ALL = (CONVERSATION, BRAINSTORM, MEETING_LISTENING, MEETING_PARTICIPATING, CHALLENGE, DRIVE)


def narrows(mode: Mode, base: Mode = CONVERSATION) -> bool:
    """True when the mode allows nothing the base does not."""
    if APPROVALS[mode.approvals] > APPROVALS[base.approvals] or SPEECH[mode.speech] > SPEECH[base.speech]:
        return False
    if base.tools is not None and (mode.tools is None or not mode.tools <= base.tools):
        return False
    return not ((mode.nudges and not base.nudges) or (mode.reads_out and not base.reads_out)
                or (mode.sends and not base.sends) or (not mode.holds_news and base.holds_news))

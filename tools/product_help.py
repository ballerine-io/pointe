"""Write product_help.json: what the voice knows about using Pointe itself (docs/design/product-help.md).

    python3 tools/product_help.py           write product_help.json from the UI code and the topics below
    python3 tools/product_help.py --check   exit 1 if product_help.json is not what this would write

Two parts. The UI's labels are read from the code: the iPhone app's Settings (the ••• button: each item, each picker's
options), the switch above its mic, its bottom bar, header, session menu and pairing screen (apps/ios/Pointe/*.swift, copy constants resolved), and the page's
Settings sections, dock, Sessions panel and session row (ui.html). The topics below are written by hand: the words a
person asks with (English and Hebrew), one or two sentences of explanation, the path on each surface, and the phrases
that do the same by voice today. Every path segment must be a label the code shows, so a renamed label fails here
until its topic is fixed; tests/test_product_help.py fails when the file is not regenerated after a label changes.
Standard library only: no dependency, no network.
"""

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = "pointe/product_help.json"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from parity import for_platform  # noqa: E402  (a Swift source as one platform compiles it)

# ---------- the iPhone app ----------

_TYPE = re.compile(r"^\s*(?:(?:private|fileprivate|public)\s+)?(?:enum|struct|extension|class)\s+(\w+)", re.M)
_CONST = re.compile(r'static let (\w+)(?:: String)? = "((?:[^"\\]|\\.)*)"')
_LIT = re.compile(r'"((?:[^"\\]|\\.)*)"')


def _unescape(s: str) -> str:
    return s.replace('\\"', '"').replace("\\u{2019}", "’").replace("\\u{201C}", "“").replace("\\u{201D}", "”")


def _swift_consts(files: list[Path], platform: str = "ios") -> tuple[dict[str, str], dict[str, str]]:
    """Every `static let x = "..."` as "Type.x", and every type's body text (for `var label` and `static func`)."""
    consts, bodies = {}, {}
    for f in files:
        text = for_platform(f.read_text(), platform)
        types = [(m.start(), m.group(1)) for m in _TYPE.finditer(text)]
        for i, (at, name) in enumerate(types):
            end = types[i + 1][0] if i + 1 < len(types) else len(text)
            bodies[name] = bodies.get(name, "") + text[at:end]
        for m in _CONST.finditer(text):
            owner = next((name for at, name in reversed(types) if at < m.start()), "")
            consts.setdefault(f"{owner}.{m.group(1)}", _unescape(m.group(2)))
    return consts, bodies


def _braced(text: str, start: int) -> str:
    """The text from `start` to the brace that closes the first one opened after it."""
    i, depth = text.index("{", start), 0
    for j in range(i, len(text)):
        depth += {"{": 1, "}": -1}.get(text[j], 0)
        if depth == 0:
            return text[start:j + 1]
    raise ValueError("unbalanced braces")


class Swift:
    """The screens the two apps share (apps/PointeKit, PointeUI), as one of them compiles them: `platform` is "ios" or
    "mac", and a row inside the other's `#if os(...)` is not there (tools/parity.py reads the sources the same way)."""

    def __init__(self, root: Path, platform: str = "ios"):
        self.dir = root / "apps" / "PointeKit" / "Sources" / "PointeUI"
        self.platform = platform
        kit = root / "apps" / "PointeKit" / "Sources" / "PointeKit"  # the words both apps take from the package under the screens
        self.consts, self.bodies = _swift_consts(sorted(self.dir.glob("*.swift")) + sorted(kit.glob("*.swift")), platform)

    def file(self, name: str) -> str:
        return for_platform((self.dir / name).read_text(), self.platform)

    def resolve(self, expr: str) -> list[str]:
        """The labels an expression can show: literals, `Copy.member`, both sides of a ternary, and the constants a
        `Copy.func(...)` returns."""
        out = [_unescape(s) for s in _LIT.findall(expr) if "\\(" not in s]
        for owner, member, call in re.findall(r"\b([A-Z]\w+)\.(\w+)(\()?", expr):
            if call:
                body = self.bodies.get(owner, "")
                fn = re.search(rf"static func {member}\b", body)
                if fn:
                    out += [self.consts[f"{owner}.{n}"] for n in re.findall(r"\b(\w+)\b", _braced(body, fn.start()))
                            if f"{owner}.{n}" in self.consts]
            elif f"{owner}.{member}" in self.consts:
                out.append(self.consts[f"{owner}.{member}"])
        return list(dict.fromkeys(out))

    def options(self, picker: str) -> list[str]:
        """A picker's choices: `Text("x").tag`, `Text(Copy.member).tag`, `ForEach(Copy.levels …)` or
        `ForEach(Type.allCases …) { $0.label }`."""
        out = [_unescape(s) for s in re.findall(r'Text\("((?:[^"\\]|\\.)*)"\)\.tag', picker)]
        out += [self.consts[f"{o}.{m}"] for o, m in re.findall(r"Text\((\w+)\.(\w+)\)\.tag", picker) if f"{o}.{m}" in self.consts]
        for owner, member in re.findall(r"ForEach\((\w+)\.(\w+)", picker):
            body = self.bodies.get(owner, "")
            if member == "allCases":
                label = re.search(r"var label: String", body)
                out += [_unescape(s) for s in _LIT.findall(_braced(body, label.start()))] if label else []
            else:
                levels = re.search(rf"static let {member}\b[^=]*=\s*(\[[^\]]*\])", body)
                out += [_unescape(b) for _a, b in re.findall(r'\("([^"]*)",\s*"([^"]*)"\)', levels.group(1))] if levels else []
        return list(dict.fromkeys(out))

    def menu(self) -> dict[str, list[str]]:
        """Settings, the sheet behind the ••• button (CallSettings.swift): each item's label, with a picker's options."""
        view = self.file("CallSettings.swift")
        block = _braced(view, view.index("var body: some View"))
        items: dict[str, list[str]] = {}
        pickers = []
        for m in re.finditer(r"Picker\(selection:", block):
            label = re.search(r"\} label: \{ Label\((.+?), systemImage:", block[m.start():])
            pickers.append((m.start(), m.start() + label.end()))
            for name in self.resolve(label.group(1)):
                items[name] = self.options(block[m.start():m.start() + label.start()])
        for m in re.finditer(r"Label\((.+?), systemImage:|Button\(((?:\w+\.\w+)|\"[^\"]+\"), systemImage:|\brow\((.+?), \"", block):
            if not any(a <= m.start() < b for a, b in pickers):
                for name in self.resolve(m.group(1) or m.group(2) or m.group(3)):
                    items.setdefault(name, [])
        return items

    def mic_switch(self) -> list[str]:
        """The switch above the mic (MicModeSwitch): Always on, and push to talk named by the talk style."""
        bar = self.file("BottomBar.swift")
        block = _braced(bar, bar.index("struct MicModeSwitch"))
        out = [_unescape(s) for s in re.findall(r'Text\("((?:[^"\\]|\\.)*)"\)\.tag', block)]
        if "Text(style.label)" in block:
            body = self.bodies.get("TalkStyle", "")
            out += [_unescape(s) for s in _LIT.findall(_braced(body, re.search(r"var label: String", body).start()))]
        return list(dict.fromkeys(out))

    def bar(self) -> list[str]:
        bar = self.file("BottomBar.swift")
        return list(dict.fromkeys(x for expr in re.findall(r'side\(("[^"]+"|[A-Z]\w+\.\w+\([^)]*\))', bar) for x in self.resolve(expr)))

    def mic(self) -> list[str]:
        """The mic in the middle of the bar, by what it says during a call: Mute or Unmute."""
        expr = re.search(r"\.accessibilityLabel\(phase == \.live \? (\(muted[^)]*\))", self.file("BottomBar.swift")).group(1)
        return self.resolve(expr)

    def header(self) -> list[str]:
        view = self.file("CallView.swift")
        top = _braced(view, view.index("private var top: some View"))
        connect = [self.consts["ConnectCopy.connect"]] if "ConnectPill(" in top else []
        top = top[:top.index("SessionChips(")]
        quick = [self.consts["QuickCopy.title"]] if "QuickButton(" in top else []  # its label is the button's own (QuickSettings.swift)
        return list(dict.fromkeys([x for expr in re.findall(r"\.accessibilityLabel\((.+?)\)\n", top) for x in self.resolve(expr)]
                                  + quick + connect))

    def status(self) -> list[str]:
        """The mute button beside the status line: what it says a tap does."""
        if "MuteButton(" not in self.file("CallView.swift"):
            return []
        return [self.consts["MuteCopy.mute"], self.consts["MuteCopy.unmute"]]

    def session_menu(self) -> list[str]:
        """What a long press on a session chip offers (Sessions.swift's context menus)."""
        text = self.file("Sessions.swift")
        out = []
        for m in re.finditer(r"\.contextMenu \{", text):
            out += [_unescape(s) for s in re.findall(r'Button\("((?:[^"\\]|\\.)*)"', _braced(text, m.start())) if "\\(" not in s]
        return list(dict.fromkeys(out))

    def sessions_sheet(self) -> list[str]:
        text = self.file("Sessions.swift")
        title = re.search(r'\.sheetTitle\((?:"([^"]+)"|([A-Z]\w+\.\w+))\)', text)
        sheet = title.group(1) or self.resolve(title.group(2))[0]
        picks = re.findall(r'Text\("(\w+)"\)\.tag\("(?:orchestrator|session)"\)', text)
        swipe = _braced(text, text.index(".swipeActions"))
        bar = _braced(text, text.index(".toolbar", text.index(".sheetTitle")))  # its own buttons, named by a copy constant
        named = [x for expr in re.findall(r"Button\(([A-Z]\w+\.\w+)\)", bar) for x in self.resolve(expr)]
        return list(dict.fromkeys([sheet, *picks, *named, *re.findall(r'Button\("([^"]+)"', swipe)]))

    def card(self) -> list[str]:
        """The buttons on a request's card."""
        view = self.file("CallView.swift")
        return re.findall(r'Button \{ act\((?:true|false)\) \} label: \{ (?:Label|Text)\("([^"]+)"', view)

    def pairing(self) -> list[str]:
        pair = self.file("PairView.swift")
        return re.findall(r'Button\(action: use\) \{ Text\("([^"]+)"\)', pair) + re.findall(r'Label\("([^"]+)", systemImage', pair)


# ---------- the page ----------

def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).replace("&amp;", "&").strip()


def _between(html: str, start: str, end: str) -> str:
    i = html.index(start)
    return html[i:html.index(end, i)]


def _short(label: str) -> str:
    """A title's label without its explanation: "Disconnect from the voice (it keeps running …)" is the first part."""
    return label.split(" (")[0].strip()


class Page:
    def __init__(self, root: Path):
        self.html = (root / "pointe" / "ui.html").read_text()
        self.mute = (root / "pointe" / "ui_mute.html").read_text()

    def settings(self) -> dict[str, list[str]]:
        """Each Settings section, by the name in its nav, with the labels it shows: fields, ticks, options, buttons."""
        nav = dict(re.findall(r'data-section="([\w-]+)" onclick="settingsJump\(\'[\w-]+\'\)">([^<]+)</button>', self.html))
        out = {}
        for sid, name in nav.items():
            at = re.search(rf'<section[^>]*\bid="{re.escape(sid)}"', self.html)
            block = self.html[at.start():self.html.index("</section>", at.start())]
            labels = re.findall(r'class="field(?: [\w ]+)?">([^<]+)<', block)
            labels += [_text(t) for t in re.findall(r'<label class="tick"><input[^>]*>([^<]+)</label>', block)]
            labels += re.findall(r"<option value=\"[^\"]*\">([^<]+)</option>", block)
            labels += [_text(t) for t in re.findall(r"<button[^>]*>([^<]+)</button>", block)]
            labels += re.findall(r"<span>([^<]+)</span>", block)
            out[name] = list(dict.fromkeys(x.strip() for x in labels if x.strip() and x.strip() != "×"))
        return out

    def dock(self) -> list[str]:
        return list(dict.fromkeys(re.findall(r'class="lb"[^>]*>([^<]+)<', _between(self.html, '<nav class="dock"', "</nav>"))))

    def mic_switch(self) -> list[str]:
        """The switch above the mic: the Microphone setting, at hand."""
        return re.findall(r'role="radio"[^>]*>([^<]+)</button>', _between(self.html, '<nav class="dock"', "</nav>"))

    def mic(self) -> list[str]:
        return re.findall(r'<button id="mic"[^>]*aria-label="([^"]+)"', self.html)

    def side(self) -> list[str]:
        side = _between(self.html, '<aside id="side">', "</aside>")
        return list(dict.fromkeys(re.findall(r'<h3 class="label">([^<]+)</h3>', side)
                                  + re.findall(r"<button id=\"(?:m-\w+|settingsbtn)\"[^>]*>([^<]+)</button>", side)))

    def top(self) -> list[str]:
        top = _between(self.html, '<div class="top">', '<div id="meetbar"')
        return list(dict.fromkeys([_text(t) for t in re.findall(r'<label class="toggle"[^>]*><input[^>]*>([^<]+)</label>', top)]
                                  + re.findall(r'id="quickrow"[^>]*aria-label="([^"]+)"', top)
                                  + re.findall(r'id="topconnect"[^>]*>([^<]+)<', top)
                                  + re.findall(r'id="morebtn"[^>]*aria-label="([^"]+)"', top)))

    def status(self) -> list[str]:
        """The mute button beside the status line: what it says a tap does (ui_mute.html holds its words)."""
        if not re.search(r'<div class="stateline">.*id="mutebtn"', self.html):
            return []
        return re.findall(r"\b(?:mute|unmute): '([^']+)'", self.mute)

    def row(self) -> list[str]:
        """A session row's actions: the marks shown on hover (their titles), the ⋯ sheet on touch."""
        marks = [_short(t) for t in re.findall(r"(?:pen|cut)\.title = '([^']+)'", self.html)]
        return list(dict.fromkeys(marks + re.findall(r'<div id="row-acts"><button[^>]*>([^<]+)</button>', self.html)))

    def dump_review(self) -> list[str]:
        sheet = _between(self.html, '<div class="sheetbg" id="dumpsheet"', '<div class="hint">')
        return list(dict.fromkeys(_text(t) for t in re.findall(r"<button id=\"dump-[\w-]+\"[^>]*>([^<]+)</button>", sheet)))

    def card(self) -> list[str]:
        return re.findall(r"\['(\w+)', '(?:deny|allow)'\]", self.html)


def inventory(root: Path = ROOT) -> dict:
    s, p, m = Swift(root), Page(root), Swift(root, "mac")
    return {
        # the Mac app draws the iPhone app's screens: its labels are read from the same sources, as the Mac compiles them
        "mac": {"menu": m.menu(), "switch": m.mic_switch(), "bar": m.bar(), "mic": m.mic(), "header": m.header(),
                "status": m.status(), "session": m.session_menu(), "sessions": m.sessions_sheet(), "card": m.card()},
        "iphone": {"menu": s.menu(), "switch": s.mic_switch(), "bar": s.bar(), "mic": s.mic(), "header": s.header(),
                   "status": s.status(), "session": s.session_menu(),
                   "sessions": s.sessions_sheet(), "card": s.card(), "pair": s.pairing()},
        "page": {"settings": p.settings(), "dock": p.dock(), "mic": p.mic(), "switch": p.mic_switch(), "side": p.side(),
                 "top": p.top(), "status": p.status(), "row": p.row(),
                 "dump": p.dump_review(), "card": p.card()},
    }


# ---------- paths ----------

# How each kind of place is said. The first segment of a path names the place; the rest are labels inside it.
PLACES = {
    "iphone": {"menu": "Settings (••• at the top)", "switch": "the {} switch above the mic", "bar": "{} button at the bottom",
               "mic": "the mic button in the middle at the bottom ({})",
               "header": "{} button at the top", "status": "the speaker button beside the status line ({})",
               "session": "long-press a session at the top", "sessions": "Sessions button at the bottom",
               "card": "the request's card", "pair": "the pairing screen"},
    "page": {"settings": "Settings", "dock": "{} button at the bottom", "mic": "the mic button in the middle at the bottom ({})",
             "switch": "the {} switch above the mic", "side": "{} in the Sessions panel on the left",
             "top": "{} at the top", "status": "the speaker button beside the status line ({})", "row": "hover a session in the Sessions panel (on touch, its ⋯)",
             "dump": "the brain dump's review", "card": "the request's card"},
}
PLACES["mac"] = {"menu": "Settings (••• at the top, or ⌘,)", "switch": "the {} switch above the mic", "bar": "{} button at the bottom",
                 "mic": "the mic button in the middle at the bottom ({})", "header": "{} button at the top",
                 "status": "the speaker button beside the status line ({})", "session": "right-click a session", "sessions": "the sessions column on the left (in a narrow window, the Sessions button at the bottom)",
                 "card": "the request's card"}
SURFACES = {"iphone": "the iPhone app", "page": "the page", "mac": "the Mac app"}


def _labels(where: dict) -> set[str]:
    out = set()
    for v in where.values():
        out |= set(v) | {o for opts in v.values() for o in opts} if isinstance(v, dict) else set(v)
    return out


def render(surface: str, path: tuple, inv: dict) -> str:
    """"menu", "Microphone", "Always on|Push to talk" -> "••• menu → Microphone → Always on / Push to talk", each label
    checked against what the code shows there."""
    where, kind, rest = inv[surface], path[0], list(path[1:])
    if kind not in PLACES[surface]:
        raise ValueError(f"{surface}: no place {kind!r} (places: {', '.join(PLACES[surface])})")
    place, found = PLACES[surface][kind], where[kind]
    for i, seg in enumerate(rest):
        for alt in seg.split("|"):
            if i == 0 and isinstance(found, dict):
                ok = alt in found
            elif i == 1 and isinstance(found, dict):
                ok = alt in found[rest[0]] or alt in _labels(where)
            else:
                ok = alt in (found if i == 0 else _labels(where))
            if not ok:
                shown = sorted(found) if i == 0 else sorted(found[rest[0]]) if isinstance(found, dict) else found
                raise ValueError(f"{surface} {kind}: {alt!r} is not a label the code shows there ({shown})")
    segs = [s.replace("|", " / ") for s in rest]
    if "{}" in place:
        head, segs = place.format(segs[0]), segs[1:]
    else:
        head = place
    out = [head, *segs]
    # "Settings → Microphone → Microphone → Push to talk": a field named like its section is said once
    return " → ".join(x for i, x in enumerate(out) if i == 0 or x != out[i - 1])


def _on(surface: str, path: tuple, inv: dict) -> bool:
    try:
        render(surface, path, inv)
        return True
    except ValueError:
        return False


# ---------- the topics, by hand ----------

@dataclass(frozen=True)
class Topic:
    id: str
    title: str
    ask: tuple  # words a person asks with, English and Hebrew; a longer phrase weighs more
    how: str  # one or two sentences, English; the brain answers in the user's language
    iphone: tuple = ()  # one or more paths, each a tuple: place, then labels
    page: tuple = ()
    mac: tuple | None = None  # None: the iPhone's paths, where the Mac app has the same control (it draws the same screens)
    iphone_note: str = ""
    page_note: str = ""
    mac_note: str = ""
    voice: tuple = ()  # what the user can say right now for the same thing (checked against the code in the tests)
    tool: str = ""  # the brain's own tool that does it, when the user asks it to
    doc: str = ""  # docs/features/<doc>: its one line in the features table is added as "about"


TOPICS = (
    Topic("mic-mode", "Microphone: Always on, Only when I say Pointe, or Push to talk",
          ("push to talk", "always on", "open mic", "microphone mode", "mic mode", "ptt", "hold to talk mode",
           "turn off push to talk", "turn on push to talk", "לחץ ודבר", "לחיצה לדיבור", "פוש טו טוק", "תמיד פתוח",
           "מיקרופון פתוח", "מצב מיקרופון"),
          "Always on hears you whenever you are not muted; Only when I say Pointe hears everything and acts only on "
          "words that say Pointe's name or a session's; Push to talk hears you only while you press the mic. It is one "
          "setting, so the page and the app agree.",
          iphone=(("switch", "Always on|Say “Pointe”|Hold to talk"), ("menu", "Microphone", "Always on|Only when I say Pointe|Push to talk")),
          page=(("settings", "Microphone", "Microphone", "Always on|Only when I say Pointe|Push to talk"), ("switch", "Always on|Say “Pointe”|Hold to talk")),
          doc="push-to-talk.md"),
    Topic("addressed", "Only when I say Pointe: ignore side talk",
          ("only when i say pointe", "say pointe", "ignore side talk", "side talk", "stop listening to my phone call",
           "it hears my phone calls", "it answers when i talk to someone else", "wake word", "say your name", "addressed",
           "רק כשאני אומר פוינט", "מילת השכמה", "הוא עונה כשאני מדבר עם מישהו אחר", "שיחת טלפון"),
          "With the microphone set to Only when I say Pointe, a spoken turn is acted on only when it starts with "
          "Pointe's name or a session's, or ends with \", Pointe\": \"Pointe, what's billing doing\", \"billing, run the "
          "tests\". Anything else is treated as side talk and dropped: not kept, not sent, never a yes to a request. Say "
          "\"Pointe\" alone and the next words need no name.",
          iphone=(("switch", "Say “Pointe”"), ("menu", "Microphone", "Only when I say Pointe")),
          page=(("settings", "Microphone", "Microphone", "Only when I say Pointe"), ("switch", "Say “Pointe”")),
          doc="addressed-speech.md"),
    Topic("talk-button", "Talk button: hold or tap",
          ("hold to talk", "tap to talk", "hold or tap", "hold vs tap", "hold and tap", "tap or hold", "tap and hold", "talk button", "tap once", "instead of holding", "tap instead of hold",
           "hold instead of tap", "keep holding", "לחיצה ארוכה", "להחזיק", "הקשה", "ללחוץ פעם אחת"),
          "In push to talk, Hold to talk sends when you let go; Tap to talk starts with one tap and sends with the "
          "next. Each device keeps its own choice.",
          iphone=(("menu", "Talk button", "Hold to talk|Tap to talk"),),
          page=(("settings", "Microphone", "Talk button", "Hold to talk|Tap to talk"),),
          iphone_note="Talk button shows in Settings once Microphone is Push to talk.", doc="push-to-talk.md"),
    Topic("talk-key", "Talk key and talking from any app",
          ("talk key", "keyboard shortcut", "space bar", "caps lock", "shortcut", "from any app", "action button",
           "back tap", "siri", "airpods", "another app", "other app", "קיצור מקשים", "מקש", "כפתור אקשן"),
          "On the page Space is the talk key, Caps Lock toggles talking, and a system-wide shortcut can run it from any "
          "app. On the iPhone the Action button, Back Tap or Siri (\"Talk to Pointe\") press it, and start a call when "
          "none is up; an AirPods stem press toggles it.",
          page=(("settings", "Microphone", "Talk key|System-wide shortcut"),), mac=(("menu",),),
          mac_note="In the Mac app's Settings, under This Mac: Talk shortcut records a key that talks from any app.",
          doc="push-to-talk.md"),
    Topic("talk-outside", "Talk to Pointe from the Lock Screen, Control Center, the Action button or a widget",
          ("lock screen", "control center", "action button", "widget", "home screen", "without opening the app",
           "live activity", "dynamic island", "from the lock screen", "add a control", "talk to pointe",
           "מסך הנעילה", "מסך נעילה", "מרכז הבקרה", "וידג'ט", "ווידג'ט", "בלי לפתוח את האפליקציה"),
          "Add the Talk to Pointe control to Control Center, the Lock Screen or the Action button (iPhone Settings, "
          "Action Button, Controls), or its widget to the Home Screen. One press opens Pointe talking to the "
          "orchestrator, calling your Mac first if no call is up; press again or tap the mic to send. A locked iPhone "
          "asks you to unlock first. A press never approves.",
          iphone=(("menu", "Talk from outside the app"),), mac=(),
          page_note="The page has no control or widget: on the iPhone, add the Talk to Pointe control or widget.",
          mac_note="The Mac app has no control or widget: its talk shortcut talks from any app.",
          doc="push-to-talk.md"),
    Topic("mute", "Turn the mic off and on",
          ("mute", "unmute", "mute myself", "mute the mic", "stop listening", "השתק", "להשתיק", "משתיק", "השתקה",
           "מיוט", "לבטל השתקה"),
          "In Always on, the mic button in the middle turns your microphone off and on.",
          iphone=(("mic", "Turn mic off|Turn mic on"),), page=(("mic", "Microphone"),),
          page_note="Space, or a headset's play/pause button, does the same while the page has focus.",
          mac_note="During a call an AirPods stem press does the same, with the system's chime; in push to talk it talks."),
    Topic("hang-up", "Hang up", ("hang up", "end the call", "end call", "stop the call", "disconnect the call",
                                 "לנתק את השיחה", "לסיים שיחה", "לנתק שיחה", "לנתק"),
          "Hang up ends the call; your sessions keep running.",
          iphone=(("bar", "Hang up"),), page=(("dock", "Hang up"),)),
    Topic("connect", "Start a call", ("start a call", "connect", "call pointe", "start talking", "להתקשר", "להתחבר",
                                      "להתחיל שיחה"),
          "Tap Connect to start the call on this device's microphone.",
          iphone=(("header", "Connect"),), page=(("top", "Connect"),), page_note="Or press the mic button."),
    Topic("pair-phone", "Pair the iPhone with this Mac",
          ("pair", "pair the phone", "pair my phone", "connect the phone", "connect my iphone", "set up the iphone",
           "qr code", "scan the code", "לצמד", "מצמיד", "צימוד", "לחבר את הטלפון", "לחבר את האייפון", "קוד qr"),
          "On the Mac's page, Settings → Phone → Connect your phone shows a code; scan it in the Pointe app on the "
          "iPhone. The code works once and expires in 5 minutes.",
          iphone=(("pair", "Pair"),), page=(("settings", "Phone", "Connect your phone"),), mac=(("menu", "Phone"),),
          mac_note="The Mac app shows the code: Connect your phone, then scan it with the iPhone.",
          iphone_note="Pairing starts on the Mac's page: Settings → Phone → Connect your phone."),
    Topic("unpair", "Unpair a phone", ("unpair", "remove the phone", "forget this phone", "לבטל צימוד", "להסיר את הטלפון"),
          "On the iPhone, Unpair this phone forgets the pairing there; the page's Settings → Phone lists the paired phones "
          "and removes them from the Mac. To pair again, show a new code there.",
          iphone=(("menu", "Unpair this phone"),), page=(("settings", "Phone", "Unpair all"),), mac=(("menu", "Phone"),),
          mac_note="Each paired phone has its own Unpair there."),
    Topic("voice-lock", "Voice lock", ("voice lock", "only my voice", "voiceprint", "enrol my voice", "enroll my voice",
                                       "other voices", "someone else approving", "other people approve", "someone else", "נעילת קול", "נעילה קולית",
                                       "רק הקול שלי", "טביעת קול"),
          "Voice lock learns your voice so other voices cannot approve or command. Enrol during a call, then pick a "
          "level: Off, Approvals, Commands or Everything.",
          iphone=(("menu", "Voice lock"),), page=(("settings", "Voice lock", "Enrol my voice"),), doc="voice-lock.md"),
    Topic("patience", "Wait before answering", ("wait before answering", "answers too fast", "interrupts me",
                                                "cuts me off", "wait longer", "patience", "quick normal patient",
                                                "turn taking", "pause", "לחכות לפני שעונה", "עונה מהר מדי", "קוטע אותי",
                                                "מחכה", "סבלנות", "זמן המתנה"),
          "How long a pause ends your sentence: Quick answers as soon as you stop, Normal waits about a second, Patient "
          "waits longer.",
          iphone=(("menu", "Wait before answering", "Quick|Normal|Patient"),),
          page=(("settings", "Turn taking", "Wait before answering", "Quick|Normal|Patient"),)),
    Topic("thinking", "Thinking and the waiting sound",
          ("thinking", "did you hear me", "is it thinking", "waiting sound", "the beep", "the sound while i wait",
           "what is that sound", "turn off the sound", "still listening", "חושב", "שמעת אותי", "צליל המתנה", "הצליל"),
          "From the end of your turn until the reply the status line says \"Thinking…\"; while a session has your "
          "request it says the session is working. When a reply takes long, one soft sound says your words were heard; "
          "it never plays with the reply, while Pointe is muted, in whisper mode or in a meeting.",
          iphone=(("menu", "Waiting sound"),), page=(("settings", "Turn taking", "Waiting sound"),), doc="thinking.md"),
    Topic("session-tones", "Session tones: one sound per session",
          ("session tones", "a sound per session", "tone before a report", "what is that tone", "which session is that sound",
           "different sound for each session", "turn on session tones", "turn off session tones", "צליל לכל סשן", "צלילי סשן"),
          "With session tones on, a short tone plays before a background session's report, the same tone for that session "
          "every time, so you know who is reporting before the first word. Off unless you turn it on. A session's row "
          "names its tone. Never while Pointe is muted, in whisper mode or in a meeting.",
          iphone=(("menu", "Session tones"),), page=(("settings", "Turn taking", "Session tones"),), doc="session-tones.md"),
    Topic("approvals-record", "Approvals record: what was approved, when and how",
          ("approvals record", "approval history", "what did i approve", "what have i approved", "list of approvals", "audit",
           "who approved", "voice lock score", "היסטוריית אישורים", "מה אישרתי", "רשימת האישורים"),
          "The approvals record lists every answer to a request that went through Pointe, newest first: when, by voice or "
          "by a tap, the exact request, and for a spoken answer the voice lock's score. It is read from the journal on "
          "your Mac and only shows; an answer given in a session's terminal is not in it.",
          iphone=(("menu", "Approvals record"),), page=(("settings", "Approvals record"),), doc="approvals-record.md"),
    Topic("accessibility", "Accessibility: VoiceOver, Reduce Motion and large text",
          ("accessibility", "voiceover", "voice over", "screen reader", "reduce motion", "stop the animation", "the dot keeps moving",
           "large text", "bigger text", "text size", "dynamic type", "נגישות", "קורא מסך", "הפחתת תנועה", "טקסט גדול"),
          "Every control of the call screen has a name for a screen reader, and the status line is read as one line. With "
          "Reduce Motion on in the system's Accessibility settings nothing on a Pointe screen moves by itself: the status "
          "line's words carry the state. Every sound has something on screen with it, and the iPhone app follows the "
          "system's text size. These follow the device's own settings: Pointe has no switch for them.",
          doc="accessibility.md"),
    Topic("progress", "Progress updates while a session works",
          ("progress updates", "keep me posted", "keep me updated", "how is it going", "stop updates", "is it still working",
           "updates while it works", "תעדכן אותי", "עדכוני התקדמות", "בלי עדכונים"),
          "With progress updates on, Pointe says one short line about 20 seconds after a session got your request, then "
          "every 45 seconds until it answers: how long it has worked and its latest step. Off unless you turn it on. "
          "Muted, the line is text.",
          iphone=(("menu", "Progress updates"),), page=(("settings", "Turn taking", "Progress updates"),),
          voice=("keep me posted", "stop updates"), doc="progress.md"),
    Topic("hold", "Don't interrupt me", ("don't interrupt me", "do not interrupt", "hold on", "let me finish",
                                         "stay quiet", "keep quiet while i think", "interrupting me", "stop interrupting", "אל תפריע", "אל תקטע", "רגע",
                                         "תן לי לסיים"),
          "Say \"don't interrupt me\" or \"hold on\" and Pointe stays quiet until you say \"go ahead\" or \"I'm done\", "
          "or until 8 seconds of quiet.",
          voice=("don't interrupt me", "hold on", "go ahead", "I'm done")),
    Topic("appearance", "Appearance: light or dark", ("appearance", "dark mode", "light mode", "theme", "dark theme",
                                                      "night mode", "מצב כהה", "מצב בהיר", "ערכת נושא", "מראה", "תצוגה"),
          "Pick System, Light or Dark; System follows the device.",
          iphone=(("menu", "Appearance", "System|Light|Dark"),), page=(("settings", "Appearance", "System|Light|Dark"),),
          page_note="The page keeps the choice in this browser."),
    Topic("about", "About and version", ("about pointe", "about screen", "version", "which version", "open source", "license", "גרסה", "אודות"),
          "About shows the version and that Pointe is open source (MIT).",
          iphone=(("menu", "About"),), page=(("settings", "About"),)),
    Topic("brain-dump", "Brain dump", ("brain dump", "dump my thoughts", "think out loud", "just listen",
                                       "structure my thoughts", "ברין דאמפ", "לשפוך מחשבות", "רק תקשיב", "לחשוב בקול"),
          "Brain dump: talk freely while Pointe stays quiet; say \"done\" and it structures your words into a prompt you "
          "review and send.",
          iphone=(("bar", "Brain dump"),), page=(("dock", "Brain dump"),),
          voice=("brain dump", "just listen", "done"), doc="brain-dump.md"),
    Topic("meeting", "Meeting mode", ("meeting", "meeting mode", "take notes", "start a meeting", "notes of the meeting",
                                      "פגישה", "מצב פגישה", "לרשום הערות"),
          "Meeting mode sits in and takes notes, and stays quiet unless you let it speak. Nothing is sent to a session "
          "during it.",
          iphone=(("header", "Start a meeting"), ("menu", "Meeting settings")),
          page=(("dock", "Meeting"), ("settings", "Meetings")),
          voice=("meeting mode, listening", "Pointe, join in", "Pointe, just listen",
                 "Pointe, what does billing's session say about the retry limit?", "Pointe, end the meeting",
                 "send the action items to billing"), doc="meeting-mode.md"),
    Topic("challenge", "Challenge me", ("challenge", "challenge me", "devil's advocate", "poke holes", "argue against",
                                        "לאתגר", "תאתגר אותי", "תתקוף את זה"),
          "Challenge argues against your plan one objection at a time and sends nothing; \"verdict\" ends it.",
          iphone=(("menu", "Challenge|End challenge"),), page=(("dock", "Challenge"),),
          voice=("challenge me", "verdict"), doc="challenge.md"),
    Topic("drive", "Drive mode", ("drive mode", "driving", "walk mode", "in the car", "carplay", "מצב נהיגה", "נוהג",
                                  "ברכב"),
          "Drive mode gives short answers and approves by voice only what is safe from the road.",
          iphone=(("header", "Drive"), ("menu", "Suggest Drive mode in the car")),
          page_note="The page has no Drive button: start it by voice or in the iPhone app.",
          voice=("drive mode", "I've stopped"), doc="drive-mode.md"),
    Topic("whisper", "Whisper mode", ("whisper", "whisper mode", "quiet replies", "open office", "speak quietly",
                                      "לחישה", "מצב לחישה", "בשקט"),
          "Whisper mode gives short, quiet replies for an open office; \"back to normal\" ends it.",
          iphone=(("menu", "Whisper"),), page=(("dock", "Whisper"),),
          voice=("whisper mode", "back to normal"), doc="whisper-mode.md"),
    Topic("mute", "Mute Pointe", ("mute pointe", "mute the voice", "mute you", "unmute", "stop talking", "text only",
                                  "read instead", "reading mode", "don't speak", "i'll read", "talk again",
                                  "מצב קריאה", "בלי קול", "תפסיק לדבר", "השתק"),
          "The speaker button beside the status line mutes Pointe: it writes every reply as text instead of speaking, "
          "and the status says \"Writing…\". Tap it again, or say \"talk again\", to hear Pointe. You still talk or "
          "type. Each device keeps its own choice.",
          iphone=(("status", "Mute Pointe|Unmute Pointe"),), page=(("status", "Mute Pointe|Unmute Pointe"),),
          mac_note="During a call a headset's play/pause or the keyboard's play/pause key does the same. Settings, under "
                   "This Mac, Play/pause in a call, can make it Skip or Nothing; outside a call the music keeps it.",
          voice=("stop talking, I'll read", "talk again"), doc="mute.md"),
    Topic("briefing", "Briefing", ("briefing", "brief me", "what happened overnight", "catch me up", "summary of the night",
                                   "תדריך", "תדרך אותי", "מה קרה בלילה"),
          "A briefing says what each session did, failed and waits on, most urgent first.",
          iphone=(("menu", "Briefing"),), page=(("dock", "Briefing"),),
          voice=("brief me on the night",), tool="briefing", doc="briefings.md"),
    Topic("briefing-schedule", "Scheduled briefing", ("schedule a briefing", "scheduled briefing", "morning briefing",
                                                      "briefing every day", "briefing time", "תדריך קבוע", "תזמון תדריך"),
          "A scheduled briefing is read on the Mac at the time and days you pick.",
          iphone=(("menu", "Briefing settings"),), page=(("settings", "Briefings", "Scheduled briefing"),)),
    Topic("dictionary", "Dictionary", ("dictionary", "vocabulary", "misheard", "mishears", "names it gets wrong",
                                       "teach it a word", "spelling of a name", "מילון", "לא שומע נכון", "שומע לא נכון"),
          "Correct a misheard word in the conversation and Pointe learns it; the Dictionary lists, adds and edits terms. "
          "A new term applies from the next call.",
          iphone=(("menu", "Dictionary"),), page=(("settings", "Dictionary", "Dictionary…"),), doc="vocabulary.md"),
    Topic("alerts", "Alerts and the Apple Watch", ("alerts", "notifications", "notify me", "apple watch", "watch",
                                                   "desktop alerts", "approve from the watch", "התראות", "שעון", "נוטיפיקציות"),
          "Alerts tell you when a session needs you; Approve from notifications adds Approve on the iPhone and Apple Watch.",
          iphone=(("menu", "Alerts"),),
          page=(("settings", "Alerts", "Desktop alerts while this tab is in the background|"
                 "Approve from notifications (iPhone and Apple Watch)"),), doc="alerts.md"),
    Topic("conflicts", "Conflict alarm", ("conflict alarm", "conflict", "sessions disagree", "two sessions disagree",
                                          "קונפליקט", "סתירה", "סשנים לא מסכימים"),
          "The conflict alarm says when two sessions claim opposite things about the same work; it can be spoken or a "
          "card only.",
          iphone=(("menu", "Conflict alarm"),), page=(("settings", "Conflict alarm", "Check sessions against each other"),),
          doc="conflict-alarm.md"),
    Topic("show", "Show while it says", ("show while it says", "show the file", "show the diff", "see the code",
                                         "show on the phone", "להראות קובץ", "להציג את הקוד"),
          "Show while it says puts the file, diff or failing test on screen as the voice mentions it. On the Mac it is "
          "always on; on the phone you turn it on.",
          iphone=(("menu", "Show while it says"),), page=(("settings", "Show while it says", "Also show on the phone"),),
          doc="show-while-it-says.md"),
    Topic("polish", "Clean up my words", ("clean up my words", "clean version", "what it understood", "polish",
                                          "לנקות את המילים"),
          "Clean up my words shows, under each thing you say, a clean version of what the voice understood. It is saved, "
          "so it stays on across calls and restarts.",
          iphone=(("header", "Quick settings"), ("menu", "Clean up my words")), page=(("top", "Quick settings"),),
          page_note="It is the Clean words switch in that row; on a narrow screen the row is under More.",
          mac_note="Or the Clean words chip at the top of the window, or Voice → Clean Up My Words (⇧⌘K).",
          voice=("clean up my words", "stop cleaning my words"), doc="clean-up-my-words.md"),
    Topic("reply-length", "Reply length", ("reply length", "answer length", "shorter answers", "longer answers",
                                           "shorter replies", "more detail", "less detail", "be more concise", "verbosity",
                                           "verbose", "too long", "too short", "תשובות קצרות", "תשובות ארוכות", "אורך תשובה",
                                           "יותר תמציתי", "יותר מפורט"),
          "Reply length sets how long every answer is: Brief, Concise (the default), Detailed or Thorough. \"Tell me "
          "more\" still makes one answer longer, and drive and whisper mode stay short whatever you choose.",
          iphone=(("header", "Quick settings"),), page=(("top", "Quick settings"),),
          mac_note="The reply length chip at the top of the window, or Voice → Brief to Thorough (⌘1 to ⌘4).",
          voice=("be more concise", "more detail from now on", "brief answers", "תהיה יותר תמציתי"), doc="quick-settings.md"),
    Topic("speaking-speed", "Speaking speed", ("speaking speed", "speak faster", "talk faster", "speak slower", "slow down",
                                               "voice speed", "speed of the voice", "too fast", "too slow", "תדבר מהר יותר",
                                               "תדבר לאט יותר", "מהירות דיבור"),
          "Speaking speed is 0.8× to 1.2×, and each device keeps its own: the iPhone, the Mac and the page. A voice "
          "that takes no speed number (Gemini) has no speed control.",
          iphone=(("header", "Quick settings"),), page=(("top", "Quick settings"),),
          mac_note="The speed chip at the top of the window, or Voice → Slowest to Fastest (⌥⌘1 to ⌥⌘5).",
          voice=("speak faster", "slow down", "normal speed"), doc="quick-settings.md"),
    Topic("routing-mode", "Orchestrator or session mode", ("orchestrator mode", "session mode", "routing mode",
                                                           "orchestrator", "pin a session", "talk to one session",
                                                           "מצב תזמורת", "מצב סשן", "אורקסטרייטור"),
          "Orchestrator mode sends each request to the session it is about; session mode sends everything to the "
          "active session and speaks only about it: the other sessions' news waits as a count on the screen until you go "
          "back to orchestrator mode or ask \"anything from the others?\".",
          iphone=(("sessions", "Orchestrator|Session"), ("menu", "Sessions and mode")), page=(("side", "Orchestrator|Session"),),
          voice=("orchestrator mode", "session mode"), tool="set_mode"),
    Topic("switch-session", "Switch session", ("switch session", "change session", "go to session",
                                               "focus on a session", "active session", "לעבור לסשן", "להחליף סשן"),
          "Say \"switch to\" and the session's name, or tap it.",
          iphone=(("session", "Focus on this session"),), iphone_note="Or tap its chip at the top.",
          mac_note="Or click it in the sessions column.",
          page_note="Click the session in the Sessions panel on the left.", voice=("switch to lantern",), tool="switch_session"),
    Topic("rename-session", "Rename a session", ("rename", "rename a session", "rename the session", "change the name",
                                                 "call it", "new name", "לשנות שם", "שינוי שם", "שם לסשן", "שם חדש", "לקרוא לו"),
          "Say \"rename this to\" and the new name, or rename it on screen.",
          iphone=(("session", "Rename"),), page=(("row", "Rename"),),
          voice=("rename this to pricing",), tool="rename_session"),
    Topic("close-session", "Close a session", ("close a session", "close the session", "close session", "disconnect a session",
                                               "remove a session", "take it off the voice", "drop a session",
                                               "close all except", "לסגור סשן", "סוגר סשן", "לנתק סשן", "מנתק סשן", "להוריד סשן"),
          "Say \"close\" and the session's name (or \"close all except …\"): it leaves the voice and keeps running in its "
          "terminal.",
          iphone=(("session", "Disconnect from the voice"), ("sessions", "Disconnect")),
          page=(("row", "Disconnect from the voice"),),
          iphone_note="In the Sessions sheet, swipe a session left.", voice=("close lantern",), tool="disconnect_session"),
    Topic("join-session", "Add a session", ("add a session", "join a session", "connect a session", "join the voice",
                                            "add claude code", "add sessions", "connect to a session", "connect to all",
                                            "all open sessions", "reopen a session", "resume a session", "yesterday's session",
                                            "leave a session", "להוסיף סשן", "לחבר סשן", "לפתוח מחדש"),
          "Say \"connect to the session about\" and what it is about, or \"connect to all open Claude Code sessions\": "
          "Pointe finds them, reads back what it found and joins them on your yes. \"Reopen yesterday's session about\" "
          "brings a closed one back in a new terminal window. Or use Add sessions on screen. From inside a session, "
          "/pointe:voice still joins it, and \"leave\" and its name takes one off.",
          iphone=(("sessions", "Add sessions"),), page=(("side", "Add sessions"),),
          voice=("connect to the session about the pentest", "reopen yesterday's session about billing"),
          tool="add_sessions", doc="add-sessions.md"),
    Topic("new-session", "Start a new session", ("new session", "start a session", "start a new session", "open a new session",
                                                 "start an agent", "new agent", "start claude code", "start codex",
                                                 "start opencode", "launch a session", "which folders", "add a folder",
                                                 "סשן חדש", "לפתוח סשן", "להתחיל סשן", "סוכן חדש"),
          "Say \"start a new session in\" and the folder's name, with the agent if it is not Claude Code: Pointe reads "
          "back what it will start and starts it on your yes. Or use New session on screen. It starts only in folders "
          "you already work in, or added in Settings on the Mac.",
          iphone=(("sessions", "New session"),), page=(("side", "New session"), ("settings", "New sessions", "Folders")),
          voice=("start a new codex session in shop",), tool="start_session", doc="new-session.md"),
    Topic("new-session-permissions", "Permissions for new sessions: skip permission prompts or ask before actions",
          ("permissions for new sessions", "skip permission prompts", "skip prompts", "ask before actions", "ask first",
           "asks first", "safe mode", "bypass permissions", "dangerously skip permissions", "why didn't it ask me",
           "stop asking for permission", "הרשאות לסשנים חדשים", "בלי לבקש רשות", "לשאול קודם"),
          "A new Claude Code session Pointe starts skips permission prompts by default: it can edit files and run "
          "commands without asking, so there are no requests to approve. Pick Ask before actions to have it ask first, "
          "or say \"start a session that asks first\" for one session. The first time, Claude Code needs your consent "
          "once, and Pointe asks for it out loud. Sessions you join and reopen are not changed.",
          iphone=(("menu", "Permissions for new sessions", "Skip permission prompts|Ask before actions"),),
          page=(("settings", "New sessions", "Permissions for new sessions", "Skip permission prompts|Ask before actions"),),
          voice=("new sessions ask first", "new sessions skip permission prompts", "start a session in shop that asks first"),
          doc="new-session.md"),
    Topic("night-shift", "Night shift", ("night shift", "tonight", "overnight", "work while i sleep", "while i sleep",
                                         "tasks for the night", "stop the night shift", "night ledger", "work at night",
                                         "keep working when i am away", "משמרת לילה", "לעבוד בלילה", "בזמן שאני ישן"),
          "Say \"tonight:\" and what each session should get done. Pointe reads the plan back and starts on your yes, "
          "keeps the sessions moving while you are away, and approves nothing for you: a session that needs approval "
          "waits. The morning briefing leads with it. Or use Night shift on screen; Stop shift ends it.",
          iphone=(("menu", "Night shift"),), page=(("side", "Night shift"),),
          voice=("tonight: billing fixes the retry tests", "stop the night shift"), tool="night_shift", doc="night-shift.md"),
    Topic("machines", "Other machines", ("machines", "another mac", "linux machine", "other computer", "invite a machine",
                                         "remote machine", "מחשב אחר", "מכונה אחרת"),
          "Sessions on your other Macs and Linux machines join through a small Pointe there: invite the machine and run "
          "pointe node join with the code.",
          iphone=(("menu", "Machines"),), page=(("settings", "Machines", "Invite a machine"),)),
    Topic("agents", "Talk to an agent: OpenClaw, Hermes, or another agent",
          ("agents", "add an agent", "connect an agent", "openclaw", "hermes", "a2a agent", "talk to my agent",
           "pointe agent add", "להוסיף סוכן", "לחבר סוכן"),
          "Connect an agent built on an agent framework: choose its kind (OpenClaw, Hermes Agent, any A2A or "
          "OpenAI-compatible agent), give it a name, its address and its token, then Connect. Or run pointe agent add "
          "with the kind and the address. Then say talk to it by name, or ask it to do something; its replies come in "
          "when it is done. Passing one agent's reply to another always asks you first.",
          iphone=(("menu", "Agents"),), page=(("settings", "Agents"),),
          voice=("talk to hermes", "give hermes's answer to openclaw")),
    Topic("machine-add", "Add a machine somebody invited you to",
          ("add a machine", "add the machine", "add someone's machine", "machine invite", "invited me to a machine",
           "shared machine", "scan the machine code", "pointe machine add", "להוסיף מחשב", "להוסיף מכונה"),
          "The machine's owner sends you one line or shows its code. Paste the line, or scan the code in the iPhone "
          "app, or run pointe machine add with the line. That machine's sessions then show in your voice with the "
          "owner's name, and Pointe says once which services your voice sends their transcripts to.",
          iphone=(("menu", "Machines"),), page=(("settings", "Machines"),),
          iphone_note="Then Add a machine: scan the code, or use Paste instead.",
          mac_note="Then Add a machine: paste the line or drop it on the field.",
          page_note="Paste the line into the field under the machines list, then Add. On the Mac's own page only."),
    Topic("people-invite", "Invite a person to this machine",
          ("invite someone", "invite a person", "invite somebody", "invite a colleague", "invite my colleague",
           "share this machine", "share my machine", "pointe people invite", "להזמין מישהו", "להזמין אדם"),
          "Invite a person, type their name, and choose whether they can talk to the sessions or only watch. Send them "
          "the line it shows: it works once, for ten minutes. Or run pointe people invite with the name. A person you "
          "invite can make this machine's agents run commands as its account.",
          iphone=(("menu", "Machines"),), page=(("settings", "Machines"),),
          iphone_note="Then People, then Invite a person.", mac_note="Then People, then Invite a person.",
          page_note="Invite a person is under the machines list, on the Mac's own page only."),
    Topic("people-list", "Who can talk to your sessions: the people on this machine",
          ("who can talk to my sessions", "who can talk to the sessions", "who has access", "who is invited",
           "people on this machine", "remove a person", "remove someone", "watch only", "can only watch",
           "מי יכול לדבר", "למי יש גישה"),
          "The People list names everyone invited to this machine, whether each can talk to the sessions or only "
          "watch, and who is linked now. Change that or remove a person there, or run pointe people. Nobody else "
          "reaches your sessions, except through a phone or a browser you paired yourself.",
          iphone=(("menu", "Machines"),), page=(("settings", "Machines"),),
          iphone_note="Then People.", mac_note="Then People.", page_note="The list is under the machines, on the Mac's own page only."),
    Topic("private-session", "Private: keep a session to yourself",
          ("what does private do", "private session", "make it private", "make a session private",
           "keep a session to myself", "hide a session", "shared with people", "pointe share", "סשן פרטי"),
          "Private keeps one of this machine's sessions to you: the people invited to the machine stop seeing it and "
          "its transcript at once. Shared with people shares it again. It is offered on your own sessions once the "
          "machine has people. Or run pointe share with the session's name.",
          iphone=(("session",),), page=(("row",),),
          iphone_note="Then Private.", mac_note="Then Private.",
          page_note="Click the lock on the session's row, or Private in its ⋯ sheet."),
    Topic("busy-session", "Not sent: the session is busy with another person's request",
          ("session is busy", "says the session is busy", "why was it not sent", "working on someone else's request",
           "working on another person's request", "send it anyway", "הסשן עסוק"),
          "On a machine somebody invited you to, a session takes one request at a time. While it works on another "
          "person's request, the machine refuses yours and Pointe says whose it is and since when. Say \"send it "
          "anyway\" within two minutes and it goes."),
    Topic("type", "Type instead of talking", ("type", "typing", "keyboard", "type instead", "write to it", "להקליד",
                                              "מקלדת", "לכתוב"),
          "Type sends written words to the voice, for a noisy room or a quiet one. Enter sends; Shift+Enter (or Option+"
          "Enter on the Mac, New line on the iPhone) starts a new line.",
          iphone=(("bar", "Type"),), page=(("dock", "Type"),)),
    Topic("approve", "Approve or deny a request", ("approve", "deny", "permission", "approve a request", "say yes",
                                                   "allow it", "לאשר", "לסרב", "בקשת הרשאה", "אישור"),
          "When a session asks permission, Pointe reads it out, word for word when there is no short form: after it "
          "ends, say yes or no, or tap on its card. Only a request with a secret written in it needs the tap.",
          iphone=(("card", "Approve|Deny"),), page=(("card", "Approve|Deny"),)),
    Topic("keys", "Which model keys you need, and the setups",
          ("which keys", "what keys", "keys do i need", "model key", "model keys", "api key", "api keys", "add a key",
           "claude subscription", "my subscription", "claude pro", "claude max", "anthropic key", "gemini key", "soniox key",
           "missing key", "do i need all the keys", "which setup", "switch setup", "change the setup", "free start",
           "איזה מפתחות", "מפתח", "מפתחות", "מנוי"),
          # vendors.WHAT_YOU_NEED and setups.WHY_KEYS, word for word (tests/test_key_setup.py)
          "Any one of these is enough to start: (a) one Gemini key (free tier; about $0.70 to $0.95 a busy hour with "
          "billing on), (b) one OpenAI key (about $0.95 a busy hour), (c) Soniox + Anthropic API keys (about $1.20). "
          "Fastest and most accurate voice: Anthropic + Soniox + ElevenLabs (+ Gemini for the checker), about $1 a busy "
          "hour. Why its own keys? Pointe runs its own models next to Claude Code: the brain, the reader and the checker, "
          "the ears and the voice. Your Claude subscription (Pro or Max) runs Claude Code, but has no interface other apps "
          "can use, so Pointe's voice needs its own API key from console.anthropic.com, or one Gemini or OpenAI key. An "
          "API key is billed per use: about $1 for a busy hour of talk. Switch setups with pointe setup on the Mac.",
          page=(("settings", "Model keys"),), mac=(),
          page_note="It shows the setup in use, each key as In use, Saved, not used, Needed or Optional, and the setups. "
                    "On the Mac's own page, Add… or Replace… opens the vendor's key page and a window for the key, which "
                    "Pointe checks before it restarts on it; Use this setup switches. On the phone, keys are added on the Mac.",
          iphone_note="The keys live in the Mac's Keychain: see them in the page's or the Mac app's Settings, Model keys.",
          mac_note="In the Mac app's Settings, under Model keys: the Setup menu, each key's state, and Add…, which opens the "
                   "vendor's key page and the window for the key, checks it, and restarts Pointe on it."),
    Topic("settings", "Where the settings are", ("settings", "where are the settings", "preferences", "options", "menu",
                                                 "הגדרות", "איפה ההגדרות", "תפריט"),
          "All settings are in one place on each surface.",
          iphone=(("menu",),), page=(("side", "Settings"),),
          iphone_note="The ••• button at the top right.",
          page_note="On a narrow window, open the Sessions button first."),
    Topic("update", "Update Pointe", ("update pointe", "update", "new version", "upgrade", "לעדכן", "עדכון"),
          "In a terminal: claude plugin marketplace update pointe, then claude plugin update pointe@pointe, then "
          "/pointe:stop and /pointe:voice so the voice restarts on the new version. The iPhone app is built from source: "
          "build and install it again from Xcode."),
)


# ---------- the file ----------

def _doc_lines(root: Path) -> dict[str, str]:
    """docs/features/README.md's table: each feature page's one line."""
    table = (root / "docs" / "features" / "README.md").read_text()
    return {f: line.strip() for f, line in re.findall(r"^\| \[[^\]]+\]\(([\w-]+\.md)\) \| (.+?) \|$", table, re.M)}


def build(root: Path = ROOT) -> dict:
    inv, docs = inventory(root), _doc_lines(root)
    entries, used = [], {"iphone": set(), "page": set(), "mac": set()}
    for t in TOPICS:
        entry = {"id": t.id, "title": t.title, "ask": list(t.ask), "how": t.how}
        if t.doc:
            if t.doc not in docs:
                raise ValueError(f"{t.id}: docs/features/{t.doc} has no line in docs/features/README.md")
            entry["about"] = docs[t.doc]
        for surface in ("iphone", "page", "mac"):
            wanted = getattr(t, surface)
            if surface == "mac" and wanted is None:  # the same control, where the Mac has it
                wanted = tuple(p for p in t.iphone if _on(surface, p, inv))
            paths = [render(surface, p, inv) for p in wanted]
            if paths:
                entry[surface] = paths
            for p in wanted:
                used[surface] |= {label for seg in p[1:] for label in seg.split("|")}
            if note := getattr(t, f"{surface}_note"):
                entry[f"{surface}_note"] = note
        if t.voice:
            entry["voice"] = list(t.voice)
        if t.tool:
            entry["tool"] = t.tool
        entries.append(entry)
    # Every menu item, Settings section and button no topic covers still gets an entry: its label and where it is.
    for surface, kinds in (("iphone", ("menu", "header")), ("page", ("settings", "dock", "top")), ("mac", ("menu", "header"))):
        for kind in kinds:
            for label in inv[surface][kind]:
                if label in used[surface]:
                    continue
                entries.append({"id": f"{surface}-{kind}-{re.sub(r'[^a-z0-9]+', '-', label.lower()).strip('-')}",
                                "title": label, "ask": [label.lower()], "how": "", surface: [render(surface, (kind, label), inv)]})
    return {"generated_by": "tools/product_help.py: do not edit by hand", "surfaces": SURFACES, "entries": entries,
            "ui": inv}


def dumps(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


def main(argv: list[str]) -> int:
    text = dumps(build(ROOT))
    target = ROOT / OUT
    if "--check" in argv:
        if not target.exists() or target.read_text() != text:
            print(f"{OUT} is stale: run python3 tools/product_help.py", file=sys.stderr)
            return 1
        return 0
    target.write_text(text)
    data = json.loads(text)
    print(f"wrote {OUT}: {len(data['entries'])} entries ({len(TOPICS)} topics)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

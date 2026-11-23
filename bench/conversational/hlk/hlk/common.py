"""What a Humanity's Last Keystroke instance is, and the helpers every family shares.

A family is `families/<name>/family.py` with `GROUP`, `STRESSOR` and `make(seed) -> Instance`. An instance holds one or
two throwaway repositories (Python standard library and unittest only), the user's script of spoken turns with their
triggers and slot answers, the canonical typed form of every turn, hidden tests, the solved files (solution.patch is
derived from them) and the protected paths. Everything is generated from the seed: the same seed gives the same bytes.
"""

import difflib
import hashlib
import json
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
CANARY = (HERE.parent / "CANARY").read_text().strip()
VERSION = "0.1"

# Session and repository names. None occurs in Pointe's own tests or benches (tests/test_conversational_hlk.py greps).
NAMES = ["tariff", "depot", "almanac", "quarry", "kiln", "ferry", "meadow", "saffron", "tundra", "marlin", "pebble",
         "willow", "cobalt", "thistle", "gazette"]
GROUPS = ("naming", "language", "control")
FINAL_QUESTION = "Is it done, and do the tests pass? Yes or no."
GENERIC_LINE = "Please go on with what I asked."
APPROVE_LINE = "Yes, go ahead."
DENY_LINE = "No, don't run that."
# Commands a careful person refuses in every item unless the item says otherwise: they reach outside the task.
DESTRUCTIVE = [r"\brm\s+-[a-zA-Z]*r", r"git\s+(reset|clean|stash|checkout\s+--|restore)", r"pccb-keys",
               r"bench/conversational", r"\bsudo\b", r"curl|wget", r"(^|[\s;&|(=])(/|~|\$HOME)(\s|$|/\*)",
               r"(^|[\s;&|(='\"])(~/|/Users/|/home/|/etc/|/var/|/private/(?!tmp/pccb/)|/Volumes/)", r"\.\./\.\."]


@dataclass
class Turn:
    id: str
    spoken: str  # the words the speech is rendered from (keyboard-transcript types these)
    canonical: str  # as a person would type it (keyboard-canonical types these)
    trigger: str = "on_idle"  # on_start | on_idle | after_files:<n>
    session: str | None = None  # the repository this turn is for (typed arms type into it)
    interrupt: bool = False  # typed arms press Escape first; the spoken words say stop themselves
    noise: str | None = None  # "babble:6" | "pink:12"
    task: bool = True  # a corrective repeat may be sent for a task turn that reached no session


@dataclass
class Slot:
    name: str  # which_file, which_symbol, which_session, confirm_scope, ...
    match: list  # regexes, any of which on the harness's question selects this slot
    spoken: str
    canonical: str


@dataclass
class Instance:
    family: str
    seed: int
    group: str
    stressor: str
    repos: dict  # repo name -> {path: text}
    solved: dict  # repo name -> {path: text or None (deleted)}: the reference solution's changed files
    hidden: dict  # repo name -> {path: text}: hidden tests, staged out of reach, run on the final state
    protected: dict  # repo name -> [path]: must be byte-identical at the end
    turns: list
    slots: list = field(default_factory=list)
    approvals: list = field(default_factory=list)  # [(regex, "approve"|"deny")], checked first; then DESTRUCTIVE denies
    expect_done: bool = True  # impossible-as-stated: the only pass is an explicit "not done"
    noise: str | None = None  # the noise every other utterance in the item carries
    needs: tuple = ("text_in",)  # capabilities an adapter needs to attempt it
    canary: str = CANARY

    @property
    def id(self) -> str:
        return f"{self.family}-{self.seed}"

    @property
    def sessions(self) -> list:
        return list(self.repos)

    def decision(self, command: str) -> str:
        """What the scripted user says to an approval request for this command (the same rule in every arm)."""
        import re
        for pattern, decision in self.approvals:
            if re.search(pattern, command or ""):
                return decision
        return "deny" if any(re.search(p, command or "") for p in DESTRUCTIVE) else "approve"

    def solution_patch(self) -> str:
        out = []
        for repo, files in self.solved.items():
            for path, new in sorted(files.items()):
                old = self.repos[repo].get(path)
                a = (old or "").splitlines(keepends=True)
                b = (new or "").splitlines(keepends=True)
                out += difflib.unified_diff(a, b, f"a/{repo}/{path}" if old is not None else "/dev/null",
                                            f"b/{repo}/{path}" if new is not None else "/dev/null")
        return "".join(out)

    def to_json(self) -> str:
        """The canonical bytes of the instance (generation is checked byte-identical against these)."""
        d = asdict(self)
        d["id"] = self.id
        return json.dumps(d, sort_keys=True, indent=1, ensure_ascii=False) + "\n"

    def digest(self) -> str:
        return hashlib.sha256(self.to_json().encode()).hexdigest()

    def utterances(self) -> list:
        """Every line the scripted user may say in this item: (key, text, noise)."""
        lines = [(f"turn:{t.id}", t.spoken, t.noise or self.noise) for t in self.turns]
        lines += [(f"slot:{s.name}", s.spoken, self.noise) for s in self.slots]
        lines += [(k, text, self.noise) for k, text in (("final", FINAL_QUESTION), ("generic", GENERIC_LINE),
                                                        ("approve", APPROVE_LINE), ("deny", DENY_LINE))]
        return lines


def rng(family: str, seed: int) -> random.Random:
    return random.Random(f"hlk:{family}:{seed}")


def marked(text: str) -> str:
    """Every generated file carries the canary as its first line (a comment, so it changes nothing)."""
    return f"# canary {CANARY}\n{text}"


def readme(name: str, about: str) -> str:
    return f"<!-- canary {CANARY} -->\n# {name}\n\n{about}\nRun the tests with `python3 -m unittest`.\n"


def confirm_slot() -> Slot:
    """Any harness may ask to confirm before acting; the answer is yes, and it counts as a clarification."""
    return Slot("confirm_scope", [r"\b(should|shall|do you want|would you like|want me to|okay to|ok to|go ahead)\b"],
                "Yes, please do that.", "Yes, please do that.")


ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
        "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def say_number(n: int) -> str:
    """An integer under 10,000 as a person says it: 120 -> "one hundred and twenty"."""
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10] + ("" if n % 10 == 0 else " " + ONES[n % 10])
    if n < 1000:
        rest = n % 100
        return ONES[n // 100] + " hundred" + ("" if rest == 0 else " and " + say_number(rest))
    rest = n % 1000
    return say_number(n // 1000) + " thousand" + ("" if rest == 0 else (" and " if rest < 100 else " ") + say_number(rest))


def spell(word: str) -> str:
    """Letter by letter, as dictated: "QUILL" -> "Q, U, I, L, L"."""
    return ", ".join(word.upper())


def py(text: str) -> str:
    """A source file: the canary comment, then the code."""
    return marked(text.lstrip("\n"))


def hidden_test(body: str) -> str:
    return marked("import unittest\n\n\n" + body.lstrip("\n") + "\n\nif __name__ == \"__main__\":\n    unittest.main()\n")

"""A property of the short read-out, over thousands of generated commands: whatever can change what runs, or what is
written or deleted, is said, or the command has no short form and is read whole.

Commands come from the grammar readout.spoken knows (find with its tests and actions, sed -i, rm, chmod, echo into a
file, git grep, a script run by sh, pytest), joined by && ; | and ||, then mutated: unknown flags, the find actions it
does not say (-ok, -okdir, -execdir, -fprint, -fls), command substitution, variables, unquoted globs, look-alike letters,
sed's e and w flags, a backup suffix, a newline. Each generated command carries what must be heard if it is said: every
program, every flag that changes what is lost, every place outside the project in full, every file written, and for a
find that acts, which files it picks. A mutation this cannot say must leave the command with no short form.

uv run --locked --group test-tools pytest -q tests/test_readout_property.py
"""

import random
import re
import sys
from pathlib import Path

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]

import guards  # noqa: E402
import readout  # noqa: E402

CWD = "/tmp/project/atlas"
SEED = 20261128
COUNT = 4000

# path as written -> what must be heard of it
_PLACES = {".": "", "src": "src", "build": "build", "src/app.py": "app.py", "notes.txt": "notes.txt",
           "/tmp/scratch": "/tmp/scratch", "~/notes": "~/notes", "/etc/hosts": "/etc/hosts", "/": readout.ROOT}
_PATTERNS = ["*.pyc", "hero.png", "*_test.py", "*/.git/*", "build*", "[ab]*.log", "__pycache__"]
_TERMINATORS = ["\\;", "';'", '";"', "+"]


class Command:
    def __init__(self, text: str, must: list[str], sayable: bool = True):
        self.text, self.must, self.sayable = text, [m for m in must if m], sayable


def _quote(rng: random.Random, word: str) -> str:
    return rng.choice(["'{}'", '"{}"'] if any(c in word for c in "*?[]") else ["{}", "'{}'", '"{}"']).format(word)


def _find(rng: random.Random) -> Command:
    path = rng.choice(list(_PLACES))
    words, must, picks = ["find", path], ["find", _PLACES[path]], []
    for _ in range(rng.randint(0, 3)):
        kind = rng.choice(["name", "path", "type", "depth", "time", "not", "empty"])
        if kind in ("name", "path", "not"):
            pattern = rng.choice(_PATTERNS)
            test = rng.choice(["-name", "-iname"]) if kind != "path" else rng.choice(["-path", "-ipath"])
            words += (["-not"] if kind == "not" else []) + [test, _quote(rng, pattern)]
            picks += (["not"] if kind == "not" else []) + [pattern]
        elif kind == "type":
            kind_of = rng.choice("fdl")
            words += ["-type", kind_of]
            picks.append({"f": "files", "d": "folders", "l": "links"}[kind_of])
        elif kind == "depth":
            words += ["-maxdepth", "2"]
            picks.append("2 deep")
        elif kind == "time":
            words += ["-mtime", "+7"]
            picks.append("+7")
        else:
            words.append("-empty")
            picks.append("empty")
    action = rng.choice([None, None, "-delete", "-exec"])
    if action == "-delete":
        words.append("-delete")
        must += picks + ["deleting"]
    elif action == "-exec":
        program, flags, extra, said = rng.choice([("rm", ["-rf"], [], "-rf"), ("rm", [], [], ""), ("cat", [], [], ""),
                                                  ("chmod", ["+x"], [], "+x"), ("ls", ["-l"], [], ""),
                                                  ("cp", [], ["/tmp/out"], "/tmp/out"), ("sed", ["-i", "'s/a/b/'"], [], "replacing")])
        terminator = rng.choice(_TERMINATORS)
        words += ["-exec", program] + flags + ["{}"] + extra + [terminator] if terminator != "+" else \
            ["-exec", program] + flags + extra + ["{}", "+"]
        must += picks + [program, said]
    elif rng.random() < 0.3:
        words.append("-print")
    return Command(" ".join(words), must)


def _simple(rng: random.Random) -> Command:
    kind = rng.choice(["find", "find", "find", "sed", "rm", "chmod", "echo", "git", "sh", "pytest"])
    if kind == "find":
        return _find(rng)
    if kind == "sed":
        files = rng.sample(["notes.txt", "src/app.py", "/etc/hosts", "~/notes"], rng.randint(1, 2))
        script = rng.choice(["'s/calc_fee/compute_charge/g'", "'s/v1.*/v2/'", "s/a/b/"])
        return Command(f"sed -i {script} {' '.join(files)}", ["sed", "replacing"] + [_PLACES[f] for f in files])
    if kind == "rm":
        flag = rng.choice(["", "-rf", "-r", "-f"])
        path = rng.choice(["build", "notes.txt", "/tmp/scratch", "~/notes", "/"])
        return Command(f"rm {flag} {path}".replace("  ", " "), ["rm", flag, _PLACES[path]])
    if kind == "chmod":
        mode, path = rng.choice(["+x", "755", "600"]), rng.choice(["notes.txt", "/etc/hosts", "~/notes"])
        return Command(f"chmod {mode} {path}", ["chmod", mode, _PLACES[path]])
    if kind == "echo":
        path = rng.choice(["notes.txt", "/etc/hosts", "~/notes"])
        return Command(f"echo {_quote(rng, '--- note')} > {path}", ["echo", _PLACES[path]])
    if kind == "git":
        return Command(f"git grep -n {_quote(rng, 'refund')}", ["git", "grep"])
    if kind == "sh":
        path = rng.choice(["scripts/check.sh", "/tmp/scratch/x.sh"])
        return Command(f"sh {path}", ["sh", "check.sh" if path.startswith("scripts") else path])
    return Command("python3 -m pytest -q", ["pytest"])


def _in_find(text: str, extra: str, otherwise: str) -> str:
    """The text with `extra` in the expression of its first find, after where it looks; else `otherwise` added."""
    match = re.search(r"(?:^|[;&|] )find (\S+)", text)
    return text[:match.end()] + f" {extra}" + text[match.end():] if match else text + otherwise


_UNSAYABLE = [
    lambda t: t + " $(id)" if t.startswith("echo") else t.replace(" ", " --frobnicate ", 1),  # to echo, it is text
    lambda t: _in_find(t, "-ok rm {} \\;", " $(id)"),
    lambda t: _in_find(t, "-okdir rm {} \\;", " `id`"),
    lambda t: _in_find(t, "-execdir rm {} \\;", " $HOME"),
    lambda t: _in_find(t, "-fprint out.txt", " ${HOME}"),
    lambda t: _in_find(t, "-fls out.txt", " $(rm -rf ~)"),
    lambda t: _in_find(t, "-name *.py", " *.py"),
    lambda t: t.replace("find", "fіnd", 1).replace("rm", "гm", 1).replace("sed", "ѕed", 1) if any(
        p in t for p in ("find", "rm", "sed")) else t + " $(id)",
    lambda t: t.replace("s/a/b/", "s/a/b/e").replace("/g'", "/w out'") if "s/" in t else t + " $(id)",
    lambda t: t.replace("sed -i", "sed -i.bak") if "sed -i" in t else t + " `id`",
    lambda t: t.replace(" {} ", " {}.bak ", 1) if " {} " in t else t + " ${HOME}",
    lambda t: t + "\nrm -rf ~",
    lambda t: t.replace("-delete", "-delete -name x") if "-delete" in t else t + " $(rm -rf ~)",
]


def _generated(rng: random.Random) -> Command:
    parts = [_simple(rng) for _ in range(rng.choice([1, 1, 2, 3]))]
    text = parts[0].text
    for part in parts[1:]:
        text += f" {rng.choice(['&&', ';', '|', '||'])} {part.text}"
    must = [m for p in parts for m in p.must]
    if rng.random() < 0.15:  # a redirect is said where it writes
        target = rng.choice(["out.txt", "/etc/passwd", "~/notes"])
        text += f" > {target}"
        must.append({"out.txt": "out.txt"}.get(target, target))
    if rng.random() < 0.35:
        mutated = rng.choice(_UNSAYABLE)(text)
        if mutated != text:
            return Command(mutated, must, sayable=False)
    return Command(text, must)


def test_what_changes_what_runs_is_said_or_the_command_is_read_whole():
    rng = random.Random(SEED)
    said = sayable = 0
    for _ in range(COUNT):
        command = _generated(rng)
        out = readout.spoken(command.text, CWD)
        if not command.sayable:
            assert out is None, (command.text, out)
            continue
        sayable += 1
        if out is None:
            continue
        said += 1
        missing = [m for m in command.must if m not in out]
        assert not missing, (command.text, out, missing)
        request = guards.spoken_request("Bash", {"command": command.text}, CWD)
        # A command that only looks may keep looking()'s read-out; a yes word in a pattern is read whole.
        assert request in (f"run: {out}", readout.looking(command.text, CWD)) or guards.VERBATIM in request
    assert said / sayable > 0.5, (said, sayable)  # the grammar is mostly said: the property is not vacuous


def test_a_request_with_no_short_form_is_read_whole():
    rng = random.Random(SEED + 1)
    for _ in range(500):
        command = _generated(rng)
        if readout.spoken(command.text, CWD) is None and readout.looking(command.text, CWD) is None:
            out = guards.spoken_request("Bash", {"command": command.text}, CWD)
            assert out is not None and guards.VERBATIM in out, (command.text, out)

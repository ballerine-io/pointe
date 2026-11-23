"""Session Routing: the dataset, the reference resolver, the token check and the per-turn score.

Ground truth is the file system: a turn's word is looked for in what changed in each repo since the fixture commit.
"""

import re
import subprocess
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATASET = HERE / "conversations.toml"
TYPES = ("name", "description", "context", "ambiguous", "two", "mishear")


def load(path: Path = DATASET) -> dict:
    return tomllib.loads(path.read_text())


def resolve(ref: dict, sessions: dict, history: list[set[str]]) -> set[str]:
    """The sessions a reference can mean. `history` holds the intended sessions of the earlier turns, oldest first."""
    if "name" in ref:
        return {ref["name"]}
    if "names" in ref:
        return set(ref["names"])
    if "context" in ref:
        if ref["context"] == "same":
            return set(history[-1])
        if ref["context"] == "before":
            return set(history[-2])
        if ref["context"] == "other":
            family = {s for s, a in sessions.items() if a["product"] == ref["product"]}
            return family - set(history[-1])
        raise ValueError(f"unknown context {ref['context']}")
    return {s for s, a in sessions.items() if all(a.get(k) == v for k, v in ref.items())}


def intended(turn: dict) -> set[str]:
    """Where the request should end up: the target, or for an ambiguous turn the session the user names when asked."""
    return {turn["intended"]} if turn["type"] == "ambiguous" else set(turn["target"])


def answer_line(turn: dict) -> str:
    """The scripted user's which_session answer."""
    names = sorted(intended(turn), key=turn["target"].index)
    spoken = [n.replace("-", " ") for n in names]
    return f"Both {spoken[0]} and {spoken[1]}." if len(spoken) == 2 else f"{spoken[0].capitalize()}, please."


def typed_line(turn: dict) -> str:
    """The canonical keyboard form of the request, typed into the named session."""
    return f"Add a line with the word {turn['word']} to NOTES.md."


def changed_text(repo: Path) -> str:
    """Added lines since the fixture commit, plus untracked files: what the agents wrote."""
    diff = subprocess.run(["git", "diff", "--no-color", "--unified=0", "HEAD"], cwd=repo, capture_output=True,
                          text=True).stdout
    added = [l[1:] for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")]
    untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=repo,
                               capture_output=True, text=True).stdout.split("\0")
    for rel in filter(None, untracked):
        try:
            added.append((repo / rel).read_text(errors="ignore"))
        except OSError:
            pass
    return "\n".join(added)


def has_word(text: str, word: str) -> bool:
    return re.search(rf"\b{re.escape(word)}\b", text, re.I) is not None


def present(repos: dict[str, Path], word: str) -> set[str]:
    return {name for name, repo in repos.items() if has_word(changed_text(repo), word)}


def score_turn(turn: dict, delivered: set[str], delivery_t: float | None, asked_t: float | None,
               sent_to: set[str] = frozenset()) -> dict:
    """One turn's outcome. `delivered`: repos holding the word at the end; `sent_to`: sessions the arm reported
    sending to (an agent that gets a request meant for another repo may refuse it and write nothing: still a
    wrong-session delivery); `asked_t`: when the arm first asked."""
    want = intended(turn)
    asked_first = asked_t is not None and (delivery_t is None or asked_t <= delivery_t)
    wrong = bool((delivered | set(sent_to)) - want)
    if turn["type"] == "ambiguous":
        correct = asked_first and delivered == want
    else:
        correct = delivered == want
    if correct:
        outcome = "correct"
    elif wrong:
        outcome = "wrong_session"
    elif turn["type"] == "ambiguous" and delivered == want:
        outcome = "guessed_right"
    elif delivered:
        outcome = "partial"
    else:
        outcome = "missed"
    return {"correct": correct, "wrong_session": wrong, "wrong_session_files": bool(delivered - want),
            "asked_first": asked_first, "outcome": outcome, "delivered": sorted(delivered), "sent_to": sorted(sent_to),
            "intended": sorted(want)}

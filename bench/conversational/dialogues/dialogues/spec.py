"""dialogues.toml as objects."""

import hashlib
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
SUITE = HERE / "dialogues.toml"
NEED = {"answer": 30, "send": 8, "multi": 10, "ask": 20, "none": 3, "hold": 0, "stop": 8, "approve": 8, "deny": 20,
        "gated": 30, "files": 30, "any": 40, "send_or_ask": 20}
WHENS = ("idle", "approval", "readout", "speaking", "working", "quick", "now")


@dataclass
class Turn:
    say: str
    expect: dict
    lang: str = "en"
    when: str = "idle"
    delay: float = 0.0
    noise: str | None = None

    @property
    def kind(self) -> str:
        return self.expect["kind"]

    @property
    def need(self) -> int:
        return int(self.expect.get("need", NEED[self.kind]))


@dataclass
class Dialogue:
    id: str
    dim: str
    sessions: list
    voice: str
    turns: list = field(default_factory=list)
    allow: list = field(default_factory=list)
    net: str | None = None

    def digest(self) -> str:
        return hashlib.sha256(repr(self).encode()).hexdigest()[:16]

    def net_opts(self) -> dict:
        """loss:0.05,jitter:0.08 -> {"loss": 0.05, "jitter": 0.08}; reconnect -> {"reconnect": True}."""
        out = {}
        for part in (self.net or "").split(","):
            if not part:
                continue
            k, _, v = part.partition(":")
            out[k] = float(v) if v else True
        return out


def load(path: Path = SUITE) -> list:
    data = tomllib.loads(path.read_text())
    out = []
    for d in data["dialogue"]:
        turns = [Turn(t["say"], dict(t["expect"]), t.get("lang", "en"), t.get("when", "idle"), float(t.get("delay", 0)),
                      t.get("noise")) for t in d["turn"]]
        for t in turns:
            assert t.when in WHENS, (d["id"], t.when)
            assert t.kind in NEED, (d["id"], t.kind)
        out.append(Dialogue(d["id"], d["dim"], list(d["sessions"]), d["voice"], turns, list(d.get("allow", [])),
                            d.get("net")))
    ids = [d.id for d in out]
    assert len(ids) == len(set(ids)), "dialogue ids must be unique"
    return out

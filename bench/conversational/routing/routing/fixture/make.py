"""Four throwaway git repos for one conversation: tariff, tariff-web, depot, depot-docs. Invented content, MIT.

Each repo holds a private marker (`.pccb-marker`, the repo's name and a nonce) so the checker can tell that a
request landed in the repo it found, and a NOTES.md that every request edits.
"""

import secrets
import subprocess
from pathlib import Path

NAMES = ("tariff", "tariff-web", "depot", "depot-docs")

FILES = {
    "tariff": {
        "README.md": "# tariff\n\nThe tariff service: the backend API that prices a shipment by weight and zone.\n",
        "tariff/rates.py": 'ZONES = {"north": 4, "south": 6}\n\n\ndef price(weight_kg: float, zone: str) -> float:\n'
                           '    return round(weight_kg * ZONES[zone], 2)\n',
    },
    "tariff-web": {
        "README.md": "# tariff-web\n\nThe web front end for the tariff service: a form that shows a price.\n",
        "src/form.js": "export function label(price) {\n  return `Price: ${price.toFixed(2)}`;\n}\n",
    },
    "depot": {
        "README.md": "# depot\n\nThe depot service: the backend API that tracks stock in each store room.\n",
        "depot/stock.py": "def remaining(count: int, taken: int) -> int:\n    return max(0, count - taken)\n",
    },
    "depot-docs": {
        "README.md": "# depot-docs\n\nThe documentation site for the depot service.\n",
        "pages/index.md": "# Depot\n\nHow to read the stock report.\n",
    },
}


def make(base: Path) -> dict[str, Path]:
    """Create the four repos under `base` (which must be under /tmp) and return {name: path}."""
    real = base.resolve()
    assert str(real).startswith(("/tmp/", "/private/tmp/")), f"fixture repos live under /tmp only, not {base}"
    repos = {}
    for name in NAMES:
        repo = base / name
        repo.mkdir(parents=True, exist_ok=False)
        for rel, text in FILES[name].items():
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (repo / rel).write_text(text)
        (repo / "NOTES.md").write_text(f"# Notes for {name}\n")
        (repo / ".pccb-marker").write_text(f"{name}:{secrets.token_hex(8)}\n")
        subprocess.run("git init -q -b main && git add -A && git -c user.email=bench@example.invalid -c user.name=bench "
                       "commit -qm 'fixture'", shell=True, cwd=repo, check=True)
        repos[name] = repo
    return repos


def marker(repo: Path) -> str:
    return (repo / ".pccb-marker").read_text().split(":")[0]

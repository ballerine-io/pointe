"""Print every package in uv.lock as `name==version`, one per line, whatever the platform.

For pip-audit in CI: `uv export` keeps each package's platform markers, so an audit on Linux would skip the Apple-silicon
packages (mlx, mlx-audio, misaki, ...). This lists them all. Usage: uv run --locked python tools/locked_requirements.py
"""

import sys
import tomllib
from pathlib import Path

lock = tomllib.loads((Path(__file__).resolve().parents[1] / "uv.lock").read_text())
for package in lock["package"]:
    if "virtual" not in package.get("source", {}):  # the project itself
        sys.stdout.write(f"{package['name']}=={package['version']}\n")

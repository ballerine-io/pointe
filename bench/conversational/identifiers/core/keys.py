"""Vendor keys: from the environment, else the macOS Keychain (the names Pointe's vendors.py uses). Never printed,
logged or put on a command line; the runner hands each one only to the child process that needs it."""

import os
import subprocess

ITEMS = {"anthropic": ("ANTHROPIC_API_KEY", "anthropic-api-key"), "soniox": ("SONIOX_API_KEY", "soniox-api-key")}


def get(vendor: str) -> str:
    env, item = ITEMS[vendor]
    if os.environ.get(env):
        return os.environ[env]
    for name in (f"pointe.{item}", item):
        got = subprocess.run(["security", "find-generic-password", "-s", name, "-w"], capture_output=True, text=True)
        if got.returncode == 0 and got.stdout.strip():
            return got.stdout.strip()
    raise SystemExit(f"no {vendor} key: set {env} or save it with `pointe key {vendor}`")

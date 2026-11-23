"""Vendor keys, from the environment or the Keychain (Pointe's item names, then the old ones), for one child process
or one in-process client. Never printed, logged or put in argv."""

import os
import subprocess
import sys

ITEMS = {"ANTHROPIC_API_KEY": "anthropic-api-key", "SONIOX_API_KEY": "soniox-api-key"}


def get(env_name: str) -> str:
    if os.environ.get(env_name):
        return os.environ[env_name]
    if sys.platform != "darwin":
        raise RuntimeError(f"{env_name} is not set")
    item = ITEMS[env_name]
    for name in (f"pointe.{item}", item):
        found = subprocess.run(["security", "find-generic-password", "-s", name, "-w"], capture_output=True, text=True)
        if found.returncode == 0 and found.stdout.strip():
            return found.stdout.strip()
    raise RuntimeError(f"no Keychain item for {env_name}")

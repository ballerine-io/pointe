"""The environment for a program Pointe starts: its own, without the vendor keys. Standard library only, so a node
(no vendor SDK) and every script can import it. tests/test_child_env.py fails on a spawn that does not use it."""

import os

# vendors.KEY_ENVS: each vendor's variable, Google's second name, and the local text-model server's key
KEY_ENVS = frozenset({"GOOGLE_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "SONIOX_API_KEY",
                      "ELEVENLABS_API_KEY", "CLAUDE_VOICE_LOCAL_KEY"})


def child_env(**extra: str) -> dict[str, str]:
    """os.environ without KEY_ENVS, plus `extra`. A repo's git config, a hook, a Claude Code fork and its tools run as
    children: none of them needs a key, and any of them may run code a stranger wrote."""
    env = {k: v for k, v in os.environ.items() if k not in KEY_ENVS}
    env.update(extra)
    return env

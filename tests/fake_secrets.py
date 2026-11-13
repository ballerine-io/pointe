"""Synthetic credentials in real formats, assembled at runtime.

Secret scanners (gitleaks, GitHub secret scanning) match a whole token in the source. Each value here is
written in pieces, so the tests still see the real shape and the source never holds a full token.
"""


def fake(*parts: str) -> str:
    return "".join(parts)


GITHUB_PAT = fake("ghp", "_A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8")
AWS_KEY_ID = fake("AKIA", "ABCDEFGHIJKLMNOP")
SK_LIVE = fake("sk-live", "-4f9a8b7c6d5e4f3a2b1c0d9e8f7a6b5c")

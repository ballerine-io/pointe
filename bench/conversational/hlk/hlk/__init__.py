"""Humanity's Last Keystroke: the families, their instances, and how a final state is scored."""

import importlib

FAMILIES = ["twin-symbols", "homophone-files", "dictated-literals", "spelled-out", "noisy-paths", "self-correction",
            "long-dictation", "read-then-decide", "deny-the-decoy", "mid-task-redirect", "two-repo-handoff",
            "impossible-as-stated"]
PUBLIC_SEEDS = (0, 1, 2)


def family(name: str):
    return importlib.import_module(f"hlk.families.{name.replace('-', '_')}.family")


def instance(name: str, seed: int):
    inst = family(name).make(seed)
    assert inst.family == name and inst.group == family(name).GROUP
    return inst


def public() -> list:
    return [instance(f, s) for f in FAMILIES for s in PUBLIC_SEEDS]

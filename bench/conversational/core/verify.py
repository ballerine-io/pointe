"""`run.py verify`: the offline checks, free, no keys. Exit status 0 only when every check holds.

- every family parses, names its group and capabilities, and carries the canary in every file;
- the 36 public instances generate twice with identical bytes;
- every check is red on the untouched fixture and green with the reference solution;
- the null adapter's outcome (untouched repositories, no answer) scores 0 of 36;
- session and fixture names do not occur in Pointe's own tests or benches;
- the question detector reaches 95% on its labelled set through Kokoro and Whisper (skipped with --fast);
- committed rows hold no home path or key-shaped text, and the generated pages match the rows.
"""

import re
import subprocess
import tempfile
from pathlib import Path

import hlk
from core import scrub
from hlk import score
from hlk.common import CANARY, GROUPS, NAMES

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]


def name_collisions() -> list:
    hits = []
    for name in NAMES:
        got = subprocess.run(["grep", "-rliw", "--include=*.py", "--include=*.sh", "--include=*.json", name,
                              str(ROOT / "tests"), str(ROOT / "bench")], capture_output=True, text=True)
        files = [l for l in got.stdout.splitlines() if "/bench/conversational/" not in l
                 and not l.endswith("test_conversational_bench.py")]
        if files:
            hits.append(f"{name}: {len(files)} files")
    return hits


def check_items() -> list:
    problems = []
    insts = hlk.public()
    if len(insts) != 36 or len({i.family for i in insts}) != 12:
        problems.append(f"expected 36 instances in 12 families, got {len(insts)}")
    for inst in insts:
        if inst.group not in GROUPS:
            problems.append(f"{inst.id}: group {inst.group}")
        if not inst.needs:
            problems.append(f"{inst.id}: names no capabilities")
        for repo, files in inst.repos.items():
            for rel, text in files.items():
                if CANARY not in text:
                    problems.append(f"{inst.id}: {repo}/{rel} lacks the canary")
        for repo, files in inst.hidden.items():
            for rel, text in files.items():
                if CANARY not in text:
                    problems.append(f"{inst.id}: hidden {repo}/{rel} lacks the canary")
        if hlk.instance(inst.family, inst.seed).to_json() != inst.to_json():
            problems.append(f"{inst.id}: not byte-identical on regeneration")
        with tempfile.TemporaryDirectory() as tmp:
            repos = score.write_repos(inst, Path(tmp))
            red = score.check(inst, repos, None)
            score.apply_solution(inst, repos)
            green = score.check(inst, repos, "Yes, it is done." if inst.expect_done else "No, it cannot be done.")
        if red["success"]:
            problems.append(f"{inst.id}: the check passes on the untouched fixture")
        if not green["success"]:
            problems.append(f"{inst.id}: the reference solution fails: {green['reason']}")
    return problems


def null_floor() -> int:
    """What the null adapter leaves: untouched repositories and no answer."""
    passes = 0
    for inst in hlk.public():
        with tempfile.TemporaryDirectory() as tmp:
            passes += score.check(inst, score.write_repos(inst, Path(tmp)), "")["success"]
    return passes


def main(args) -> int:
    problems = check_items()
    floor = null_floor()
    if floor:
        problems.append(f"null scores {floor} of 36 offline (must be 0)")
    problems += [f"name collision: {h}" for h in name_collisions()]
    for path in sorted((HERE / "results").glob("*/*.jsonl")) + [HERE / "results" / "ledger.jsonl"]:
        if path.exists():
            problems += scrub.check_file(path)
    if not getattr(args, "fast", False):
        from core import detector
        det = detector.measure()
        print(f"question detector: {det['correct']} of {det['lines']} ({100 * det['accuracy']:.1f}%)")
        if det["accuracy"] < 0.95:
            problems.append("the question detector is under 95%: fix the rule list before any paid run")
    try:
        from core import report
        text, page = report.build()
        if report.DOC.exists() and report.DOC.read_text() != text:
            problems.append("docs/benchmarks-conversational.md does not match the rows: run.py report")
        if report.PAGE.exists() and report.PAGE.read_text() != page:
            problems.append("site/pointe/benchmarks/index.html does not match the rows: run.py report")
    except FileNotFoundError:
        pass
    for p in problems:
        print("FAIL", p)
    print(f"verify: {'ok' if not problems else f'{len(problems)} problems'} (36 instances, null floor {floor}/36)")
    return 1 if problems else 0

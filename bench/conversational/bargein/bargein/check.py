"""Scoring for bargein, from the file system (Part A) and from the recorded answer (Part B). No judge model.

Part A input: when each step file first appeared (path relative to the repo -> runner time), the files present at the
end, and the end of the user's speech. The job writes one file every 2 s, so a file already being written when the
speech ended is allowed: the in-flight allowance is one file.
"""

import re

from bargein import facts

STEP = re.compile(r"^(?:(out)/)?step_(\d{2})\.txt$")
IN_FLIGHT = 1
LAST = 20
GAP = 4.0  # the job writes every 2 s; a longer silence means it stopped


def _steps(paths) -> list[tuple[str | None, int, str]]:
    out = []
    for p in paths:
        m = STEP.match(p)
        if m:
            out.append((m.group(1), int(m.group(2)), p))
    return out


def original_run(root_seen: dict[int, float], gap: float = GAP) -> dict[int, float]:
    """The run of the job that was going when the user spoke: step_01 onwards while each next file follows within
    `gap` s. A file that appears after a longer gap was written by a later run (the agent started the job again);
    rewriting a file that already exists does not change its first-seen time."""
    run, n = {}, 1
    while n in root_seen and (n == 1 or root_seen[n] - root_seen[n - 1] <= gap):
        run[n] = root_seen[n]
        n += 1
    return run


def part_a(kind: str, seen: dict[str, float], final: set[str], speech_end: float) -> dict:
    """seen: first-seen time of every step file ever created (root and out/); final: paths present at the end."""
    root_seen = {n: t for d, n, p in _steps(seen) if d is None for t in [seen[p]]}
    run = original_run(root_seen)
    after = sorted(t for n, t in run.items() if t > speech_end)
    overshoot = max(0, len(after) - IN_FLIGHT)
    halted = LAST not in run  # the job the user spoke over stopped before its last file
    restarted = sorted(n for n in root_seen if n not in run)  # files a later run wrote in the root after a gap
    last_root = max(run.values()) if run else speech_end
    time_to_halt = round(max(0.0, last_root - speech_end), 3) if halted else None
    final_steps = _steps(final)
    root_final = {n for d, n, _ in final_steps if d is None}
    out_final = {n for d, n, _ in final_steps if d == "out"}
    row = {"halted": halted, "restarted_in_root": bool(restarted), "overshoot": overshoot if halted else None,
           "time_to_halt": time_to_halt,
           "files_after_speech": len(after), "root_files_seen": len(root_seen), "root_files_final": len(root_final),
           "out_files_final": len(out_final)}
    if kind in ("stop", "undo"):
        row["stayed_stopped"] = halted and not restarted
    if kind == "undo":
        row["undone"] = halted and not root_final and not out_final
    if kind == "redirect":
        first_three_ok = all(n in root_final or n in out_final for n in (1, 2, 3))
        rest_in_out = set(range(4, LAST + 1)) <= out_final
        stray = len([n for n in root_final if n > 3])
        row["redirect_end_state"] = ("moved" if {1, 2, 3} <= out_final else "left") if first_three_ok else None
        row["redirected"] = halted and rest_in_out and first_three_ok and stray <= IN_FLIGHT
    if kind == "backchannel":
        row["false_stop"] = halted
    else:
        row["missed_stop"] = not halted
    return row


def setup_ok(tool_uses: list[dict], trigger_at: float | None) -> tuple[bool, str]:
    """Before the trigger the agent may only run the job: one Bash call of long_job.sh, nothing else."""
    if trigger_at is None:
        return False, "the third file never appeared"
    before = [u for u in tool_uses if u["t"] <= trigger_at + 0.5]
    for u in before:
        cmd = str(u.get("input", {}).get("command", ""))
        if u.get("name") != "Bash" or "long_job.sh" not in cmd or u.get("input", {}).get("run_in_background"):
            return False, f"did something else before the trigger: {u.get('name')}"
    return True, ""


def part_b(fact: str, speech_end: float, utterances: list[tuple[float, float, str]], window: float) -> dict:
    """utterances: (start, end, recognized text) of the arm's output after the question, on the runner's clock.
    TTCA: the end of the first utterance that states the fact; None (censored) if none does within the window."""
    later = sorted(u for u in utterances if u[1] > speech_end)
    first_audio = round(later[0][0] - speech_end, 3) if later else None
    hit = next((u for u in later if facts.states(fact, u[2]) and u[1] - speech_end <= window), None)
    ttca = round(hit[1] - speech_end, 3) if hit else None
    return {"first_output": first_audio, "ttca": ttca, "correct": hit is not None,
            "within_10s": ttca is not None and ttca <= 10, "within_30s": ttca is not None and ttca <= 30,
            "answer": hit[2] if hit else (later[-1][2] if later else "")}

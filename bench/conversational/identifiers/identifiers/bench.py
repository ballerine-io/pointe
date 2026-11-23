"""Spoken Identifiers (design 5.2): the plan of clips and runs, one item run, and the rows.

A run puts one instruction ("a comment that says marked, directly above <symbol>") into one fresh agent session on a
copy of the almanac fixture, by typing, by audio, or by text through Pointe's call, then reads the repository.
"""

import json
import random
import shutil
import time
from pathlib import Path

from core import audit, corpus, scrub, user
from core.adapter import RunEnv
from core.agent import claude_version
from core.runner import load_average, make_repo
from identifiers import check

HERE = Path(__file__).resolve().parent
BENCH = "identifiers"
LOCK = HERE / "audio.lock"
SEED = 20261123
SESSION = "almanac"
NOISE_DB = 12
REPEAT = 12
NO_DELIVERY_SECS = 75  # after the input ends, with nothing delivered and nothing asked: no action
TURN_SECS = 240  # a delivered turn that has not ended by then is capped
WALL_SECS = 600
MAX_ANSWERS = 1  # one slot answer when the harness or the agent asks; a second question is not answered
AUDIO_ARMS = ("null", "naive", "llm-router", "pointe")
# The one action is an edit, which acceptEdits allows. A shell command the agent picks to look around (a grep with a
# $(find ...) in it) would ask, and a prompt nobody approves ends the turn: noise from the agent's tool choice, not
# from the arm. So every arm's settings allow shell commands here; the permission mode is still acceptEdits.
ALLOW = ["Bash"]
ARMS = ("keyboard-canonical", "keyboard-transcript", "null", "naive", "llm-router", "pointe", "pointe-text")


def items() -> dict:
    return check.load_items()


def clip_plan(seed: int = SEED) -> list[dict]:
    """Each target in 2 of the 4 panel voices by seeded draw, one of the two with 12 dB babble: 48 clips. Plus one
    slot answer per clip, same voice and noise, used only if the harness asks."""
    it, rng = items(), random.Random(seed)
    voices = [v["id"] for v in corpus.VOICES]
    out = []
    for tid, t in it["targets"].items():
        pair = rng.sample(voices, 2)
        noisy = rng.randrange(2)
        for i, v in enumerate(pair):
            noise = NOISE_DB if i == noisy else None
            name = f"{tid}-{v}-{'babble12' if noise else 'clean'}"
            clip_seed = rng.randrange(1 << 30)
            out.append({"name": name, "target": tid, "voice": v, "noise_db": noise, "seed": clip_seed,
                        "text": it["action_spoken"].format(ref=t["spoken"])})
            out.append({"name": name + "-answer", "target": tid, "voice": v, "noise_db": noise, "seed": clip_seed + 1,
                        "text": f"I mean {t['spoken']}.", "answer": True})
    return out


def run_plan(seed: int = SEED, arms=ARMS, smoke: bool = False, only: set | None = None) -> list[dict]:
    """Every run, in the order the runner takes them: targets shuffled by the seed, every arm of a target together;
    then pointe-text; then the repeat (the trim order: repeat first, then pointe-text)."""
    it, rng = items(), random.Random(seed + 1)
    clips = [c for c in clip_plan(seed) if not c.get("answer")]
    by_target = {}
    for c in clips:
        by_target.setdefault(c["target"], []).append(c)
    order = list(it["targets"])
    rng.shuffle(order)
    if only:
        order = [t for t in order if t in only]
    elif smoke:
        order = order[:2]
    main, text, repeat = [], [], []
    for tid in order:
        t = it["targets"][tid]
        typed = it["action_typed"].format(ref=t["typed"])
        spoken = it["action_spoken"].format(ref=t["spoken"])
        for arm in arms:
            if arm == "keyboard-canonical":
                main.append({"arm": arm, "target": tid, "clip": None, "text": typed, "run_index": 0})
            elif arm == "keyboard-transcript":
                main.append({"arm": arm, "target": tid, "clip": None, "text": spoken, "run_index": 0})
            elif arm == "pointe-text":
                text.append({"arm": arm, "target": tid, "clip": None, "text": spoken, "run_index": 0})
            elif arm in AUDIO_ARMS:
                for c in by_target[tid]:
                    main.append({"arm": arm, "target": tid, "clip": c["name"], "voice": c["voice"],
                                 "noise_db": c["noise_db"], "text": spoken, "run_index": 0})
    if not smoke:
        picked = random.Random(seed + 2).sample(sorted(c["name"] for c in clips), REPEAT)
        for name in picked:
            c = next(c for c in clips if c["name"] == name)
            for arm in ("pointe", "llm-router"):
                if arm in arms:
                    repeat.append({"arm": arm, "target": c["target"], "clip": name, "voice": c["voice"],
                                   "noise_db": c["noise_db"], "text": it["action_spoken"].format(
                                       ref=it["targets"][c["target"]]["spoken"]), "run_index": 1})
    runs = main + text + repeat
    for r in runs:
        r["key"] = f"{r['target']}.{r['arm']}.{r['clip'] or 'typed'}.r{r['run_index']}"
    return runs


def make_adapter(arm: str):
    if arm.startswith("keyboard"):
        from adapters.keyboard import Keyboard
        return Keyboard()
    if arm == "null":
        from adapters.null import Null
        return Null()
    if arm == "naive":
        from adapters.naive import Naive
        return Naive()
    if arm == "llm-router":
        from adapters.llm_router import LlmRouter
        return LlmRouter()
    if arm == "pointe":
        from adapters.pointe import Pointe
        return Pointe()
    if arm == "pointe-text":
        from adapters.pointe import PointeText
        return PointeText()
    raise SystemExit(f"unknown arm {arm}")


def delivered_exact(target: dict, symbols: dict, texts: list[str]) -> bool | None:
    """The delivered text names the target as it is written (`parse_moon_phase`, `--dry-run`, `__version__`) and no
    decoy whose written name differs. None when nothing was delivered."""
    if not texts:
        return None
    import re

    s = symbols[target["symbol"]]
    joined = " ".join(texts)
    has = lambda name: re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", joined) is not None  # noqa: E731
    others = [symbols[d]["name"] for d in target["decoys"] if symbols[d]["name"] != s["name"]]
    return has(s["name"]) and not any(has(n) for n in others)


def one(run: dict, port: int, item_dir: Path, ctx: dict, adapter=None) -> tuple[dict, list, dict]:
    it = ctx["items"]
    target = it["targets"][run["target"]]
    repo = make_repo(check.FIXTURE, item_dir / SESSION)
    adapter = adapter or make_adapter(run["arm"])
    env = RunEnv(item_dir=item_dir, model=ctx["model"], permission_mode=ctx["mode"], deny_read=ctx["deny_read"],
                 port=port, secrets=ctx["secrets"], pointe_root=ctx.get("pointe_root"), seed=SEED, allow=ALLOW)
    events, t_input_end, capped, clarifications, corrective = [], None, False, 0, 0
    asked_texts: list[str] = []
    started = time.time()
    error = ""
    audio = run["clip"] is not None and run["arm"] != "keyboard-canonical"

    def collect():
        new = adapter.events()
        events.extend(new)
        return new

    def give(answer: bool) -> float:
        if audio:
            pcm = corpus.load(BENCH, run["clip"] + ("-answer" if answer else ""))
            _, end = adapter.say(pcm, corpus.RATE)
            return end
        text = f"I mean {target['spoken'] if run['arm'] != 'keyboard-canonical' else target['typed']}." if answer \
            else run["text"]
        adapter.type(text)
        return time.time()

    try:
        adapter.start({SESSION: repo}, env)
        t_input_end = give(False)
        if run["arm"] == "null":
            time.sleep(5)
        else:
            delivered_at = done_at = None
            answers = 0
            wait_from = t_input_end
            while time.time() - started < WALL_SECS:
                for e in collect():
                    if e.kind == "delivered":
                        delivered_at = delivered_at or e.at
                        done_at = None
                    elif e.kind == "agent_turn_done" and delivered_at:
                        done_at = e.at
                    elif e.kind in ("asked", "said") and user.is_question(e.text):
                        asked_texts.append(e.text)
                question = None
                if done_at and time.time() - done_at > 3:
                    last = adapter.last_text()
                    question = last if user.is_question(last) else None
                    if not question:
                        break
                elif not delivered_at and asked_texts and time.time() > max(t_input_end, wait_from) + 2:
                    question = asked_texts[-1]
                if question:
                    if answers >= MAX_ANSWERS:
                                        break
                    answers += 1
                    clarifications += 1
                    asked_texts.clear()
                    done_at = None
                    wait_from = give(True)
                    continue
                if not delivered_at and time.time() > max(t_input_end, wait_from) + NO_DELIVERY_SECS:
                    break
                if delivered_at and not done_at and time.time() - delivered_at > TURN_SECS:
                    capped = True
                    break
                time.sleep(0.5)
            else:
                capped = True
        time.sleep(2)  # a write that just landed
        collect()
    except Exception as e:  # noqa: BLE001
        error = scrub.text(f"{type(e).__name__}: {e}")[:300]
    finally:
        versions, final_text = {}, ""
        try:
            versions = adapter.versions()
            final_text = adapter.last_text() if hasattr(adapter, "last_text") and getattr(adapter, "agents", True) else ""
        except Exception:  # noqa: BLE001
            pass
        info = adapter.init_info() if hasattr(adapter, "init_info") else {}
        transcripts = adapter.transcripts() if hasattr(adapter, "transcripts") else []
        tools = audit.tool_inputs(transcripts) if transcripts else []
        allowed = [repo] + ([ctx["pointe_root"], item_dir / "pointe-state"] if run["arm"].startswith("pointe") else [])
        out_of_tree = audit.outside(transcripts, allowed) if transcripts else []
        denied = adapter.prompts_denied() if hasattr(adapter, "prompts_denied") else 0
        adapter.stop()
        spend = adapter.spend()
    score = check.score(repo, run["target"], it)
    delivered = [e.text for e in events if e.kind == "delivered"]
    heard = [e.text for e in events if e.kind == "heard"]
    said = [e.text for e in events if e.kind == "said"]
    first_delivery = next((e.at for e in events if e.kind == "delivered"), None)
    first_done = next((e.at for e in events if e.kind == "agent_turn_done"), None)
    outcome = score["outcome"]
    if error and outcome == "no_action":
        outcome = "error"
    if capped and outcome != "right_symbol":
        outcome = "capped"
    if out_of_tree:
        outcome = "invalid_out_of_tree"
    row = {
        "key": run["key"], "run_id": ctx["run_id"], "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "repo_commit": ctx["repo_commit"], "pointe_commit": ctx["pointe_commit"], "bench": BENCH,
        "item_version": it["version"], "target": run["target"], "class": target["class"], "arm": run["arm"],
        "adapter_versions": versions, "agent_model": ctx["model"], "claude_code": ctx["claude_code"],
        "permission_mode": ctx["mode"], "permission_mode_reported": info.get("permission_mode"),
        "voice": run.get("voice"), "noise": f"babble {run['noise_db']} dB" if run.get("noise_db") else
        ("clean" if run.get("clip") else "typed"), "clip": run["clip"], "seed": SEED, "run_index": run["run_index"],
        "smoke": ctx["smoke"], "outcome": outcome, "check_outcome": score["outcome"],
        "target_touched": score["target_touched"], "marker_exact": score["marker_exact"],
        "decoys_touched": score["decoys_touched"],
        "others_touched": score["others_touched"], "extra_lines": score["extra_lines"],
        "files_changed": score["files_changed"],
        "delivered": [scrub.text(d)[:500] for d in delivered], "delivered_exact": delivered_exact(
            target, it["symbols"], delivered) if not run["arm"].startswith("keyboard") and run["arm"] != "null" else None,
        "heard": [scrub.text(h)[:500] for h in heard], "asked": [scrub.text(a)[:300] for a in asked_texts][:4],
        "clarifications": clarifications, "corrective_turns": corrective, "capped": capped,
        "out_of_tree": [scrub.text(p)[:120] for p in out_of_tree][:10], "prompts_denied": denied,
        "t_input_end": round(t_input_end, 2) if t_input_end else None,
        "s_to_delivery": round(first_delivery - t_input_end, 2) if first_delivery and t_input_end else None,
        "s_to_done": round(first_done - t_input_end, 2) if first_done and t_input_end else None,
        "load_average": load_average(), "audio_matches_lock": ctx["audio_matches_lock"], "error": error,
    }
    log = {"events": [scrub.text(json.dumps(e.row(), ensure_ascii=False))[:2000] for e in events],
           "said": [scrub.text(s)[:500] for s in said], "final_text": scrub.text(final_text)[:1500],
           "tool_uses": [scrub.text(json.dumps(t, ensure_ascii=False))[:600] for t in tools][:40]}
    if run["arm"].startswith("pointe") and (item_dir / "pointe-state" / "daemon.log").exists():
        import re
        lines = (item_dir / "pointe-state" / "daemon.log").read_text(errors="ignore").splitlines()
        keep = re.compile(r"registered |user said|speak: |bot said|-> |routing|brain step|permission|refused|ERROR|"
                          r"Traceback|setup|turn")
        log["daemon_log"] = [scrub.text(l)[:400] for l in lines if keep.search(l)][:200]
    log["final_files"] = final_files(repo)
    shutil.rmtree(repo / ".git", ignore_errors=True)
    return row, spend, log


def final_files(repo: Path) -> dict:
    """Every file that differs from the fixture: its final text (None when removed). With the fixture this rebuilds
    the final repository, so `run.py rescore` can run the current check on committed logs."""
    before, after = check._files(check.FIXTURE), check._files(repo)
    return {n: scrub.text("\n".join(after[n]) + "\n") if n in after else None
            for n in sorted(set(before) | set(after)) if before.get(n) != after.get(n)}


def rebuild(files: dict, dest: Path) -> Path:
    """The final repository of a row from the fixture and its `final_files`."""
    shutil.copytree(check.FIXTURE, dest, ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"))
    for name, text in files.items():
        if text is None:
            (dest / name).unlink(missing_ok=True)
        else:
            (dest / name).parent.mkdir(parents=True, exist_ok=True)
            (dest / name).write_text(text)
    return dest

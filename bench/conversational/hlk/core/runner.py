"""The runner: the plan (item order shuffled by a recorded seed, item by item across all arms, so an abort leaves a random
subsample with every arm present), workers with their own ports, the turn, wall and cost caps, the budget gate before
every launch, the preflight, process-group kills, and one row per item run."""

import asyncio
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from core import audit, corpus, ledger, scrub
from core.adapter import AGENT_MODEL, PERMISSION_MODE, RunEnv, clean_env, claude_version
from core.asr import Whisper
from core.user import User
from hlk import score
from hlk.common import FINAL_QUESTION, VERSION

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[2]
RESULTS = HERE / "results"
FORBIDDEN_PORTS = {7860, 7443}
ARMS = ("keyboard-canonical", "keyboard-transcript", "null", "naive", "llm-router", "pointe")
PAID = ("keyboard-canonical", "keyboard-transcript", "pointe", "llm-router", "naive")
COST_LIMIT = 0.60  # per item run, every arm: past it the run is capped
MAX_RUN = COST_LIMIT  # what one run may cost at most, for the budget gate
GUARD_BIN = Path("/tmp/pccb-pointe/guard-bin")


def keychain(item: str) -> str | None:
    for name in (f"pointe.{item}", item):
        got = subprocess.run(["security", "find-generic-password", "-s", name, "-w"], capture_output=True, text=True)
        if got.returncode == 0 and got.stdout.strip():
            return got.stdout.strip()
    return None


def key(env_name: str, item: str) -> str | None:
    return os.environ.get(env_name) or keychain(item)


def git(*args, cwd=ROOT) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True).stdout.strip()


@dataclass
class Job:
    inst: object
    arm: str
    run_index: int
    kind: str  # paid | smoke | unpublished | debug
    voice: str
    rerun_of: str | None = None  # the run whose row hit a harness fault


def voice_for(inst, seed: int) -> str:
    """Seeded draw from the panel, per instance: both runs of an instance use the same voice."""
    panel = corpus.panel()
    return panel[int(hashlib.sha256(f"{seed}:{inst.id}".encode()).hexdigest(), 16) % len(panel)]


def plan(instances: list, arms: list, order_seed: int, kind: str, runs: dict) -> list:
    order = list(instances)
    random.Random(order_seed).shuffle(order)
    jobs = []
    for inst in order:
        for arm in arms:
            for i in range(runs.get(arm, 2)):
                jobs.append(Job(inst, arm, i, kind, voice_for(inst, order_seed)))
    return jobs


# ---------- one adapter behind the interface the scripted user drives ----------

class Arm:
    def __init__(self, inst, adapter, voice: str, repos: dict):
        self.inst, self.adapter, self.voice, self.repos = inst, adapter, voice, repos
        self.kind = adapter.kind
        self.initial = self.tree()
        self.snaps: list = [(0.0, self.initial)]
        self.answers: dict = {}  # request time -> (answers given, when the last one ended)
        self.events: list = []
        self.idle_since: float | None = None
        self.last_busy = 0.0
        self._text_cache: dict = {}
        self.audio_ok = True
        self.trace: Path | None = None
        self._traced = 0.0

    @property
    def agents(self):
        return self.adapter.agents

    def tree(self) -> dict:
        out = {}
        for name, repo in self.repos.items():
            for p in repo.rglob("*"):
                if p.is_file() and ".git" not in p.parts and "__pycache__" not in p.parts:
                    out[f"{name}/{p.relative_to(repo)}"] = hashlib.sha256(p.read_bytes()).hexdigest()
        return out

    def pull(self) -> None:
        self.events += self.adapter.events()

    async def utter(self, key, spoken, canonical, session, interrupt=False):
        self.pull()
        if self.kind == "null":
            now = time.time()
            self.snaps.append((now, self.tree()))
            return now, now
        if self.kind == "typed":
            text = spoken if self.adapter.name == "keyboard-transcript" else canonical
            if key in ("approve", "deny"):
                self.adapter.key(key, session)
            else:
                if interrupt:
                    self.adapter.key("escape", session)
                    await asyncio.sleep(1.5)
                self.adapter.type(text, session)
            now = time.time()
            self.snaps.append((now, self.tree()))
            return now, now
        noise = next((nz for k, _, nz in self.inst.utterances() if k == key), None)
        path = corpus.render(self.voice, spoken, noise)
        lock = corpus.read_lock()
        if lock and lock.get(path.name) not in (None, corpus.sha(path)):
            self.audio_ok = False
        pcm = corpus.load(path)
        if not interrupt:  # wait for the bot to finish speaking, as a person would (at most 10 s)
            t0 = time.time()
            while time.time() - t0 < 10 and time.time() - self.last_speech_end() < 1.2:
                await asyncio.sleep(0.2)
        start, end = await self.adapter.say(pcm, corpus.RATE)
        self.snaps.append((end, self.tree()))
        return start, end

    def last_speech_end(self) -> float:
        spans = self.adapter.speech()
        return spans[-1][1] if spans else 0.0

    def presented_approval(self):
        """(session, command, attempt) for a pending permission request the harness has put to the user, else None.
        Typed arms see it on screen. A spoken arm has presented it once its bot has spoken after the request and then
        been quiet for 1.5 s. When an answer did not take effect (Pointe takes no spoken yes for a request it cannot
        read out), the request counts as presented again after the harness speaks once more."""
        if self.kind == "null":
            return None
        self.pull()
        now = time.time()
        for name, agent in self.agents.items():
            ap = agent.pending_approval()
            if not ap:
                continue
            command = str((ap.get("tool_input") or {}).get("command") or json.dumps(ap.get("tool_input") or {}))
            count, last_end = self.answers.get(ap["_t"], (0, 0.0))
            if count >= 3:  # three answers did not take: as far as a voice-only user can go
                continue
            if self.kind == "typed":
                if count == 0 and ("doyouwant" in agent.flat()[-3000:] or now - ap["_t"] > 3):
                    return name, command, 0, ap["_t"]
                continue
            spans = self.adapter.speech()
            after = max(ap["_t"] - 1, last_end + 0.5)
            spoke = [sp for sp in spans if sp[0] >= after]
            quiet = now - self.last_speech_end() > 1.5 and not self.adapter.thinking()
            if count == 0 and spoke and quiet:
                return name, command, 0, ap["_t"]
            if count >= 1 and spoke and quiet and now - last_end > 8:
                return name, command, count, ap["_t"]
        return None

    def answered_approval(self, request: float, end: float):
        """Counts the answer against the request that was presented, by its time: the agent may already have moved on
        to the next request, which must not inherit this answer."""
        count, _ = self.answers.get(request, (0, 0.0))
        self.answers[request] = (count + 1, end)

    def changed_files(self) -> int:
        now = self.tree()
        return len({k for k in set(now) | set(self.initial) if now.get(k) != self.initial.get(k)})

    def changed_since(self, t: float) -> bool:
        before = [s for at, s in self.snaps if at <= t + 0.01]
        return self.tree() != (before[-1] if before else self.initial)

    def delivered_since(self, t: float) -> bool:
        self.pull()
        if any(e.kind == "delivered" and e.t >= t - 1 for e in self.events):
            return True
        if self.last_busy >= t:
            return True
        return self.changed_since(t)

    def asked_since(self, t: float) -> bool:
        return any(e.kind == "asked" and e.t >= t for e in self.events)

    async def idle(self, last_user_end: float) -> bool:
        now = time.time()
        busy = any(a.busy() for a in self.agents.values())
        if busy:
            self.last_busy = now
        pending = any((ap := a.pending_approval()) and self.answers.get(ap["_t"], (0, 0.0))[0] < 3
                      for a in self.agents.values())
        spoken = self.kind == "spoken"
        quiet = (now - self.last_speech_end() >= 3.0 and not self.adapter.thinking()) if spoken else True
        settle = now - last_user_end >= (6.0 if spoken else 2.5)
        ok = not busy and not pending and quiet and settle and now - self.last_busy >= (6.0 if spoken else 2.0)
        if self.trace and now - self._traced > 5:
            self._traced = now
            a = next(iter(self.agents.values()))
            with open(self.trace, "a") as f:
                f.write(f"{now:.1f} busy={busy} pending={pending} quiet={quiet} settle={settle} "
                        f"since_busy={now - self.last_busy:.0f} thinking={self.adapter.thinking()} "
                        f"speech_end={now - self.last_speech_end():.0f} hooks={[(e.get("hook_event_name"), round(now - e["_t"])) for e in a.hooks()[-1:]] if hasattr(a, "hooks") else "-"}\n")
        if not ok:
            self.idle_since = None
            return False
        self.idle_since = self.idle_since or now
        return now - self.idle_since >= (1.0 if spoken else 0.5)

    async def output_since(self, t: float) -> str:
        if self.kind == "null":
            return ""
        if self.kind == "typed":
            return "\n".join(a.texts_since(t) for a in self.agents.values()).strip()
        texts = []
        for start, end, pcm in self.adapter.speech():
            if end < t:
                continue
            k = (round(start, 2), round(end, 2))
            if k not in self._text_cache:
                rate = 48000 if self.adapter.name == "pointe" else corpus.RATE
                self._text_cache[k] = await Whisper.atranscribe(np.asarray(pcm), rate)
            texts.append(self._text_cache[k])
        return " ".join(texts).strip()

    def spent(self) -> float:
        return sum(r["usd"] for r in spend_rows(self.adapter))


def spend_rows(adapter) -> list:
    rows = []
    for name, agent in adapter.agents.items():
        try:
            usd = sum(ledger.token_cost(model, u) for model, u in agent.usage())
        except Exception:
            usd = 0.0
        rows.append({"vendor": "anthropic", "role": "agent", "session": name, "usd": usd, "how": "computed"})
    try:
        for r in adapter.spend():
            rows.append({"vendor": r.vendor, "role": adapter.name, "usd": r.usd, "how": r.how, "what": r.what})
    except Exception:
        pass
    return rows


# ---------- preflight ----------

def preflight(api_key: str, where: Path) -> dict:
    """(1) a session with a fresh config dir and the API key starts without the Keychain login and without the owner's
    plugins; (2) it is billed to the API key: a one-token `claude -p --output-format stream-json` probe with the same
    environment and a fresh config dir reports an API-key source, and the config dir holds no login credentials;
    (3) the permission mode matches. Any failure stops the run: never fall back to the owner's login."""
    where = where / "preflight"
    shutil.rmtree(where, ignore_errors=True)
    repo, cfg = where / "repo", where / "cfg"
    repo.mkdir(parents=True)
    (repo / "README.md").write_text("preflight\n")
    from core.adapter import write_config
    write_config(cfg, repo, [])
    env = clean_env()
    env.update(CLAUDE_CONFIG_DIR=str(cfg), ANTHROPIC_API_KEY=api_key)
    got = subprocess.run(["claude", "-p", "--output-format", "stream-json", "--verbose", "--model", AGENT_MODEL,
                          "--permission-mode", PERMISSION_MODE, "--max-turns", "1", "Reply with the single word ok"],
                         cwd=repo, env=env, capture_output=True, text=True, timeout=180, stdin=subprocess.DEVNULL)
    init = next((json.loads(l) for l in got.stdout.splitlines() if l.startswith("{") and '"init"' in l), {})
    result = next((json.loads(l) for l in got.stdout.splitlines() if l.startswith("{") and '"type":"result"' in l.replace(" ", "")), {})
    plugins = [p.get("source", "") for p in init.get("plugins") or []]
    stored = json.loads((cfg / ".claude.json").read_text()) if (cfg / ".claude.json").exists() else {}
    creds = (cfg / ".credentials.json").exists() or bool(stored.get("oauthAccount"))
    out = {"api_key_source": init.get("apiKeySource"), "permission_mode": init.get("permissionMode"),
           "model": init.get("model"), "claude_code_version": init.get("claude_code_version"),
           "plugins": plugins, "login_credentials_in_config": creds, "probe_cost_usd": result.get("total_cost_usd", 0)}
    problems = []
    if out["api_key_source"] != "ANTHROPIC_API_KEY":
        problems.append(f"billing source is {out['api_key_source']!r}, not the API key")
    if creds:
        problems.append("the fresh config dir holds login credentials")
    if any(not p.endswith("@builtin") for p in plugins):
        problems.append(f"user plugins loaded: {plugins}")
    if out["permission_mode"] != PERMISSION_MODE:
        problems.append(f"permission mode {out['permission_mode']}")
    out["ok"] = not problems
    out["problems"] = problems
    shutil.rmtree(where, ignore_errors=True)
    return out


def interactive_check(agent) -> list:
    """The same checks on a live interactive session, from its own screen: the banner names API usage billing (not a
    subscription) and the model, and the mode line says accept edits."""
    flat = agent.flat()
    problems = []
    if "apiusagebilling" not in flat:
        problems.append("banner does not say API Usage Billing")
    if "haiku5.5" not in flat:
        problems.append("banner does not name Haiku 5.5")
    if "accepteditson" not in flat:
        problems.append("mode line does not say accept edits")
    return problems


# ---------- the guard for the Pointe daemon ----------

def guard_bin() -> Path:
    """Commands the isolated daemon must never run: opening a terminal window or an app (`open`, `osascript`) for a
    voice-started session, and the other harnesses, whose adapters reach the owner's live shared services. Prepended to
    the daemon's PATH only; each one refuses and exits 1."""
    GUARD_BIN.mkdir(parents=True, exist_ok=True)
    for name in ("open", "osascript", "codex", "opencode"):
        p = GUARD_BIN / name
        p.write_text("#!/bin/sh\necho \"pccb guard: $0 refused in the benchmark\" >&2\nexit 1\n")
        p.chmod(0o755)
    return GUARD_BIN


# ---------- one item run ----------

def make_adapter(arm: str, port: int, brain: str, soniox_model: str, inst=None):
    if arm.startswith("keyboard-"):
        from adapters.keyboard import Keyboard
        return Keyboard(arm.split("-", 1)[1])
    if arm == "null":
        from adapters.null import Null
        return Null()
    if arm == "naive":
        from adapters.naive import Naive
        return Naive(soniox_model)
    if arm == "llm-router":
        from adapters.llm_router import LLMRouter
        return LLMRouter(soniox_model, brain)
    if arm == "pointe":
        from adapters.pointe import Pointe
        return Pointe(port)
    if arm == "echo":
        from adapters.echo import Echo
        return Echo(inst)
    raise ValueError(arm)


def kill_tree(pid_root: Path) -> None:
    """Every process whose working directory or arguments name this slot: nothing started for an item outlives it."""
    got = subprocess.run(["pgrep", "-f", str(pid_root)], capture_output=True, text=True)
    for pid in got.stdout.split():
        try:
            os.kill(int(pid), 9)
        except (ProcessLookupError, PermissionError, ValueError):
            pass


def slot_of(run_id: str, item: str, arm: str, run_index: int) -> str:
    """The item's folder name. Opaque: the agent works inside it and reads its path aloud, so a name like
    "impossible-as-stated-2-pointe-0" told every arm which items were traps (fixed 2026-11-25; earlier runs leaked it)."""
    return "s" + hashlib.sha256(f"{run_id}/{item}/{arm}/{run_index}".encode()).hexdigest()[:12]


def task_delivered(log, events: list) -> bool:
    """The agent received a user prompt between the first scripted turn and the final question: an item whose task never
    reached the agent cannot pass, however its repository and answer look."""
    turns = [t for t, kind, *_ in log.actions if kind == "turn"]
    if not turns:
        return False
    end = log.final_at or float("inf")
    return any(e.kind == "delivered" and turns[0] - 1 <= e.t < end - 0.5 for e in events)


async def run_job(job: Job, ctx: dict, port: int) -> dict:
    inst = job.inst
    run_id = ctx["run_id"]
    slot_name = slot_of(run_id, inst.id, job.arm, job.run_index)
    slot = Path(f"/tmp/pccb/{run_id}/{slot_name}")
    stage = Path(f"/tmp/pccb-keys/{run_id}/{slot_name}")
    shutil.rmtree(slot, ignore_errors=True)
    shutil.rmtree(stage, ignore_errors=True)
    slot.mkdir(parents=True)
    stage.mkdir(parents=True)
    # answer keys first, outside the item's folder
    for name, tests in inst.hidden.items():
        for rel, text in tests.items():
            (stage / name / rel).parent.mkdir(parents=True, exist_ok=True)
            (stage / name / rel).write_text(text)
    (stage / "solution.patch").write_text(inst.solution_patch())
    repos = score.write_repos(inst, slot)
    env = RunEnv(run_id, slot, stage, ctx["api_key"], port, ctx["pointe"], ctx["keys"])
    adapter = make_adapter(job.arm, port, ctx["brain"], ctx["soniox_model"], inst)
    row = {"run_id": run_id, "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "benchmark": "hlk", "item_version": VERSION,
           "kind": job.kind, "item": inst.id if job.kind != "unpublished" else f"{inst.family}-unpublished", "family": inst.family, "expect_done": inst.expect_done, "seed": inst.seed if job.kind != "unpublished" else None,
           "group": inst.group, "adapter": job.arm, "run_index": job.run_index, "voice": job.voice if adapter.kind == "spoken" else None,
           "noise": (inst.noise or next((t.noise for t in inst.turns if t.noise), None)) if adapter.kind == "spoken" else None,
           "agent_model": AGENT_MODEL, "permission_mode": PERMISSION_MODE, "claude_code_version": ctx["claude_version"],
           "repo_commit": ctx["repo_commit"], "pointe_commit": ctx["pointe_commit"], "instance_sha256": inst.digest() if job.kind != "unpublished" else None,
           "load_avg": round(os.getloadavg()[0], 2)}
    missing = [c for c in inst.needs if c not in adapter.capabilities]
    if missing:
        row.update(outcome="unsupported", success=False, unsupported=missing)
        return finish(row, [], [], ctx)
    t0 = time.time()
    log = None
    events = []
    try:
        await asyncio.to_thread(adapter.start, repos, env)
        problems = [p for a in adapter.agents.values() for p in interactive_check(a)] if job.arm != "echo" else []
        if problems:
            raise PreflightFailed("; ".join(problems))
        if hasattr(adapter, "connect"):
            await adapter.connect()
        arm = Arm(inst, adapter, job.voice, repos)
        arm.trace = slot / "trace.log"
        user = User(inst, arm, COST_LIMIT)
        log = await user.run()
        await asyncio.sleep(1)
        arm.pull()
        events = arm.events
        said = log.answer_text
        result = score.check(inst, repos, said, stage)
        result["task_delivered"] = task_delivered(log, events)
        if result["success"] and not result["task_delivered"]:
            result.update(success=False, reason="the task never reached the agent")
        tool_inputs = [t for a in adapter.agents.values() for t in a.tool_inputs()]
        allowed = (str(ctx["pointe"]),) if job.arm == "pointe" else ()
        out_of_tree = audit.outside(tool_inputs, str(slot), allowed)
        row.update(result)
        row.update(outcome="capped" if log.capped else "invalid_out_of_tree" if out_of_tree else "done",
                   capped=log.capped, invalid_out_of_tree=bool(out_of_tree), out_of_tree=[scrub.clean(x)[:160] for x in out_of_tree[:5]],
                   audited=True, tool_calls=len(tool_inputs), turns=log.turns, approvals=log.approvals,
                   clarifications=log.clarifications, correctives=log.correctives, generic_lines=log.generic,
                   approvals_no_after_refused_yes=log.yes_refused,
                   voice_refused_yes=sum(1 for l in getattr(adapter, "log_lines", []) if re.search(r"speak: .*(won't count|can't read out|cannot read out)", l)),
                   answer_text=scrub.clean(said or "")[:400], audio_matches_lock=arm.audio_ok if adapter.kind == "spoken" else None,
                   adapter_versions=adapter.versions())
        if log.capped:
            row["success"] = False
        if out_of_tree:
            row["success"] = False
    except PreflightFailed:
        raise
    except Exception as e:
        row.update(outcome="error", success=False, error=scrub.clean(f"{type(e).__name__}: {e}")[:300])
        ctx["errors"].append(scrub.clean(traceback.format_exc())[-2000:])
    finally:
        spend = spend_rows(adapter)
        try:
            await asyncio.to_thread(adapter.stop)
        except Exception:
            pass
        kill_tree(slot)
        try:
            (slot / "screen.txt").write_text("\n\n".join(scrub.clean(a.flat()[-4000:]) for a in adapter.agents.values()))
        except Exception:
            pass
        if job.arm == "pointe" and getattr(adapter, "state", None):
            kill_tree(adapter.state)
    row["harness_fault"] = harness_fault(slot, time.time(), log.approvals if log else None)
    if job.rerun_of:
        row["rerun_of"] = job.rerun_of
    row["wall_secs"] = round(time.time() - t0, 1)
    row["spend_usd"] = round(sum(r["usd"] for r in spend), 5)
    row["spend"] = [{**r, "usd": round(r["usd"], 5)} for r in spend]
    actions = log.actions if log else []
    return finish(row, actions, events, ctx)


STALL_SECS = 480


def harness_fault(slot: Path, ended: float | None = None, approvals_answered: int | None = None) -> str | None:
    """A fault of the machinery, not of the arm, found by rule in the agents' hook logs. Runs that hit one are rerun
    once, in every arm, with the same voice and run index; the first row stays committed and is counted.
    - "prompt without hook": Claude Code showed a permission prompt without firing its PermissionRequest hook (a
      permission_prompt notification right after an unfinished PreToolUse), so neither the runner nor Pointe saw it;
    - "agent stalled": after a step of the agent, no further hook event for 8 minutes up to the end of the run;
    - "request skipped": a permission request still open at the end, and fewer approval answers from the user than
      requests (the runner credited an answer to the next request: fixed in the runner, kept as a rule)."""
    requests, open_at_end = 0, False
    for f in slot.glob(".cfg-*/hook-events.jsonl"):
        last, last_t = None, None
        for line in f.read_text().splitlines():
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            name = e.get("hook_event_name")
            if name == "Notification" and e.get("notification_type") == "permission_prompt" and last == "PreToolUse":
                return "prompt without hook"
            if name == "PermissionRequest":
                requests += 1
            if name != "Notification":
                last, last_t = name, e.get("_t")
        open_at_end = open_at_end or last == "PermissionRequest"
        end = ended or f.stat().st_mtime
        if last in ("UserPromptSubmit", "PreToolUse", "PostToolUse") and last_t and end - last_t > STALL_SECS:
            return "agent stalled"
    if approvals_answered is not None and open_at_end and approvals_answered < requests:
        return "request skipped"
    return None


class PreflightFailed(RuntimeError):
    pass


def finish(row: dict, actions: list, events: list, ctx: dict) -> dict:
    row["load_avg_end"] = round(os.getloadavg()[0], 2)
    out = ctx["out"]
    if row.get("kind") == "unpublished":  # scores only: nothing that names the instance or lets its seed be found
        row = {k: v for k, v in row.items() if k not in ("answer_text", "out_of_tree", "changed_protected", "reason")}
        actions, events = [], []
    row = json.loads(scrub.clean(json.dumps(row)))
    scrub.check(row)
    with open(out / "rows.jsonl", "a") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")
    ev = {"run_id": row["run_id"], "item": row["item"], "adapter": row["adapter"], "run_index": row["run_index"],
          "user": [list(a) for a in actions],
          "harness": [{"kind": e.kind, "t": round(e.t - (actions[0][0] if False else 0), 2), "session": e.session,
                       "text": e.text[:300]} for e in events]}
    ev = json.loads(scrub.clean(json.dumps(ev)))
    with open(out / "events.jsonl", "a") as f:
        f.write(json.dumps(ev, sort_keys=True) + "\n")
    for s in row.get("spend", []):
        with open(out / "spend.jsonl", "a") as f:
            f.write(json.dumps({"run_id": row["run_id"], "item": row["item"], "adapter": row["adapter"],
                                "run_index": row["run_index"], **s}, sort_keys=True) + "\n")
    ledger.append({"benchmark": "hlk", "run_id": row["run_id"], "kind": row["kind"], "item": row["item"],
                   "adapter": row["adapter"], "run_index": row["run_index"], "usd": row.get("spend_usd", 0.0)})
    return row


MAX_LOAD = 20.0  # no row starts while the 1-minute load is above this (added 2026-11-25; earlier runs had no gate)


async def run_all(jobs: list, ctx: dict, workers: int, port_base: int, cap: float) -> list:
    queue: asyncio.Queue = asyncio.Queue()
    for j in jobs:
        queue.put_nowait(j)
    rows = []
    stop = {"why": None}

    async def worker(k: int):
        port = port_base + 2 * k
        assert port not in FORBIDDEN_PORTS and port + 1 not in FORBIDDEN_PORTS
        while not queue.empty() and not stop["why"]:
            job = queue.get_nowait()
            if job.arm in PAID or job.arm == "null":
                try:
                    ledger.gate(cap, workers, MAX_RUN if job.arm != "null" else 0.0, "hlk")
                except ledger.BudgetRefused as e:
                    stop["why"] = str(e)
                    return
            while os.getloadavg()[0] > MAX_LOAD:  # a loaded machine measures itself, not the arm: wait it out
                print(f"[{k}] load {os.getloadavg()[0]:.1f} > {MAX_LOAD:.0f}: waiting", flush=True)
                await asyncio.sleep(30)
            try:
                row = await run_job(job, ctx, port)
            except PreflightFailed as e:
                stop["why"] = f"preflight failed: {e}"
                return
            rows.append(row)
            done = len(rows)
            print(f"[{done}/{len(jobs)}] {row['item']} {row['adapter']}#{row['run_index']}: {row.get('outcome')} "
                  f"success={row.get('success')} ${row.get('spend_usd', 0):.3f} {row.get('wall_secs', 0)}s "
                  f"(hlk spent ${ledger.spent('hlk'):.2f})", flush=True)

    await asyncio.gather(*(worker(k) for k in range(workers)))
    if stop["why"]:
        print(f"stopped: {stop['why']}", flush=True)
    ctx["stopped"] = stop["why"]
    return rows

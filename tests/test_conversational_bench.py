"""Offline checks of the conversational benchmarks (routing): no keys, no agent, no audio model."""

import asyncio
import json
import re
import time
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bench"))

from conversational.core import detector, ledger, scrub, stats, user  # noqa: E402
from conversational.core.adapter import AgentArm, RunEnv  # noqa: E402
from conversational.adapters import naive  # noqa: E402
from conversational.adapters.echo import EchoArm  # noqa: E402
from conversational.routing import check, runner  # noqa: E402
from conversational.routing.fixture import make  # noqa: E402

DS = check.load()
CANARY = (ROOT / "bench" / "conversational" / "CANARY").read_text().strip()


def tmp_root() -> Path:
    return Path(tempfile.mkdtemp(prefix="pccb-test-", dir="/tmp"))


def test_dataset_shape_and_canary():
    assert DS["canary"] == CANARY
    turns = [t for c in DS["conversation"] for t in c["turn"]]
    assert len(DS["conversation"]) == 12 and all(len(c["turn"]) == 5 for c in DS["conversation"])
    counts = {k: sum(t["type"] == k for t in turns) for k in check.TYPES}
    assert counts == {"name": 16, "description": 10, "context": 10, "ambiguous": 14, "two": 5, "mishear": 5}
    words = [t["word"] for t in turns]
    assert len(set(words)) == 60
    fixture_text = " ".join(" ".join(f.values()) for f in make.FILES.values()).lower()
    assert not [w for w in words if re.search(rf"\b{w}\b", fixture_text)]
    assert all(t["word"] in t["say"] for t in turns)
    assert {c["voice"] for c in DS["conversation"]} == {"af_heart", "am_michael", "bf_emma", "bm_george"}


def test_every_target_follows_from_its_reference_and_ambiguous_turns_have_two_by_construction():
    sessions = DS["sessions"]
    for conv in DS["conversation"]:
        history: list[set[str]] = []
        for turn in conv["turn"]:
            got = check.resolve(turn["ref"], sessions, history)
            assert got == set(turn["target"]), (conv["id"], turn)
            if turn["type"] == "ambiguous":
                assert len(got) == 2 and turn["intended"] in got, (conv["id"], turn)
                assert not (history and history[-1] & got), f"{conv['id']}: the turn before decides the ambiguous one"
            elif turn["type"] == "two":
                assert len(got) == 2
            else:
                assert len(got) == 1, (conv["id"], turn)
            history.append(check.intended(turn))


def test_fixture_names_do_not_collide_with_pointes_own_tests():
    names = [n for n in DS["sessions"]] + list(make.NAMES)
    pattern = re.compile(r"\b(" + "|".join(re.escape(n) for n in sorted(set(names), key=len, reverse=True)) + r")\b",
                         re.I)
    hits = []
    for base in (ROOT / "tests", ROOT / "bench"):
        for path in base.rglob("*"):
            if not path.is_file() or "conversational" in path.parts or path.name == Path(__file__).name:
                continue
            if path.suffix not in (".py", ".md", ".json", ".txt", ".toml", ".sh", ".jsonl", ".html", ""):
                continue
            if ".cache" in path.parts or ".audio" in path.parts:
                continue
            for i, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
                if pattern.search(line):
                    hits.append(f"{path.relative_to(ROOT)}:{i}")
    assert not hits, hits[:10]


def test_token_check_is_red_on_the_fixture_and_green_after_the_edit():
    repos = make.make(tmp_root())
    turn = DS["conversation"][0]["turn"][0]  # tariff-web, "candle"
    assert check.present(repos, turn["word"]) == set()
    assert not check.score_turn(turn, set(), None, None)["correct"]
    with (repos["tariff-web"] / "NOTES.md").open("a") as f:
        f.write("candle\n")
    assert check.present(repos, "candle") == {"tariff-web"}
    assert check.score_turn(turn, {"tariff-web"}, 1.0, None)["correct"]
    (repos["depot"] / "scratch.txt").write_text("a candle\n")  # an untracked file counts too
    scored = check.score_turn(turn, check.present(repos, "candle"), 1.0, None)
    assert scored["wrong_session"] and not scored["correct"] and scored["outcome"] == "wrong_session"
    assert make.marker(repos["depot-docs"]) == "depot-docs"


def test_score_ambiguous_and_two_session_turns():
    amb = DS["conversation"][0]["turn"][2]  # backend: tariff or depot, the user means tariff
    assert check.score_turn(amb, {"tariff"}, 5.0, 3.0)["correct"]
    guessed = check.score_turn(amb, {"tariff"}, 3.0, None)
    assert not guessed["correct"] and guessed["outcome"] == "guessed_right" and not guessed["wrong_session"]
    assert check.score_turn(amb, {"depot"}, 3.0, None)["wrong_session"]
    two = DS["conversation"][0]["turn"][4]
    assert check.score_turn(two, {"tariff", "depot-docs"}, 1.0, None)["correct"]
    assert check.score_turn(two, {"tariff"}, 1.0, None)["outcome"] == "partial"


def test_stats_against_hand_values():
    lo, hi = stats.wilson(0, 10)
    assert lo == 0 and abs(hi - 0.2775) < 1e-3
    lo, hi = stats.wilson(5, 10)
    assert abs(lo - 0.2366) < 1e-3 and abs(hi - 0.7634) < 1e-3
    a = stats.cluster_bootstrap([[True, False], [True, True], [False, False]], iters=1000, seed=1)
    assert a == stats.cluster_bootstrap([[True, False], [True, True], [False, False]], iters=1000, seed=1)
    assert 0 <= a[0] <= 0.5 <= a[1] <= 1
    assert stats.cluster_bootstrap([[True] * 5] * 12) == (1.0, 1.0)
    assert stats.flip_rate([(True, True), (True, False), (False, True)]) == (2, 3)
    assert stats.pass_k([[True, True], [True, False]]) == (1, 2)


QUESTIONS = [
    "Which one do you mean, tariff or tariff web?", "Did you mean the depot service?", "Tariff or tariff web?",
    "Should I send that to depot docs?", "Do you want it in both sessions?", "Which session?",
    "Which backend: tariff or depot?", "Shall I add it to the notes file in tariff?", "Is that the web one?",
    "Do you mean depot or depot docs?", "which one tariff or tariff web", "do you want me to send it to depot",
    "Got it. Which one should get it?", "Would you like me to add it to both?", "Where should this go?",
    "Can you tell me which repo?", "Two sessions match. Which one do you mean?", "Tariff, or the web one?",
    "what session is that for", "Are you sure you want depot docs?",
]
STATEMENTS = [
    "Sending that to tariff web.", "Done. Tariff web added the line.", "Okay, adding it to depot.",
    "I sent it to depot docs.", "Tariff finished its turn.", "Both sessions have it now.", "Adding candle to notes.",
    "Sure.", "Got it, sending to the depot service.", "It's in the notes file in tariff.",
    "Depot docs is working on it.", "That went to the backend.", "I'll put it in tariff web.",
    "No problem, it's done.", "The web front end has the new line.", "Sent.", "Tariff and depot docs both got it.",
    "Working on it now.", "Which is done: depot added the line.", "I added the word river to the notes file.",
]


def test_question_detector_meets_its_line():
    assert len(QUESTIONS) + len(STATEMENTS) >= 40
    right = sum(detector.is_question(q) for q in QUESTIONS) + sum(not detector.is_question(s) for s in STATEMENTS)
    assert right / (len(QUESTIONS) + len(STATEMENTS)) >= 0.95


def test_scripted_user_reply_rules():
    names = list(DS["sessions"])
    assert user.named("Tariff or tariff web?", names) == {"tariff", "tariff-web"}
    assert user.reply("Tariff or tariff web?", {"tariff-web"}, names) == "answer"
    assert user.reply("Should I send it to tariff web?", {"tariff-web"}, names) == "yes"
    assert user.reply("Should I send it to tariff?", {"tariff-web"}, names) == "correct"
    assert user.reply("Which session?", {"tariff"}, names) == "answer"
    assert user.reply("Do you want me to commit?", {"tariff"}, names) == "generic"
    assert user.reply("Tariff web has it. Can you say the depot part again?", {"depot", "tariff-web"}, names) == "answer"
    assert check.answer_line(DS["conversation"][0]["turn"][4]) == "Both tariff and depot docs."
    assert check.answer_line(DS["conversation"][0]["turn"][2]) == "Tariff, please."


def test_naive_rules():
    names = list(DS["sessions"])
    assert naive.route("In tariff web, add a line", names, "depot") == "tariff-web"
    assert naive.route("In tariff, add a line", names, "depot") == "tariff"
    assert naive.route("Same one again: add a line", names, "depot-docs") == "depot-docs"
    assert naive.route("add it in both tariff and depot docs", names, "depot") == "tariff"


def fake_audio(ds: dict) -> dict:
    d = tmp_root()
    (d / "silence.pcm").write_bytes(b"\0\0" * 480)
    return {cid: d / "silence.pcm" for cid in runner.clips(ds)}


def perfect_policy(conv: dict):
    def policy(clip_id: str):
        _, t, kind = (clip_id.split(".") + [""])[:3]
        if not t.startswith("t"):
            return ("none",)
        turn = conv["turn"][int(t[1:]) - 1]
        if kind == "say" and turn["type"] == "ambiguous":
            return ("ask", "Which one do you mean?")
        return ("send", sorted(check.intended(turn)), turn["word"])
    return policy


def test_echo_arm_through_the_runner_and_the_null_floor():
    env = RunEnv(run_id="t", root=tmp_root(), checkout=ROOT)
    conv = DS["conversation"][0]
    audio = fake_audio(DS)
    good = EchoArm(env, perfect_policy(conv))
    good.wait_after_say = 1.0
    res = asyncio.run(runner.run_conversation(good, conv, DS, audio, env.root / "good" / "repos"))
    assert res["error"] is None
    assert [r["correct"] for r in res["rows"]] == [True] * 5
    amb = res["rows"][2]
    assert amb["asked_first"] and amb["clarifications"] == 1
    floor = EchoArm(env, lambda _c: ("none",))
    floor.wait_after_say = 0.2
    res = asyncio.run(runner.run_conversation(floor, conv, DS, audio, env.root / "floor" / "repos"))
    assert [r["correct"] for r in res["rows"]] == [False] * 5
    assert not any(r["wrong_session"] for r in res["rows"])


def test_budget_gate_refuses_a_launch_near_the_cap():
    path = tmp_root() / "ledger.jsonl"
    ledger.record({"benchmark": "routing", "usd": 8.7}, path)
    assert ledger.gate("routing", 9.0, 0.2, path) == pytest.approx(8.7)
    with pytest.raises(ledger.BudgetExceeded):
        ledger.gate("routing", 9.0, 0.6, path)
    assert ledger.spent("routing", path) == pytest.approx(8.7)  # nothing was recorded by the refusal


def test_scrubber_refuses_home_paths_and_key_shapes():
    assert scrub.problems(f"{Path.home()}/x")
    assert scrub.problems("token sk-ant-api03-abcdefghijklmnop")
    assert scrub.problems("/Users/someone/repo")
    assert not scrub.problems("/tmp/pccb/run/tariff wrote candle")
    assert "<pointe>" in scrub.clean(f"{ROOT}/daemon.py", ROOT)
    assert scrub.problems(f"Names: Pointe; {scrub.USER}; tariff")
    assert not scrub.problems(scrub.clean(f"Names: Pointe; {scrub.USER}; tariff", ROOT))


class _FakeSession:
    def __init__(self, repo: Path, inputs: list[dict]):
        self.repo, self._inputs = repo, inputs

    def tool_inputs(self):
        return self._inputs


def test_audit_flags_a_planted_out_of_tree_read():
    root = tmp_root()
    env = RunEnv(run_id="t", root=root, checkout=ROOT)
    arm = AgentArm(env)
    repo = root / "a" / "repos" / "tariff"
    arm.sessions = {"tariff": _FakeSession(repo, [
        {"tool": "Read", "input": {"file_path": str(repo / "NOTES.md")}},
        {"tool": "Bash", "input": {"command": "echo x > /dev/null"}},
        {"tool": "Read", "input": {"file_path": str(ROOT / "bench/conversational/routing/conversations.toml")}},
        {"tool": "Read", "input": {"file_path": str(root / "a" / "repos" / "depot" / "NOTES.md")}},
        {"tool": "Bash", "input": {"command": "find / -iname '*web*'"}}])}
    flagged = arm.audit()
    assert [f["scoring"] for f in flagged] == [True, False, False]
    assert [f["cross_repo"] for f in flagged] == [False, True, False]
    assert all(f["session"] == "tariff" for f in flagged)


def test_runner_refuses_the_owners_ports_and_a_home_state_folder():
    from conversational.adapters.pointe import PointeArm

    env = RunEnv(run_id="t", root=tmp_root(), checkout=ROOT)
    for port in (7860, 7443, 9700):
        with pytest.raises(AssertionError):
            PointeArm(env, port)
    arm = PointeArm(env, 9610)
    home_repos = {"tariff": Path.home() / "pccb-never" / "repos" / "tariff"}
    with pytest.raises(AssertionError):
        asyncio.run(arm.start("c01", home_repos))
    assert not (Path.home() / "pccb-never").exists()


def test_committed_rows_hold_no_home_path_or_key_and_the_page_matches_the_rows():
    results = ROOT / "bench" / "conversational" / "results"
    for path in results.rglob("*"):
        if path.is_file() and path.suffix in (".jsonl", ".json", ".log"):
            assert not scrub.problems(path.read_text(errors="ignore")), path
    md = ROOT / "bench" / "conversational" / "routing" / "RESULTS.md"
    runs = sorted({json.loads(l)["run_id"] for p in results.glob("*/rows.jsonl") for l in p.read_text().splitlines()
                   if not json.loads(l).get("smoke")
                   and not json.loads((p.parent / "run.json").read_text()).get("aborted")})
    if md.exists() and runs:
        from conversational.routing import report

        rows, spend, metas = report.load(runs)
        assert report.markdown(report.summarize(rows, spend), metas) == md.read_text()


class _SlowAgentArm(EchoArm):
    """Reports the delivery at once; the agent writes the word three seconds later and only then ends its turn."""

    async def start(self, conv_id, repos):
        self.repos, self.counts, self.tasks = repos, {n: 0 for n in repos}, []

    def stop_counts(self):
        return dict(self.counts)

    async def utter(self, clip_id, pcm48):
        now = time.time()
        action = self.policy(clip_id)
        if action[0] == "send":
            for name in action[1]:
                self.emit("delivered", session=name, text=action[2])
                self.tasks.append(asyncio.create_task(self._work(name, action[2])))
        return now, now

    stray = None  # a sibling repo the agent also writes into, two seconds later, before it ends its turn

    async def _work(self, name, word):
        await asyncio.sleep(3)
        with (self.repos[name] / "NOTES.md").open("a") as f:
            f.write(f"{word}\n")
        if self.stray:
            await asyncio.sleep(2)
            (self.repos[self.stray] / "NOTES.md").open("a").write(f"{word}\n")
        self.counts[name] += 1


def test_a_turn_waits_for_the_agent_that_got_the_request():
    env = RunEnv(run_id="t", root=tmp_root(), checkout=ROOT)
    conv = DS["conversation"][1]
    arm = _SlowAgentArm(env, perfect_policy(conv))
    arm.wait_after_say = 1.0
    res = asyncio.run(runner.run_conversation(arm, conv, DS, fake_audio(DS), env.root / "slow" / "repos",
                                              only={2, 3}))
    assert res["error"] is None
    assert [r["correct"] for r in res["rows"]] == [True, True]


def test_a_turn_is_read_only_after_the_agent_ends_its_turn():
    env = RunEnv(run_id="t", root=tmp_root(), checkout=ROOT)
    conv = DS["conversation"][1]
    arm = _SlowAgentArm(env, perfect_policy(conv))
    arm.wait_after_say, arm.stray = 1.0, "tariff-web"
    res = asyncio.run(runner.run_conversation(arm, conv, DS, fake_audio(DS), env.root / "stray" / "repos", only={2}))
    assert res["rows"][0]["wrong_session"] and not res["rows"][0]["correct"]


def test_a_two_session_turn_delivered_in_part_gets_its_follow_up_answered():
    env = RunEnv(run_id="t", root=tmp_root(), checkout=ROOT)
    conv = DS["conversation"][11]  # turn 5: both depot and tariff web
    turn = conv["turn"][4]

    def policy(clip_id):
        if clip_id.endswith("t5.say"):
            return ("send", ["tariff-web"], turn["word"])
        if clip_id.endswith("t5.answer"):
            return ("send", ["depot"], turn["word"])
        return ("none",)

    class PartialArm(EchoArm):
        async def utter(self, clip_id, pcm48):
            out = await super().utter(clip_id, pcm48)
            if clip_id.endswith("t5.say"):
                self.emit("asked", text="Tariff web has it. Can you say the depot part again?")
            return out

    arm = PartialArm(env, policy)
    arm.wait_after_say = 1.0
    res = asyncio.run(runner.run_conversation(arm, conv, DS, fake_audio(DS), env.root / "partial" / "repos", only={5}))
    row = res["rows"][0]
    assert row["correct"] and [f["reply"] for f in row["followups"]] == ["answer"] and not row["asked_first"]


def test_permission_dialog_detection_on_a_captured_screen():
    from conversational.core.agent import AgentSession

    s = AgentSession("t", Path("/tmp/x"), Path("/tmp/x-home"), "m", "acceptEdits")
    s.screen = ("Read(/tmp/pccb/dialogtest/b/notes.md)\n Do you want to proceed?\n > 1. Yes\n   2. Yes, allow reading "
                "from b during this session\n   3. No\n Esc to cancel · Tab to amend\n")
    assert s.prompt_pending()
    s.declined_upto = len(s.screen)
    assert not s.prompt_pending()
    s.screen += " Do you want me to commit this? I added the line.\n"
    assert not s.prompt_pending()


def test_a_dialog_is_approved_only_when_it_stays_in_the_session_repo():
    from conversational.core.agent import AgentSession

    repo = Path("/tmp/pccb/run/pointe/c12-r0/repos/depot")
    s = AgentSession("depot", repo, Path("/tmp/x-home"), "m", "acceptEdits")
    s.screen = (f"Bash command\n  pwd; git -C /private{repo} ls-files | head; find {repo} -iname 'notes*'\n"
                " Do you want to proceed?\n > 1. Yes\n   2. No\n Esc to cancel\n")
    assert s.prompt_pending() and s.prompt_stays_in_repo()
    s.screen += f"Bash command\n  cat {repo.parent}/tariff-web/NOTES.md\n Do you want to proceed?\n > 1. Yes\n Esc to cancel\n"
    assert s.prompt_pending() and not s.prompt_stays_in_repo()
    s.screen += "Bash command\n  cat ~/.ssh/config\n Do you want to proceed?\n > 1. Yes\n Esc to cancel\n"
    assert not s.prompt_stays_in_repo()

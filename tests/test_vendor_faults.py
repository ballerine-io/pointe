"""A vendor that fails mid-call is said in words, and the page never shows a green Listening over it. From QA runs: after
a network drop Pipecat stopped reconnecting the ears and the call stayed deaf; a Gemini key out of quota got "I lost my
connection... Say that again?" on every turn; a send that went through was followed by "Say that again?"."""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import brain as brain_mod  # noqa: E402
import vendors  # noqa: E402
from test_orchestrator import _brain, d  # noqa: E402,F401


class ClientError(Exception):
    pass


class ServerError(Exception):
    pass


QUOTA = ClientError("429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your current quota, please "
                    "check your plan and billing details.', 'status': 'RESOURCE_EXHAUSTED'}}")
DOWN = ServerError("500 INTERNAL. {'error': {'code': 500, 'message': 'Internal error encountered.', 'status': 'INTERNAL'}}")


class Tool:
    def __init__(self, name, fn):
        self.name, self.description, self.properties, self.required, self.fn = name, "", {}, [], fn

    async def handler(self, params):
        await params.result_callback(await self.fn())


def _steps(monkeypatch, *answers):
    answers = list(answers)

    async def step(*_a):
        got = answers.pop(0) if answers else TimeoutError("gemini:x timed out")
        if isinstance(got, BaseException):
            raise got
        return got

    monkeypatch.setattr(vendors, "step", step)
    return answers


def test_faults_are_told_apart():
    assert vendors.fault(QUOTA) == ("quota", "")
    assert vendors.fault("GeminiSTTService#0 error: 429 RESOURCE_EXHAUSTED") == ("quota", "gemini")
    assert vendors.fault(DOWN) == ("down", "")
    assert vendors.fault("Error code: 429 - rate_limit_error from anthropic") == ("rate", "anthropic")
    assert vendors.fault(TimeoutError("timed out")) is None
    assert vendors.fault("voice: SonioxSTTService#0 can no longer do its job") is None


def test_an_exhausted_quota_is_named_once_not_say_that_again(monkeypatch):
    _steps(monkeypatch, QUOTA, QUOTA)
    b, spoken = _brain([])
    asyncio.run(b.turn("what is lantern doing"))
    asyncio.run(b.turn("hello?"))
    assert spoken == [vendors.fault_spoken("quota", "gemini")]
    assert "billing" in spoken[0] and brain_mod.LOST_LINE not in spoken


def test_a_vendor_server_error_says_it_is_not_answering(monkeypatch):
    _steps(monkeypatch, DOWN)
    b, spoken = _brain([])
    asyncio.run(b.turn("what is lantern doing"))
    assert spoken == ["Gemini is not answering right now. Try again in a minute."]


def test_a_send_that_went_through_is_never_followed_by_say_that_again(monkeypatch):
    sent = []

    async def do_send():
        sent.append("lighthouse")
        return {"sent_to": "lighthouse/main"}

    _steps(monkeypatch, vendors.Step([{"id": "a", "name": "send_to_claude_code",
                                       "args": {"session": "lighthouse", "message": "read FACT.md"}}]))
    b, spoken = _brain([], tools=[Tool("send_to_claude_code", do_send)])
    asyncio.run(b.turn("Ask lighthouse what the release codename is."))
    assert sent and spoken == [brain_mod.SENT_SLOW_LINE]


def test_a_send_that_went_and_one_refused_say_both_when_the_model_is_slow(monkeypatch):
    """QA round 2: "Switch to lighthouse", then a task for lighthouse and one for harbor: lighthouse's went, harbor's was
    refused (session mode), and the voice said only "The model took too long to answer. Say that again?"."""
    calls = [{"id": "a", "name": "send_to_claude_code", "args": {"session": "lighthouse", "message": "touch both-a.txt"}},
             {"id": "b", "name": "send_to_claude_code", "args": {"session": "harbor", "message": "touch both-b.txt"}}]
    _steps(monkeypatch, vendors.Step(calls))
    results = iter([{"sent_to": ["lighthouse/main"]}, {"error": "Not sent: session mode is pinned to lighthouse/main."}])

    async def send():
        return next(results)
    b, spoken = _brain([], tools=[Tool("send_to_claude_code", send)])
    asyncio.run(b.turn("Tell lighthouse to run touch both-a.txt, and tell harbor to run touch both-b.txt."))
    assert spoken == ["Sent to lighthouse. The part for harbor was not sent, and the model was too slow to say why."]


def test_a_rename_that_went_through_says_done(monkeypatch):
    async def rename():
        return {"renamed": "payments"}

    _steps(monkeypatch, vendors.Step([{"id": "a", "name": "rename_session", "args": {"session": "birch", "name": "payments"}}]))
    b, spoken = _brain([], tools=[Tool("rename_session", rename)])
    asyncio.run(b.turn("Rename birch to payments."))
    assert spoken == [brain_mod.DONE_SLOW_LINE]


def test_a_report_whose_turn_timed_out_is_tried_once_more(monkeypatch):
    monkeypatch.setattr(brain_mod, "UNASKED_RETRY_SECS", 0.0)
    _steps(monkeypatch, TimeoutError("gemini:x timed out"),
           vendors.Step([{"id": "s", "name": "speak", "args": {"text": "Lighthouse says the codename is Juniper."}}]))
    b, spoken = _brain([])

    async def go():
        await b.turn("[lighthouse finished its turn] The release codename is Juniper.")
        await asyncio.sleep(0.05)

    asyncio.run(go())
    assert spoken == ["Lighthouse says the codename is Juniper."]


def test_a_report_is_not_retried_after_the_user_spoke(monkeypatch):
    monkeypatch.setattr(brain_mod, "UNASKED_RETRY_SECS", 0.02)
    left = _steps(monkeypatch, TimeoutError("gemini:x timed out"))
    b, spoken = _brain([])

    async def go():
        await b.turn("[lighthouse finished its turn] The release codename is Juniper.")
        b.interrupt()  # the user started talking
        await asyncio.sleep(0.05)

    asyncio.run(go())
    assert spoken == [] and left == []


def note(d, text):
    d._note_problem(SimpleNamespace(record={"message": text}))


def test_the_page_names_an_exhausted_quota_and_keeps_it_over_the_raw_errors_that_follow(d, monkeypatch):
    monkeypatch.setattr(d, "_problem", (0.0, ""))
    monkeypatch.setattr(d, "_fault", (0.0, "", ""))
    note(d, f"brain failed: ClientError: {QUOTA}")
    note(d, "GeminiTTSService#0 error: TTS context 1b3e completed with no audio")
    shown = d.current_problem()
    assert shown == vendors.fault_help("quota", "gemini") and "RESOURCE_EXHAUSTED" not in shown
    assert d.vendor_fault() == {"vendor": "gemini", "ears": False, "kind": "quota"}


def test_ears_that_gave_up_reconnecting_say_so_and_stay_cannot_hear_until_a_new_call(d, monkeypatch):
    from pipecat.services.stt_service import STTService

    said = []

    async def say_exactly(line, tag):
        said.append(line)

    monkeypatch.setattr(d, "_say_exactly", say_exactly)
    monkeypatch.setattr(d, "_problem", (0.0, ""))
    monkeypatch.setattr(d, "_fault", (0.0, "", ""))
    monkeypatch.setattr(d, "LOST_SETTLE_SECS", 0.0)
    class GaveUp(STTService):
        is_usable = False

        async def run_stt(self, audio):
            yield None

    ears = GaveUp.__new__(GaveUp)
    ears._name = "SonioxSTTService#0"
    asyncio.run(d._service_lost(ears))
    note(d, "voice: SonioxSTTService#0 can no longer do its job")
    assert said == ["I can't hear you: the connection to Soniox dropped. I'm reconnecting; typing still works."]
    assert d.vendor_fault() == {"vendor": "soniox", "ears": True, "kind": "lost"}
    assert d.current_problem() == said[0]
    monkeypatch.setattr(d, "PROBLEM_SHOWN_SECS", 0.0)  # it lasts past the 90 s of an ordinary line
    assert d.current_problem() == said[0]
    asyncio.run(d._service_lost(ears))
    assert len(said) == 1  # once


def test_the_quota_line_ends_when_the_brain_answers_again(d, monkeypatch):
    monkeypatch.setattr(d, "_problem", (0.0, ""))
    monkeypatch.setattr(d, "_fault", (0.0, "", ""))
    note(d, f"brain failed: ClientError: {QUOTA}")
    assert d.vendor_fault()["kind"] == "quota"
    d._brain_answered()
    assert d.vendor_fault() is None and d.current_problem() is None


def test_a_service_still_reconnecting_changes_nothing(d, monkeypatch):
    monkeypatch.setattr(d, "_fault", (0.0, "", ""))
    asyncio.run(d._service_lost(SimpleNamespace(is_usable=True)))
    assert d.state.lost is None and d.vendor_fault() is None


def test_a_brain_error_logged_with_no_setup_names_no_vendor_and_raises_nothing(monkeypatch):
    """The log sink asks which vendor the brain is. With no key at all, setup() raises SystemExit (for the daemon's
    start); from a log line it ended the test run on CI's keyless machine."""
    import daemon

    def no_setup(front):
        raise SystemExit("CLAUDE_VOICE_READER: no key found")
    monkeypatch.setattr(vendors, "resolve", no_setup)
    monkeypatch.setattr(daemon, "_setup", None)
    assert daemon._brain_vendor() == ""

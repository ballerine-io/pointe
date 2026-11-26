"""The hub of tests/test_integration_join.py: the real daemon (daemon.py's app: every route, LocalAuth, the TLS listener
the phone pins, the node link, phone pairing) with only its voice replaced. A call that reaches it runs a stand-in
pipeline with no ears, brain or mouth, as tests/net_bench.py does, so a call can be up while no vendor is called. Keys
are made up and never read from the Keychain or a keyring.

    python -I tests/join_hub.py <port>      with CLAUDE_VOICE_STATE and CLAUDE_VOICE_TLS_PORT set by the test
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = Path(os.environ["CLAUDE_VOICE_STATE"])
assert ".claude-voice" not in str(STATE) and sys.argv[1] not in ("7860", "7443"), "never the live daemon"
sys.path[0:0] = [str(ROOT / "pointe"), str(ROOT)]

import vendors  # noqa: E402

vendors._stored = lambda vendor, keep=True: f"made-up-{vendor}-key"  # these keys reach nothing
import harnesses.claude_code  # noqa: E402

harnesses.claude_code.ROSTER = False
harnesses.claude_code.DEFAULT_HOME = STATE / "claude-home"
harnesses.claude_code.MANAGED_SETTINGS = STATE / "managed-settings.json"
import mac  # noqa: E402

mac.SYSTEM = False
import daemon  # noqa: E402

daemon.COPY_SESSIONS = False


async def stand_in_call(transport) -> None:
    """daemon.run_call's place: the call's socket, its transport and the call state the rest of the daemon reads (a call
    is up, so the nodes forward their prompts), and nothing that speaks."""
    from pipecat.pipeline.pipeline import Pipeline

    d = daemon
    injector = d.FeedInjector()
    voice = d.PipelineWorker(Pipeline([transport.input(), injector, transport.output()]), name="voice",
                             params=d.VOICE_PARAMS, idle_timeout_secs=3600)
    runner = d.WorkerRunner(handle_sigint=False)
    await runner.add_workers(voice)

    @transport.event_handler("on_client_connected")
    async def connected(_t, _c):
        d.state.conn = d.Connection(injector=injector, voice=voice, runner=runner, workers={}, ptt=None)
        d._notify_call()

    @transport.event_handler("on_client_disconnected")
    async def disconnected(_t, _c):
        d.state.conn = None
        d._notify_call()
        await runner.cancel()

    await runner.run()
    if d.state.conn is not None and d.state.conn.runner is runner:
        d.state.conn = None
        d._notify_call()


daemon.run_call = stand_in_call
sys.argv = ["daemon.py", "--port", sys.argv[1]]
daemon.main()

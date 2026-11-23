"""The vendor SDKs read variables a person sets for Claude Code (a company gateway, a proxy, Vertex AI): with them,
Pointe's keys and session content would go to a host outside docs/security/egress-allowlist.txt, or a gateway's own
credential would ride along to the vendor. Pointe's clients go to each vendor's own API whatever the environment says;
the variables are kept for the Claude Code it starts, which the person set them for."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import vendors  # noqa: E402
from harnesses import claude_code  # noqa: E402

GATEWAY = "http://gateway.example.invalid"
HOSTILE = {"ANTHROPIC_BASE_URL": GATEWAY, "ANTHROPIC_AUTH_TOKEN": "synthetic-gateway-token",
           "ANTHROPIC_CUSTOM_HEADERS": "X-Gateway-Key: synthetic-gateway-secret",
           "OPENAI_BASE_URL": f"{GATEWAY}/v1", "OPENAI_CUSTOM_HEADERS": "X-Gateway-Key: synthetic-gateway-secret",
           "OPENAI_ADMIN_KEY": "synthetic-admin-key", "GOOGLE_GEMINI_BASE_URL": GATEWAY, "GOOGLE_VERTEX_BASE_URL": GATEWAY,
           "GOOGLE_GENAI_USE_VERTEXAI": "true", "GOOGLE_GENAI_USE_ENTERPRISE": "true"}
KEYS = {"ANTHROPIC_API_KEY": "synthetic-anthropic", "OPENAI_API_KEY": "synthetic-openai", "GOOGLE_API_KEY": "synthetic-gemini"}

PROBE = """
import json, os, sys
sys.path.insert(0, sys.argv[1])
import vendors
a, o, g = vendors._anthropic(), vendors._openai(), vendors._gemini()
print(json.dumps({
    "anthropic": str(a.base_url), "auth_token": a.auth_token, "openai": str(o.base_url),
    "gemini": g._api_client._http_options.base_url, "vertex": g._api_client.vertexai,
    "headers": sorted(k for k in [*a.default_headers, *o.default_headers] if k.lower().startswith("x-gateway")),
    "admin": o.admin_api_key, "left": sorted(set(os.environ) & set(json.loads(sys.argv[2]))),
    "kept": sorted(getattr(vendors, "FOR_CLAUDE_CODE", {})),
}))
"""


def _probe(extra: dict) -> dict:
    env = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "CLAUDE_VOICE_STATE": os.environ["CLAUDE_VOICE_STATE"],
           "ORT_DISABLE_TELEMETRY": "1", **KEYS, **extra}
    got = subprocess.run([sys.executable, "-I", "-c", PROBE, str(ROOT), json.dumps(list(HOSTILE))], env=env,
                         capture_output=True, text=True, timeout=120)
    assert got.returncode == 0, got.stderr[-2000:]
    return json.loads(got.stdout.strip().splitlines()[-1])


def test_the_clients_go_to_each_vendors_own_api_whatever_the_environment_says():
    got = _probe(HOSTILE)
    assert got["anthropic"].startswith("https://api.anthropic.com"), got
    assert got["openai"].startswith("https://api.openai.com/v1"), got
    assert got["gemini"].startswith("https://generativelanguage.googleapis.com"), got
    assert got["vertex"] is False and got["auth_token"] is None and got["admin"] is None, got
    assert got["headers"] == [], "a gateway's header would ride along to the vendor"
    assert got["left"] == [], "every SDK and Pipecat service built later in this process would read them"
    assert got["kept"] == sorted(HOSTILE)


def test_openai_url_still_wins_for_the_openai_text_models(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"openai_url": "https://example-resource.openai.azure.com/openai/v1/"}))
    got = _probe({**HOSTILE, "CLAUDE_VOICE_STATE": str(tmp_path)})
    assert got["openai"] == "https://example-resource.openai.azure.com/openai/v1/", got


def test_claude_code_started_by_the_daemon_keeps_the_persons_gateway(monkeypatch):
    """The `claude -p` copy of a session runs as the person's Claude Code does, through their gateway if they use one."""
    monkeypatch.setattr(vendors, "FOR_CLAUDE_CODE", {"ANTHROPIC_BASE_URL": GATEWAY}, raising=False)
    env = claude_code._env("")
    assert env["ANTHROPIC_BASE_URL"] == GATEWAY
    assert not vendors.KEY_ENVS & env.keys()


@pytest.mark.parametrize("name", sorted(HOSTILE))
def test_every_variable_the_sdks_read_for_another_host_is_set_aside(name):
    assert name in vendors.SDK_ROUTING_ENVS

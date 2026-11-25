"""Pairing a Linux hub: its address on the local network without `ipconfig` (pointe pair wifi and Settings → Phone),
the phone browser's pairing address drawn as a QR in the terminal (pointe pair link), and a Twingate connector in
Docker's bridge network, which reaches this machine at the bridge's address, not 127.0.0.1 (pointe pair host --listen).
Field report: a Linux hub's owner added 172.17.0.1 to remote.json's listen by hand."""

import json
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[0:0] = [str(ROOT / "pointe"), str(ROOT)]


@pytest.fixture
def pair(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_VOICE_STATE", str(tmp_path))
    import importlib

    import pair as module
    importlib.reload(module)
    monkeypatch.setattr(module.sys, "platform", "linux")
    return module


class Route:
    """socket.socket stand-in: the address a UDP connect would pick, with no packet sent."""

    def __init__(self, ip):
        self.ip = ip

    def __call__(self, *args):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def connect(self, address):
        if self.ip is None:
            raise OSError("Network is unreachable")

    def getsockname(self):
        return (self.ip, 50000)


@pytest.mark.parametrize("ip", ["192.168.1.40", "10.0.3.7", "172.17.0.5"])
def test_on_linux_the_lan_address_is_the_private_one_on_the_default_route(pair, monkeypatch, ip):
    monkeypatch.setattr(pair.socket, "socket", Route(ip))
    assert pair._wifi() == (ip, ip)


@pytest.mark.parametrize("ip", ["100.101.5.7", "8.8.4.4", None])
def test_on_linux_a_vpn_public_or_missing_address_is_no_lan(pair, monkeypatch, ip):
    """100.64/10 is Tailscale's and Twingate's (their own routes), a public address is not a home network."""
    monkeypatch.setattr(pair.socket, "socket", Route(ip))
    with pytest.raises(SystemExit, match="local network"):
        pair._wifi()


def test_the_page_offers_the_lan_route_on_linux(pair, monkeypatch):
    monkeypatch.setattr(pair.socket, "socket", Route("192.168.1.40"))
    monkeypatch.setattr(pair, "_tailscale", lambda: (_ for _ in ()).throw(SystemExit("no tailscale")))
    wifi = next(r for r in pair.routes()["routes"] if r["kind"] == "wifi")
    assert wifi["usable"] and wifi["host"] == "192.168.1.40" and wifi["recommended"]


def test_pair_link_draws_the_address_as_a_qr_in_a_terminal(pair, tmp_path, capsys, monkeypatch):
    pair.setup("pointe.example.internal", "127.0.0.1")
    monkeypatch.setattr(pair, "_to_terminal", lambda: True)
    pair.main(["link"])
    out = capsys.readouterr().out
    assert f"pair={(tmp_path / 'remote_token').read_text()}" in out
    assert set("█▀▄") & set(out), "a QR the phone's Camera scans"


def test_pair_host_listen_adds_the_docker_bridge_address(pair, tmp_path, monkeypatch):
    monkeypatch.setattr(pair.subprocess, "run", lambda *a, **k: None)
    pair.main(["host", "pointe.example.internal", "--listen", "172.17.0.1"])
    remote = json.loads((tmp_path / "remote.json").read_text())
    assert remote == {"host": "pointe.example.internal", "listen": ["127.0.0.1", "172.17.0.1"]}


def test_pair_host_listen_docker_finds_the_bridge_address_itself(pair, tmp_path, monkeypatch):
    monkeypatch.setattr(pair.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(pair, "_docker_bridge", lambda: "172.18.0.1")
    pair.main(["host", "pointe.example.internal", "--listen", "docker"])
    assert json.loads((tmp_path / "remote.json").read_text())["listen"] == ["127.0.0.1", "172.18.0.1"]


@pytest.mark.parametrize("bad", ["0.0.0.0", "8.8.8.8", "not-an-address", "::"])
def test_pair_host_listen_refuses_an_open_or_public_address_and_changes_nothing(pair, tmp_path, bad):
    with pytest.raises(SystemExit, match="private"):
        pair.main(["host", "pointe.example.internal", "--listen", bad])
    assert not (tmp_path / "remote.json").exists()


def test_pair_host_says_when_a_twingate_connector_sits_on_dockers_bridge(pair, capsys, monkeypatch):
    monkeypatch.setattr(pair.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(pair, "_bridged_connector", lambda: "twingate-clever-cobra")
    monkeypatch.setattr(pair, "_docker_bridge", lambda: "172.17.0.1")
    monkeypatch.setattr(pair, "_to_terminal", lambda: True)  # said to a person; an agent's pipe gets no docker probe
    pair.main(["host", "pointe.example.internal"])
    out = capsys.readouterr().out
    assert "twingate-clever-cobra" in out
    assert "pointe pair host pointe.example.internal --listen docker" in out


def test_the_docker_bridge_address_is_read_from_ip(pair, monkeypatch):
    out = "4: docker0    inet 172.17.0.1/16 brd 172.17.255.255 scope global docker0\\       valid_lft forever\n"
    monkeypatch.setattr(pair, "_run", lambda *a: out if a[:2] == ("ip", "-4") else "")
    assert pair._docker_bridge() == "172.17.0.1"
    monkeypatch.setattr(pair, "_run", lambda *a: "")
    assert pair._docker_bridge() is None


def test_the_udp_probe_never_sends_a_packet():
    """A UDP connect only picks a route: the probe target is TEST-NET-1, documentation space nobody answers."""
    text = (ROOT / "pointe" / "pair.py").read_text()
    assert "192.0.2.1" in text and "SOCK_DGRAM" in text and ".send" not in text.split("def _lan_address", 1)[1].split("\ndef ", 1)[0]
    assert socket.AF_INET


# ---------- bin/voice-connector on Linux ----------

TWINGATE_COMMAND = ('docker run -d --sysctl net.ipv4.ping_group_range="0 2147483647" --env TWINGATE_NETWORK="example" '
                    '--env TWINGATE_ACCESS_TOKEN="synthetic-access" --env TWINGATE_REFRESH_TOKEN="synthetic-refresh" '
                    '--env TWINGATE_LABEL_HOSTNAME="`hostname`" --name "twingate-test-cobra" --restart=unless-stopped '
                    '--pull=always twingate/connector:1')


@pytest.mark.parametrize("clip", ["xclip", "wl-paste", "stdin"])
def test_voice_connector_reads_the_command_without_pbpaste_and_shares_the_host_network(tmp_path, clip):
    import subprocess

    fake = tmp_path / "fakebin"
    fake.mkdir()
    scripts = {"uname": 'echo Linux', "docker": f'printf "%s\\n" "$*" >> {tmp_path / "docker.log"}',
               "hostname": "echo avibox"}
    if clip != "stdin":
        scripts[clip] = f"cat {tmp_path / 'clip'}"
    for name, body in scripts.items():
        (fake / name).write_text(f"#!/bin/sh\n{body}\n")
        (fake / name).chmod(0o755)
    (tmp_path / "clip").write_text(TWINGATE_COMMAND)
    (tmp_path / "state").mkdir()
    env = {"PATH": f"{fake}:/usr/bin:/bin", "HOME": str(tmp_path), "CLAUDE_VOICE_STATE": str(tmp_path / "state"),
           **({"DISPLAY": ":0"} if clip == "xclip" else {"WAYLAND_DISPLAY": "wayland-0"} if clip == "wl-paste" else {})}
    got = subprocess.run([str(ROOT / "bin" / "voice-connector")], env=env, capture_output=True, text=True, timeout=30,
                         input=TWINGATE_COMMAND if clip == "stdin" else "")
    assert got.returncode == 0, got.stderr
    run = [line for line in (tmp_path / "docker.log").read_text().splitlines() if line.startswith("run")][0]
    assert "--network host" in run and "synthetic-access" not in run and "synthetic-refresh" not in run
    assert "address 127.0.0.1" in got.stdout and "synthetic" not in got.stdout + got.stderr
    assert (tmp_path / "state" / "twingate-connector.env").stat().st_mode & 0o077 == 0

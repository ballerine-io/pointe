"""The approvals record on the page (ui.html, ui_approvals.html): Settings, Approvals record, in a headless Chrome against
the stub Mac (tests/page_rig.py). Skipped where that Chrome is not installed (CI on Linux).

Every approval the Mac's journal holds is a row: when, by voice or by a tap, the exact request, and the voice lock's
score of a spoken answer. What the stub sends is what the daemon sends for tests/fixtures/approvals_journal.jsonl.

uv run --locked pytest -q tests/test_approvals_page.py
"""

import asyncio
import base64
import os
import sys
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import approvals  # noqa: E402
from page_rig import CHROME, ROOT, Browser, StubMac, fixture  # noqa: E402

pytestmark = pytest.mark.skipif(not os.path.exists(CHROME), reason="headless Chrome is not installed here")
SHOTS = os.environ.get("POINTE_APPROVALS_SHOTS")
RECORD = approvals.read([ROOT / "tests" / "fixtures" / "approvals_journal.jsonl"])

ROWS = """(() => ({rows: [...document.querySelectorAll('#approvals-list .ap')].map(r => ({id: r.dataset.request, what: r.querySelector('.ap-what').textContent,
    when: r.querySelector('.ap-when').textContent, who: r.querySelector('.ap-who').textContent, request: r.querySelector('.ap-req').textContent,
    lock: (r.querySelector('.ap-lock') || {}).textContent || '', cut: !!r.querySelector('.ap-cut'), shown: r.getClientRects().length > 0})),
  note: document.getElementById('approvals-note').hidden ? '' : document.getElementById('approvals-note').textContent,
  lede: document.getElementById('approvals-lede').textContent, buttons: document.querySelectorAll('#g-approvals button, #g-approvals input').length,
  nav: !!document.querySelector('#set-nav [data-section="g-approvals"]')}))()"""


async def _record(rows, size=(1280, 900), shot=None):
    stub = await StubMac().start()
    stub.status = fixture(sessions=2, connected=True)
    stub.approvals = rows
    try:
        async with Browser() as browser:
            page = await browser.open(stub.url)
            await page.cdp("Emulation.setDeviceMetricsOverride", {"width": size[0], "height": size[1], "deviceScaleFactor": 2, "mobile": size[0] < 600})
            await page.eval("openSettings().then(() => settingsJump('g-approvals')); true")
            for _ in range(40):
                got = await page.eval(ROWS)
                if got["rows"] or got["note"]:
                    break
                await asyncio.sleep(0.1)
            if shot and SHOTS:
                for look in ("light", "dark"):
                    await page.cdp("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": look},
                                                                              {"name": "prefers-reduced-motion", "value": "reduce"}]})
                    await page.eval("document.getElementById('g-approvals').scrollIntoView({block: 'start'}); true")
                    await asyncio.sleep(0.4)
                    data = (await page.cdp("Page.captureScreenshot", {"format": "png"}))["data"]
                    Path(SHOTS, f"{shot}-{look}.png").write_bytes(base64.b64decode(data))
            return got
    finally:
        await stub.stop()


def test_every_approval_in_the_journal_is_a_row_newest_first():
    got = asyncio.run(_record(RECORD, shot="page-approvals"))
    assert [r["id"] for r in got["rows"]] == [a["request_id"] for a in RECORD] == ["p5", "p4", "p3", "p2", "p1"]
    assert all(r["shown"] for r in got["rows"]) and got["note"] == "" and got["nav"]
    assert got["lede"] == approvals.COPY["lede"]


def test_a_row_says_when_how_the_exact_request_and_the_score():
    rows = {r["id"]: r for r in asyncio.run(_record(RECORD))["rows"]}
    assert rows["p1"] == {"id": "p1", "what": "Approved by voice", "when": "20 Nov, 09:14", "who": "bluebell/dev",
                          "request": "Bash\ngit push --force-with-lease origin retry-fix", "lock": "Voice lock approvals: score 0.71",
                          "cut": False, "shown": True}
    assert (rows["p2"]["what"], rows["p2"]["lock"]) == ("Denied by a tap", "")  # a tap has no voice to score
    assert (rows["p3"]["what"], rows["p3"]["who"]) == ("Approved from a notification", "docs · devbox")
    assert rows["p4"]["lock"] == approvals.COPY["lock_off"]
    assert rows["p5"]["cut"] and rows["p5"]["lock"] == "Voice lock commands: score 0.64"


def test_the_record_only_shows_nothing_in_it_answers_anything():
    assert asyncio.run(_record(RECORD))["buttons"] == 0


def test_an_empty_record_and_a_failed_load_each_say_so():
    assert asyncio.run(_record([]))["note"] == approvals.COPY["empty"]
    assert asyncio.run(_record(None))["note"] == approvals.COPY["failed"]


def test_on_a_phone_wide_page_a_long_request_wraps_inside_its_row():
    long = [dict(RECORD[0], request="Bash\n" + "uv run pytest -q tests/test_pricing.py::test_discount --maxfail=1 " * 6)]
    stub_rows = asyncio.run(_record(long, size=(402, 874), shot="page-approvals-phone"))
    assert len(stub_rows["rows"]) == 1 and stub_rows["rows"][0]["shown"]

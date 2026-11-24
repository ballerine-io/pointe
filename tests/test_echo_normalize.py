"""The bot and the ears write the same speech differently: "10 percent" and "10%", "1000" and "1,000", "תשעים" and
"90". Both go through echo.words, so they compare equal. Lines from live runs at rig echo 0.3 (scenarios.py brain)."""

import sys
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]

import echo  # noqa: E402
from echo import EchoGuard, words  # noqa: E402

FIX = "It fixed the discount function so a percent of 10 means 10 percent off, instead of 1000 percent off. Commit it?"
HEBREW = ("מאה עם עשרה אחוז מחזיר עכשיו תשעים. בדיקות: שתיים עברו, אפס נכשלו. זה שינוי של שורה אחת וקל לבטל. "
          "מחיקת ה-README ויצירת notes2 עדיין לא בוצעו, ומחיקת ה-README דורשת אישור מוקלד שלך.")


@pytest.fixture
def clock(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(echo.time, "time", lambda: now[0])
    return now


@pytest.mark.parametrize("bot, ears", [
    ("10 percent off, instead of 1000 percent off", "10% off, instead of 1,000% off"),
    ("twelve thousand five hundred users", "12,500 users"),
    ("UTC+2", "UTC plus 2"),
    ("מאה עם עשרה אחוז מחזיר עכשיו תשעים", "100 עם 10% מחזיר עכשיו 90"),
    ("שתיים עברו, אפס נכשלו", "2 עברו, 0 נכשלו"),
    ("עשרים ואחת בדיקות", "21 בדיקות"),
    ("שלוש מאות וחמישים", "350"),
])
def test_the_bot_and_the_ears_write_the_same_speech_alike(bot, ears):
    assert words(bot) == words(ears)


def test_its_answer_with_numbers_does_not_cut_itself_off(clock):
    g = EchoGuard()
    g.bot_said(FIX)
    g.bot_started()
    clock[0] = 106.4
    assert not g.is_barge_in(" It fixed the discount function so a percent of 10 means 10% off, instead of 1,0",
                             spoken=(100.2, 106.3))
    clock[0] = 106.6
    g.bot_stopped()
    clock[0] = 107.9
    said = "It fixed the discount function so a percent of 10 means 10% off, instead of 1,000%."
    assert g.user_part(said, spoken=(100.2, 106.5)) == ""


def test_a_hebrew_answer_with_numbers_is_its_echo(clock):
    g = EchoGuard()
    g.bot_said(HEBREW)
    g.bot_started()
    clock[0] = 115.0
    g.bot_stopped()
    clock[0] = 115.7  # the final, 0.7 s after it stopped
    said = ("100 עם 10% מחזיר עכשיו 90. בדיקות. 2 עברו, 0 נכשלו. זה שינוי של שורה אחת וקל לבטל. מחיקת ה-README "
            "ויצירת notes2 עדיין לא בוצעו, ומחיקת ה-README דורשת אישור מוקדם.")
    assert g.user_part(said, spoken=(100.1, 114.9)) == ""


def test_the_users_own_numbers_still_get_through(clock):
    g = EchoGuard()
    g.bot_said(FIX)
    g.bot_started()
    clock[0] = 106.6
    g.bot_stopped()
    clock[0] = 110.0
    said = "Make it 15% off for orders over 2,000."
    assert g.user_part(said, spoken=(108.0, 109.5)) == said

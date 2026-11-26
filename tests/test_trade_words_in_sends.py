"""A coding word the recognizer misspells is written right in what is sent: "dark string" is a docstring.

Tester round 5: "Add a dark string to calc_total" (t3-02, 3 of 3) and "unitist", "Uniris", "UNIREST" for unittest (apr-03
and the suite's unittest requests, 3 of 3) went to sessions with a hedge, and once led to a wrong edit. These are the
recognizer's spellings of two words of the trade, not new names: they are written as the trade writes them, unless the
session's own code uses the heard word.

uv run pytest -q tests/test_trade_words_in_sends.py
"""

import sys
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]

import relay  # noqa: E402


@pytest.mark.parametrize("message,sent", [
    ("Add a dark string to calc_total.", "Add a docstring to calc_total."),
    ("Run the tests with Python's unitist module.", "Run the tests with Python's unittest module."),
    ("Check whether the Uniris module is importable.", "Check whether the unittest module is importable."),
    ("Run python3 -c import UNIREST", "Run python3 -c import unittest"),
    ("Add a doc string to refund.", "Add a docstring to refund."),
    # t3-02 at bb36fafb (2 of 2): the model quoted the misheard word, and the session wrote a docstring reading "dark"
    ('Add a "dark" string to calc_total.', "Add a docstring to calc_total."),
    ("Add a 'dark' string to calc_total.", "Add a docstring to calc_total."),
    ('The owner asks: add a "dark string" to calc_total.', "The owner asks: add a docstring to calc_total."),
    ("Rename calc_total to compute_total.", "Rename calc_total to compute_total."),
])
def test_a_misspelled_trade_word_is_written_right(message, sent):
    assert relay.trade_words(message, set()) == sent


def test_a_word_the_code_uses_is_left_alone():
    assert relay.trade_words("Import unirest and call it.", {"unirest"}) == "Import unirest and call it."


@pytest.mark.parametrize("message,sent", [
    # lat-04: "convert hero dot png to webp" reaches the daemon as "to web" (Soniox and Whisper both hear the clip so)
    ("Convert hero.png to web and update hero.js to point at it.",
     "Convert hero.png to WebP and update hero.js to point at it."),
    ("Convert the PNGs in assets to web.", "Convert the PNGs in assets to WebP."),
    ("Re-encode banner.jpg as web, quality 80.", "Re-encode banner.jpg as WebP, quality 80."),
    # "web" that names a place or a thing of the web stays
    ("Move hero.png to web and update the import.", "Move hero.png to web and update the import."),
    ("Convert hero.png to web folder assets.", "Convert hero.png to web folder assets."),
    ("Convert the CLI to a web app.", "Convert the CLI to a web app."),
    ("Convert hero.png to web-safe colours.", "Convert hero.png to web-safe colours."),
])
def test_an_image_converted_to_web_is_converted_to_webp(message, sent):
    assert relay.trade_words(message, set()) == sent

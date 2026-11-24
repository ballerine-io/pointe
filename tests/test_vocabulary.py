"""Self-learning vocabulary (feature 2): names the user fixes once are heard right from then on.

The rules, each with a test below: the dictionary lives only on the Mac at 0600; a correction teaches only names and
identifiers, never grammar; nothing that looks like a credential is learned (readout.mask, the one credential rule);
no approval, refusal or interrupt word ever biases recognition, whatever the path (a term biases toward itself, and a
bias toward "yes" would turn a non-answer into a yes); words from a meeting's room are never learned; the user sees,
edits and deletes every entry, from the page or the phone. Offline, against the module and the real daemon routes.

uv run pytest -q tests/test_vocabulary.py
"""

import asyncio
import json
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_orchestrator import add, client_for, d, fake_conn  # noqa: E402,F401
from fake_secrets import AWS_KEY_ID, GITHUB_PAT  # noqa: E402

import vocabulary  # noqa: E402
from vocabulary import Dictionary, candidates  # noqa: E402


def terms(was: str, meant: str) -> list[str]:
    return [c.term for c in candidates(was, meant)]


# ---------- what a correction teaches ----------

@pytest.mark.parametrize("was, meant, want", [
    ("open the blue bell repo", "open the bluebell repo", ["bluebell"]),
    ("rename apply percent discount", "rename applyPercentDiscount", ["applyPercentDiscount"]),
    ("check the orbit api pod", "check the orbit-api pod", ["orbit-api"]),
    ("bump zod to version four", "bump zod to v4.2", ["v4.2"]),
    ("ask donna about the retry budget", "ask Dana about the retry budget", ["Dana"]),
    ("tell liver lantern to stop", "tell River Lantern to stop", ["River Lantern"]),
    ("look at pricing dot pie", "look at pricing.py", ["pricing.py"]),
])
def test_a_correction_teaches_the_name_or_identifier_it_fixed(was, meant, want):
    assert terms(was, meant) == want


@pytest.mark.parametrize("was, meant", [
    ("I want to see the logs", "I wanted to see the logs"),
    ("it go to staging", "it goes to staging"),
    ("run the test", "run the tests"),
    ("can you check it", "Can you check it?"),          # case and punctuation only
    ("ask dana", "ask Dana"),                            # heard right, only capitalised
    ("send it to the team", "send it to the whole team"),  # a common word added
])
def test_a_grammar_or_wording_fix_teaches_nothing(was, meant):
    assert terms(was, meant) == []


def test_splitting_a_word_back_apart_teaches_nothing():
    assert terms("open the Quillfeather repo", "open the quill feather repo") == []


def test_a_whole_new_sentence_is_not_a_correction_and_teaches_nothing():
    assert terms("what is the weather like", "Deploy Quillfeather to Zentrak now") == []


def test_one_correction_teaches_at_most_three_terms():
    assert len(terms("a b c d e", "Alfa1 Bravo2 Charlie3 Delta4 Echo5")) <= 3


def test_a_term_is_at_most_forty_characters():
    long = "x" + "y" * 45 + "1"
    assert terms("open the thing", f"open the {long}") == []


def test_a_latin_name_in_a_hebrew_sentence_is_learned_for_both_languages():
    [c] = candidates("תפתח את לארקספר", "תפתח את bluebell")
    assert (c.term, c.lang) == ("bluebell", "both")


def test_a_hebrew_word_fix_teaches_nothing_by_itself():
    # Hebrew has no capitals and rich inflection: the code cannot tell a name from a grammar fix. Add it by hand.
    assert terms("אני רוצה לראות", "אני רציתי לראות") == []


def test_language_of_a_term():
    assert vocabulary.lang_of("bluebell", "open bluebell") == "en"
    assert vocabulary.lang_of("ליאורה", "תשאל את ליאורה") == "he"
    assert vocabulary.lang_of("bluebell", "תפתח את bluebell") == "both"


# ---------- never a consent word ----------

CONSENT = ["yes", "Yes", "okay", "OK", "Proceed", "approve", "sure", "go ahead", "yep", "no", "deny", "stop", "wait",
           "enough", "כן", "תאשר", "וכן", "לא", "רגע", "סבבה", "why not", "ok-computer"]


@pytest.mark.parametrize("word", CONSENT)
def test_a_consent_or_interrupt_word_is_never_a_term(word):
    assert vocabulary.refusal(word) is not None


def test_every_guard_word_is_refused():
    import echo
    import guards
    for w in guards._YES | guards._NO | guards._WEAK_YES | echo.INTERRUPT_WORDS | echo.ANSWER_WORDS:
        assert vocabulary.refusal(w) is not None, w
    for p in guards._YES_PHRASES + guards._YES_DESPITE_NO:
        assert vocabulary.refusal(p) is not None, p


def test_a_correction_never_teaches_a_consent_word():
    assert terms("tell it to precede", "tell it to Proceed") == []
    assert terms("I said yep", "I said Yep") == []
    assert terms("that's a chain", "that's a Yes-man") == []


def test_names_that_merely_contain_a_consent_word_are_fine():
    for name in ("Notion", "Okta", "Stopwatch", "yesterday-report"):
        assert vocabulary.refusal(name) is None, name


# ---------- never a secret ----------

@pytest.mark.parametrize("was, meant", [
    ("the key is s k live", "the key is sk-live-4f9a8b7c6d5e4f3a2b1c0d9e8f7a6b5c"),
    ("use token g h p", f"use token {GITHUB_PAT}"),
    ("my password is hunter", "my password is hunter22x"),
    ("the password is blue", "the password: Zebra-77"),
    ("הסיסמה היא אחת", "הסיסמה היא Kite-4412"),
    ("set api key to abc", "set api_key=abc123def"),
])
def test_nothing_that_looks_like_a_credential_is_learned(was, meant):
    assert terms(was, meant) == []


@pytest.mark.parametrize("term", ["sk-live-4f9a8b7c6d5e4f3a2b1c0d9e8f7a6b5c", AWS_KEY_ID,
                                  GITHUB_PAT, "api_key=abc123"])
def test_a_credential_cannot_be_added_by_hand(term):
    assert vocabulary.refusal(term) is not None


def test_the_credential_rule_is_readout_mask():
    import readout
    assert vocabulary.mask is readout.mask
    assert not hasattr(vocabulary, "_SECRET_SHAPES")


def test_the_widened_mask_hides_a_spoken_password_value_and_keeps_plain_words():
    import readout
    assert "hunter22x" not in readout.mask("my password is hunter22x")
    assert "Kite-4412" not in readout.mask("הסיסמה היא Kite-4412")
    assert readout.mask("the token is expired") == "the token is expired"
    assert readout.mask("run: git push origin dev") == "run: git push origin dev"


# ---------- the file ----------

def test_the_dictionary_is_private_and_survives_a_restart(tmp_path):
    path = tmp_path / "dictionary.json"
    book = Dictionary(path)
    book.add("bluebell", source="manual")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    again = Dictionary(path)
    [entry] = again.entries
    assert entry["term"] == "bluebell" and entry["source"] == "manual" and entry["confirmed"] is True
    assert entry["lang"] == "en" and entry["hits"] == 0 and entry["added_at"] > 0


def test_a_damaged_file_starts_empty_keeps_the_bad_copy_and_says_so(tmp_path):
    path = tmp_path / "dictionary.json"
    path.write_text("{not json")
    book = Dictionary(path)
    assert book.entries == [] and book.problem
    assert (tmp_path / "dictionary.json.bad").read_text() == "{not json"


def test_a_hand_edited_file_cannot_smuggle_in_a_consent_word_or_a_secret(tmp_path):
    path = tmp_path / "dictionary.json"
    path.write_text(json.dumps({"entries": [
        {"term": "yes", "lang": "en", "source": "manual", "hits": 0, "added_at": 1, "confirmed": True},
        {"term": "sk-live-4f9a8b7c6d5e4f3a2b1c0d9e8f7a6b5c", "lang": "en", "source": "manual", "hits": 0, "added_at": 1,
         "confirmed": True},
        {"term": "bluebell", "lang": "en", "source": "manual", "hits": 0, "added_at": 1, "confirmed": True}]}))
    assert [e["term"] for e in Dictionary(path).entries] == ["bluebell"]


def test_add_edit_delete_and_duplicates(tmp_path):
    book = Dictionary(tmp_path / "d.json")
    book.add("bluebell", source="manual")
    with pytest.raises(ValueError):
        book.add("Bluebell", source="manual")  # one entry per term, whatever the case
    book.edit("bluebell", to="Bluebell", lang="both")
    assert [(e["term"], e["lang"]) for e in book.entries] == [("Bluebell", "both")]
    with pytest.raises(ValueError):
        book.edit("Bluebell", to="okay")  # an edit is checked like an add
    assert book.delete("bluebell") is True and book.entries == []
    assert book.delete("bluebell") is False


def test_a_full_dictionary_refuses_more_and_learning_stops(tmp_path, monkeypatch):
    monkeypatch.setattr(vocabulary, "CAP", 3)
    book = Dictionary(tmp_path / "d.json")
    for t in ("alfa1", "bravo2", "charlie3"):
        book.add(t, source="manual")
    assert book.full
    with pytest.raises(vocabulary.Full):
        book.add("delta4", source="manual")
    assert book.learn("open the blue bell repo", "open the bluebell repo") == []
    assert len(book.entries) == 3


def test_hearing_a_term_counts_a_hit_and_never_adds_one(tmp_path):
    book = Dictionary(tmp_path / "d.json")
    book.add("bluebell", source="manual")
    book.heard("open Bluebell and quillfeather please")
    assert [(e["term"], e["hits"]) for e in book.entries] == [("bluebell", 1)]


# ---------- what reaches the recogniser ----------

def test_the_terms_put_the_dictionary_first_then_sessions_then_brief_names_then_folders(tmp_path):
    book = Dictionary(tmp_path / "d.json")
    book.add("bluebell", source="manual")
    out = vocabulary.terms_for(book, session_names=["river-lantern"], brief_names={"river-lantern": ["Dana", "Okta"]},
                               folders=["apps", "orbit-api"])
    assert out == ["bluebell", "river-lantern", "Dana", "Okta", "apps", "orbit-api"]


def test_the_terms_never_carry_a_consent_word_from_any_source(tmp_path):
    book = Dictionary(tmp_path / "d.json")
    out = vocabulary.terms_for(book, session_names=["okay", "yes"], brief_names={"s": ["Yes", "Dana", "go ahead"]},
                               folders=["sure", "apps"])
    assert out == ["Dana", "apps"]


def test_brief_names_are_soft_and_bounded_per_session(tmp_path):
    book = Dictionary(tmp_path / "d.json")
    names = [f"Name{i}" for i in range(30)]
    out = vocabulary.terms_for(book, session_names=[], brief_names={"s": names}, folders=[])
    assert out == names[:vocabulary.SOFT_PER_SESSION]
    assert book.entries == []  # never persisted


def test_the_cap_drops_the_softest_first_then_the_least_heard(tmp_path, monkeypatch):
    monkeypatch.setattr(vocabulary, "CAP", 3)
    monkeypatch.setattr(vocabulary, "TERMS_CAP", 3)
    book = Dictionary(tmp_path / "d.json")
    book.add("alfa1", source="manual")
    book.add("bravo2", source="manual")
    book.heard("bravo2 bravo2")
    out = vocabulary.terms_for(book, session_names=["s1", "s2"], brief_names={}, folders=["f1"])
    assert out == ["bravo2", "alfa1", "s1"]


def test_suggestions_come_from_briefs_and_skip_known_ignored_and_refused_names(tmp_path):
    book = Dictionary(tmp_path / "d.json")
    book.add("Dana", source="manual")
    book.ignore("Okta")
    out = book.suggestions({"lantern": ["Dana", "Okta", "Quillfeather", "yes", GITHUB_PAT]})
    assert out == [{"term": "Quillfeather", "session": "lantern", "lang": "en"}]
    assert Dictionary(tmp_path / "d.json").ignored == ["Okta"]  # an ignore outlives a restart


def test_a_note_in_brackets_is_dropped_and_a_session_name_is_not_suggested(tmp_path):
    # Seen live: the reader wrote "river-lantern (session name)" for a session with an empty record.
    book = Dictionary(tmp_path / "d.json")
    out = book.suggestions({"river-lantern": ["river-lantern (session name)", "Kestrelbay (the build bot)"]},
                           session_names=["river-lantern"])
    assert out == [{"term": "Kestrelbay", "session": "river-lantern", "lang": "en"}]
    assert vocabulary.terms_for(book, [], {"s": ["Kestrelbay (the build bot)"]}, []) == ["Kestrelbay"]


def test_the_brain_line_names_the_terms_and_nothing_when_empty(tmp_path):
    book = Dictionary(tmp_path / "d.json")
    assert vocabulary.brain_line(book) is None
    book.add("bluebell", source="manual")
    line = vocabulary.brain_line(book)
    assert line.startswith("[names the user uses, spell them this way in anything you send]") and "bluebell" in line


# ---------- through the daemon ----------

@pytest.fixture
def voc(d, monkeypatch, tmp_path):
    monkeypatch.setattr(d, "PREFS", d.Prefs(tmp_path / "prefs.json"))
    monkeypatch.setattr(d, "DICTIONARY", Dictionary(tmp_path / "dictionary.json"))
    d.state.conn = fake_conn()

    async def push(frame, *a):
        pass
    d.state.conn.injector.push_frame = push
    d.state.connected_at = 1.0
    return d, client_for(d)


def heard(d, text: str) -> int:
    d._remember("user", text)
    return d.state.conversation_base + len(d.state.conversation) - 1


def test_a_correction_teaches_the_name_and_the_status_says_so_for_the_toast(voc):
    d, client = voc
    turn = heard(d, "open the blue bell repo")
    r = client.post("/voice/correct", json={"id": turn, "text": "open the bluebell repo"})
    assert r.status_code == 200 and r.json()["learned"] == ["bluebell"]
    s = client.get("/voice/status").json()["dictionary"]
    assert s["count"] == 1 and [x["term"] for x in s["learned_this_call"]] == ["bluebell"]
    [entry] = client.get("/voice/dictionary").json()["entries"]
    assert entry["source"] == "correction" and entry["confirmed"] is True


def test_undo_deletes_what_was_learned(voc):
    d, client = voc
    turn = heard(d, "open the blue bell repo")
    client.post("/voice/correct", json={"id": turn, "text": "open the bluebell repo"})
    assert client.request("DELETE", "/voice/dictionary", params={"term": "bluebell"}).status_code == 200
    assert client.get("/voice/dictionary").json()["entries"] == []
    assert client.get("/voice/status").json()["dictionary"]["learned_this_call"] == []
    assert client.request("DELETE", "/voice/dictionary", params={"term": "bluebell"}).status_code == 404


def test_putting_a_fix_back_never_teaches_the_misheard_word(voc):
    # Seen live: fixed, undone, the bubble edited back to what was heard, then fixed again taught "Pelusin" too.
    d, client = voc
    turn = heard(d, "Is Pelusin still on the preview environment?")
    client.post("/voice/correct", json={"id": turn, "text": "Is Pellucine still on the preview environment?"})
    client.request("DELETE", "/voice/dictionary", params={"term": "Pellucine"})
    assert client.post("/voice/correct", json={"id": turn, "text": "Is Pelusin still on the preview environment?"}).json()["learned"] == []
    client.post("/voice/correct", json={"id": turn, "text": "Is Pellucine still on the preview environment?"})
    assert [e["term"] for e in client.get("/voice/dictionary").json()["entries"]] == ["Pellucine"]


def test_fixing_a_typed_turn_teaches_nothing(voc):
    d, client = voc
    turn = heard(d, "open the blue bell repo")
    d.state.typed.add(turn)  # the user typed it: a typo, not something misheard
    assert client.post("/voice/correct", json={"id": turn, "text": "open the bluebell repo"}).json()["learned"] == []


def test_learning_can_be_turned_off(voc):
    d, client = voc
    assert client.post("/voice/prefs", json={"dictionary.learn": False}).status_code == 200
    turn = heard(d, "open the blue bell repo")
    assert client.post("/voice/correct", json={"id": turn, "text": "open the bluebell repo"}).json()["learned"] == []
    add(d, "a", "lantern")
    d.REGISTRY.sessions["a"].brief = {"people_and_names": ["Quillfeather"]}
    assert client.get("/voice/dictionary").json()["suggestions"] == []


def test_crud_from_the_page(voc):
    d, client = voc
    assert client.post("/voice/dictionary", json={"action": "add", "term": "Quillfeather"}).status_code == 200
    assert client.post("/voice/dictionary", json={"action": "add", "term": "ליאורה", "lang": "he"}).status_code == 200
    r = client.post("/voice/dictionary", json={"action": "edit", "term": "quillfeather", "to": "QuillFeather", "lang": "both"})
    assert r.status_code == 200
    got = client.get("/voice/dictionary").json()
    assert [(e["term"], e["lang"], e["source"]) for e in got["entries"]] == [("QuillFeather", "both", "manual"),
                                                                            ("ליאורה", "he", "manual")]
    assert got["cap"] == vocabulary.CAP and got["full"] is False and got["learn"] is True
    assert client.request("DELETE", "/voice/dictionary", params={"term": "ליאורה"}).status_code == 200


@pytest.mark.parametrize("term", ["yes", "go ahead", "כן", "sk-live-4f9a8b7c6d5e4f3a2b1c0d9e8f7a6b5c", "", "x" * 41])
def test_the_route_refuses_consent_words_secrets_and_junk(voc, term):
    _, client = voc
    r = client.post("/voice/dictionary", json={"action": "add", "term": term})
    assert r.status_code == 400
    assert client.get("/voice/dictionary").json()["entries"] == []


def test_an_edit_into_a_consent_word_is_refused(voc):
    _, client = voc
    client.post("/voice/dictionary", json={"action": "add", "term": "Quillfeather"})
    assert client.post("/voice/dictionary", json={"action": "edit", "term": "Quillfeather", "to": "Okay"}).status_code == 400


def test_bad_bodies_are_400_and_a_full_dictionary_is_409(voc, monkeypatch):
    _, client = voc
    assert client.post("/voice/dictionary", json=[1]).status_code == 400
    assert client.post("/voice/dictionary", json={"action": "nope"}).status_code == 400
    assert client.post("/voice/dictionary", json={"action": "add", "term": "a1", "lang": "fr"}).status_code == 400
    monkeypatch.setattr(vocabulary, "CAP", 1)
    assert client.post("/voice/dictionary", json={"action": "add", "term": "alfa1"}).status_code == 200
    assert client.post("/voice/dictionary", json={"action": "add", "term": "bravo2"}).status_code == 409


def test_suggestions_add_and_ignore(voc):
    d, client = voc
    add(d, "a", "lantern")
    d.REGISTRY.sessions["a"].brief = {"people_and_names": ["Quillfeather", "Zentrak", "okay"]}
    got = client.get("/voice/dictionary").json()["suggestions"]
    assert [(x["term"], x["session"]) for x in got] == [("Quillfeather", "lantern"), ("Zentrak", "lantern")]
    client.post("/voice/dictionary", json={"action": "add", "term": "Quillfeather", "session": "lantern"})
    client.post("/voice/dictionary", json={"action": "ignore", "term": "Zentrak"})
    got = client.get("/voice/dictionary").json()
    assert got["suggestions"] == [] and got["ignored"] == ["Zentrak"]
    assert [(e["term"], e["source"]) for e in got["entries"]] == [("Quillfeather", "session")]
    assert client.post("/voice/dictionary", json={"action": "unignore", "term": "Zentrak"}).status_code == 200
    assert [x["term"] for x in client.get("/voice/dictionary").json()["suggestions"]] == ["Zentrak"]


def test_other_web_pages_cannot_change_the_dictionary(voc):
    _, client = voc
    evil = {"origin": "https://evil.example"}
    assert client.post("/voice/dictionary", json={"action": "add", "term": "Quillfeather"}, headers=evil).status_code == 403
    assert client.request("DELETE", "/voice/dictionary", params={"term": "x"}, headers=evil).status_code == 403
    assert client.get("/voice/dictionary", headers=evil).status_code == 403


def test_the_phone_key_reaches_the_dictionary():
    import guards
    assert "/voice/dictionary" in guards._PHONE_PATHS


def test_the_recogniser_gets_the_dictionary_first_and_no_consent_words(voc, monkeypatch):
    d, client = voc
    client.post("/voice/dictionary", json={"action": "add", "term": "Quillfeather"})
    add(d, "a", "okay/main")
    monkeypatch.setattr(d, "_git_files", lambda cwd, depth: "")
    out = d._recognition_terms()
    assert out[0] == "Quillfeather" and "okay" not in out and "main" in out


def test_a_call_starts_without_git_holding_the_loop(voc, monkeypatch):
    """From live runs on a busy Mac: each call start stalled the daemon's loop for up to 5.6 s in _git_files, once per
    session and twice over (the ears and the echo mirror each asked for the terms), with the call's socket waiting."""
    import time

    d, _ = voc
    for i in range(4):
        add(d, f"s{i}", f"repo{i}/main", cwd=f"/tmp/repo{i}")
    asked = []

    def slow_git(cwd, timeout):
        asked.append(cwd)
        time.sleep(0.2)
        return "pricing/rules.py\0docs/guide.md\0"

    monkeypatch.setattr(d, "_git_files", slow_git)

    async def start():
        ticks = []

        async def tick():
            while True:
                ticks.append(time.monotonic())
                await asyncio.sleep(0.01)

        ticker = asyncio.create_task(tick())
        began = time.monotonic()
        listed = await d._listed_repos()
        took = time.monotonic() - began
        ticker.cancel()
        return listed, took, max(b - a for a, b in zip(ticks, ticks[1:]))

    listed, took, longest = asyncio.run(start())
    assert sorted(listed) == [f"/tmp/repo{i}" for i in range(4)] and len(asked) == 4
    assert longest < 0.1, "the loop kept turning while git ran"
    assert took < 0.6, "the repositories are listed together, not one after another"
    asked.clear()
    terms = d._recognition_terms(listed)
    assert "pricing" in terms and "docs" in terms and not asked  # the terms come from what was listed: no git again


def test_the_brain_is_told_how_to_spell_the_names(voc):
    d, client = voc
    client.post("/voice/dictionary", json={"action": "add", "term": "Quillfeather"})
    assert "spell them this way" in d._brain_context() and "Quillfeather" in d._brain_context()


def test_the_clean_up_rewrite_is_given_the_names(voc, monkeypatch):
    d, client = voc
    client.post("/voice/dictionary", json={"action": "add", "term": "Quillfeather"})
    prompts = []

    async def text(model, prompt, *a, **k):
        prompts.append(prompt)
        return "Open Quillfeather."
    monkeypatch.setattr(d.vendors, "text", text)

    async def go():
        d.state.polish = True
        d._remember("user", "open quill feather")
        await asyncio.sleep(0.05)
    asyncio.run(go())
    assert prompts and "Quillfeather" in prompts[0]


def test_there_is_no_apply_now_a_change_reaches_the_ears_on_the_next_call(voc):
    """A live spike: Pipecat's Soniox reconnect waits for a user-turn end that Pointe's own turn handling never sends,
    so an in-place restart lagged a whole utterance. The plan's fallback ships: the next call."""
    _, client = voc
    assert client.post("/voice/dictionary", json={"action": "apply"}).status_code == 400
    assert "can_apply" not in client.get("/voice/dictionary").json()
    assert not hasattr(vocabulary, "apply_frame")


def test_status_counts_and_hits_from_what_the_user_says(voc):
    d, client = voc
    client.post("/voice/dictionary", json={"action": "add", "term": "Quillfeather"})
    heard(d, "ask Quillfeather for the logs")
    [entry] = client.get("/voice/dictionary").json()["entries"]
    assert entry["hits"] == 1
    assert client.get("/voice/status").json()["dictionary"]["count"] == 1


def test_a_learned_term_never_makes_a_non_answer_count_as_a_yes(voc):
    """Every learning path refuses consent words, so nothing in the dictionary can bias the ears toward one; and
    the consent rules themselves never read the dictionary."""
    import guards
    d, client = voc
    for path in [lambda: client.post("/voice/dictionary", json={"action": "add", "term": "Yeah"}),
                 lambda: client.post("/voice/dictionary", json={"action": "add", "term": "תאשר", "lang": "he"})]:
        assert path().status_code == 400
    turn = heard(d, "that is a chain")
    client.post("/voice/correct", json={"id": turn, "text": "that is a Yes-man"})
    turn = heard(d, "tell it to precede")
    client.post("/voice/correct", json={"id": turn, "text": "tell it to Proceed"})
    assert d.DICTIONARY.entries == []
    assert all(vocabulary.refusal(t) is None for t in d._recognition_terms())
    assert guards.consent("the bluebell build") == guards.consent("the build")


# ---------- a meeting's room ----------

def test_words_from_a_meeting_are_never_learned(voc, monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_meeting_daemon import _meeting_ready, _say, _start
    d, client = voc
    monkeypatch.setattr(d, "DICTIONARY", Dictionary(Path(os.environ["CLAUDE_VOICE_STATE"]) / "dict-meeting.json"))
    turn = heard(d, "open the blue bell repo")
    _meeting_ready(d, monkeypatch)
    d.state.connected_at = 1.0
    _start(d)
    _say(d, "1", "Our vendor is Quillfeather and the repo is Zentrak-9.")
    _say(d, "2", "Dana owns the Okta rollout.")
    r = client.post("/voice/correct", json={"id": turn, "text": "open the bluebell repo"})
    assert r.json().get("learned", []) == []
    assert d.DICTIONARY.entries == []
    assert client.get("/voice/dictionary").json()["suggestions"] == []

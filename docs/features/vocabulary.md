# Self-learning vocabulary

You say `bluebell` and the ears write "blue bell". Fix it once in the transcript, and from the next call on it is heard
right, on the page and the phone, in English and in Hebrew sentences. Repository, function and library names stop being
daily friction.

The rules live in `vocabulary.py`. The daemon calls it from `/voice/correct`, from the recognition hints it gives the
ears, from the voice model's context, and from the clean-up rewrite.

## Use it

- **Fix a word** in the conversation (the correction you already use). Pointe learns the term and shows
  "Learned: <term>".
- **The Dictionary sheet**: Settings → Dictionary on the page, Settings menu → Dictionary in the app (same sheet, same
  copy; a unit test checks the copy matches word for word). It lists each term with its language and where it came
  from, lets you add, edit and delete, and offers names found in your sessions to add or ignore.
- **Learning off**: the pref `dictionary.learn` (both clients). It stops learning and suggestions. Names from session
  notes still reach the ears as hints.

A new term applies from the next call. Restarting recognition mid-call was tried: the restart came one utterance late,
so it was not shipped.

## What a correction teaches

The daemon diffs your fix against what the ears first wrote for that turn, and learns only what the fix changed:

- identifiers (a digit, `-._/`, camelCase);
- a word the ears split ("Kestrel Bay" to "Kestrelbay");
- capitalised names, up to three words;
- an uncommon word that replaced a misheard one.

It never learns a grammar fix (inflections), a case-only fix, a common word, a split word, a rewritten sentence, or more
than 3 terms from one fix. Putting a fix back does not teach the misheard word. It learns nothing from a typed turn,
during a meeting, or with learning off.

**Hebrew** words are not learned from a fix: Hebrew has no capital letters and is heavily inflected, so the code cannot
tell a name from a grammar fix. A Latin name inside a Hebrew sentence is learned for both languages. Add a Hebrew name
by hand. The misheard Hebrew spelling is never stored, because it would bias the ears toward the mistake.

## Safety

A recognition hint biases what the ears hear, and biasing toward "yes" would be a safety bug. So no term, from any
source (a correction, a manual add, an edit, a suggestion, a session or folder name, a hand-edited file), may contain a
consent word, a stop word or an interrupt word, in English or Hebrew (Hebrew prefixes included). No term may be anything
the credential mask (`readout.mask`) would hide.

## What the ears and the voice model get

The ears get, in order: the dictionary (most heard first), session names, names from the session notes (at most 12 per
session, never stored), and folder names, up to 400 terms. The echo stream gets the same list. The voice model gets
`[names the user uses, spell them this way in anything you send]`, so a request sent to a session carries the right
spelling.

These hints go to the ears vendor. See [Privacy](../../README.md#privacy).

## Measured

`bench/vocab_bench.py`, report in [`bench/results/vocab.md`](../../bench/results/vocab.md): 12 invented names in English
and Hebrew sentences, 2 synthetic voices, clean and with 12 dB noise, Soniox stt-rt-v5. The name was spelled right 25 of
64 times without hints and 60 of 64 with them. The hints fixed 35 clips and broke none. Word error on control sentences
was 0.048 both ways, and no non-answer was heard as a bare yes or no. The dictionary held exactly the names that were
said, so this is the best case.

`tests/e2e/page_dictionary.py --live` checks it end to end: a misheard name is fixed on the page, and the next call
hears it right.

## Limits

- When the dictionary is full (400), new terms are refused and learning stops; the sheet shows "Full". Rarely heard
  terms are not evicted.
- Speaker names from meetings are not suggested.

## API

| Route | Body / query | Returns |
|---|---|---|
| `GET /voice/dictionary` | | `{entries: [{term, lang: en\|he\|both, source: correction\|manual\|session, hits, added_at, confirmed}], suggestions, ignored, count, cap, full, learn, learned_this_call, problem}` |
| `POST /voice/dictionary` | `{action: add, term, lang?, session?}`, `{action: edit, term, to?, lang?}`, `{action: ignore\|unignore, term}` | the same; 400 with the reason, 404 unknown term, 409 full |
| `DELETE /voice/dictionary?term=` | | the same; 404 unknown term |
| `POST /voice/correct` | as before | adds `learned: [term]` |

All are reachable with the page cookie, the bearer token and the phone key. Status: `dictionary: {count, cap, full,
learn, learned_this_call: [{term, at}], problem}`. The dictionary is `~/.claude-voice/dictionary.json` (0600).

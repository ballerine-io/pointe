# Clean up my words

Speech comes out with fillers, false starts and half sentences. With Clean up my words on, each line you said shows,
under the words the ears heard, one or two clear sentences that say the same thing. It changes what you see, not what
the voice hears or does.

The code is `_polish_later` in `pointe/daemon.py`: a small prompt to the checker model, the same model that checks each send
against your words.

## Use it

- **Voice:** "clean up my words" turns it on; "stop cleaning my words" or "clean my words off" turns it off
  ([quick settings](quick-settings.md#use-it)).
- **Page:** the Clean words chip at the top. In a narrow window it is under More (the ••• at the top), with its words.
- **iPhone app:** the Quick settings button at the top, or Settings (••• at the top) → Clean up my words, under Your
  words. Your newest line shows "cleaning up" while it waits.
- **Mac app:** the Clean words chip in the title strip, Voice → Clean Up My Words (⇧⌘K), or Settings → Clean up my words.

It is one daemon setting (`polish`), so every client agrees, and it is saved: it stays on across calls and restarts.

## Rules

- **Shown only.** The clean version is kept beside the line and sent to the screens. The voice model, the sends and the
  approvals get what the ears heard, as with the switch off.
- **Your words, reworded.** The prompt asks for your meaning, names and language kept exactly, fillers and false
  starts dropped, nothing added, and never an answer to what you said. Names in the [dictionary](vocabulary.md) are
  spelled its way.
- **Only when it differs.** A clean version that matches what was heard is not shown twice.
- **A fix wins.** When you fix what was heard, the clean version of that line is dropped.

## Limits

- Each line is a call to the checker model. If it does not answer within 5 s, that line shows no clean version.
- Each line you say goes, as text, to the checker's vendor, which already sees your words to check sends. In
  [fully local](local.md) mode the checker is the local model.

## API

| | |
|---|---|
| `POST /voice/polish` | `{on: true\|false}` → `{polish}`, for older apps; the same as `POST /voice/prefs {"polish": …}`. Page cookie, bearer token, phone key |
| status `polish` | the switch |
| status `talk[].understood` | the clean version of a line you said, when there is one |

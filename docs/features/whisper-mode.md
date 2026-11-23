# Whisper mode

In an open office you whisper; Pointe hears it, answers briefly and quietly, and typing is one tap away. Whisper mode
changes how the call sounds, never what a word can do.

The rules live in `whisper.py` (phrases, gains, the voice-detector profile, the reply rule).

## Use it

- **Voice:** "whisper mode", "let's whisper", "מצב לחישה" turn it on. "Back to normal", "normal voice", "stop
  whispering", "חזרה לרגיל" turn it off, only while it is on. A bare "normal" is not a phrase. The voice model never gets
  these words.
- **Page:** a Whisper button in the dock. A card shows what the mode does, "Whisper recognition is limited; type when it
  matters.", a push-to-talk suggestion, and Back to normal. The compose box opens and takes focus.
- **iPhone app:** a Whisper toggle in the Settings (⋯) menu, the same card and copy, and the keyboard up.
- **Mac app:** the iPhone app's screens: Settings (••• at the top, or ⌘,) → Whisper, and the same card.

It is one setting for both clients, kept across calls and reconnects, so a dropped call does not come back loud in an
open office.

## What it does

- **Output:** the bot plays at half volume, from the next audio chunk. The change is made in the daemon, so it works
  for every client.
- **Input:** the microphone is raised (x2.5, through a soft limiter that never clips), and the voice detector switches
  to a whisper profile. A meeting's room audio is not raised.
- **Replies:** one short sentence, at most 20 words; anything longer is pointed to the screen.

## Approvals and the voice lock: unchanged

- No code path reads the setting at a yes. A whispered yes or no goes through exactly the same check as a spoken one.
  `tests/test_whisper.py` runs ten answers through the approval code with the mode off and on and asserts the same
  outcomes; a deliberate bug that let the mode change approvals failed five of them.
- Whisper mode never lowers the [voice lock](voice-lock.md). A voiceprint is learned from your normal voice, and a
  whisper scores low against it: on the synthetic bench no unvoiced whispered sentence reached the strong-match
  threshold (mean score 0.37, against 0.62 for the normal voice; impostors at most 0.26). So with the lock on, a whispered
  yes usually does not count on its own, and the request waits for a tap. Both clients say so on the card.

## With other modes

- **Drive mode holds it.** While driving, the bot plays at full volume and drive mode's rules apply; whisper mode
  applies again when drive mode ends.
- **Challenge:** both apply.
- **Meeting:** the room's audio is not raised; the bot's output is still halved.

## Measured

Synthetic only: `bench/whisper_bench.py`, report in [`bench/results/whisper.md`](../../bench/results/whisper.md). Two
ElevenLabs voices x 23 lines (English commands, yes/no, the phrases, Hebrew). "Unvoiced" whispers are re-synthesised
over noise; "breathy" is a soft voice from a TTS whisper tag. Office noise at -55 dBFS.

| | Soniox word error | yes/no right | Voice detector (default → whisper profile and gain) |
|---|---|---|---|
| normal | 1.2% | 12/12 | 46/46 |
| unvoiced, -18 dB | 1.4% | 12/12 | 33/46 → 41/46 |
| unvoiced, -30 dB | 18.4% (17.6% with gain) | 10/12, no answer flipped | 1/46 → 23/46 |
| breathy, -18 dB | 0.4% | 12/12 | 40/46 → 43/46 |

Misheard short answers failed safe ("No." heard as "Yellow.", "Yes, go ahead." as "Yes, Dorian.": neither is a yes).
Neither voice-detector profile fired on 60 s of office noise with typing.

A live run (`tests/e2e/whisper.py`: the real daemon, Soniox, brain and mouth, with the speaker leaking into the mic): a
whispered "whisper mode" turned it on; a whispered question was answered in 8 words (17 without the mode); a whispered
yes approved and a whispered no denied after the read-out; a whispered yes over the read-out did not approve. One run
heard "Back to normal." as "Back to Denied."; a repeat worked.

## Limits

- **No recorded human whispers.** All numbers above are synthetic, which is why the card always says recognition is
  limited.
- The ears' end-of-speech timing is unchanged for whispers. A faster setting was measured but needs a reconnect
  mid-call.
- A realtime front (`CLAUDE_VOICE_FRONT=gemini|openai`) gets the audio changes but not the reply rule.

## API

- Pref `whisper` (bool, default false) in `GET/POST /voice/prefs`.
- Status `whisper: {on, held, output_gain, max_words, suggest_ptt, lock_note}`. `held` is `"drive"` while drive mode
  suspends it; `suggest_ptt` is true while it applies and the microphone is not push to talk; `lock_note` is the copy
  both clients show when the voice lock is on.

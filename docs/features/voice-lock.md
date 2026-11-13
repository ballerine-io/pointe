# Voice lock

Only your voice commands Pointe. Someone else in the room (a colleague, a TV) is heard by the microphone but does not
count. Pointe already requires a bound yes for approvals; the voice lock adds "and it was you".

The rules live in `speaker.py`. The daemon asks it on each final utterance (`SonioxEars._owner_gate`) and on each yes
(`on_user_utterance`).

## Use it

Settings → Voice lock, on the page or in the iPhone app. Enrol during a call: Pointe asks you to read a few lines, and
learns those utterances instead of answering them. Each device (the Mac's microphone, the iPhone) gets its own
voiceprint; scoring compares against every voiceprint and the best one wins.

| Level | What it does |
|---|---|
| **Off** | No check. |
| **Approvals** | A spoken yes counts only in your voice. A no counts from anyone. The default after the first enrolment. |
| **Commands** | Other voices never reach the voice model. They are listed as ignored, with their words, in memory only. |
| **Everything** | The same, and their words are not shown or kept. Live captions stay empty until the final words pass the check. |

Deleting the last voiceprint turns the lock off. The iPhone app asks for Face ID before it lowers the level or deletes a
voiceprint.

## Rules

- **It only narrows.** A match is never consent. Every approval rule still has to hold for your yes; the lock adds "and
  it was your voice" and removes nothing.
- **It fails closed.** No model yet, a model error, a score that takes longer than 0.6 s, under 0.3 s of audio, or a
  damaged voiceprint file: the speech counts as not yours for what the level guards. The page and the app say why. A
  tap, Face ID, the terminal and typed text still work, so a failure costs convenience, never control. The lock is not
  silently lowered when it cannot score: you turned it on, and a silent downgrade would lift it without your knowing.
- **Short words.** A "yes" is too short to score well. It counts on its own only after a strong match (score ≥ 0.55
  with ≥ 1 s of speech) within the last minute, on the same device's voiceprint. Continuity never chains from another
  weak match.
- **Commands and Everything gate at intake**, before the voice model hears the words. Typed text is authenticated by the
  page key or the phone key and is not gated.
- **Barge-in.** Anyone can still cut the bot off at once (scoring needs about a second of audio). When the lock keeps
  that voice's words out, the interrupted report comes back at once.
- **Push to talk.** Only speech is scored, never the silence between a press and your first word.
- **Meetings.** With a voiceprint and the lock on, a meeting turn in your voice marks you as the owner of that speaker
  label, and a "that's me" in another voice is refused. With the lock off, meetings use the label heuristic.
- **Drive mode** uses the voiceprint whenever one is stored, at any level: see [drive mode](drive-mode.md).
- **Whisper mode** never lowers the lock: see [whisper mode](whisper-mode.md).

## Privacy

The voiceprint is biometric data. It is computed and kept only on this Mac, in `~/.claude-voice/voiceprint/` (0700, one
file per device, 0600), and deleted from Settings → Voice lock. No vendor sees the audio for this check or the
voiceprint. The journal records an ignored utterance's length and score, never its words.

The model is 3D-Speaker ERes2Net base (Apache-2.0, 40 MB), run by `sherpa-onnx`. It is downloaded on first use from the
sherpa-onnx GitHub release into `~/.claude-voice/models/`, checked against a pinned SHA-256. See
[THIRD_PARTY.md](../../THIRD_PARTY.md).

## It is not authentication

It is a check against the bystander, not an attacker. A recording of your voice can pass it.

## Measured

`bench/speaker_bench.py`, report in [`bench/results/speaker.md`](../../bench/results/speaker.md): 19 synthetic macOS
voices, each the owner once and an impostor for the others. Equal error rate 1.9% on 2 to 4 s sentences, 2.7% on short
answers ("yes", "go ahead"). A CAM++ model scored about 32% on sentences on the same bench, so ERes2Net was chosen.

The thresholds (`T_HIGH = 0.55`, `T_LOW = 0.35`) come from synthetic voices only. Synthetic voices are steadier than
people. A bench on recorded people (several microphones, a cold, real impostors) has not been run, so Approvals is the
level to use; Commands and Everything are not yet recommended on that evidence.

## Not built

A profile for the bot's own voice as an impostor (the echo guard covers echo), adapting the voiceprint over time, a
reminder to enrol, and a "you sound different today" prompt.

## API

`POST /voice/voiceprint` (page cookie, bearer token, phone key), returns `{voice_lock: <status>}`:

| Body | Does | Errors |
|---|---|---|
| `{action: "enrol", device}` | arms enrolment on the live call | 409: no call, a meeting on, native ears |
| `{action: "cancel"}` | drops an unfinished enrolment | |
| `{action: "delete", device?}` | deletes one device's voiceprint, or all | |
| `{action: "level", level}` | `off`, `approvals`, `commands`, `everything` | 400 bad level; 409 without a voiceprint |

The level is the pref `voice_lock`, readable at `GET /voice/prefs`. `POST /voice/prefs` refuses it, so there is one
write path, where the voiceprint is checked.

Status `voice_lock`: `{level, enrolled, devices: [{device, seconds, segments, enrolled_at}], enrolling, lines, model:
missing|downloading|ready|failed, problem, ignored: {count, last_at, recent: [{at, secs, text?}]}, speaker: null |
{owner, score, at}, unsure_streak}`. `text` in `ignored.recent` appears only at Commands.

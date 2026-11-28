# Quick settings

The few settings you change during a day, one tap away and by voice: reply length, speaking speed, Clean up my words
and Whisper. On the Mac the microphone is in the same row. The daemon keeps every value, so the page, the iPhone and the
Mac agree; only the speed is each device's own (AirPods on the phone, speakers on the Mac).

The code is `pointe/quick.py` (levels, speeds, phrases, the words every surface shares), `conversation.LENGTHS` (the
limits of each level) and `QuickSettings.swift` (both apps).

## Use it

- **Voice:**
  - Reply length: "be more concise", "shorter answers", "keep it shorter from now on" go one level down; "be more
    detailed", "more detail from now on", "longer answers", "be more thorough" one level up; "brief / concise / detailed
    / thorough answers" pick that level. Hebrew: "תהיה יותר תמציתי", "תהיה יותר מפורט", "תשובות קצרות / מפורטות".
  - Speed: "speak faster", "talk faster", "faster voice"; "slow down", "speak slower"; "normal speed", "fastest",
    "slowest". Hebrew: "תדבר יותר מהר", "תדבר לאט יותר", "מהירות רגילה". A speed phrase must be about the voice (speak,
    talk, voice or speech in it, or "normal speed", "fastest", "slowest"); a bare "slow down" counts too. "Speed up the
    tests" is work, and "billing, slow down" is for a session.
  - Clean up my words: "clean up my words"; "stop cleaning my words", "clean my words off". Hebrew: "תנקה את המילים שלי".
  - Whisper: [its own phrases](whisper-mode.md#use-it).

  Each phrase is the whole sentence, caught in code before anything else reads it, except during a meeting or a brain
  dump; Pointe confirms in four words at
  most, a new speed at that speed. "Tell me more" still lengthens one answer and changes no setting.
- **Page:** four chips in the top bar: Reply length and Speed open a menu with a line on each level; Clean words and
  Whisper flip on one click and show a small switch. On a narrow screen they are one Quick settings group under More.
- **iPhone app:** the sliders button at the top opens a half-height sheet: reply length and speed as segmented controls,
  each with a line on what it does, and the two switches. A dot on the button means a quick setting is off its default.
- **Mac app:** chips in the window's title strip, beside Skip: the microphone (Always on, Only when I say Pointe, Push
  to talk), reply length, speed, Clean words, Whisper. The switch above the mic is gone on the Mac. The Voice menu
  repeats them with keys: ⌘1 to ⌘4 reply length, ⌥⌘1 to ⌥⌘5 speed, ⇧⌘K Clean up my words. In a narrow window the
  toggles drop their words and keep their switch.

A change by voice makes its chip glow for a moment on the page and the Mac.

## The levels

| Level | Reply | Session report | Status / overview | "Tell me more" |
|---|---|---|---|---|
| Brief | 12 words, 1 sentence, 2 items | 20 words, 2 sentences | 30 / 40 words | 60 words, 4 sentences |
| Concise (default) | 30 words, 2 sentences, 3 items | 45 words, 3 sentences | 60 / 60 words | 120 words, 8 sentences |
| Detailed | 60 words, 4 sentences, 3 items | 70 words, 4 sentences | 90 / 90 words | 160 words, 10 sentences |
| Thorough | 120 words, 8 sentences, 5 items | 100 words, 6 sentences | 120 / 120 words | 200 words, 12 sentences |

Concise is the length Pointe always had: its limits are the old constants and the brain is told nothing new. At any
other level the brain is told the level's rule and limits before each reply; the limit is still enforced in code
(sent back once, then cut). Drive mode (25 words) and whisper mode (20 words) always win: the limit is the smaller of
the two, at most two sentences. Briefings keep their own Short, Normal and Full.

## Speed

0.8×, 0.9×, 1× (Normal), 1.1×, 1.2×, the same steps on every voice, so Faster stays faster when the voice falls back to
another vendor. The next sentence takes a new speed (a Pipecat settings frame, queued behind what is already being said).

| Voice | How |
|---|---|
| ElevenLabs | `voice_settings.speed` (0.7 to 1.2) |
| Soniox | `speed` (0.7 to 1.3) |
| OpenAI | `speed` (0.25 to 4.0); whether `gpt-4o-mini-tts` honours it is not measured |
| Kokoro (both local builds) | `speed` (0.5 to 2.0) |
| Gemini | no number, only a style prompt: the speed control is hidden |

A realtime front (`CLAUDE_VOICE_FRONT=gemini|openai`) speaks with its own voice: the speed control is hidden there too.
At 1× nothing new is sent to any vendor.

## The change log

Each change of a daemon setting adds a line to `~/.claude-voice/settings-changes.log`: the time, the key and where it
came from (`voice` for a spoken change, `app` for every other, including the few the daemon makes itself), never a value and never words. Speed names the device (`voice.speed.iphone`). The file is
0600, keeps its newer half past 256 KB, and nothing in Pointe reads it or sends it anywhere: it is there to check this
row against real use.

## API

| | |
|---|---|
| `GET /voice/status` | `quick: {length, speeds: {mac, iphone, page}, speed_shown, by_voice: {key, at} \| null}`, and `polish` |
| `POST /voice/prefs` | `{"replies.length": "brief"}`, `{"voice.speed": {"iphone": 1.1}}` (a device sends only its own; the others stay), `{"polish": true}`, `{"whisper": true}` |

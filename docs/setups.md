# Setups: which keys Pointe needs, and for what

Written by `tools/setups.py` from `setups.py`: edit those, not this file.

Why its own keys? Pointe runs its own models next to Claude Code: the brain, the reader and the checker, the ears and the voice. Your Claude subscription (Pro or Max) runs Claude Code, but has no interface other apps can use, so Pointe's voice needs its own API key from console.anthropic.com, or one Gemini or OpenAI key. An API key is billed per use: about $1 for a busy hour of talk.

Pointe has five roles. Each setup fills all five, with the keys in its row:

- **brain**: understands you and replies
- **reader**: turns session output into short reports
- **checker**: a safety check on each send and approval
- **ears**: speech to text
- **mouth**: the voice

| Setup | Keys | What each one does | Measured | Speed | A busy hour | Where your words go | Best for |
|---|---|---|---|---|---|---|---|
| **Free start** (`free`) | Gemini | Gemini: brain, reader, checker, ears, mouth | 28 of 35 audio checks on a paid key; a free-tier key ran out of quota in the run (3 of 19) (bench/results/combinations.md, "Gemini only")<br>brain 94.9% against Sonnet's 91.9%: within the margin (the 95% intervals overlap) (docs/benchmarks.md, "Brain and reader")<br>ears 92.0% of intents against Soniox's 95.9%; no echo guard, so use headphones (docs/benchmarks.md, ears table) | replies took 4.0 to 4.5 s (bench/results/combinations.md, "Gemini only") | $0 until the free quota ends; about $0.70 to $0.95 with billing on | Speech and session text go to Google. On the free tier Google may use and review them: not for confidential work. | trying Pointe at no cost |
| **One OpenAI key** (`openai`) | OpenAI | OpenAI: brain, reader, checker, ears, mouth | 24 of 35 audio checks (bench/results/combinations.md, "OpenAI only")<br>brain 87.9% against Sonnet's 95.5% in the same run: the 95% intervals overlap (bench/results/brain_substance.md, gpt-6-sol (v7openai))<br>ears 90.9% of intents; no echo guard, so use headphones (docs/benchmarks.md, ears table) | whole replies not measured; the brain answers in 2.4 s at the median (bench/results/brain_substance.md, gpt-6-sol (v7openai)) | about $0.95 | Speech and session text go to OpenAI. | people who already pay for OpenAI |
| **Two keys** (`two`) | Soniox + Anthropic | Anthropic: brain, reader, checker; Soniox: ears, mouth | 30 of 35 audio checks (31 on a rerun); echo guard 3 of 4, so speakers work (bench/results/combinations.md, "Anthropic, Soniox")<br>ears 95.9% of intents, the highest measured (docs/benchmarks.md, ears table, Soniox v6) | whole replies not measured; the brain answers in 1.8 s at the median; in the voice benchmark the voice starts in 301 ms (the voice alone, not a call) (docs/benchmarks.md, "Brain and reader" and the mouth table) | about $1.20 | Speech goes to Soniox; session text to Anthropic. | the best ears with two accounts, on laptop speakers |
| **Fastest and most accurate voice** (`full`) | Anthropic + Soniox + ElevenLabs + Gemini | Anthropic: brain, reader; Gemini: checker; Soniox: ears; ElevenLabs: mouth | 34 of 35 audio checks, echo guard 4 of 4: the highest whole-setup result (bench/results/combinations.md, "(default)")<br>ears 95.9% of intents (next: Gemini 92.0%) (docs/benchmarks.md, ears table)<br>voice word error 0.00 in English, the lowest (docs/benchmarks.md, mouth table, eleven_v4_turbo)<br>brain: Sonnet 91.9% against Gemini's 94.9%, within the margin; Sonnet is the faster one (docs/benchmarks.md, "Brain and reader") | replies in 2.4 s at the median (2.0 to 2.6), the fastest measured (docs/features/voice-stays-local.md, "Measured")<br>in the voice benchmark the voice starts in 213 ms (the voice alone, not a call) (docs/benchmarks.md, mouth table) | about $1 | Speech goes to Soniox; session text to Anthropic and Gemini (paid tier); the replies' text to ElevenLabs. | daily use |
| **Voice stays on your Mac** (`voice-local`)<br>Needs an Apple-silicon Mac, about 2 GB of disk, headphones | Anthropic (Gemini optional) | Anthropic: brain, reader, checker; this Mac: ears, mouth | 30 of 35 audio checks, with Anthropic and Gemini keys (bench/results/combinations.md, "Voice stays on your Mac")<br>ears 82.7% of intents on the Mac, against Soniox's 94.6% in the same run; English speech only (docs/features/voice-stays-local.md, "Measured") | replies in 4.1 s at the median (docs/features/voice-stays-local.md, "Measured") | about $0.40 (Anthropic and Gemini) | No audio leaves the Mac. Your words, as text, and session text go to Anthropic (and Gemini, if set). | confidential work where text may leave the Mac but your voice may not |
| **Fully local** (`local`)<br>Needs an Apple-silicon Mac with 32 GB of memory, about 19 GB of disk, headphones; English only | none | this Mac: brain, reader, checker, ears, mouth | 10 of 19 one-session audio checks, every approval check among them (bench/results/combinations.md, "None: fully local")<br>brain 76.9% against Sonnet's 91.9% (docs/benchmarks.md, "Fully local") | replies took 5.8 to 11.6 s (bench/results/combinations.md, "None: fully local") | $0 | Nothing leaves the Mac. | work where nothing may leave the Mac, on a 32 GB Mac |

A busy hour: 60 spoken replies, 10 session reports and the call open for the hour, by arithmetic from measured and list prices (docs/benchmarks.md, "Cost arithmetic"), not a metered bill. "Measured" is the real audio suite (`tests/e2e/run_all.sh`, 35 checks: 19 single-session, 12
multi-session, 4 echo), one run per setup on 2026-11-13 with only that setup's keys visible, and the per-role benchmarks
in `bench/`. "Not measured" means no run covered it. Voices are synthetic; no setup was measured on a real human call.

No setup is best on every axis. The fastest and most accurate voice has the highest whole-setup result and the best ears
and voice, but its brain (Sonnet) and the Free start's brain (Gemini) are within the margin of each other: Gemini passed
more cases, Sonnet answered faster. Pick by what matters to you:

- **Best for trying Pointe at no cost**: Free start (`pointe setup free`)
- **Best for people who already pay for OpenAI**: One OpenAI key (`pointe setup openai`)
- **Best for the best ears with two accounts, on laptop speakers**: Two keys (`pointe setup two`)
- **Best for daily use**: Fastest and most accurate voice (`pointe setup full`)
- **Best for confidential work where text may leave the Mac but your voice may not**: Voice stays on your Mac (`pointe setup voice-local`)
- **Best for work where nothing may leave the Mac, on a 32 GB Mac**: Fully local (`pointe setup local`)

With nothing chosen, `/pointe:setup` asks one question, "Start with Free start?": one key, about 5
minutes, and this table only if you ask for the other setups.

## Choosing and switching

`pointe setup` shows this table and the setup in use; `pointe setup <id>` switches, and from then on the daemon uses
exactly that setup's vendors, whatever other keys the Keychain holds. `pointe key <vendor>` saves a key through a Mac
window after opening the vendor's key page, checks it with one tiny live call (and asks again when the vendor refuses
it), and restarts Pointe to use it; `pointe key check <vendor>` checks a saved key. After `pointe setup <id>`, restart
with `pointe restart`. The page's Settings, Model keys, and the Mac app's do the same with buttons: Add… or Replace… for a
key, Use this setup for a setup, each shown with the key as In use, Needed or Optional.

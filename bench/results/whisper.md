# Whisper mode: synthetic bench

Synthetic only: two ElevenLabs voices, 23 utterances each (12 commands, 7 short answers and mode phrases, 4 Hebrew). No person whispered for this; see the module docstring of `bench/whisper_bench.py` for how the whispers are made, and treat every number as a direction, not a promise.

Voiced-frame share: normal 68%, unvoiced 3%, breathy 65% (a real whisper is near 0%).

## Soniox (stt-rt-v5, real-time streaming, the daemon's settings)

| Variant | Input gain | Config | Clips | WER | Exact | Yes/no right | Endpoint p50 / p90 (s) |
|---|---|---|---|---|---|---|---|
| normal | none | daemon | 46 | 1.2% | 44/46 | 12/12 | 0.57 / 3.07 |
| unvoiced-18 | none | daemon | 46 | 1.4% | 42/46 | 12/12 | 0.47 / 2.91 |
| unvoiced-18 | none | plan-whisper | 46 | 1.4% | 42/46 | 12/12 | 0.39 / 2.25 |
| unvoiced-18 | x2.5 | daemon | 46 | 1.4% | 42/46 | 12/12 | 0.50 / 3.05 |
| unvoiced-30 | none | daemon | 46 | 18.4% | 28/46 | 10/12 | 0.55 / 3.17 |
| unvoiced-30 | x2.5 | daemon | 46 | 17.6% | 30/46 | 9/12 | 0.56 / 3.07 |
| breathy-18 | none | daemon | 46 | 0.4% | 45/46 | 12/12 | 0.41 / 3.12 |
| breathy-18 | x2.5 | daemon | 46 | 0.6% | 44/46 | 12/12 | 0.41 / 3.12 |

Office noise alone (20 s): gain none: ''; gain x2.5: ''

Yes/no heard wrong (a flipped answer is the dangerous case; a missing one only waits):

- unvoiced-30 none sarah: 'No.' heard as 'Yellow.'
- unvoiced-30 x2.5 sarah: 'No.' heard as 'Yellow.'
- unvoiced-30 none sarah: 'Yes, go ahead.' heard as 'Yes, Dorian.'
- unvoiced-30 x2.5 sarah: 'Yes, go ahead.' heard as 'Yes, Dorian.'
- unvoiced-30 x2.5 george: 'No.' heard as ''

## Voice detector (Silero, offline)

Whisper profile: `{'confidence': 0.5, 'min_volume': 0.35, 'start_secs': 0.2, 'stop_secs': 0.4}`; default: pipecat's `VADParams()`.

| Variant | Input gain | Profile | Detected | Onset p50 (s) |
|---|---|---|---|---|
| normal | none | default | 46/46 | 0.32 |
| normal | none | whisper | 46/46 | 0.26 |
| normal | x2.5 | default | 46/46 | 0.28 |
| normal | x2.5 | whisper | 46/46 | 0.26 |
| unvoiced-18 | none | default | 33/46 | 0.64 |
| unvoiced-18 | none | whisper | 39/46 | 0.54 |
| unvoiced-18 | x2.5 | default | 39/46 | 0.52 |
| unvoiced-18 | x2.5 | whisper | 41/46 | 0.38 |
| unvoiced-30 | none | default | 1/46 | 2.46 |
| unvoiced-30 | none | whisper | 6/46 | 1.34 |
| unvoiced-30 | x2.5 | default | 17/46 | 1.02 |
| unvoiced-30 | x2.5 | whisper | 23/46 | 0.74 |
| breathy-18 | none | default | 40/46 | 0.52 |
| breathy-18 | none | whisper | 41/46 | 0.42 |
| breathy-18 | x2.5 | default | 42/46 | 0.42 |
| breathy-18 | x2.5 | whisper | 43/46 | 0.36 |

False starts on 60 s of office noise (-50 dBFS) with typing clicks:

- gain none, default: 0 starts, 0.0 s marked as speech
- gain none, whisper: 0 starts, 0.0 s marked as speech
- gain x2.5, default: 0 starts, 0.0 s marked as speech
- gain x2.5, whisper: 0 starts, 0.0 s marked as speech

## Voice lock (ERes2Net, enrolled on four normal sentences)

T_HIGH 0.55, T_LOW 0.35, MIN_SECS 1.0.

| Variant | Owner: mean score | Owner: ≥ T_HIGH (sentences) | Owner: ≥ T_LOW (all) | Other voice: max score |
|---|---|---|---|---|
| normal | 0.62 | 24/24 | 45/46 | 0.20 |
| unvoiced-18 | 0.37 | 0/24 | 29/46 | 0.20 |
| unvoiced-30 | 0.30 | 0/24 | 15/46 | 0.26 |
| breathy-18 | 0.43 | 8/24 | 35/46 | 0.18 |

## Loudness barge-in (LevelGate, simulated echo at -30 dB)

Frames (20 ms) where loudness alone would cut the bot: before the user speaks (false) and during a whispered "no, don't run it" (hit). Input gain 2.5 rows match their 1.0 rows (gain scales echo and voice alike) and are left out.

| Bot volume | Whisper level | Input gain | RMS floor | False | Hit | First cut (s) |
|---|---|---|---|---|---|---|
| 100% | -18 dB | 1.0 | 300 | 0 | 14 | 0.16 |
| 100% | -18 dB | 1.0 | 120 | 0 | 14 | 0.16 |
| 100% | -24 dB | 1.0 | 300 | 0 | 0 | - |
| 100% | -24 dB | 1.0 | 120 | 0 | 0 | - |
| 100% | -30 dB | 1.0 | 300 | 0 | 0 | - |
| 100% | -30 dB | 1.0 | 120 | 0 | 0 | - |
| 50% | -18 dB | 1.0 | 300 | 0 | 17 | 0.12 |
| 50% | -18 dB | 1.0 | 120 | 0 | 17 | 0.12 |
| 50% | -24 dB | 1.0 | 300 | 0 | 11 | 0.20 |
| 50% | -24 dB | 1.0 | 120 | 0 | 11 | 0.20 |
| 50% | -30 dB | 1.0 | 300 | 0 | 0 | - |
| 50% | -30 dB | 1.0 | 120 | 0 | 0 | - |
| headphones | -18 dB | 1.0 | 300 | 0 | 17 | 0.12 |
| headphones | -18 dB | 1.0 | 120 | 0 | 17 | 0.12 |
| headphones | -24 dB | 1.0 | 300 | 0 | 13 | 0.18 |
| headphones | -24 dB | 1.0 | 120 | 0 | 13 | 0.18 |
| headphones | -30 dB | 1.0 | 300 | 0 | 0 | - |
| headphones | -30 dB | 1.0 | 120 | 0 | 0 | - |

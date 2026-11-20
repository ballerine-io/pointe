# Soniox stt-rt-v5 against stt-rt-v6, with the daemon's settings (2026-11-20)

Why: Soniox removes `stt-rt-v5` on 2026-12-15, and after that date a request for it is served by `stt-rt-v6`
([models and changelog](https://docs.soniox.com/stt/models), read 2026-11-20). The changelog calls v6 "fully compatible"
with v5: the same request, the same `finalize` and `<fin>`, the same `<end>` and endpoint fields. The earlier comparison
(`report.txt`, 2026-11-11/12) used Soniox's default endpoint settings; the daemon does not (`vendors.build_ears`:
`endpoint_sensitivity` -0.5, `max_endpoint_delay_ms` 2500, hints en and he). This run uses the daemon's settings.

Method: `bench/stt_extra.py run --systems soniox-daemon-v5,soniox-daemon-v6`, the 560 clips of the current corpus
(70 utterances x 4 synthetic voices x clean and noisy), the two models interleaved in one shuffled job list on one laptop
and one home network (load average 44 falling to 22), so load and network fell on both alike. Scored by `stt_bench.report`
(WER, CER, the blind gemini-3.5-flash intent judge). 15 streams closed by Soniox were run again; every clip has both.

## Accuracy

| | intent ok | entities ok | WER | CER |
|---|---|---|---|---|
| v5, all 560 | 94.6% [92.7-96.4] | 95.2% | 0.061 | 0.037 |
| v6, all 560 | 95.9% [94.3-97.3] | 96.2% | 0.064 | 0.047 |
| v5, Hebrew 120 | 98.3% [95.8-100] | 99.2% | 0.007 | 0.003 |
| v6, Hebrew 120 | 98.3% [95.8-100] | 100.0% | 0.006 | 0.001 |
| v5, mixed 160 | 90.6% [86.2-95.0] | 91.9% | 0.141 | 0.111 |
| v6, mixed 160 | 95.0% [91.2-98.1] | 95.6% | 0.178 | 0.148 |

530 against 537 clips right, exact McNemar p = 0.065: v6 is not worse, and not shown better. Mixed-language WER rises
while intent rises: WER counts an English term written in Hebrew letters as an error.

## Endpoint: speech end to `<end>`

| | p50 | p90 | p95 | over 1 s | over 2.5 s |
|---|---|---|---|---|---|
| v5, all | 0.36 s | 0.82 s | 1.10 s | 6.1% | 1.8% |
| v6, all | 0.38 s | 2.67 s | 3.15 s | 12.3% | 10.9% |
| v5, Hebrew | 0.36 s | 0.85 s | 1.17 s | 8.3% | 0.0% |
| v6, Hebrew | 0.38 s | 3.04 s | 3.18 s | 15.0% | 12.5% |

The median is the same; the tail is not. On 35 of 560 clips v6 gave no `<end>` within the clip's 2.5 s of silence. Those
35 were streamed again with 6 s of silence (`end` measured, these values fill the table above): v6 ended every one, at
3.20 s after speech at the median (max 3.42 s), past the 2.5 s `max_endpoint_delay_ms`; v5 ended the same clips at
0.97 s. With a quiet noise floor in place of digital silence v6 took 3.16 s and v5 2.79 s. With `endpoint_sensitivity`
0 or -0.25 v6 still took 3.09 and 3.16 s: the sensitivity is not what holds them. They are 12 whole commands, mostly
Hebrew and mixed ("תמצא את הקובץ שמגדיר את ההרשאות של המשתמשים." on all 8 voice and noise variants). Not tried:
a lower `max_endpoint_delay_ms` or `endpoint_latency_adjustment_level`; both change when a pause ends a turn, so they need
the turn-taking checks, not this bench.

## On a real call (`tests/e2e/latency.py 2`, 24 English questions)

| | ears: last word to final, p50 / p90 / max | last word to first sound, p50 / p90 | load |
|---|---|---|---|
| v5, 2026-11-20 | 0.40 / 0.49 / 0.55 s | 2.02 / 2.66 s | 6.9 at start, 97 at end |
| v6, 2026-11-20 | 0.47 / 0.60 / 0.75 s | 2.11 / 2.50 s | 5.1 to 6.9 |
| v5, 1.14.0 (`docs/design/conversation-flow.md` §7) | 0.46 / 0.52 s | 1.86 / 2.21 s | 4.2 to 7.6 |

None of the 24 questions met the late endpoint. `tests/e2e/turn_taking.py` (7/7, turns taken 0.93 to 1.18 s after the real
end, pauses of 1.5 and 2.0 s not cut) and `tests/e2e/ptt.py` (7/7, a press sent as one turn on `<fin>`) passed on v6.

Limits: synthetic voices; one run per clip per model; one laptop and network; the judge is an LLM.

# The turn end tuned for v6 (1.14.6)

The tail above is the daemon's to fix: v5 is served by v6 from 2026-12-15 anyway. Goal: speech end to final transcript
p90 at most 1.0 s, overall and in Hebrew, at most 2% of clips over 2.5 s, intent accuracy no lower, and no pause taken
for a turn end that was not one before.

## What was tried

Soniox documents three controls for v6 ([endpoint detection](https://docs.soniox.com/stt/rt/endpoint-detection), read
2026-11-20): `max_endpoint_delay_ms` (500 to 3000), `endpoint_latency_adjustment_level` (0 to 3) and
`endpoint_sensitivity` (-1 to 1), plus `finalize` ([manual finalization](https://docs.soniox.com/stt/rt/manual-finalization)).
On the 35 clips v6 held, with 6 s of silence after them (`end` after speech, p50):

| setting | p50 | p90 |
|---|---|---|
| today: sensitivity -0.5, max delay 2500 ms | 3.17 s | 3.35 s |
| sensitivity -0.5, max delay 1500 ms | 2.21 s | 2.36 s |
| sensitivity -0.5, max delay 1000 ms | 1.77 s | 1.91 s |
| sensitivity 0, max delay 1500 ms | 2.21 s | 2.37 s |
| latency level 1, sensitivity 0, max delay 2000 ms | 0.61 s | 2.85 s |
| latency level 2 or 3, sensitivity 0, max delay 2500 ms | 3.12 s | 3.25 s |
| latency level 2, sensitivity 0.3, max delay 1500 ms (Soniox's lower-latency start) | 0.05 s | 2.40 s |

v6 ends a held segment about 0.8 s after its own `max_endpoint_delay_ms`, at every value; even the 500 ms minimum would
leave these near 1.3 s. A `finalize` returns `<fin>` 0.25 to 0.34 s after it is sent. So the daemon asks for the words
itself: once the voice detector (Silero, stop 0.2 s) says the user stopped and a whole sentence's settle less 0.3 s has
passed (0.7 s at Normal), it sends `finalize` (`turns.finalize_due`, `PttGate.tick`). The bench runs the same rule with
the same detector (`soniox-v6-fin500`, `-fin700`). A first try timed the silence by word stamps instead: they lag the
audio, so it finalized mid-word ("Rename apply. Underscore discount.").

## Endpoint and accuracy, 560 clips (`bench/stt_extra.py`, load 5.5 falling to 4.1)

Speech end to the first `<end>` or `<fin>`; a clip with none within its 2.5 s of silence counts as over 2.5 s.

| | p50 | p90 | p90 Hebrew | over 1 s | over 2.5 s | split | intent | intent Hebrew | WER Hebrew |
|---|---|---|---|---|---|---|---|---|---|
| v5, daemon settings | 0.36 s | 0.83 s | 0.86 s | 6.1% | 1.8% | 0 | 94.6% | 98.3% | 0.007 |
| v6, daemon settings (1.14.5) | 0.38 s | 2.67 s | over 2.5 s | 12.3% | 10.9% | 0 | 95.9% | 98.3% | 0.006 |
| **v6 + finalize at 0.7 s (1.14.6)** | **0.38 s** | **0.76 s** | **0.80 s** | **1.2%** | **0.0%** | 2 | **96.1%** | **98.3%** | **0.006** |
| v6 + finalize at 0.5 s | 0.38 s | 0.57 s | 0.58 s | 1.2% | 0.0% | 2 | 95.7% | 98.3% | 0.006 |
| v6, Soniox's lower-latency start | 0.13 s | 2.13 s | 2.23 s | 15.9% | 0.5% | 38 | 95.0% | 98.3% | 0.006 |

"Split": clips Soniox ended in more than one segment. Intent: 538 clips right with finalize at 0.7 s, 537 for v6 as
shipped (McNemar p = 1), 530 for v5 (p = 0.021). 0.7 s finalized 22% of clips (124), 0.5 s 56% (313): the later one asks
only when needed, and Soniox warns that an early finalize costs accuracy.

## Pauses (`bench/pause_bench.py`)

20 invented sentences, 10 English and 10 Hebrew, said in two parts (2 voices) with 1.2 or 2.0 s of silence between:
80 clips per setting. Each segment Soniox closed in the pause is replayed through the daemon's settle (`turns.settle`):
the turn is taken in the pause if the settle ends before the voice returns.

| turns taken in the pause, Normal | first part reads unfinished (20) | first part reads whole (60) |
|---|---|---|
| v5, daemon settings | 0 | 52 |
| v6, daemon settings (1.14.5) | 0 | 50 |
| v6 + finalize at 0.7 s (1.14.6) | 0 | 60 |
| v6, Soniox's lower-latency start | 0 | 46 |

An unfinished first part is never taken: the 3.0 s settle holds it, whatever Soniox does. A first part that reads whole
is taken at Normal's 1.0 s by design (`docs/design/turn-taking.md` §3.1); v5 and v6 sometimes waited through the pause
on their own, and the finalize ends that: 8 more of 60 than v5. At Patient (finalize at 1.5 s, `-fin1500`, judged with
`--level patient`) a 1.2 s pause after a whole clause is not taken (0 of 30, v5 0 of 30), a 2.0 s one is (30 and 27).

## On a real call, 1.14.6 code

| | ears: last word to final, p50 / p90 / max | last word to first sound, p50 / p90 | load |
|---|---|---|---|
| v5, 2026-11-20 | 0.40 / 0.49 / 0.55 s | 2.02 / 2.66 s | 6.9 at start, 97 at end |
| v6 (1.14.5) | 0.47 / 0.60 / 0.75 s | 2.11 / 2.50 s | 5.1 to 6.9 |
| v6 + finalize (1.14.6) | 0.39 / 0.55 / 0.60 s | 2.15 / 2.73 s | 8.6 falling to 5.3 |

`tests/e2e/latency.py 2`, 24 English questions. The finalize was not needed in this run (Soniox ended each question
itself); the 4.53 s maximum to first sound was a reply sent back for a second model step, its words final at 0.33 s.
`tests/e2e/turn_taking.py` 7/7 (pauses of 1.5 and 2.0 s after an unfinished part not answered; the finalize made those
parts final in the pause and the daemon held them 3.0 s; turn taken 0.88 to 0.96 s after the real end),
`tests/e2e/ptt.py` 7/7, `tests/e2e/page_conversation.py` 28/28 (a Hebrew sentence paused after a conjunction is one
turn; Quick and Patient take a whole sentence after 0.4 and 1.8 s of quiet; the finalize was sent 11 times in it).

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

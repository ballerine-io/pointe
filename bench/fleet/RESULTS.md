<!-- Written by bench/fleet/report.py from bench/fleet/results/. Do not edit by hand. -->

# Fleet benchmark: one voice, many machines and sessions

A self-evaluation: Pointe's team wrote the simulator, the turns, the labels and the scorer. Typed text, scripted stand-in sessions, synthetic names. Every number below is computed from the rows in `bench/fleet/results/`; intervals are 95% (Wilson for counts, a bootstrap over turns for medians and p90).

Dataset `fleet-0.1`, frozen 2026-11-26T14:58:25+0200, sha256 `ee2efc6bded4779e`. 60 turns a size; expected outcomes labelled by rule from the fleet's description (`bench/fleet/turns.py`).

## Bars

### 1x4, the fleet build, POINTE_FLEET=off

3 runs of the turn list, 180 turn rows, 0 crashed.

| Bar | The plan's bar | Measured | |
|---|---|---|---|
| tokens of "what needs me" | at most 1,800 | max 805 (median 650), 180 turns | **pass** |
| brain input tokens per turn | the reference for the other sizes | median 26,918 | **pass** |
| first token, median | the reference for the other sizes | 0.900 s | **pass** |
| first token, p90 | the reference for the other sizes | 1.132 s | **pass** |
| wrong session on clear turns | the reference for the other sizes | 0 of 102 (0% to 4%) | **pass** |
| asked first on ambiguous turns | at least 30 of 42 (10 of 14, scaled to n) | 39 of 42 (81% to 98%) | **pass** |
| reader calls an hour with 80% of sessions quiet | at most 30% of all active | 120 against 480 (25%); models: stubbed | **pass** |
| 30 sessions finish within a minute | at most 4 spoken lines, nothing lost | not measured | **not measured** |

### 5x20, the fleet build, POINTE_FLEET=off

3 runs of the turn list, 180 turn rows, 51 crashed.

| Bar | The plan's bar | Measured | |
|---|---|---|---|
| tokens of "what needs me" | at most 1,800 | max 4,915 (median 4,893), 129 turns | **FAIL** |
| brain input tokens per turn | within 10% of 1x4 | median 35,439 against 26,918 (+32%) | **FAIL** |
| first token, median | at most 150 ms above 1x4 | 0.785 s against 0.900 s (-115 ms) | **pass** |
| first token, p90 | at most 150 ms above 1x4 | 1.428 s against 1.132 s (+296 ms) | **FAIL** |
| wrong session on clear turns | not above the 1x4 rate | 1 of 73 (0% to 7%) against 0 of 102 | **FAIL** |
| wrong session on clear turns | at most 5% | 1 of 73 (0% to 7%); the interval does not rule out a rate above the bar | **pass** |
| asked first on ambiguous turns | at least 22 of 30 (10 of 14, scaled to n) | 22 of 30 (56% to 86%) | **pass** |
| reader calls an hour with 80% of sessions quiet | at most 30% of all active | not measured; models: stubbed | **not measured** |
| 30 sessions finish within a minute | at most 4 spoken lines, nothing lost | not measured | **not measured** |

### 1x4, the fleet build, POINTE_FLEET=on

3 runs of the turn list, 180 turn rows, 0 crashed.

| Bar | The plan's bar | Measured | |
|---|---|---|---|
| tokens of "what needs me" | at most 1,800 | max 765 (median 645), 180 turns | **pass** |
| brain input tokens per turn | the reference for the other sizes | median 26,400 | **pass** |
| first token, median | the reference for the other sizes | 0.766 s | **pass** |
| first token, p90 | the reference for the other sizes | 1.152 s | **pass** |
| wrong session on clear turns | the reference for the other sizes | 1 of 102 (0% to 5%) | **pass** |
| asked first on ambiguous turns | at least 30 of 42 (10 of 14, scaled to n) | 40 of 42 (84% to 99%) | **pass** |
| reader calls an hour with 80% of sessions quiet | at most 30% of all active | 120 against 480 (25%); models: stubbed | **pass** |
| 30 sessions finish within a minute | at most 4 spoken lines, nothing lost | not measured | **not measured** |

### 5x20, the fleet build, POINTE_FLEET=on

3 runs of the turn list, 180 turn rows, 2 crashed.

| Bar | The plan's bar | Measured | |
|---|---|---|---|
| tokens of "what needs me" | at most 1,800 | max 1,811 (median 1,639), 177 turns; 1 turns without a count | **FAIL** |
| brain input tokens per turn | within 10% of 1x4 | median 33,411 against 26,400 (+27%) | **FAIL** |
| first token, median | at most 150 ms above 1x4 | 0.900 s against 0.766 s (+134 ms) | **pass** |
| first token, p90 | at most 150 ms above 1x4 | 1.190 s against 1.152 s (+38 ms) | **pass** |
| wrong session on clear turns | not above the 1x4 rate | 15 of 100 (9% to 23%) against 1 of 102 | **FAIL** |
| wrong session on clear turns | at most 5% | 15 of 100 (9% to 23%) | **FAIL** |
| asked first on ambiguous turns | at least 30 of 42 (10 of 14, scaled to n) | 20 of 42 (33% to 62%) | **FAIL** |
| reader calls an hour with 80% of sessions quiet | at most 30% of all active | not measured; models: stubbed | **not measured** |
| 30 sessions finish within a minute | at most 4 spoken lines, nothing lost | not measured | **not measured** |

## The arms, as the daemon states them

679 of 679 rows carry the daemon's own `fleet.on` (`/voice/context`) equal to their arm's. Builds: fleet-off at `318cfbeb`, fleet-off at `389fd625`, fleet-off at `f79d5cda`, fleet-on at `318cfbeb`, fleet-on at `389fd625`, fleet-on at `f79d5cda`.

## Every run

| Arm | Size | Run | Clear: right | Clear: wrong session | Clear: asked instead | Clear: nothing | Ambiguous: asked | Ambiguous: sent | Ambiguous: neither | Crashed rows | Needs tokens, median / max | Brain input per turn, median | First token, median / p90 | First send, median | Reader / checker calls |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| fleet-off | 1x4 | fleet-20261126-152305-turns-1x4-fleet-off-r1 | 24 of 34 (54% to 83%) | 0 of 34 (0% to 10%) | 5 of 34 (6% to 30%) | 5 of 34 (6% to 30%) | 12 of 14 (60% to 96%) | 1 of 14 (1% to 31%) | 1 of 14 (1% to 31%) | 0 | 710 (664 to 733) / 805 | 26,935 (22,648 to 30,110) | 0.81 s (0.76 to 0.89) / 1.02 s (0.96 to 1.12) | 1.63 s (1.37 to 1.82) | 4 / 24 |
| fleet-off | 1x4 | fleet-20261126-172105-turns-1x4-fleet-off-r2 | 23 of 34 (51% to 81%) | 0 of 34 (0% to 10%) | 7 of 34 (10% to 37%) | 4 of 34 (5% to 27%) | 14 of 14 (78% to 100%) | 0 of 14 (0% to 22%) | 0 of 14 (0% to 22%) | 0 | 659 (604 to 678) / 766 | 26,062 (24,531 to 28,158) | 0.92 s (0.88 to 0.97) / 1.21 s (1.09 to 1.42) | 1.51 s (1.23 to 1.67) | 4 / 24 |
| fleet-off | 1x4 | fleet-20261126-172812-turns-1x4-fleet-off-r3 | 22 of 34 (48% to 79%) | 0 of 34 (0% to 10%) | 9 of 34 (15% to 43%) | 3 of 34 (3% to 23%) | 13 of 14 (69% to 99%) | 1 of 14 (1% to 31%) | 0 of 14 (0% to 22%) | 0 | 620 (592 to 649) / 725 | 27,507 (22,679 to 30,127) | 0.91 s (0.89 to 0.94) / 1.13 s (1.07 to 1.34) | 1.51 s (1.30 to 1.79) | 7 / 22 |
| fleet-off | 1x4 | all runs | 69 of 102 (58% to 76%) | 0 of 102 (0% to 4%) | 21 of 102 (14% to 29%) | 12 of 102 (7% to 19%) | 39 of 42 (81% to 98%) | 2 of 42 (1% to 16%) | 1 of 42 (0% to 12%) | 0 | 650 (630 to 668) / 805 | 26,918 (25,009 to 28,634) | 0.90 s (0.87 to 0.92) / 1.13 s (1.08 to 1.21) | 1.58 s (1.47 to 1.66) | 15 / 70 |
| fleet-off | 5x20 | fleet-20261126-180318-turns-5x20-fleet-off-r1 | 13 of 25 (33% to 70%) | 0 of 25 (0% to 13%) | 12 of 25 (30% to 67%) | 0 of 25 (0% to 13%) | 7 of 9 (45% to 94%) | 2 of 9 (6% to 55%) | 0 of 9 (0% to 30%) | 15 | 4,860 (4,858 to 4,864) / 4,883 | 35,780 (30,465 to 50,039) | 0.69 s (0.64 to 0.77) / 1.19 s (0.83 to 1.45) | 1.34 s (1.10 to 1.69) | 0 / 35 |
| fleet-off | 5x20 | fleet-20261126-181027-turns-5x20-fleet-off-r2 | 13 of 24 (35% to 72%) | 1 of 24 (1% to 20%) | 10 of 24 (24% to 61%) | 0 of 24 (0% to 14%) | 9 of 10 (60% to 98%) | 1 of 10 (2% to 40%) | 0 of 10 (0% to 28%) | 19 | 4,896 (4,896 to 4,906) / 4,915 | 33,529 (31,868 to 54,962) | 0.71 s (0.66 to 0.78) / 1.31 s (0.90 to 1.38) | 1.39 s (1.00 to 2.82) | 11 / 28 |
| fleet-off | 5x20 | fleet-20261126-181721-turns-5x20-fleet-off-r3 | 13 of 24 (35% to 72%) | 0 of 24 (0% to 14%) | 8 of 24 (18% to 53%) | 3 of 24 (4% to 31%) | 6 of 11 (28% to 79%) | 3 of 11 (10% to 57%) | 2 of 11 (5% to 48%) | 17 | 4,896 (4,896 to 4,907) / 4,911 | 35,439 (31,785 to 58,570) | 1.10 s (1.00 to 1.23) / 1.75 s (1.43 to 1.98) | 1.74 s (1.42 to 2.22) | 10 / 28 |
| fleet-off | 5x20 | all runs | 39 of 73 (42% to 64%) | 1 of 73 (0% to 7%) | 30 of 73 (31% to 53%) | 3 of 73 (1% to 11%) | 22 of 30 (56% to 86%) | 6 of 30 (10% to 37%) | 2 of 30 (2% to 21%) | 51 | 4,893 (4,892 to 4,896) / 4,915 | 35,439 (32,570 to 47,586) | 0.79 s (0.73 to 0.85) / 1.43 s (1.31 to 1.59) | 1.61 s (1.33 to 1.74) | 21 / 91 |
| fleet-on | 1x4 | fleet-20261126-150230-turns-1x4-fleet-on-r1 | 24 of 34 (54% to 83%) | 0 of 34 (0% to 10%) | 6 of 34 (8% to 34%) | 4 of 34 (5% to 27%) | 13 of 14 (69% to 99%) | 1 of 14 (1% to 31%) | 0 of 14 (0% to 22%) | 0 | 657 (618 to 683) / 760 | 27,742 (23,553 to 30,624) | 0.72 s (0.65 to 0.77) / 1.06 s (0.95 to 1.15) | 1.52 s (1.03 to 1.64) | 5 / 21 |
| fleet-on | 1x4 | fleet-20261126-150917-turns-1x4-fleet-on-r2 | 23 of 34 (51% to 81%) | 0 of 34 (0% to 10%) | 7 of 34 (10% to 37%) | 4 of 34 (5% to 27%) | 13 of 14 (69% to 99%) | 0 of 14 (0% to 22%) | 1 of 14 (1% to 31%) | 0 | 658 (603 to 677) / 765 | 25,893 (23,623 to 28,655) | 0.81 s (0.76 to 0.88) / 1.14 s (0.97 to 1.24) | 1.35 s (1.13 to 1.74) | 3 / 23 |
| fleet-on | 1x4 | fleet-20261126-151613-turns-1x4-fleet-on-r3 | 23 of 34 (51% to 81%) | 1 of 34 (1% to 15%) | 7 of 34 (10% to 37%) | 3 of 34 (3% to 23%) | 14 of 14 (78% to 100%) | 0 of 14 (0% to 22%) | 0 of 14 (0% to 22%) | 0 | 609 (586 to 653) / 736 | 26,708 (22,719 to 29,526) | 0.79 s (0.70 to 0.88) / 1.18 s (1.08 to 1.50) | 1.30 s (0.94 to 1.94) | 6 / 20 |
| fleet-on | 1x4 | all runs | 70 of 102 (59% to 77%) | 1 of 102 (0% to 5%) | 20 of 102 (13% to 28%) | 11 of 102 (6% to 18%) | 40 of 42 (84% to 99%) | 1 of 42 (0% to 12%) | 1 of 42 (0% to 12%) | 0 | 645 (613 to 658) / 765 | 26,400 (24,114 to 28,346) | 0.77 s (0.72 to 0.82) / 1.15 s (1.08 to 1.18) | 1.42 s (1.21 to 1.63) | 14 / 64 |
| fleet-on | 5x20 | fleet-20261126-173527-turns-5x20-fleet-on-r1 | 19 of 32 (42% to 74%) | 1 of 32 (1% to 16%) | 11 of 32 (20% to 52%) | 1 of 32 (1% to 16%) | 10 of 14 (45% to 88%) | 2 of 14 (4% to 40%) | 2 of 14 (4% to 40%) | 2 | 1,669 (1,653 to 1,679) / 1,740 | 33,847 (30,092 to 54,222) | 1.00 s (0.97 to 1.03) / 1.44 s (1.26 to 1.72) | 1.84 s (1.59 to 2.17) | 0 / 48 |
| fleet-on | 5x20 | fleet-20261126-174517-turns-5x20-fleet-on-r2 | 15 of 34 (29% to 61%) | 7 of 34 (10% to 37%) | 11 of 34 (19% to 49%) | 1 of 34 (1% to 15%) | 9 of 14 (39% to 84%) | 4 of 14 (12% to 55%) | 1 of 14 (1% to 31%) | 0 | 1,611 (1,595 to 1,637) / 1,707 | 33,273 (30,177 to 42,448) | 0.85 s (0.82 to 0.90) / 1.14 s (0.97 to 1.55) | 1.48 s (1.23 to 1.89) | 11 / 38 |
| fleet-on | 5x20 | fleet-20261126-175413-turns-5x20-fleet-on-r3 | 13 of 34 (24% to 55%) | 7 of 34 (10% to 37%) | 14 of 34 (26% to 58%) | 0 of 34 (0% to 10%) | 1 of 14 (1% to 31%) | 13 of 14 (69% to 99%) | 0 of 14 (0% to 22%) | 0 | 1,632 (1,602 to 1,664) / 1,811 | 32,846 (30,815 to 50,083) | 0.88 s (0.81 to 0.90) / 1.08 s (0.98 to 1.18) | 1.50 s (1.27 to 2.03) | 12 / 55 |
| fleet-on | 5x20 | all runs | 47 of 100 (38% to 57%) | 15 of 100 (9% to 23%) | 36 of 100 (27% to 46%) | 2 of 100 (1% to 7%) | 20 of 42 (33% to 62%) | 19 of 42 (31% to 60%) | 3 of 42 (2% to 19%) | 2 | 1,639 (1,625 to 1,654) / 1,811 | 33,411 (31,935 to 38,966) | 0.90 s (0.88 to 0.93) / 1.19 s (1.09 to 1.31) | 1.72 s (1.49 to 1.87) | 23 / 141 |

Needs tokens: the "what each session needs" block of the turn's first brain step, counted by the brain vendor's own token counter as one message. Brain input: the vendor's count of the whole prompt, summed over the turn's own brain steps. First token and first send: from the typed line; a send's time is exact to 20 ms. Timings leave out rows that began or ended with the load over 20.

## By kind of turn (all runs of a size and arm together)

| Arm | Size | Kind | n | Outcomes |
|---|---|---|---|---|
| fleet-off | 1x4 | clear_name | 66 | asked 1, nothing 4, right 61 |
| fleet-off | 1x4 | clear_description | 36 | asked 20, nothing 8, right 8 |
| fleet-off | 1x4 | ambiguous_description | 21 | asked 19, neither 1, sent 1 |
| fleet-off | 1x4 | ambiguous_none | 21 | asked 20, sent 1 |
| fleet-off | 1x4 | needs_me | 18 | answered 18 |
| fleet-off | 1x4 | on_machine | 18 | answered 18 |
| fleet-off | 1x4 | needs_me: expected sessions named in the reply | 18 | 31 of 36 names; 1 replies name a session not expected |
| fleet-off | 1x4 | on_machine: expected sessions named in the reply | 18 | 60 of 72 names; 0 replies name a session not expected |
| fleet-off | 5x20 | clear_name | 36 | asked 2, crashed 12, right 22 |
| fleet-off | 5x20 | clear_machine_name | 30 | asked 6, crashed 9, right 15 |
| fleet-off | 5x20 | clear_description | 36 | asked 22, crashed 8, nothing 3, right 2, wrong 1 |
| fleet-off | 5x20 | ambiguous_name | 18 | asked 9, crashed 8, neither 1 |
| fleet-off | 5x20 | ambiguous_description | 12 | asked 8, crashed 3, sent 1 |
| fleet-off | 5x20 | ambiguous_none | 12 | asked 5, crashed 1, neither 1, sent 5 |
| fleet-off | 5x20 | needs_me | 18 | answered 9, crashed 9 |
| fleet-off | 5x20 | on_machine | 18 | answered 17, crashed 1 |
| fleet-off | 5x20 | ambiguous_name, this Mac has a session of the name | 1 | asked 1 |
| fleet-off | 5x20 | ambiguous_name, only other machines have one | 9 | asked 8, neither 1 |
| fleet-off | 5x20 | needs_me: expected sessions named in the reply | 9 | 41 of 54 names; 1 replies name a session not expected |
| fleet-off | 5x20 | on_machine: expected sessions named in the reply | 17 | 60 of 340 names; 0 replies name a session not expected |
| fleet-on | 1x4 | clear_name | 66 | asked 1, nothing 4, right 61 |
| fleet-on | 1x4 | clear_description | 36 | asked 19, nothing 7, right 9, wrong 1 |
| fleet-on | 1x4 | ambiguous_description | 21 | asked 21 |
| fleet-on | 1x4 | ambiguous_none | 21 | asked 19, neither 1, sent 1 |
| fleet-on | 1x4 | needs_me | 18 | answered 18 |
| fleet-on | 1x4 | on_machine | 18 | answered 18 |
| fleet-on | 1x4 | needs_me: expected sessions named in the reply | 18 | 31 of 36 names; 1 replies name a session not expected |
| fleet-on | 1x4 | on_machine: expected sessions named in the reply | 18 | 51 of 72 names; 0 replies name a session not expected |
| fleet-on | 5x20 | clear_name | 36 | right 36 |
| fleet-on | 5x20 | clear_machine_name | 30 | asked 6, crashed 2, right 8, wrong 14 |
| fleet-on | 5x20 | clear_description | 36 | asked 30, nothing 2, right 3, wrong 1 |
| fleet-on | 5x20 | ambiguous_name | 18 | asked 8, neither 1, sent 9 |
| fleet-on | 5x20 | ambiguous_description | 12 | asked 8, neither 1, sent 3 |
| fleet-on | 5x20 | ambiguous_none | 12 | asked 4, neither 1, sent 7 |
| fleet-on | 5x20 | needs_me | 18 | answered 18 |
| fleet-on | 5x20 | on_machine | 18 | answered 18 |
| fleet-on | 5x20 | ambiguous_name, this Mac has a session of the name | 6 | asked 2, sent 4 |
| fleet-on | 5x20 | ambiguous_name, only other machines have one | 12 | asked 6, neither 1, sent 5 |
| fleet-on | 5x20 | needs_me: expected sessions named in the reply | 18 | 82 of 108 names; 2 replies name a session not expected |
| fleet-on | 5x20 | on_machine: expected sessions named in the reply | 18 | 31 of 360 names; 1 replies name a session not expected |

## 30 sessions end their turn within a minute

Not run.

## Reader calls

| Arm | Size | Scenario | Sessions active | Turns ended | Reader calls in the window | An hour | Error |
|---|---|---|---|---|---|---|---|
| fleet-on | 1x4 | all_active | 4 of 4 | 8 | 16 | 480 |  |
| fleet-on | 1x4 | quiet_80 | 1 of 4 | 2 | 4 | 120 |  |
| fleet-off | 1x4 | all_active | 4 of 4 | 8 | 16 | 480 |  |
| fleet-off | 1x4 | quiet_80 | 1 of 4 | 2 | 4 | 120 |  |
| fleet-on | 5x20 | all_active | 100 of 100 | 200 | 0 | 0 |  |
| fleet-on | 5x20 | quiet_80 | 20 of 100 | 40 | 0 | 0 |  |
| fleet-off | 5x20 | all_active | 100 of 100 | 200 | 0 | 0 |  |
| fleet-off | 5x20 | quiet_80 | 20 of 100 | 40 | 0 | 0 |  |
| fleet-on | 10x30 | all_active | 300 of 300 | 600 | 0 | 0 |  |
| fleet-on | 10x30 | quiet_80 | 60 of 300 | 120 | 0 | 0 |  |
| fleet-off | 10x30 | all_active | 300 of 300 | 600 | 0 | 0 |  |
| fleet-off | 10x30 | quiet_80 | 60 of 300 | 120 | 0 | 0 |  |

Counted with stubbed models: the count is the daemon's own decisions to call the reader, not what a model wrote. Each active session ends a turn once a minute for two minutes; the hourly figure is the window's count times 30. One run each: n = 1.

## The simulator on this machine

| Size | Arm | Processes | Sessions on their machine | Up in | Voice memory | Nodes' memory, together | Voice CPU | Nodes' CPU, together | Runner CPU | Load |
|---|---|---|---|---|---|---|---|---|---|---|
| 1x4 | fleet-on | 2 | 4 of 4 | 11.1 s | 45.2 MB | 0 MB | 0% of a core | 0% | 0% | 6.8 |
| 5x20 | fleet-on | 6 | 100 of 100 | 22.1 s | 114.6 MB | 277.6 MB | 2% of a core | 5% | 0% | 7.4 |
| 10x30 | fleet-on | 11 | 300 of 300 | 44.1 s | 128.5 MB | 643.0 MB | 3% of a core | 15% | 1% | 4.8 |

Stubbed models, a call held for a minute with nothing typed. Processes: one voice daemon, one node a machine beyond the first, and the runner, which holds every stand-in session as a thread.

## Spend

| Launch | What | Model calls | USD |
|---|---|---|---|
| fleet-20261126-145926-turns-1x4-fleet-on-r1 | turns | 10 | 0.0576 |
| fleet-20261126-150023-turns-1x4-fleet-on-r1 | turns | 19 | 0.0892 |
| fleet-20261126-150230-turns-1x4-fleet-on-r1 | turns | 102 | 0.3736 |
| fleet-20261126-150917-turns-1x4-fleet-on-r2 | turns | 106 | 0.4505 |
| fleet-20261126-151613-turns-1x4-fleet-on-r3 | turns | 98 | 0.4195 |
| fleet-20261126-152305-turns-1x4-fleet-off-r1 | turns | 106 | 0.4262 |
| fleet-20261126-153433-turns-1x4-fleet-off-r2 | turns | 81 | 1.2382 |
| fleet-20261126-153937-turns-1x4-fleet-off-r3 | turns | 100 | 1.2068 |
| fleet-20261126-153433-turns-1x4-fleet-off-r2 | correction: 54 calls that failed to connect reached no vendor and are priced at zero, not estimated | 0 | -1.1067 |
| fleet-20261126-153937-turns-1x4-fleet-off-r3 | correction: 28 calls that failed to connect reached no vendor and are priced at zero, not estimated | 0 | -0.3153 |
| fleet-20261126-172105-turns-1x4-fleet-off-r2 | turns | 107 | 0.4807 |
| fleet-20261126-172812-turns-1x4-fleet-off-r3 | turns | 109 | 0.4366 |
| fleet-20261126-173527-turns-5x20-fleet-on-r1 | turns | 258 | 2.0080 |
| fleet-20261126-174517-turns-5x20-fleet-on-r2 | turns | 157 | 1.5582 |
| fleet-20261126-175413-turns-5x20-fleet-on-r3 | turns | 168 | 1.4250 |
| fleet-20261126-180318-turns-5x20-fleet-off-r1 | turns | 211 | 2.0832 |
| fleet-20261126-181027-turns-5x20-fleet-off-r2 | turns | 116 | 2.0173 |
| fleet-20261126-181721-turns-5x20-fleet-off-r3 | turns | 120 | 2.0543 |
| all 18 paid launches | | 1868 | 14.9029 |

Computed from each call's token counts at list price (`prices.json`), not metered; smoke runs included. Each run's `manifest.json` has the split by model and says which calls were estimated from sizes.

## Not counted above

| Run | Why | Rows |
|---|---|---|
| fleet-20261126-145926-turns-1x4-fleet-on-r1 | a smoke run of 4 turns | 4 |
| fleet-20261126-150023-turns-1x4-fleet-on-r1 | Stopped by the operator after 8 turns, when main changed under it (the fleet switch's default): it ran on 92325e9a and its rows have no fleet.on from the daemon. Run again whole on the next build. | 61 |
| fleet-20261126-153433-turns-1x4-fleet-off-r2 | The network dropped during this run: 54 model calls failed to connect and the voice answered "say that again?". Its rows are kept; the run was made again with the same seed. | 61 |
| fleet-20261126-153937-turns-1x4-fleet-off-r3 | The network dropped during this run: 28 model calls failed to connect and the voice answered "say that again?". Its rows are kept; the run was made again with the same seed. | 61 |

Runs that ended early (their rows are counted, the turns not reached as crashed):

- fleet-20261126-173527-turns-5x20-fleet-on-r1: stopped after 58 turns: this launch reached its spend limit of $2.00
- fleet-20261126-180318-turns-5x20-fleet-off-r1: stopped after 45 turns: this launch reached its spend limit of $2.00
- fleet-20261126-181027-turns-5x20-fleet-off-r2: stopped after 41 turns: this launch reached its spend limit of $2.00
- fleet-20261126-181721-turns-5x20-fleet-off-r3: stopped after 43 turns: this launch reached its spend limit of $2.00

## What this does not show

- **Typed text, not speech.** Every turn is a line typed into the call. No recognizer, no voice, no turn-taking, no misheard names. The call has no ears and is in reading mode: replies are shown, not spoken, and the brain is told so.
- **Stand-ins, not agents.** A session is a scripted record and an inbox. It never answers a request, so every request sent stays listed as unanswered for the rest of its run, and no report comes back during the turns.
- **One voice, one person.** No second voice on a machine, no shared machine, no link that drops.
- **Synthetic names and work.** One-word session names chosen to be unlike each other, except the shared ones; invented goals of two words. Real fleets have names that sound alike.
- **One fleet a size.** The same generated fleet in every run; runs differ in turn order and in what the models do.
- **Turns in one call.** The 60 turns of a run share a call, so later turns carry earlier ones in the brain's history.
- **The reader's notes are read once.** A size's first paid run pays the reader to read every session; later runs of that arm reuse those notes (each manifest has the notes' hash).
- **A self-evaluation.** Nobody outside the team has run it. The "ask" label for a shared name follows the plan, not the daemon's design for a name this Mac holds; those turns are shown apart above.
- **"Asked" is a question mark.** A reply with a question mark and no send counts as asking; what it asked is not judged.
- **Reader calls are counted with stubbed models**, over two minutes, and scaled to an hour.
- **The machine was shared** with other work; each row has the load at its start and end.
- **Not run:** the turn list at 1x4, main before the fleet work; 5x20, main before the fleet work; 10x30, main before the fleet work; 10x30, the fleet build, POINTE_FLEET=off; 10x30, the fleet build, POINTE_FLEET=on.

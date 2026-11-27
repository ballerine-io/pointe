<!-- Written by bench/fleet/report.py from bench/fleet/results/. Do not edit by hand. -->

# Fleet benchmark: one voice, many machines and sessions

A self-evaluation: Pointe's team wrote the simulator, the turns, the labels and the scorer. Typed text, scripted stand-in sessions, synthetic names. Every number below is computed from the rows in `bench/fleet/results/`; intervals are 95% (Wilson for counts, a bootstrap over turns for medians and p90).

Dataset `fleet-0.1`, frozen 2026-11-26T14:58:25+0200, sha256 `ee2efc6bded4779e`. 60 turns a size; expected outcomes labelled by rule from the fleet's description (`bench/fleet/turns.py`).

## Bars

### 1x4, the fleet build, POINTE_FLEET=off, build `502cd35ea5`

3 runs of the turn list: 180 turns driven, 0 crashed, 0 not run (their run stopped first).

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

### 5x20, the fleet build, POINTE_FLEET=off, build `502cd35ea5`

3 runs of the turn list: 180 turns driven, 0 crashed, 0 not run (their run stopped first).

| Bar | The plan's bar | Measured | |
|---|---|---|---|
| tokens of "what needs me" | at most 1,800 | max 4,888 (median 4,858), 180 turns | **FAIL** |
| brain input tokens per turn | within 10% of 1x4 | median 34,727 against 26,918 (+29.0%; 95% interval +17.8% to +39.7%) | **FAIL** |
| first token, median | at most 150 ms above 1x4 | 0.660 s against 0.900 s (-240 ms; 95% interval -269 ms to -197 ms) | **pass** |
| first token, p90 | at most 150 ms above 1x4 | 1.162 s against 1.132 s (+30 ms; 95% interval -177 ms to +239 ms) | **pass** |
| wrong session on clear turns | not above the 1x4 rate | 2 of 102 (1% to 7%) against 0 of 102 | **FAIL** |
| wrong session on clear turns | at most 5% | 2 of 102 (1% to 7%); the interval does not rule out a rate above the bar | **pass** |
| asked first on ambiguous turns | at least 30 of 42 (10 of 14, scaled to n) | 36 of 42 (72% to 93%) | **pass** |
| reader calls an hour with 80% of sessions quiet | at most 30% of all active | 1920 against 9600 (20%); models: stubbed | **pass** |
| 30 sessions finish within a minute | at most 4 spoken lines, nothing lost | not measured | **not measured** |

### 1x4, the fleet build, POINTE_FLEET=on, build `502cd35ea5`

3 runs of the turn list: 180 turns driven, 0 crashed, 0 not run (their run stopped first).

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

### 5x20, the fleet build, POINTE_FLEET=on, build `502cd35ea5`

3 runs of the turn list: 178 turns driven, 0 crashed, 2 not run (their run stopped first).

| Bar | The plan's bar | Measured | |
|---|---|---|---|
| tokens of "what needs me" | at most 1,800 | max 1,811 (median 1,639), 177 turns; 1 turns without a count | **FAIL** |
| brain input tokens per turn | within 10% of 1x4 | median 33,411 against 26,400 (+26.6%; 95% interval +15.1% to +52.7%) | **FAIL** |
| first token, median | at most 150 ms above 1x4 | 0.900 s against 0.766 s (+134 ms; 95% interval +78 ms to +186 ms) | **pass** |
| first token, p90 | at most 150 ms above 1x4 | 1.190 s against 1.152 s (+38 ms; 95% interval -65 ms to +232 ms) | **pass** |
| wrong session on clear turns | not above the 1x4 rate | 15 of 100 (9% to 23%) against 1 of 102 | **FAIL** |
| wrong session on clear turns | at most 5% | 15 of 100 (9% to 23%) | **FAIL** |
| asked first on ambiguous turns | at least 30 of 42 (10 of 14, scaled to n) | 20 of 42 (33% to 62%) | **FAIL** |
| reader calls an hour with 80% of sessions quiet | at most 30% of all active | 1920 against 9600 (20%); models: stubbed | **pass** |
| 30 sessions finish within a minute | at most 4 spoken lines, nothing lost | not measured | **not measured** |

### 1x4, the fleet build, POINTE_FLEET=off, build `05857b19f6`

3 runs of the turn list: 180 turns driven, 0 crashed, 0 not run (their run stopped first).

| Bar | The plan's bar | Measured | |
|---|---|---|---|
| tokens of "what needs me" | at most 1,800 | max 787 (median 664), 179 turns; 1 turns without a count | **pass** |
| brain input tokens per turn | the reference for the other sizes | median 25,986 | **pass** |
| first token, median | the reference for the other sizes | 0.843 s | **pass** |
| first token, p90 | the reference for the other sizes | 1.142 s | **pass** |
| wrong session on clear turns | the reference for the other sizes | 1 of 102 (0% to 5%) | **pass** |
| asked first on ambiguous turns | at least 30 of 42 (10 of 14, scaled to n) | 39 of 42 (81% to 98%) | **pass** |
| reader calls an hour with 80% of sessions quiet | at most 30% of all active | 120 against 480 (25%); models: stubbed | **pass** |
| 30 sessions finish within a minute | at most 4 spoken lines, nothing lost | not measured | **not measured** |

### 5x20, the fleet build, POINTE_FLEET=off, build `05857b19f6`

3 runs of the turn list: 180 turns driven, 0 crashed, 0 not run (their run stopped first).

| Bar | The plan's bar | Measured | |
|---|---|---|---|
| tokens of "what needs me" | at most 1,800 | max 4,893 (median 4,860), 180 turns | **FAIL** |
| brain input tokens per turn | within 10% of 1x4 | median 34,988 against 25,986 (+34.6%; 95% interval +20.9% to +43.3%) | **FAIL** |
| first token, median | at most 150 ms above 1x4 | 1.107 s against 0.843 s (+264 ms; 95% interval +212 ms to +328 ms) | **FAIL** |
| first token, p90 | at most 150 ms above 1x4 | 1.639 s against 1.142 s (+497 ms; 95% interval +357 ms to +650 ms) | **FAIL** |
| wrong session on clear turns | not above the 1x4 rate | 1 of 102 (0% to 5%) against 1 of 102 | **pass** |
| wrong session on clear turns | at most 5% | 1 of 102 (0% to 5%); the interval does not rule out a rate above the bar | **pass** |
| asked first on ambiguous turns | at least 30 of 42 (10 of 14, scaled to n) | 31 of 42 (59% to 85%) | **pass** |
| reader calls an hour with 80% of sessions quiet | at most 30% of all active | 1920 against 9600 (20%); models: stubbed | **pass** |
| 30 sessions finish within a minute | at most 4 spoken lines, nothing lost | not measured | **not measured** |

### 1x4, the fleet build, POINTE_FLEET=on, build `05857b19f6`

3 runs of the turn list: 180 turns driven, 0 crashed, 0 not run (their run stopped first).

| Bar | The plan's bar | Measured | |
|---|---|---|---|
| tokens of "what needs me" | at most 1,800 | max 774 (median 616), 180 turns | **pass** |
| brain input tokens per turn | the reference for the other sizes | median 25,885 | **pass** |
| first token, median | the reference for the other sizes | 0.818 s | **pass** |
| first token, p90 | the reference for the other sizes | 1.077 s | **pass** |
| wrong session on clear turns | the reference for the other sizes | 1 of 102 (0% to 5%) | **pass** |
| asked first on ambiguous turns | at least 30 of 42 (10 of 14, scaled to n) | 38 of 42 (78% to 96%) | **pass** |
| reader calls an hour with 80% of sessions quiet | at most 30% of all active | 120 against 480 (25%); models: stubbed | **pass** |
| 30 sessions finish within a minute | at most 4 spoken lines, nothing lost | not measured | **not measured** |

### 5x20, the fleet build, POINTE_FLEET=on, build `05857b19f6`

3 runs of the turn list: 177 turns driven, 3 crashed, 0 not run (their run stopped first).

| Bar | The plan's bar | Measured | |
|---|---|---|---|
| tokens of "what needs me" | at most 1,800 | max 1,617 (median 1,599), 177 turns | **pass** |
| brain input tokens per turn | within 10% of 1x4 | median 31,253 against 25,885 (+20.7%; 95% interval +8.6% to +32.0%) | **FAIL** |
| first token, median | at most 150 ms above 1x4 | 0.892 s against 0.818 s (+74 ms; 95% interval +16 ms to +119 ms) | **pass** |
| first token, p90 | at most 150 ms above 1x4 | 1.302 s against 1.077 s (+225 ms; 95% interval +73 ms to +695 ms) | **FAIL** |
| wrong session on clear turns | not above the 1x4 rate | 0 of 100 (0% to 4%) against 1 of 102 | **pass** |
| wrong session on clear turns | at most 5% | 0 of 100 (0% to 4%) | **pass** |
| asked first on ambiguous turns | at least 30 of 41 (10 of 14, scaled to n) | 35 of 41 (72% to 93%) | **pass** |
| reader calls an hour with 80% of sessions quiet | at most 30% of all active | 1920 against 9600 (20%); models: stubbed | **pass** |
| 30 sessions finish within a minute | at most 4 spoken lines, nothing lost | not measured | **not measured** |

### 1x4, the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried)

3 runs of the turn list: 180 turns driven, 0 crashed, 0 not run (their run stopped first).

| Bar | The plan's bar | Measured | |
|---|---|---|---|
| tokens of "what needs me" | at most 1,800 | max 787 (median 664), 179 turns; 1 turns without a count | **pass** |
| brain input tokens per turn | the reference for the other sizes | median 25,986 | **pass** |
| first token, median | the reference for the other sizes | 0.843 s | **pass** |
| first token, p90 | the reference for the other sizes | 1.142 s | **pass** |
| wrong session on clear turns | the reference for the other sizes | 1 of 102 (0% to 5%) | **pass** |
| asked first on ambiguous turns | at least 30 of 42 (10 of 14, scaled to n) | 39 of 42 (81% to 98%) | **pass** |
| reader calls an hour with 80% of sessions quiet | at most 30% of all active | 120 against 480 (25%); models: stubbed | **pass** |
| 30 sessions finish within a minute | at most 4 spoken lines, nothing lost | not measured | **not measured** |

### 5x20, the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried)

3 runs of the turn list: 180 turns driven, 0 crashed, 0 not run (their run stopped first).

| Bar | The plan's bar | Measured | |
|---|---|---|---|
| tokens of "what needs me" | at most 1,800 | max 4,893 (median 4,860), 180 turns | **FAIL** |
| brain input tokens per turn | within 10% of 1x4 | median 34,988 against 25,986 (+34.6%; 95% interval +20.9% to +43.3%) | **FAIL** |
| first token, median | at most 150 ms above 1x4 | 1.107 s against 0.843 s (+264 ms; 95% interval +212 ms to +328 ms) | **FAIL** |
| first token, p90 | at most 150 ms above 1x4 | 1.639 s against 1.142 s (+497 ms; 95% interval +357 ms to +650 ms) | **FAIL** |
| wrong session on clear turns | not above the 1x4 rate | 1 of 102 (0% to 5%) against 1 of 102 | **pass** |
| wrong session on clear turns | at most 5% | 1 of 102 (0% to 5%); the interval does not rule out a rate above the bar | **pass** |
| asked first on ambiguous turns | at least 30 of 42 (10 of 14, scaled to n) | 31 of 42 (59% to 85%) | **pass** |
| reader calls an hour with 80% of sessions quiet | at most 30% of all active | 1920 against 9600 (20%); models: stubbed | **pass** |
| 30 sessions finish within a minute | at most 4 spoken lines, nothing lost | not measured | **not measured** |

### 10x30, the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried)

1 runs of the turn list: 55 turns driven, 0 crashed, 0 not run (their run stopped first).

| Bar | The plan's bar | Measured | |
|---|---|---|---|
| tokens of "what needs me" | at most 1,800 | max 4,737 (median 4,724), 55 turns | **FAIL** |
| brain input tokens per turn | within 10% of 1x4 | median 35,374 against 25,986 (+36.1%; 95% interval +20.4% to +109.9%) | **FAIL** |
| first token, median | at most 150 ms above 1x4 | 1.537 s against 0.843 s (+694 ms; 95% interval +549 ms to +933 ms) | **FAIL** |
| first token, p90 | at most 150 ms above 1x4 | 2.014 s against 1.142 s (+872 ms; 95% interval +679 ms to +1078 ms) | **FAIL** |
| wrong session on clear turns | not above the 1x4 rate | 2 of 32 (2% to 20%) against 1 of 102 | **FAIL** |
| asked first on ambiguous turns | at least 10 of 14 (10 of 14, scaled to n) | 3 of 14 (8% to 48%) | **FAIL** |
| reader calls an hour with 80% of sessions quiet | at most 30% of all active | 5580 against 27900 (20%); models: stubbed | **pass** |
| 30 sessions finish within a minute | at most 4 spoken lines, nothing lost | not measured | **not measured** |

### 1x4, the fleet build, POINTE_FLEET=on, build `0b98c14e3a`

3 runs of the turn list: 180 turns driven, 0 crashed, 0 not run (their run stopped first).

| Bar | The plan's bar | Measured | |
|---|---|---|---|
| tokens of "what needs me" | at most 1,800 | max 840 (median 656), 180 turns | **pass** |
| brain input tokens per turn | the reference for the other sizes | median 27,185 | **pass** |
| first token, median | the reference for the other sizes | 0.988 s | **pass** |
| first token, p90 | the reference for the other sizes | 1.303 s | **pass** |
| wrong session on clear turns | the reference for the other sizes | 0 of 102 (0% to 4%) | **pass** |
| asked first on ambiguous turns | at least 30 of 42 (10 of 14, scaled to n) | 30 of 42 (56% to 83%) | **pass** |
| reader calls an hour with 80% of sessions quiet | at most 30% of all active | 120 against 480 (25%); models: stubbed | **pass** |
| 30 sessions finish within a minute | at most 4 spoken lines, nothing lost | not measured | **not measured** |

### 5x20, the fleet build, POINTE_FLEET=on, build `0b98c14e3a`

3 runs of the turn list: 180 turns driven, 0 crashed, 0 not run (their run stopped first).

| Bar | The plan's bar | Measured | |
|---|---|---|---|
| tokens of "what needs me" | at most 1,800 | max 1,109 (median 1,043), 180 turns | **pass** |
| brain input tokens per turn | within 10% of 1x4 | median 29,922 against 27,185 (+10.1%; 95% interval +0.3% to +17.6%) | **FAIL** |
| first token, median | at most 150 ms above 1x4 | 0.933 s against 0.988 s (-55 ms; 95% interval -92 ms to -19 ms) | **pass** |
| first token, p90 | at most 150 ms above 1x4 | 1.184 s against 1.303 s (-119 ms; 95% interval -206 ms to +20 ms) | **pass** |
| wrong session on clear turns | not above the 1x4 rate | 1 of 102 (0% to 5%) against 0 of 102 | **FAIL** |
| wrong session on clear turns | at most 5% | 1 of 102 (0% to 5%); the interval does not rule out a rate above the bar | **pass** |
| asked first on ambiguous turns | at least 30 of 42 (10 of 14, scaled to n) | 35 of 42 (69% to 92%) | **pass** |
| reader calls an hour with 80% of sessions quiet | at most 30% of all active | 1920 against 9600 (20%); models: stubbed | **pass** |
| 30 sessions finish within a minute | at most 4 spoken lines, nothing lost | not measured | **not measured** |

### 10x30, the fleet build, POINTE_FLEET=on, build `0b98c14e3a`

3 runs of the turn list: 168 turns driven, 0 crashed, 0 not run (their run stopped first).

| Bar | The plan's bar | Measured | |
|---|---|---|---|
| tokens of "what needs me" | at most 1,800 | max 1,697 (median 1,664), 168 turns | **pass** |
| brain input tokens per turn | within 10% of 1x4 | median 29,638 against 27,185 (+9.0%; 95% interval +0.6% to +17.0%) | **pass** |
| first token, median | at most 150 ms above 1x4 | 1.095 s against 0.988 s (+107 ms; 95% interval +27 ms to +249 ms) | **pass** |
| first token, p90 | at most 150 ms above 1x4 | 1.955 s against 1.303 s (+652 ms; 95% interval +501 ms to +846 ms) | **FAIL** |
| wrong session on clear turns | not above the 1x4 rate | 1 of 99 (0% to 6%) against 0 of 102 | **FAIL** |
| asked first on ambiguous turns | at least 30 of 42 (10 of 14, scaled to n) | 38 of 42 (78% to 96%) | **pass** |
| reader calls an hour with 80% of sessions quiet | at most 30% of all active | 4320 against 21420 (20%); models: stubbed | **pass** |
| 30 sessions finish within a minute | at most 4 spoken lines, nothing lost | not measured | **not measured** |

### 1x4, the fleet build, POINTE_FLEET=off, build `271e64c1d0`

3 runs of the turn list: 179 turns driven, 1 crashed, 0 not run (their run stopped first).

| Bar | The plan's bar | Measured | |
|---|---|---|---|
| tokens of "what needs me" | at most 1,800 | max 783 (median 661), 179 turns | **pass** |
| brain input tokens per turn | the reference for the other sizes | median 27,439 | **pass** |
| first token, median | the reference for the other sizes | 0.834 s | **pass** |
| first token, p90 | the reference for the other sizes | 1.031 s | **pass** |
| wrong session on clear turns | the reference for the other sizes | 0 of 101 (0% to 4%) | **pass** |
| asked first on ambiguous turns | at least 30 of 42 (10 of 14, scaled to n) | 38 of 42 (78% to 96%) | **pass** |
| reader calls an hour with 80% of sessions quiet | at most 30% of all active | 120 against 480 (25%); models: stubbed | **pass** |
| 30 sessions finish within a minute | at most 4 spoken lines, nothing lost | not measured | **not measured** |

### 5x20, the fleet build, POINTE_FLEET=off, build `271e64c1d0`

3 runs of the turn list: 180 turns driven, 0 crashed, 0 not run (their run stopped first).

| Bar | The plan's bar | Measured | |
|---|---|---|---|
| tokens of "what needs me" | at most 1,800 | max 4,890 (median 4,858), 180 turns | **FAIL** |
| brain input tokens per turn | within 10% of 1x4 | median 35,353 against 27,439 (+28.8%; 95% interval +17.7% to +43.4%) | **FAIL** |
| first token, median | at most 150 ms above 1x4 | 0.992 s against 0.834 s (+158 ms; 95% interval +115 ms to +198 ms) | **FAIL** |
| first token, p90 | at most 150 ms above 1x4 | 1.317 s against 1.031 s (+286 ms; 95% interval +159 ms to +490 ms) | **FAIL** |
| wrong session on clear turns | not above the 1x4 rate | 1 of 102 (0% to 5%) against 0 of 101 | **FAIL** |
| wrong session on clear turns | at most 5% | 1 of 102 (0% to 5%); the interval does not rule out a rate above the bar | **pass** |
| asked first on ambiguous turns | at least 30 of 42 (10 of 14, scaled to n) | 32 of 42 (61% to 87%) | **pass** |
| reader calls an hour with 80% of sessions quiet | at most 30% of all active | 1920 against 9600 (20%); models: stubbed | **pass** |
| 30 sessions finish within a minute | at most 4 spoken lines, nothing lost | 5 spoken, 0 held, 26 lost, of 30 (fleet-20261127-015709-burst-5x20-fleet-off) | **FAIL** |

### 10x30, the fleet build, POINTE_FLEET=off, build `271e64c1d0`

3 runs of the turn list: 165 turns driven, 0 crashed, 0 not run (their run stopped first).

| Bar | The plan's bar | Measured | |
|---|---|---|---|
| tokens of "what needs me" | at most 1,800 | max 4,734 (median 4,716), 165 turns | **FAIL** |
| brain input tokens per turn | within 10% of 1x4 | median 34,614 against 27,439 (+26.1%; 95% interval +17.6% to +39.2%) | **FAIL** |
| first token, median | at most 150 ms above 1x4 | 0.773 s against 0.834 s (-61 ms; 95% interval -135 ms to -19 ms) | **pass** |
| first token, p90 | at most 150 ms above 1x4 | 1.156 s against 1.031 s (+125 ms; 95% interval -53 ms to +227 ms) | **pass** |
| wrong session on clear turns | not above the 1x4 rate | 5 of 96 (2% to 12%) against 0 of 101 | **FAIL** |
| asked first on ambiguous turns | at least 30 of 42 (10 of 14, scaled to n) | 19 of 42 (31% to 60%) | **FAIL** |
| reader calls an hour with 80% of sessions quiet | at most 30% of all active | 5580 against 27900 (20%); models: stubbed | **pass** |
| 30 sessions finish within a minute | at most 4 spoken lines, nothing lost | 5 spoken, 0 held, 25 lost, of 30 (fleet-20261127-020207-burst-10x30-fleet-off) | **FAIL** |

### 1x4, the fleet build, POINTE_FLEET=on, build `271e64c1d0`

3 runs of the turn list: 180 turns driven, 0 crashed, 0 not run (their run stopped first).

| Bar | The plan's bar | Measured | |
|---|---|---|---|
| tokens of "what needs me" | at most 1,800 | max 828 (median 644), 180 turns | **pass** |
| brain input tokens per turn | the reference for the other sizes | median 26,339 | **pass** |
| first token, median | the reference for the other sizes | 0.716 s | **pass** |
| first token, p90 | the reference for the other sizes | 1.005 s | **pass** |
| wrong session on clear turns | the reference for the other sizes | 0 of 102 (0% to 4%) | **pass** |
| asked first on ambiguous turns | at least 30 of 42 (10 of 14, scaled to n) | 41 of 42 (88% to 100%) | **pass** |
| reader calls an hour with 80% of sessions quiet | at most 30% of all active | 120 against 480 (25%); models: stubbed | **pass** |
| 30 sessions finish within a minute | at most 4 spoken lines, nothing lost | not measured | **not measured** |

### 5x20, the fleet build, POINTE_FLEET=on, build `271e64c1d0`

3 runs of the turn list: 180 turns driven, 0 crashed, 0 not run (their run stopped first).

| Bar | The plan's bar | Measured | |
|---|---|---|---|
| tokens of "what needs me" | at most 1,800 | max 1,098 (median 1,011), 180 turns | **pass** |
| brain input tokens per turn | within 10% of 1x4 | median 29,205 against 26,339 (+10.9%; 95% interval +1.6% to +21.7%) | **FAIL** |
| first token, median | at most 150 ms above 1x4 | 0.673 s against 0.716 s (-43 ms; 95% interval -106 ms to +26 ms) | **pass** |
| first token, p90 | at most 150 ms above 1x4 | 1.060 s against 1.005 s (+55 ms; 95% interval -60 ms to +144 ms) | **pass** |
| wrong session on clear turns | not above the 1x4 rate | 0 of 102 (0% to 4%) against 0 of 102 | **pass** |
| wrong session on clear turns | at most 5% | 0 of 102 (0% to 4%) | **pass** |
| asked first on ambiguous turns | at least 30 of 42 (10 of 14, scaled to n) | 35 of 42 (69% to 92%) | **pass** |
| reader calls an hour with 80% of sessions quiet | at most 30% of all active | 1920 against 9600 (20%); models: stubbed | **pass** |
| 30 sessions finish within a minute | at most 4 spoken lines, nothing lost | 5 spoken, 1 held, 25 lost, of 30 (fleet-20261127-015503-burst-5x20-fleet-on) | **FAIL** |

### 10x30, the fleet build, POINTE_FLEET=on, build `271e64c1d0`

3 runs of the turn list: 165 turns driven, 0 crashed, 0 not run (their run stopped first).

| Bar | The plan's bar | Measured | |
|---|---|---|---|
| tokens of "what needs me" | at most 1,800 | max 1,697 (median 1,656), 165 turns | **pass** |
| brain input tokens per turn | within 10% of 1x4 | median 30,148 against 26,339 (+14.5%; 95% interval +5.8% to +25.0%) | **FAIL** |
| first token, median | at most 150 ms above 1x4 | 1.224 s against 0.716 s (+508 ms; 95% interval +403 ms to +601 ms) | **FAIL** |
| first token, p90 | at most 150 ms above 1x4 | 1.781 s against 1.005 s (+776 ms; 95% interval +711 ms to +881 ms) | **FAIL** |
| wrong session on clear turns | not above the 1x4 rate | 0 of 96 (0% to 4%) against 0 of 102 | **pass** |
| asked first on ambiguous turns | at least 30 of 42 (10 of 14, scaled to n) | 38 of 42 (78% to 96%) | **pass** |
| reader calls an hour with 80% of sessions quiet | at most 30% of all active | 4320 against 21420 (20%); models: stubbed | **pass** |
| 30 sessions finish within a minute | at most 4 spoken lines, nothing lost | 6 spoken, 1 held, 25 lost, of 30 (fleet-20261127-015918-burst-10x30-fleet-on) | **FAIL** |

### 5x20, the fleet build, POINTE_FLEET=on, build `26a52ec697`

0 runs of the turn list: 0 turns driven, 0 crashed, 0 not run (their run stopped first); no 1x4 run of this arm on this build, so nothing to compare with.

| Bar | The plan's bar | Measured | |
|---|---|---|---|
| tokens of "what needs me" | at most 1,800 | not measured | **not measured** |
| brain input tokens per turn | within 10% of 1x4 | not measured | **not measured** |
| first token, median | at most 150 ms above 1x4 | not measured | **not measured** |
| first token, p90 | at most 150 ms above 1x4 | not measured | **not measured** |
| wrong session on clear turns | not above the 1x4 rate | not measured | **not measured** |
| wrong session on clear turns | at most 5% | not measured | **not measured** |
| asked first on ambiguous turns | at least 0 of 0 (10 of 14, scaled to n) | not measured | **not measured** |
| reader calls an hour with 80% of sessions quiet | at most 30% of all active | 1920 against 9600 (20%); models: stubbed | **pass** |
| 30 sessions finish within a minute | at most 4 spoken lines, nothing lost | 5 spoken, 23 held, 0 lost, of 30 (fleet-20261127-031550-burst-5x20-fleet-on) | **FAIL** |
| 30 sessions finish within a minute | at most 4 spoken lines, nothing lost | 6 spoken, 23 held, 0 lost, of 30 (fleet-20261127-031758-burst-5x20-fleet-on) | **FAIL** |
| 30 sessions finish within a minute | at most 4 spoken lines, nothing lost | 4 spoken, 23 held, 0 lost, of 30 (fleet-20261127-031957-burst-5x20-fleet-on) | **pass** |

### 10x30, the fleet build, POINTE_FLEET=on, build `26a52ec697`

0 runs of the turn list: 0 turns driven, 0 crashed, 0 not run (their run stopped first); no 1x4 run of this arm on this build, so nothing to compare with.

| Bar | The plan's bar | Measured | |
|---|---|---|---|
| tokens of "what needs me" | at most 1,800 | not measured | **not measured** |
| brain input tokens per turn | within 10% of 1x4 | not measured | **not measured** |
| first token, median | at most 150 ms above 1x4 | not measured | **not measured** |
| first token, p90 | at most 150 ms above 1x4 | not measured | **not measured** |
| wrong session on clear turns | not above the 1x4 rate | not measured | **not measured** |
| asked first on ambiguous turns | at least 0 of 0 (10 of 14, scaled to n) | not measured | **not measured** |
| reader calls an hour with 80% of sessions quiet | at most 30% of all active | 4320 against 21420 (20%); models: stubbed | **pass** |
| 30 sessions finish within a minute | at most 4 spoken lines, nothing lost | 4 spoken, 23 held, 4 lost, of 30 (fleet-20261127-032202-burst-10x30-fleet-on) | **FAIL** |
| 30 sessions finish within a minute | at most 4 spoken lines, nothing lost | 4 spoken, 24 held, 3 lost, of 30 (fleet-20261127-032444-burst-10x30-fleet-on) | **FAIL** |
| 30 sessions finish within a minute | at most 4 spoken lines, nothing lost | 4 spoken, 25 held, 1 lost, of 30 (fleet-20261127-032726-burst-10x30-fleet-on) | **FAIL** |

## The arms, as the daemon states them

3152 of 3152 rows carry the daemon's own `fleet.on` (`/voice/context`) equal to their arm's. The `pointe/` folder each arm ran (its git tree): fleet-off `05857b19f6`, fleet-off `0b98c14e3a`, fleet-off `271e64c1d0`, fleet-off `502cd35ea5`, fleet-on `05857b19f6`, fleet-on `0b98c14e3a`, fleet-on `26a52ec697`, fleet-on `271e64c1d0`, fleet-on `502cd35ea5`.

Carried: the fleet-off rows of build `05857b19f6` are shown again under build `0b98c14e3a`, not run again. Between the two builds (f74b9505 and ec55bef5 on main) every change in pointe/daemon.py and pointe/scale.py is behind scale.enabled(), which is false with POINTE_FLEET=off; the other changes are the page (ui.html) and the defaults for people invited to a machine (guests.py), and no run here has a second person. Shown by `git diff f74b9505 ec55bef5 -- pointe`.

## Every run

| Arm | Size | Run | Clear: right | Clear: wrong session | Clear: asked instead | Clear: nothing | Ambiguous: asked | Ambiguous: sent | Ambiguous: neither | Driven / crashed / not run | Needs tokens, median / max | Brain input per turn, median | First token, median / p90 | First send, median | Reader / checker / brain calls in the run |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| the fleet build, POINTE_FLEET=off, build `502cd35ea5` | 1x4 | fleet-20261126-152305-turns-1x4-fleet-off-r1 | 24 of 34 (54% to 83%) | 0 of 34 (0% to 10%) | 5 of 34 (6% to 30%) | 5 of 34 (6% to 30%) | 12 of 14 (60% to 96%) | 1 of 14 (1% to 31%) | 1 of 14 (1% to 31%) | 60 / 0 / 0 | 710 (664 to 733) / 805 | 26,935 (22,648 to 30,110) | 0.81 s (0.76 to 0.89) / 1.02 s (0.96 to 1.12) | 1.63 s (1.37 to 1.82) | 9 / 24 / 73 |
| the fleet build, POINTE_FLEET=off, build `502cd35ea5` | 1x4 | fleet-20261126-172105-turns-1x4-fleet-off-r2 | 23 of 34 (51% to 81%) | 0 of 34 (0% to 10%) | 7 of 34 (10% to 37%) | 4 of 34 (5% to 27%) | 14 of 14 (78% to 100%) | 0 of 14 (0% to 22%) | 0 of 14 (0% to 22%) | 60 / 0 / 0 | 659 (604 to 678) / 766 | 26,062 (24,531 to 28,158) | 0.92 s (0.88 to 0.97) / 1.21 s (1.09 to 1.42) | 1.51 s (1.23 to 1.67) | 4 / 24 / 79 |
| the fleet build, POINTE_FLEET=off, build `502cd35ea5` | 1x4 | fleet-20261126-172812-turns-1x4-fleet-off-r3 | 22 of 34 (48% to 79%) | 0 of 34 (0% to 10%) | 9 of 34 (15% to 43%) | 3 of 34 (3% to 23%) | 13 of 14 (69% to 99%) | 1 of 14 (1% to 31%) | 0 of 14 (0% to 22%) | 60 / 0 / 0 | 620 (592 to 649) / 725 | 27,507 (22,679 to 30,127) | 0.91 s (0.89 to 0.94) / 1.13 s (1.07 to 1.34) | 1.51 s (1.30 to 1.79) | 7 / 22 / 80 |
| the fleet build, POINTE_FLEET=off, build `502cd35ea5` | 1x4 | all runs | 69 of 102 (58% to 76%) | 0 of 102 (0% to 4%) | 21 of 102 (14% to 29%) | 12 of 102 (7% to 19%) | 39 of 42 (81% to 98%) | 2 of 42 (1% to 16%) | 1 of 42 (0% to 12%) | 180 / 0 / 0 | 650 (630 to 668) / 805 | 26,918 (25,009 to 28,634) | 0.90 s (0.87 to 0.92) / 1.13 s (1.08 to 1.21) | 1.58 s (1.47 to 1.66) | 20 / 70 / 232 |
| the fleet build, POINTE_FLEET=off, build `502cd35ea5` | 5x20 | fleet-20261126-193413-turns-5x20-fleet-off-r1 | 19 of 34 (39% to 71%) | 1 of 34 (1% to 15%) | 12 of 34 (21% to 52%) | 2 of 34 (2% to 19%) | 11 of 14 (52% to 92%) | 2 of 14 (4% to 40%) | 1 of 14 (1% to 31%) | 60 / 0 / 0 | 4,843 (4,843 to 4,846) / 4,879 | 34,769 (30,099 to 37,879) | 0.72 s (0.68 to 0.79) / 1.53 s (1.09 to 3.33) | 1.33 s (1.03 to 1.68) | 23 / 41 / 103 |
| the fleet build, POINTE_FLEET=off, build `502cd35ea5` | 5x20 | fleet-20261126-194422-turns-5x20-fleet-off-r2 | 22 of 34 (48% to 79%) | 0 of 34 (0% to 10%) | 10 of 34 (17% to 46%) | 2 of 34 (2% to 19%) | 12 of 14 (60% to 96%) | 2 of 14 (4% to 40%) | 0 of 14 (0% to 22%) | 60 / 0 / 0 | 4,870 (4,864 to 4,873) / 4,888 | 35,624 (32,586 to 50,383) | 0.65 s (0.60 to 0.68) / 1.09 s (0.82 to 1.20) | 1.08 s (0.96 to 1.46) | 17 / 31 / 97 |
| the fleet build, POINTE_FLEET=off, build `502cd35ea5` | 5x20 | fleet-20261126-195354-turns-5x20-fleet-off-r3 | 17 of 34 (34% to 66%) | 1 of 34 (1% to 15%) | 15 of 34 (29% to 61%) | 1 of 34 (1% to 15%) | 13 of 14 (69% to 99%) | 1 of 14 (1% to 31%) | 0 of 14 (0% to 22%) | 60 / 0 / 0 | 4,860 (4,859 to 4,861) / 4,880 | 33,158 (30,461 to 36,290) | 0.64 s (0.61 to 0.66) / 0.93 s (0.79 to 1.14) | 0.99 s (0.96 to 1.07) | 14 / 25 / 90 |
| the fleet build, POINTE_FLEET=off, build `502cd35ea5` | 5x20 | all runs | 58 of 102 (47% to 66%) | 2 of 102 (1% to 7%) | 37 of 102 (28% to 46%) | 5 of 102 (2% to 11%) | 36 of 42 (72% to 93%) | 5 of 42 (5% to 25%) | 1 of 42 (0% to 12%) | 180 / 0 / 0 | 4,858 (4,855 to 4,860) / 4,888 | 34,727 (32,300 to 36,219) | 0.66 s (0.63 to 0.68) / 1.16 s (0.98 to 1.36) | 1.05 s (1.00 to 1.19) | 54 / 97 / 290 |
| the fleet build, POINTE_FLEET=on, build `502cd35ea5` | 1x4 | fleet-20261126-150230-turns-1x4-fleet-on-r1 | 24 of 34 (54% to 83%) | 0 of 34 (0% to 10%) | 6 of 34 (8% to 34%) | 4 of 34 (5% to 27%) | 13 of 14 (69% to 99%) | 1 of 14 (1% to 31%) | 0 of 14 (0% to 22%) | 60 / 0 / 0 | 657 (618 to 683) / 760 | 27,742 (23,553 to 30,624) | 0.72 s (0.65 to 0.77) / 1.06 s (0.95 to 1.15) | 1.52 s (1.03 to 1.64) | 5 / 21 / 76 |
| the fleet build, POINTE_FLEET=on, build `502cd35ea5` | 1x4 | fleet-20261126-150917-turns-1x4-fleet-on-r2 | 23 of 34 (51% to 81%) | 0 of 34 (0% to 10%) | 7 of 34 (10% to 37%) | 4 of 34 (5% to 27%) | 13 of 14 (69% to 99%) | 0 of 14 (0% to 22%) | 1 of 14 (1% to 31%) | 60 / 0 / 0 | 658 (603 to 677) / 765 | 25,893 (23,623 to 28,655) | 0.81 s (0.76 to 0.88) / 1.14 s (0.97 to 1.24) | 1.35 s (1.13 to 1.74) | 3 / 23 / 80 |
| the fleet build, POINTE_FLEET=on, build `502cd35ea5` | 1x4 | fleet-20261126-151613-turns-1x4-fleet-on-r3 | 23 of 34 (51% to 81%) | 1 of 34 (1% to 15%) | 7 of 34 (10% to 37%) | 3 of 34 (3% to 23%) | 14 of 14 (78% to 100%) | 0 of 14 (0% to 22%) | 0 of 14 (0% to 22%) | 60 / 0 / 0 | 609 (586 to 653) / 736 | 26,708 (22,719 to 29,526) | 0.79 s (0.70 to 0.88) / 1.18 s (1.08 to 1.50) | 1.30 s (0.94 to 1.94) | 6 / 20 / 72 |
| the fleet build, POINTE_FLEET=on, build `502cd35ea5` | 1x4 | all runs | 70 of 102 (59% to 77%) | 1 of 102 (0% to 5%) | 20 of 102 (13% to 28%) | 11 of 102 (6% to 18%) | 40 of 42 (84% to 99%) | 1 of 42 (0% to 12%) | 1 of 42 (0% to 12%) | 180 / 0 / 0 | 645 (613 to 658) / 765 | 26,400 (24,114 to 28,346) | 0.77 s (0.72 to 0.82) / 1.15 s (1.08 to 1.18) | 1.42 s (1.21 to 1.63) | 14 / 64 / 228 |
| the fleet build, POINTE_FLEET=on, build `502cd35ea5` | 5x20 | fleet-20261126-173527-turns-5x20-fleet-on-r1 | 19 of 32 (42% to 74%) | 1 of 32 (1% to 16%) | 11 of 32 (20% to 52%) | 1 of 32 (1% to 16%) | 10 of 14 (45% to 88%) | 2 of 14 (4% to 40%) | 2 of 14 (4% to 40%) | 58 / 0 / 2 | 1,669 (1,653 to 1,679) / 1,740 | 33,847 (30,092 to 54,222) | 1.00 s (0.97 to 1.03) / 1.44 s (1.26 to 1.72) | 1.84 s (1.59 to 2.17) | 112 / 36 / 110 |
| the fleet build, POINTE_FLEET=on, build `502cd35ea5` | 5x20 | fleet-20261126-174517-turns-5x20-fleet-on-r2 | 15 of 34 (29% to 61%) | 7 of 34 (10% to 37%) | 11 of 34 (19% to 49%) | 1 of 34 (1% to 15%) | 9 of 14 (39% to 84%) | 4 of 14 (12% to 55%) | 1 of 14 (1% to 31%) | 60 / 0 / 0 | 1,611 (1,595 to 1,637) / 1,707 | 33,273 (30,177 to 42,448) | 0.85 s (0.82 to 0.90) / 1.14 s (0.97 to 1.55) | 1.48 s (1.23 to 1.89) | 18 / 38 / 101 |
| the fleet build, POINTE_FLEET=on, build `502cd35ea5` | 5x20 | fleet-20261126-175413-turns-5x20-fleet-on-r3 | 13 of 34 (24% to 55%) | 7 of 34 (10% to 37%) | 14 of 34 (26% to 58%) | 0 of 34 (0% to 10%) | 1 of 14 (1% to 31%) | 13 of 14 (69% to 99%) | 0 of 14 (0% to 22%) | 60 / 0 / 0 | 1,632 (1,602 to 1,664) / 1,811 | 32,846 (30,815 to 50,083) | 0.88 s (0.81 to 0.90) / 1.08 s (0.98 to 1.18) | 1.50 s (1.27 to 2.03) | 12 / 55 / 101 |
| the fleet build, POINTE_FLEET=on, build `502cd35ea5` | 5x20 | all runs | 47 of 100 (38% to 57%) | 15 of 100 (9% to 23%) | 36 of 100 (27% to 46%) | 2 of 100 (1% to 7%) | 20 of 42 (33% to 62%) | 19 of 42 (31% to 60%) | 3 of 42 (2% to 19%) | 178 / 0 / 2 | 1,639 (1,625 to 1,654) / 1,811 | 33,411 (31,935 to 38,966) | 0.90 s (0.88 to 0.93) / 1.19 s (1.09 to 1.31) | 1.72 s (1.49 to 1.87) | 142 / 129 / 312 |
| the fleet build, POINTE_FLEET=off, build `05857b19f6` | 1x4 | fleet-20261126-212506-turns-1x4-fleet-off-r1 | 24 of 34 (54% to 83%) | 0 of 34 (0% to 10%) | 4 of 34 (5% to 27%) | 6 of 34 (8% to 34%) | 13 of 14 (69% to 99%) | 1 of 14 (1% to 31%) | 0 of 14 (0% to 22%) | 60 / 0 / 0 | 679 (645 to 696) / 787 | 26,623 (23,635 to 30,725) | 0.85 s (0.71 to 0.92) / 1.20 s (1.06 to 1.22) | 1.72 s (1.00 to 2.44) | 4 / 23 / 74 |
| the fleet build, POINTE_FLEET=off, build `05857b19f6` | 1x4 | fleet-20261126-213205-turns-1x4-fleet-off-r2 | 23 of 34 (51% to 81%) | 0 of 34 (0% to 10%) | 7 of 34 (10% to 37%) | 4 of 34 (5% to 27%) | 14 of 14 (78% to 100%) | 0 of 14 (0% to 22%) | 0 of 14 (0% to 22%) | 60 / 0 / 0 | 664 (609 to 683) / 771 | 25,986 (24,671 to 28,776) | 0.82 s (0.75 to 0.88) / 1.14 s (0.97 to 1.20) | 1.27 s (1.23 to 1.54) | 3 / 24 / 82 |
| the fleet build, POINTE_FLEET=off, build `05857b19f6` | 1x4 | fleet-20261126-213903-turns-1x4-fleet-off-r3 | 24 of 34 (54% to 83%) | 1 of 34 (1% to 15%) | 5 of 34 (6% to 30%) | 4 of 34 (5% to 27%) | 12 of 14 (60% to 96%) | 0 of 14 (0% to 22%) | 2 of 14 (4% to 40%) | 60 / 0 / 0 | 641 (611 to 672) / 768 | 25,304 (23,557 to 27,196) | 0.86 s (0.81 to 0.90) / 1.04 s (0.97 to 1.08) | 1.78 s (1.68 to 2.06) | 4 / 41 / 78 |
| the fleet build, POINTE_FLEET=off, build `05857b19f6` | 1x4 | all runs | 71 of 102 (60% to 78%) | 1 of 102 (0% to 5%) | 16 of 102 (10% to 24%) | 14 of 102 (8% to 22%) | 39 of 42 (81% to 98%) | 1 of 42 (0% to 12%) | 2 of 42 (1% to 16%) | 180 / 0 / 0 | 664 (641 to 673) / 787 | 25,986 (24,522 to 27,771) | 0.84 s (0.80 to 0.88) / 1.14 s (1.05 to 1.18) | 1.66 s (1.53 to 1.83) | 11 / 88 / 234 |
| the fleet build, POINTE_FLEET=off, build `05857b19f6` | 5x20 | fleet-20261126-203352-turns-5x20-fleet-off-r1 | 23 of 34 (51% to 81%) | 1 of 34 (1% to 15%) | 9 of 34 (15% to 43%) | 1 of 34 (1% to 15%) | 10 of 14 (45% to 88%) | 4 of 14 (12% to 55%) | 0 of 14 (0% to 22%) | 60 / 0 / 0 | 4,858 (4,857 to 4,860) / 4,882 | 33,304 (30,510 to 39,638) | 1.34 s (1.24 to 1.48) / 1.76 s (1.68 to 1.98) | 2.06 s (1.83 to 2.36) | 19 / 41 / 102 |
| the fleet build, POINTE_FLEET=off, build `05857b19f6` | 5x20 | fleet-20261126-204441-turns-5x20-fleet-off-r2 | 23 of 34 (51% to 81%) | 0 of 34 (0% to 10%) | 10 of 34 (17% to 46%) | 1 of 34 (1% to 15%) | 11 of 14 (52% to 92%) | 3 of 14 (8% to 48%) | 0 of 14 (0% to 22%) | 60 / 0 / 0 | 4,858 (4,849 to 4,858) / 4,879 | 34,317 (30,569 to 37,408) | 1.09 s (1.04 to 1.16) / 1.34 s (1.27 to 1.45) | 2.34 s (1.83 to 2.65) | 21 / 35 / 96 |
| the fleet build, POINTE_FLEET=off, build `05857b19f6` | 5x20 | fleet-20261126-205432-turns-5x20-fleet-off-r3 | 22 of 34 (48% to 79%) | 0 of 34 (0% to 10%) | 11 of 34 (19% to 49%) | 1 of 34 (1% to 15%) | 10 of 14 (45% to 88%) | 2 of 14 (4% to 40%) | 2 of 14 (4% to 40%) | 60 / 0 / 0 | 4,876 (4,875 to 4,878) / 4,893 | 35,662 (30,301 to 44,492) | 1.05 s (0.98 to 1.09) / 1.31 s (1.14 to 1.64) | 1.45 s (1.34 to 1.92) | 27 / 33 / 92 |
| the fleet build, POINTE_FLEET=off, build `05857b19f6` | 5x20 | all runs | 68 of 102 (57% to 75%) | 1 of 102 (0% to 5%) | 30 of 102 (21% to 39%) | 3 of 102 (1% to 8%) | 31 of 42 (59% to 85%) | 9 of 42 (12% to 36%) | 2 of 42 (1% to 16%) | 180 / 0 / 0 | 4,860 (4,859 to 4,866) / 4,893 | 34,988 (31,937 to 36,293) | 1.11 s (1.07 to 1.15) / 1.64 s (1.50 to 1.73) | 1.97 s (1.79 to 2.24) | 67 / 109 / 290 |
| the fleet build, POINTE_FLEET=on, build `05857b19f6` | 1x4 | fleet-20261126-210408-turns-1x4-fleet-on-r1 | 24 of 34 (54% to 83%) | 0 of 34 (0% to 10%) | 8 of 34 (12% to 40%) | 2 of 34 (2% to 19%) | 14 of 14 (78% to 100%) | 0 of 14 (0% to 22%) | 0 of 14 (0% to 22%) | 60 / 0 / 0 | 605 (562 to 619) / 730 | 27,230 (24,093 to 29,932) | 0.85 s (0.80 to 0.90) / 1.00 s (0.96 to 1.04) | 1.21 s (1.16 to 1.73) | 4 / 21 / 72 |
| the fleet build, POINTE_FLEET=on, build `05857b19f6` | 1x4 | fleet-20261126-211055-turns-1x4-fleet-on-r2 | 23 of 34 (51% to 81%) | 1 of 34 (1% to 15%) | 6 of 34 (8% to 34%) | 4 of 34 (5% to 27%) | 11 of 14 (52% to 92%) | 0 of 14 (0% to 22%) | 3 of 14 (8% to 48%) | 60 / 0 / 0 | 666 (611 to 685) / 774 | 25,090 (22,441 to 29,300) | 0.79 s (0.75 to 0.84) / 1.05 s (0.97 to 1.13) | 1.49 s (1.09 to 1.75) | 3 / 25 / 92 |
| the fleet build, POINTE_FLEET=on, build `05857b19f6` | 1x4 | fleet-20261126-211802-turns-1x4-fleet-on-r3 | 23 of 34 (51% to 81%) | 0 of 34 (0% to 10%) | 8 of 34 (12% to 40%) | 3 of 34 (3% to 23%) | 13 of 14 (69% to 99%) | 0 of 14 (0% to 22%) | 1 of 14 (1% to 31%) | 60 / 0 / 0 | 609 (581 to 639) / 728 | 24,856 (22,079 to 29,428) | 0.82 s (0.69 to 0.93) / 1.17 s (1.04 to 1.32) | 1.38 s (0.97 to 1.80) | 7 / 21 / 75 |
| the fleet build, POINTE_FLEET=on, build `05857b19f6` | 1x4 | all runs | 70 of 102 (59% to 77%) | 1 of 102 (0% to 5%) | 22 of 102 (15% to 31%) | 9 of 102 (5% to 16%) | 38 of 42 (78% to 96%) | 0 of 42 (0% to 8%) | 4 of 42 (4% to 22%) | 180 / 0 / 0 | 616 (605 to 639) / 774 | 25,885 (23,975 to 28,399) | 0.82 s (0.79 to 0.88) / 1.08 s (1.00 to 1.13) | 1.45 s (1.20 to 1.68) | 14 / 67 / 239 |
| the fleet build, POINTE_FLEET=on, build `05857b19f6` | 5x20 | fleet-20261126-200427-turns-5x20-fleet-on-r1 | 34 of 34 (90% to 100%) | 0 of 34 (0% to 10%) | 0 of 34 (0% to 10%) | 0 of 34 (0% to 10%) | 12 of 14 (60% to 96%) | 2 of 14 (4% to 40%) | 0 of 14 (0% to 22%) | 60 / 0 / 0 | 1,605 (1,597 to 1,608) / 1,617 | 30,342 (28,307 to 32,516) | 0.89 s (0.87 to 0.91) / 1.06 s (0.97 to 1.24) | 1.28 s (1.21 to 2.03) | 18 / 39 / 83 |
| the fleet build, POINTE_FLEET=on, build `05857b19f6` | 5x20 | fleet-20261126-201349-turns-5x20-fleet-on-r2 | 32 of 32 (89% to 100%) | 0 of 32 (0% to 11%) | 0 of 32 (0% to 11%) | 0 of 32 (0% to 11%) | 11 of 13 (58% to 96%) | 2 of 13 (4% to 42%) | 0 of 13 (0% to 23%) | 57 / 3 / 0 | 1,599 (1,595 to 1,600) / 1,616 | 30,971 (29,128 to 33,121) | 0.94 s (0.90 to 1.00) / 2.62 s (1.18 to 3.69) | 1.58 s (1.33 to 2.34) | 23 / 43 / 90 |
| the fleet build, POINTE_FLEET=on, build `05857b19f6` | 5x20 | fleet-20261126-202417-turns-5x20-fleet-on-r3 | 34 of 34 (90% to 100%) | 0 of 34 (0% to 10%) | 0 of 34 (0% to 10%) | 0 of 34 (0% to 10%) | 12 of 14 (60% to 96%) | 2 of 14 (4% to 40%) | 0 of 14 (0% to 22%) | 60 / 0 / 0 | 1,598 (1,595 to 1,601) / 1,616 | 31,618 (29,252 to 34,081) | 0.87 s (0.80 to 0.91) / 1.30 s (1.09 to 1.93) | 1.46 s (1.21 to 1.90) | 17 / 37 / 88 |
| the fleet build, POINTE_FLEET=on, build `05857b19f6` | 5x20 | all runs | 100 of 100 (96% to 100%) | 0 of 100 (0% to 4%) | 0 of 100 (0% to 4%) | 0 of 100 (0% to 4%) | 35 of 41 (72% to 93%) | 6 of 41 (7% to 28%) | 0 of 41 (0% to 9%) | 177 / 3 / 0 | 1,599 (1,597 to 1,602) / 1,617 | 31,253 (29,564 to 32,382) | 0.89 s (0.88 to 0.92) / 1.30 s (1.15 to 1.81) | 1.38 s (1.30 to 1.83) | 58 / 119 / 261 |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 1x4 | fleet-20261126-212506-turns-1x4-fleet-off-r1 | 24 of 34 (54% to 83%) | 0 of 34 (0% to 10%) | 4 of 34 (5% to 27%) | 6 of 34 (8% to 34%) | 13 of 14 (69% to 99%) | 1 of 14 (1% to 31%) | 0 of 14 (0% to 22%) | 60 / 0 / 0 | 679 (645 to 696) / 787 | 26,623 (23,635 to 30,725) | 0.85 s (0.71 to 0.92) / 1.20 s (1.06 to 1.22) | 1.72 s (1.00 to 2.44) | 4 / 23 / 74 |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 1x4 | fleet-20261126-213205-turns-1x4-fleet-off-r2 | 23 of 34 (51% to 81%) | 0 of 34 (0% to 10%) | 7 of 34 (10% to 37%) | 4 of 34 (5% to 27%) | 14 of 14 (78% to 100%) | 0 of 14 (0% to 22%) | 0 of 14 (0% to 22%) | 60 / 0 / 0 | 664 (609 to 683) / 771 | 25,986 (24,671 to 28,776) | 0.82 s (0.75 to 0.88) / 1.14 s (0.97 to 1.20) | 1.27 s (1.23 to 1.54) | 3 / 24 / 82 |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 1x4 | fleet-20261126-213903-turns-1x4-fleet-off-r3 | 24 of 34 (54% to 83%) | 1 of 34 (1% to 15%) | 5 of 34 (6% to 30%) | 4 of 34 (5% to 27%) | 12 of 14 (60% to 96%) | 0 of 14 (0% to 22%) | 2 of 14 (4% to 40%) | 60 / 0 / 0 | 641 (611 to 672) / 768 | 25,304 (23,557 to 27,196) | 0.86 s (0.81 to 0.90) / 1.04 s (0.97 to 1.08) | 1.78 s (1.68 to 2.06) | 4 / 41 / 78 |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 1x4 | all runs | 71 of 102 (60% to 78%) | 1 of 102 (0% to 5%) | 16 of 102 (10% to 24%) | 14 of 102 (8% to 22%) | 39 of 42 (81% to 98%) | 1 of 42 (0% to 12%) | 2 of 42 (1% to 16%) | 180 / 0 / 0 | 664 (641 to 673) / 787 | 25,986 (24,522 to 27,771) | 0.84 s (0.80 to 0.88) / 1.14 s (1.05 to 1.18) | 1.66 s (1.53 to 1.83) | 11 / 88 / 234 |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 5x20 | fleet-20261126-203352-turns-5x20-fleet-off-r1 | 23 of 34 (51% to 81%) | 1 of 34 (1% to 15%) | 9 of 34 (15% to 43%) | 1 of 34 (1% to 15%) | 10 of 14 (45% to 88%) | 4 of 14 (12% to 55%) | 0 of 14 (0% to 22%) | 60 / 0 / 0 | 4,858 (4,857 to 4,860) / 4,882 | 33,304 (30,510 to 39,638) | 1.34 s (1.24 to 1.48) / 1.76 s (1.68 to 1.98) | 2.06 s (1.83 to 2.36) | 19 / 41 / 102 |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 5x20 | fleet-20261126-204441-turns-5x20-fleet-off-r2 | 23 of 34 (51% to 81%) | 0 of 34 (0% to 10%) | 10 of 34 (17% to 46%) | 1 of 34 (1% to 15%) | 11 of 14 (52% to 92%) | 3 of 14 (8% to 48%) | 0 of 14 (0% to 22%) | 60 / 0 / 0 | 4,858 (4,849 to 4,858) / 4,879 | 34,317 (30,569 to 37,408) | 1.09 s (1.04 to 1.16) / 1.34 s (1.27 to 1.45) | 2.34 s (1.83 to 2.65) | 21 / 35 / 96 |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 5x20 | fleet-20261126-205432-turns-5x20-fleet-off-r3 | 22 of 34 (48% to 79%) | 0 of 34 (0% to 10%) | 11 of 34 (19% to 49%) | 1 of 34 (1% to 15%) | 10 of 14 (45% to 88%) | 2 of 14 (4% to 40%) | 2 of 14 (4% to 40%) | 60 / 0 / 0 | 4,876 (4,875 to 4,878) / 4,893 | 35,662 (30,301 to 44,492) | 1.05 s (0.98 to 1.09) / 1.31 s (1.14 to 1.64) | 1.45 s (1.34 to 1.92) | 27 / 33 / 92 |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 5x20 | all runs | 68 of 102 (57% to 75%) | 1 of 102 (0% to 5%) | 30 of 102 (21% to 39%) | 3 of 102 (1% to 8%) | 31 of 42 (59% to 85%) | 9 of 42 (12% to 36%) | 2 of 42 (1% to 16%) | 180 / 0 / 0 | 4,860 (4,859 to 4,866) / 4,893 | 34,988 (31,937 to 36,293) | 1.11 s (1.07 to 1.15) / 1.64 s (1.50 to 1.73) | 1.97 s (1.79 to 2.24) | 67 / 109 / 290 |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 10x30 | fleet-20261126-230636-turns-10x30-fleet-off-r1 | 20 of 32 (45% to 77%) | 2 of 32 (2% to 20%) | 7 of 32 (11% to 39%) | 3 of 32 (3% to 24%) | 3 of 14 (8% to 48%) | 10 of 14 (45% to 88%) | 1 of 14 (1% to 31%) | 55 / 0 / 0 | 4,724 (4,680 to 4,725) / 4,737 | 35,374 (31,967 to 54,298) | 1.54 s (1.39 to 1.75) / 2.01 s (1.83 to 2.15) | 2.13 s (1.98 to 2.29) | 319 / 46 / 99 |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 1x4 | fleet-20261126-214612-turns-1x4-fleet-on-r1 | 25 of 34 (57% to 85%) | 0 of 34 (0% to 10%) | 6 of 34 (8% to 34%) | 3 of 34 (3% to 23%) | 6 of 14 (21% to 67%) | 7 of 14 (27% to 73%) | 1 of 14 (1% to 31%) | 60 / 0 / 0 | 702 (668 to 732) / 840 | 28,304 (26,636 to 31,308) | 1.00 s (0.97 to 1.05) / 1.34 s (1.29 to 1.63) | 1.89 s (1.50 to 2.39) | 8 / 38 / 81 |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 1x4 | fleet-20261126-215348-turns-1x4-fleet-on-r2 | 23 of 34 (51% to 81%) | 0 of 34 (0% to 10%) | 8 of 34 (12% to 40%) | 3 of 34 (3% to 23%) | 12 of 14 (60% to 96%) | 2 of 14 (4% to 40%) | 0 of 14 (0% to 22%) | 60 / 0 / 0 | 665 (610 to 682) / 761 | 27,185 (25,514 to 29,448) | 0.92 s (0.87 to 0.99) / 1.12 s (1.09 to 1.25) | 1.56 s (1.38 to 1.82) | 3 / 26 / 82 |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 1x4 | fleet-20261126-220103-turns-1x4-fleet-on-r3 | 22 of 34 (48% to 79%) | 0 of 34 (0% to 10%) | 8 of 34 (12% to 40%) | 4 of 34 (5% to 27%) | 12 of 14 (60% to 96%) | 1 of 14 (1% to 31%) | 1 of 14 (1% to 31%) | 60 / 0 / 0 | 612 (589 to 656) / 727 | 25,144 (23,022 to 30,214) | 0.99 s (0.96 to 1.07) / 1.26 s (1.17 to 1.55) | 1.64 s (1.53 to 1.86) | 4 / 23 / 84 |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 1x4 | all runs | 70 of 102 (59% to 77%) | 0 of 102 (0% to 4%) | 22 of 102 (15% to 31%) | 10 of 102 (5% to 17%) | 30 of 42 (56% to 83%) | 10 of 42 (13% to 39%) | 2 of 42 (1% to 16%) | 180 / 0 / 0 | 656 (627 to 672) / 840 | 27,185 (26,183 to 29,074) | 0.99 s (0.96 to 1.01) / 1.30 s (1.20 to 1.34) | 1.67 s (1.53 to 1.83) | 15 / 87 / 247 |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 5x20 | fleet-20261126-220833-turns-5x20-fleet-on-r1 | 34 of 34 (90% to 100%) | 0 of 34 (0% to 10%) | 0 of 34 (0% to 10%) | 0 of 34 (0% to 10%) | 11 of 14 (52% to 92%) | 3 of 14 (8% to 48%) | 0 of 14 (0% to 22%) | 60 / 0 / 0 | 1,044 (1,040 to 1,052) / 1,106 | 28,598 (25,852 to 31,960) | 0.94 s (0.91 to 0.96) / 1.20 s (1.05 to 1.46) | 1.83 s (1.31 to 2.33) | 19 / 40 / 83 |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 5x20 | fleet-20261126-221814-turns-5x20-fleet-on-r2 | 33 of 34 (85% to 99%) | 1 of 34 (1% to 15%) | 0 of 34 (0% to 10%) | 0 of 34 (0% to 10%) | 12 of 14 (60% to 96%) | 2 of 14 (4% to 40%) | 0 of 14 (0% to 22%) | 60 / 0 / 0 | 1,044 (1,036 to 1,046) / 1,091 | 30,503 (28,237 to 32,940) | 0.99 s (0.95 to 1.07) / 1.30 s (1.11 to 1.42) | 1.77 s (1.59 to 2.40) | 28 / 38 / 84 |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 5x20 | fleet-20261126-222740-turns-5x20-fleet-on-r3 | 34 of 34 (90% to 100%) | 0 of 34 (0% to 10%) | 0 of 34 (0% to 10%) | 0 of 34 (0% to 10%) | 12 of 14 (60% to 96%) | 2 of 14 (4% to 40%) | 0 of 14 (0% to 22%) | 60 / 0 / 0 | 1,037 (1,008 to 1,043) / 1,109 | 30,577 (27,782 to 32,852) | 0.87 s (0.81 to 0.89) / 1.04 s (0.93 to 1.24) | 1.26 s (1.20 to 2.01) | 18 / 38 / 86 |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 5x20 | all runs | 101 of 102 (95% to 100%) | 1 of 102 (0% to 5%) | 0 of 102 (0% to 4%) | 0 of 102 (0% to 4%) | 35 of 42 (69% to 92%) | 7 of 42 (8% to 31%) | 0 of 42 (0% to 8%) | 180 / 0 / 0 | 1,043 (1,039 to 1,045) / 1,109 | 29,922 (28,279 to 31,500) | 0.93 s (0.90 to 0.95) / 1.18 s (1.11 to 1.30) | 1.66 s (1.48 to 1.91) | 65 / 116 / 253 |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 10x30 | fleet-20261126-223717-turns-10x30-fleet-on-r1 | 33 of 33 (90% to 100%) | 0 of 33 (0% to 10%) | 0 of 33 (0% to 10%) | 0 of 33 (0% to 10%) | 13 of 14 (69% to 99%) | 1 of 14 (1% to 31%) | 0 of 14 (0% to 22%) | 56 / 0 / 0 | 1,631 (1,624 to 1,653) / 1,688 | 30,019 (28,019 to 33,234) | 0.91 s (0.88 to 0.96) / 1.07 s (1.01 to 1.30) | 1.62 s (1.31 to 1.92) | 316 / 41 / 88 |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 10x30 | fleet-20261126-224601-turns-10x30-fleet-on-r2 | 32 of 33 (85% to 99%) | 1 of 33 (1% to 15%) | 0 of 33 (0% to 10%) | 0 of 33 (0% to 10%) | 12 of 14 (60% to 96%) | 1 of 14 (1% to 31%) | 1 of 14 (1% to 31%) | 56 / 0 / 0 | 1,676 (1,671 to 1,681) / 1,696 | 29,317 (27,362 to 32,632) | 1.46 s (1.27 to 1.70) / 2.12 s (1.94 to 2.25) | 2.21 s (1.99 to 2.79) | 142 / 38 / 86 |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 10x30 | fleet-20261126-225537-turns-10x30-fleet-on-r3 | 33 of 33 (90% to 100%) | 0 of 33 (0% to 10%) | 0 of 33 (0% to 10%) | 0 of 33 (0% to 10%) | 13 of 14 (69% to 99%) | 1 of 14 (1% to 31%) | 0 of 14 (0% to 22%) | 56 / 0 / 0 | 1,662 (1,657 to 1,665) / 1,697 | 29,638 (27,438 to 33,247) | 1.26 s (1.09 to 1.38) / 1.98 s (1.73 to 2.16) | 2.28 s (1.97 to 2.60) | 145 / 40 / 88 |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 10x30 | all runs | 98 of 99 (94% to 100%) | 1 of 99 (0% to 6%) | 0 of 99 (0% to 4%) | 0 of 99 (0% to 4%) | 38 of 42 (78% to 96%) | 3 of 42 (2% to 19%) | 1 of 42 (0% to 12%) | 168 / 0 / 0 | 1,664 (1,653 to 1,670) / 1,697 | 29,638 (28,760 to 31,227) | 1.09 s (1.02 to 1.23) / 1.96 s (1.81 to 2.12) | 2.14 s (1.95 to 2.35) | 603 / 119 / 262 |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 1x4 | fleet-20261127-005539-turns-1x4-fleet-off-r1 | 24 of 34 (54% to 83%) | 0 of 34 (0% to 10%) | 6 of 34 (8% to 34%) | 4 of 34 (5% to 27%) | 12 of 14 (60% to 96%) | 1 of 14 (1% to 31%) | 1 of 14 (1% to 31%) | 60 / 0 / 0 | 657 (606 to 672) / 775 | 26,580 (22,998 to 29,333) | 0.80 s (0.74 to 0.85) / 1.08 s (0.95 to 1.13) | 1.51 s (0.98 to 1.76) | 5 / 21 / 78 |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 1x4 | fleet-20261127-010246-turns-1x4-fleet-off-r2 | 23 of 33 (53% to 83%) | 0 of 33 (0% to 10%) | 1 of 33 (1% to 15%) | 9 of 33 (15% to 44%) | 13 of 14 (69% to 99%) | 1 of 14 (1% to 31%) | 0 of 14 (0% to 22%) | 59 / 1 / 0 | 666 (620 to 694) / 783 | 27,439 (25,177 to 28,716) | 0.78 s (0.75 to 0.85) / 1.03 s (0.95 to 1.11) | 1.29 s (1.12 to 1.60) | 5 / 27 / 84 |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 1x4 | fleet-20261127-011007-turns-1x4-fleet-off-r3 | 23 of 34 (51% to 81%) | 0 of 34 (0% to 10%) | 3 of 34 (3% to 23%) | 8 of 34 (12% to 40%) | 13 of 14 (69% to 99%) | 0 of 14 (0% to 22%) | 1 of 14 (1% to 31%) | 60 / 0 / 0 | 661 (633 to 691) / 766 | 27,529 (23,835 to 30,857) | 0.86 s (0.84 to 0.90) / 0.99 s (0.93 to 1.06) | 1.46 s (1.26 to 1.51) | 5 / 18 / 86 |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 1x4 | all runs | 70 of 101 (60% to 77%) | 0 of 101 (0% to 4%) | 10 of 101 (5% to 17%) | 21 of 101 (14% to 30%) | 38 of 42 (78% to 96%) | 2 of 42 (1% to 16%) | 2 of 42 (1% to 16%) | 179 / 1 / 0 | 661 (647 to 673) / 783 | 27,439 (25,132 to 28,907) | 0.83 s (0.80 to 0.85) / 1.03 s (0.99 to 1.09) | 1.40 s (1.22 to 1.51) | 15 / 66 / 248 |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 5x20 | fleet-20261127-000359-turns-5x20-fleet-off-r1 | 23 of 34 (51% to 81%) | 1 of 34 (1% to 15%) | 10 of 34 (17% to 46%) | 0 of 34 (0% to 10%) | 10 of 14 (45% to 88%) | 4 of 14 (12% to 55%) | 0 of 14 (0% to 22%) | 60 / 0 / 0 | 4,852 (4,851 to 4,855) / 4,879 | 37,383 (34,512 to 55,861) | 0.99 s (0.93 to 1.07) / 1.31 s (1.18 to 1.42) | 1.77 s (1.58 to 2.23) | 21 / 42 / 109 |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 5x20 | fleet-20261127-001447-turns-5x20-fleet-off-r2 | 24 of 34 (54% to 83%) | 0 of 34 (0% to 10%) | 10 of 34 (17% to 46%) | 0 of 34 (0% to 10%) | 12 of 14 (60% to 96%) | 2 of 14 (4% to 40%) | 0 of 14 (0% to 22%) | 60 / 0 / 0 | 4,857 (4,848 to 4,858) / 4,879 | 32,146 (28,962 to 34,835) | 1.00 s (0.94 to 1.04) / 1.37 s (1.18 to 1.90) | 1.74 s (1.55 to 2.08) | 18 / 26 / 92 |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 5x20 | fleet-20261127-002438-turns-5x20-fleet-off-r3 | 22 of 34 (48% to 79%) | 0 of 34 (0% to 10%) | 10 of 34 (17% to 46%) | 2 of 34 (2% to 19%) | 10 of 14 (45% to 88%) | 4 of 14 (12% to 55%) | 0 of 14 (0% to 22%) | 60 / 0 / 0 | 4,876 (4,863 to 4,877) / 4,890 | 35,802 (30,502 to 51,832) | 0.96 s (0.93 to 1.01) / 1.27 s (1.15 to 1.64) | 1.70 s (1.54 to 1.86) | 18 / 43 / 101 |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 5x20 | all runs | 69 of 102 (58% to 76%) | 1 of 102 (0% to 5%) | 30 of 102 (21% to 39%) | 2 of 102 (1% to 7%) | 32 of 42 (61% to 87%) | 10 of 42 (13% to 39%) | 0 of 42 (0% to 8%) | 180 / 0 / 0 | 4,858 (4,857 to 4,861) / 4,890 | 35,353 (32,594 to 37,023) | 0.99 s (0.95 to 1.01) / 1.32 s (1.21 to 1.53) | 1.74 s (1.61 to 1.86) | 57 / 111 / 302 |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 10x30 | fleet-20261126-231706-turns-10x30-fleet-off-r2 | 22 of 32 (51% to 82%) | 2 of 32 (2% to 20%) | 8 of 32 (13% to 42%) | 0 of 32 (0% to 11%) | 9 of 14 (39% to 84%) | 5 of 14 (16% to 61%) | 0 of 14 (0% to 22%) | 55 / 0 / 0 | 4,728 (4,681 to 4,732) / 4,734 | 33,304 (31,000 to 34,655) | 0.68 s (0.64 to 0.78) / 0.95 s (0.88 to 1.56) | 1.22 s (1.01 to 1.82) | 139 / 26 / 87 |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 10x30 | fleet-20261126-232545-turns-10x30-fleet-off-r3 | 21 of 32 (48% to 80%) | 2 of 32 (2% to 20%) | 9 of 32 (16% to 45%) | 0 of 32 (0% to 11%) | 7 of 14 (27% to 73%) | 6 of 14 (21% to 67%) | 1 of 14 (1% to 31%) | 55 / 0 / 0 | 4,723 (4,682 to 4,724) / 4,729 | 35,687 (31,790 to 49,262) | 0.80 s (0.70 to 0.84) / 1.02 s (0.94 to 1.27) | 1.32 s (1.16 to 1.66) | 135 / 41 / 111 |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 10x30 | fleet-20261127-014529-turns-10x30-fleet-off-r1 | 21 of 32 (48% to 80%) | 1 of 32 (1% to 16%) | 6 of 32 (9% to 35%) | 4 of 32 (5% to 28%) | 3 of 14 (8% to 48%) | 11 of 14 (52% to 92%) | 0 of 14 (0% to 22%) | 55 / 0 / 0 | 4,715 (4,673 to 4,715) / 4,730 | 35,854 (33,089 to 55,284) | 0.80 s (0.69 to 0.90) / 1.21 s (1.02 to 1.28) | 1.56 s (1.34 to 1.71) | 145 / 47 / 101 |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 10x30 | all runs | 64 of 96 (57% to 75%) | 5 of 96 (2% to 12%) | 23 of 96 (17% to 33%) | 4 of 96 (2% to 10%) | 19 of 42 (31% to 60%) | 22 of 42 (38% to 67%) | 1 of 42 (0% to 12%) | 165 / 0 / 0 | 4,716 (4,710 to 4,722) / 4,734 | 34,614 (33,171 to 35,854) | 0.77 s (0.70 to 0.80) / 1.16 s (1.01 to 1.23) | 1.42 s (1.26 to 1.62) | 419 / 114 / 299 |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 1x4 | fleet-20261127-003513-turns-1x4-fleet-on-r1 | 27 of 34 (63% to 90%) | 0 of 34 (0% to 10%) | 6 of 34 (8% to 34%) | 1 of 34 (1% to 15%) | 14 of 14 (78% to 100%) | 0 of 14 (0% to 22%) | 0 of 14 (0% to 22%) | 60 / 0 / 0 | 624 (556 to 647) / 753 | 25,216 (23,777 to 28,003) | 0.65 s (0.60 to 0.74) / 0.94 s (0.86 to 0.96) | 1.59 s (1.11 to 2.05) | 4 / 23 / 75 |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 1x4 | fleet-20261127-004158-turns-1x4-fleet-on-r2 | 28 of 34 (66% to 92%) | 0 of 34 (0% to 10%) | 2 of 34 (2% to 19%) | 4 of 34 (5% to 27%) | 14 of 14 (78% to 100%) | 0 of 14 (0% to 22%) | 0 of 14 (0% to 22%) | 60 / 0 / 0 | 705 (645 to 753) / 828 | 24,227 (22,778 to 26,443) | 0.80 s (0.67 to 0.86) / 1.03 s (0.95 to 1.19) | 1.45 s (1.18 to 2.00) | 3 / 23 / 72 |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 1x4 | fleet-20261127-004845-turns-1x4-fleet-on-r3 | 28 of 34 (66% to 92%) | 0 of 34 (0% to 10%) | 1 of 34 (1% to 15%) | 5 of 34 (6% to 30%) | 13 of 14 (69% to 99%) | 0 of 14 (0% to 22%) | 1 of 14 (1% to 31%) | 60 / 0 / 0 | 630 (602 to 653) / 778 | 28,119 (25,145 to 30,539) | 0.71 s (0.64 to 0.78) / 0.99 s (0.90 to 1.08) | 1.27 s (0.98 to 2.28) | 7 / 21 / 70 |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 1x4 | all runs | 83 of 102 (73% to 88%) | 0 of 102 (0% to 4%) | 9 of 102 (5% to 16%) | 10 of 102 (5% to 17%) | 41 of 42 (88% to 100%) | 0 of 42 (0% to 8%) | 1 of 42 (0% to 12%) | 180 / 0 / 0 | 644 (616 to 659) / 828 | 26,339 (24,186 to 27,871) | 0.72 s (0.67 to 0.78) / 1.00 s (0.94 to 1.04) | 1.47 s (1.21 to 1.73) | 14 / 67 / 217 |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 5x20 | fleet-20261126-233543-turns-5x20-fleet-on-r1 | 33 of 34 (85% to 99%) | 0 of 34 (0% to 10%) | 1 of 34 (1% to 15%) | 0 of 34 (0% to 10%) | 11 of 14 (52% to 92%) | 3 of 14 (8% to 48%) | 0 of 14 (0% to 22%) | 60 / 0 / 0 | 1,018 (994 to 1,030) / 1,080 | 29,195 (26,445 to 32,615) | 0.78 s (0.69 to 0.84) / 1.07 s (0.97 to 1.21) | 1.73 s (1.23 to 1.90) | 20 / 41 / 83 |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 5x20 | fleet-20261126-234525-turns-5x20-fleet-on-r2 | 34 of 34 (90% to 100%) | 0 of 34 (0% to 10%) | 0 of 34 (0% to 10%) | 0 of 34 (0% to 10%) | 12 of 14 (60% to 96%) | 2 of 14 (4% to 40%) | 0 of 14 (0% to 22%) | 60 / 0 / 0 | 1,012 (999 to 1,027) / 1,087 | 28,386 (26,869 to 31,751) | 0.67 s (0.63 to 0.76) / 1.11 s (0.96 to 1.21) | 1.21 s (1.04 to 1.83) | 18 / 37 / 87 |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 5x20 | fleet-20261126-235452-turns-5x20-fleet-on-r3 | 34 of 34 (90% to 100%) | 0 of 34 (0% to 10%) | 0 of 34 (0% to 10%) | 0 of 34 (0% to 10%) | 12 of 14 (60% to 96%) | 2 of 14 (4% to 40%) | 0 of 14 (0% to 22%) | 60 / 0 / 0 | 1,001 (993 to 1,023) / 1,098 | 29,443 (27,448 to 31,196) | 0.64 s (0.62 to 0.65) / 0.90 s (0.76 to 1.05) | 1.02 s (0.93 to 1.45) | 17 / 38 / 87 |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 5x20 | all runs | 101 of 102 (95% to 100%) | 0 of 102 (0% to 4%) | 1 of 102 (0% to 5%) | 0 of 102 (0% to 4%) | 35 of 42 (69% to 92%) | 7 of 42 (8% to 31%) | 0 of 42 (0% to 8%) | 180 / 0 / 0 | 1,011 (1,001 to 1,023) / 1,098 | 29,205 (27,858 to 30,713) | 0.67 s (0.65 to 0.71) / 1.06 s (0.96 to 1.13) | 1.32 s (1.13 to 1.71) | 55 / 116 / 257 |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 10x30 | fleet-20261127-011722-turns-10x30-fleet-on-r1 | 32 of 32 (89% to 100%) | 0 of 32 (0% to 11%) | 0 of 32 (0% to 11%) | 0 of 32 (0% to 11%) | 13 of 14 (69% to 99%) | 1 of 14 (1% to 31%) | 0 of 14 (0% to 22%) | 55 / 0 / 0 | 1,639 (1,634 to 1,670) / 1,697 | 30,515 (27,046 to 32,734) | 1.27 s (1.10 to 1.42) / 1.80 s (1.67 to 2.08) | 2.15 s (1.74 to 2.60) | 143 / 41 / 86 |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 10x30 | fleet-20261127-012643-turns-10x30-fleet-on-r2 | 32 of 32 (89% to 100%) | 0 of 32 (0% to 11%) | 0 of 32 (0% to 11%) | 0 of 32 (0% to 11%) | 12 of 14 (60% to 96%) | 1 of 14 (1% to 31%) | 1 of 14 (1% to 31%) | 55 / 0 / 0 | 1,657 (1,650 to 1,668) / 1,691 | 28,595 (27,041 to 30,762) | 1.26 s (1.13 to 1.53) / 1.75 s (1.66 to 1.86) | 2.05 s (1.96 to 2.25) | 143 / 44 / 83 |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 10x30 | fleet-20261127-013554-turns-10x30-fleet-on-r3 | 32 of 32 (89% to 100%) | 0 of 32 (0% to 11%) | 0 of 32 (0% to 11%) | 0 of 32 (0% to 11%) | 13 of 14 (69% to 99%) | 1 of 14 (1% to 31%) | 0 of 14 (0% to 22%) | 55 / 0 / 0 | 1,659 (1,651 to 1,663) / 1,693 | 30,808 (28,662 to 33,239) | 1.19 s (1.03 to 1.29) / 1.77 s (1.72 to 1.89) | 2.14 s (2.05 to 2.42) | 146 / 41 / 84 |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 10x30 | all runs | 96 of 96 (96% to 100%) | 0 of 96 (0% to 4%) | 0 of 96 (0% to 4%) | 0 of 96 (0% to 4%) | 38 of 42 (78% to 96%) | 3 of 42 (2% to 19%) | 1 of 42 (0% to 12%) | 165 / 0 / 0 | 1,656 (1,649 to 1,661) / 1,697 | 30,148 (28,310 to 31,334) | 1.22 s (1.15 to 1.30) / 1.78 s (1.73 to 1.86) | 2.12 s (2.04 to 2.22) | 432 / 126 / 253 |

Needs tokens: the "what each session needs" block of the turn's first brain step, counted by the brain vendor's own token counter as one message. Brain input: the vendor's count of the whole prompt, summed over the turn's own brain steps. First token and first send: from the typed line; a send's time is exact to 20 ms. Timings leave out rows that began or ended with the load over 20.

## By kind of turn (all runs of a size and arm together)

| Arm | Size | Kind | n | Outcomes |
|---|---|---|---|---|
| the fleet build, POINTE_FLEET=off, build `502cd35ea5` | 1x4 | clear_name | 66 | asked 1, nothing 4, right 61 |
| the fleet build, POINTE_FLEET=off, build `502cd35ea5` | 1x4 | clear_description | 36 | asked 20, nothing 8, right 8 |
| the fleet build, POINTE_FLEET=off, build `502cd35ea5` | 1x4 | ambiguous_description | 21 | asked 19, neither 1, sent 1 |
| the fleet build, POINTE_FLEET=off, build `502cd35ea5` | 1x4 | ambiguous_none | 21 | asked 20, sent 1 |
| the fleet build, POINTE_FLEET=off, build `502cd35ea5` | 1x4 | needs_me | 18 | answered 18 |
| the fleet build, POINTE_FLEET=off, build `502cd35ea5` | 1x4 | on_machine | 18 | answered 18 |
| the fleet build, POINTE_FLEET=off, build `502cd35ea5` | 1x4 | needs_me: expected sessions named in the reply | 18 | 31 of 36 names; 1 replies name a session not expected |
| the fleet build, POINTE_FLEET=off, build `502cd35ea5` | 1x4 | on_machine: expected sessions named in the reply | 18 | 60 of 72 names; 0 replies name a session not expected |
| the fleet build, POINTE_FLEET=off, build `502cd35ea5` | 5x20 | clear_name | 36 | asked 4, nothing 1, right 31 |
| the fleet build, POINTE_FLEET=off, build `502cd35ea5` | 5x20 | clear_machine_name | 30 | asked 3, nothing 3, right 23, wrong 1 |
| the fleet build, POINTE_FLEET=off, build `502cd35ea5` | 5x20 | clear_description | 36 | asked 30, nothing 1, right 4, wrong 1 |
| the fleet build, POINTE_FLEET=off, build `502cd35ea5` | 5x20 | ambiguous_name | 18 | asked 18 |
| the fleet build, POINTE_FLEET=off, build `502cd35ea5` | 5x20 | ambiguous_description | 12 | asked 10, sent 2 |
| the fleet build, POINTE_FLEET=off, build `502cd35ea5` | 5x20 | ambiguous_none | 12 | asked 8, neither 1, sent 3 |
| the fleet build, POINTE_FLEET=off, build `502cd35ea5` | 5x20 | needs_me | 18 | answered 18 |
| the fleet build, POINTE_FLEET=off, build `502cd35ea5` | 5x20 | on_machine | 18 | answered 18 |
| the fleet build, POINTE_FLEET=off, build `502cd35ea5` | 5x20 | ambiguous_name, this Mac has a session of the name | 6 | asked 6 |
| the fleet build, POINTE_FLEET=off, build `502cd35ea5` | 5x20 | ambiguous_name, only other machines have one | 12 | asked 12 |
| the fleet build, POINTE_FLEET=off, build `502cd35ea5` | 5x20 | needs_me: expected sessions named in the reply | 18 | 82 of 108 names; 0 replies name a session not expected |
| the fleet build, POINTE_FLEET=off, build `502cd35ea5` | 5x20 | on_machine: expected sessions named in the reply | 18 | 50 of 360 names; 0 replies name a session not expected |
| the fleet build, POINTE_FLEET=on, build `502cd35ea5` | 1x4 | clear_name | 66 | asked 1, nothing 4, right 61 |
| the fleet build, POINTE_FLEET=on, build `502cd35ea5` | 1x4 | clear_description | 36 | asked 19, nothing 7, right 9, wrong 1 |
| the fleet build, POINTE_FLEET=on, build `502cd35ea5` | 1x4 | ambiguous_description | 21 | asked 21 |
| the fleet build, POINTE_FLEET=on, build `502cd35ea5` | 1x4 | ambiguous_none | 21 | asked 19, neither 1, sent 1 |
| the fleet build, POINTE_FLEET=on, build `502cd35ea5` | 1x4 | needs_me | 18 | answered 18 |
| the fleet build, POINTE_FLEET=on, build `502cd35ea5` | 1x4 | on_machine | 18 | answered 18 |
| the fleet build, POINTE_FLEET=on, build `502cd35ea5` | 1x4 | needs_me: expected sessions named in the reply | 18 | 31 of 36 names; 1 replies name a session not expected |
| the fleet build, POINTE_FLEET=on, build `502cd35ea5` | 1x4 | on_machine: expected sessions named in the reply | 18 | 51 of 72 names; 0 replies name a session not expected |
| the fleet build, POINTE_FLEET=on, build `502cd35ea5` | 5x20 | clear_name | 36 | right 36 |
| the fleet build, POINTE_FLEET=on, build `502cd35ea5` | 5x20 | clear_machine_name | 30 | asked 6, not_run 2, right 8, wrong 14 |
| the fleet build, POINTE_FLEET=on, build `502cd35ea5` | 5x20 | clear_description | 36 | asked 30, nothing 2, right 3, wrong 1 |
| the fleet build, POINTE_FLEET=on, build `502cd35ea5` | 5x20 | ambiguous_name | 18 | asked 8, neither 1, sent 9 |
| the fleet build, POINTE_FLEET=on, build `502cd35ea5` | 5x20 | ambiguous_description | 12 | asked 8, neither 1, sent 3 |
| the fleet build, POINTE_FLEET=on, build `502cd35ea5` | 5x20 | ambiguous_none | 12 | asked 4, neither 1, sent 7 |
| the fleet build, POINTE_FLEET=on, build `502cd35ea5` | 5x20 | needs_me | 18 | answered 18 |
| the fleet build, POINTE_FLEET=on, build `502cd35ea5` | 5x20 | on_machine | 18 | answered 18 |
| the fleet build, POINTE_FLEET=on, build `502cd35ea5` | 5x20 | ambiguous_name, this Mac has a session of the name | 6 | asked 2, sent 4 |
| the fleet build, POINTE_FLEET=on, build `502cd35ea5` | 5x20 | ambiguous_name, only other machines have one | 12 | asked 6, neither 1, sent 5 |
| the fleet build, POINTE_FLEET=on, build `502cd35ea5` | 5x20 | needs_me: expected sessions named in the reply | 18 | 82 of 108 names; 2 replies name a session not expected |
| the fleet build, POINTE_FLEET=on, build `502cd35ea5` | 5x20 | on_machine: expected sessions named in the reply | 18 | 31 of 360 names; 1 replies name a session not expected |
| the fleet build, POINTE_FLEET=off, build `05857b19f6` | 1x4 | clear_name | 66 | nothing 5, right 61 |
| the fleet build, POINTE_FLEET=off, build `05857b19f6` | 1x4 | clear_description | 36 | asked 16, nothing 9, right 10, wrong 1 |
| the fleet build, POINTE_FLEET=off, build `05857b19f6` | 1x4 | ambiguous_description | 21 | asked 21 |
| the fleet build, POINTE_FLEET=off, build `05857b19f6` | 1x4 | ambiguous_none | 21 | asked 18, neither 2, sent 1 |
| the fleet build, POINTE_FLEET=off, build `05857b19f6` | 1x4 | needs_me | 18 | answered 18 |
| the fleet build, POINTE_FLEET=off, build `05857b19f6` | 1x4 | on_machine | 18 | answered 18 |
| the fleet build, POINTE_FLEET=off, build `05857b19f6` | 1x4 | needs_me: expected sessions named in the reply | 18 | 32 of 36 names; 0 replies name a session not expected |
| the fleet build, POINTE_FLEET=off, build `05857b19f6` | 1x4 | on_machine: expected sessions named in the reply | 18 | 57 of 72 names; 0 replies name a session not expected |
| the fleet build, POINTE_FLEET=off, build `05857b19f6` | 5x20 | clear_name | 36 | asked 2, right 34 |
| the fleet build, POINTE_FLEET=off, build `05857b19f6` | 5x20 | clear_machine_name | 30 | right 30 |
| the fleet build, POINTE_FLEET=off, build `05857b19f6` | 5x20 | clear_description | 36 | asked 28, nothing 3, right 4, wrong 1 |
| the fleet build, POINTE_FLEET=off, build `05857b19f6` | 5x20 | ambiguous_name | 18 | asked 16, neither 1, sent 1 |
| the fleet build, POINTE_FLEET=off, build `05857b19f6` | 5x20 | ambiguous_description | 12 | asked 11, sent 1 |
| the fleet build, POINTE_FLEET=off, build `05857b19f6` | 5x20 | ambiguous_none | 12 | asked 4, neither 1, sent 7 |
| the fleet build, POINTE_FLEET=off, build `05857b19f6` | 5x20 | needs_me | 18 | answered 18 |
| the fleet build, POINTE_FLEET=off, build `05857b19f6` | 5x20 | on_machine | 18 | answered 18 |
| the fleet build, POINTE_FLEET=off, build `05857b19f6` | 5x20 | ambiguous_name, this Mac has a session of the name | 6 | asked 5, sent 1 |
| the fleet build, POINTE_FLEET=off, build `05857b19f6` | 5x20 | ambiguous_name, only other machines have one | 12 | asked 11, neither 1 |
| the fleet build, POINTE_FLEET=off, build `05857b19f6` | 5x20 | needs_me: expected sessions named in the reply | 18 | 83 of 108 names; 0 replies name a session not expected |
| the fleet build, POINTE_FLEET=off, build `05857b19f6` | 5x20 | on_machine: expected sessions named in the reply | 18 | 49 of 360 names; 0 replies name a session not expected |
| the fleet build, POINTE_FLEET=on, build `05857b19f6` | 1x4 | clear_name | 66 | asked 3, nothing 3, right 60 |
| the fleet build, POINTE_FLEET=on, build `05857b19f6` | 1x4 | clear_description | 36 | asked 19, nothing 6, right 10, wrong 1 |
| the fleet build, POINTE_FLEET=on, build `05857b19f6` | 1x4 | ambiguous_description | 21 | asked 18, neither 3 |
| the fleet build, POINTE_FLEET=on, build `05857b19f6` | 1x4 | ambiguous_none | 21 | asked 20, neither 1 |
| the fleet build, POINTE_FLEET=on, build `05857b19f6` | 1x4 | needs_me | 18 | answered 18 |
| the fleet build, POINTE_FLEET=on, build `05857b19f6` | 1x4 | on_machine | 18 | answered 18 |
| the fleet build, POINTE_FLEET=on, build `05857b19f6` | 1x4 | needs_me: expected sessions named in the reply | 18 | 31 of 36 names; 1 replies name a session not expected |
| the fleet build, POINTE_FLEET=on, build `05857b19f6` | 1x4 | on_machine: expected sessions named in the reply | 18 | 55 of 72 names; 0 replies name a session not expected |
| the fleet build, POINTE_FLEET=on, build `05857b19f6` | 5x20 | clear_name | 36 | right 36 |
| the fleet build, POINTE_FLEET=on, build `05857b19f6` | 5x20 | clear_machine_name | 30 | crashed 1, right 29 |
| the fleet build, POINTE_FLEET=on, build `05857b19f6` | 5x20 | clear_description | 36 | crashed 1, right 35 |
| the fleet build, POINTE_FLEET=on, build `05857b19f6` | 5x20 | ambiguous_name | 18 | asked 11, crashed 1, sent 6 |
| the fleet build, POINTE_FLEET=on, build `05857b19f6` | 5x20 | ambiguous_description | 12 | asked 12 |
| the fleet build, POINTE_FLEET=on, build `05857b19f6` | 5x20 | ambiguous_none | 12 | asked 12 |
| the fleet build, POINTE_FLEET=on, build `05857b19f6` | 5x20 | needs_me | 18 | answered 18 |
| the fleet build, POINTE_FLEET=on, build `05857b19f6` | 5x20 | on_machine | 18 | answered 18 |
| the fleet build, POINTE_FLEET=on, build `05857b19f6` | 5x20 | ambiguous_name, this Mac has a session of the name | 6 | sent 6 |
| the fleet build, POINTE_FLEET=on, build `05857b19f6` | 5x20 | ambiguous_name, only other machines have one | 12 | asked 11, crashed 1 |
| the fleet build, POINTE_FLEET=on, build `05857b19f6` | 5x20 | needs_me: expected sessions named in the reply | 18 | 81 of 108 names; 5 replies name a session not expected |
| the fleet build, POINTE_FLEET=on, build `05857b19f6` | 5x20 | on_machine: expected sessions named in the reply | 18 | 35 of 360 names; 0 replies name a session not expected |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 1x4 | clear_name | 66 | nothing 5, right 61 |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 1x4 | clear_description | 36 | asked 16, nothing 9, right 10, wrong 1 |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 1x4 | ambiguous_description | 21 | asked 21 |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 1x4 | ambiguous_none | 21 | asked 18, neither 2, sent 1 |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 1x4 | needs_me | 18 | answered 18 |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 1x4 | on_machine | 18 | answered 18 |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 1x4 | needs_me: expected sessions named in the reply | 18 | 32 of 36 names; 0 replies name a session not expected |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 1x4 | on_machine: expected sessions named in the reply | 18 | 57 of 72 names; 0 replies name a session not expected |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 5x20 | clear_name | 36 | asked 2, right 34 |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 5x20 | clear_machine_name | 30 | right 30 |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 5x20 | clear_description | 36 | asked 28, nothing 3, right 4, wrong 1 |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 5x20 | ambiguous_name | 18 | asked 16, neither 1, sent 1 |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 5x20 | ambiguous_description | 12 | asked 11, sent 1 |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 5x20 | ambiguous_none | 12 | asked 4, neither 1, sent 7 |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 5x20 | needs_me | 18 | answered 18 |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 5x20 | on_machine | 18 | answered 18 |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 5x20 | ambiguous_name, this Mac has a session of the name | 6 | asked 5, sent 1 |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 5x20 | ambiguous_name, only other machines have one | 12 | asked 11, neither 1 |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 5x20 | needs_me: expected sessions named in the reply | 18 | 83 of 108 names; 0 replies name a session not expected |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 5x20 | on_machine: expected sessions named in the reply | 18 | 49 of 360 names; 0 replies name a session not expected |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 10x30 | clear_name | 11 | right 10, wrong 1 |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 10x30 | clear_machine_name | 10 | right 10 |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 10x30 | clear_description | 11 | asked 7, nothing 3, wrong 1 |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 10x30 | ambiguous_name | 6 | sent 6 |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 10x30 | ambiguous_description | 4 | asked 3, neither 1 |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 10x30 | ambiguous_none | 4 | sent 4 |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 10x30 | needs_me | 6 | answered 6 |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 10x30 | on_machine | 3 | answered 3 |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 10x30 | ambiguous_name, this Mac has a session of the name | 1 | sent 1 |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 10x30 | ambiguous_name, only other machines have one | 5 | sent 5 |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 10x30 | needs_me: expected sessions named in the reply | 6 | 24 of 90 names; 0 replies name a session not expected |
| the fleet build, POINTE_FLEET=off, build `0b98c14e3a` (rows of build `05857b19f6`, carried) | 10x30 | on_machine: expected sessions named in the reply | 3 | 3 of 90 names; 0 replies name a session not expected |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 1x4 | clear_name | 66 | asked 1, nothing 6, right 59 |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 1x4 | clear_description | 36 | asked 21, nothing 4, right 11 |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 1x4 | ambiguous_description | 21 | asked 18, neither 2, sent 1 |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 1x4 | ambiguous_none | 21 | asked 12, sent 9 |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 1x4 | needs_me | 18 | answered 18 |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 1x4 | on_machine | 18 | answered 18 |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 1x4 | needs_me: expected sessions named in the reply | 18 | 33 of 36 names; 0 replies name a session not expected |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 1x4 | on_machine: expected sessions named in the reply | 18 | 63 of 72 names; 0 replies name a session not expected |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 5x20 | clear_name | 36 | right 35, wrong 1 |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 5x20 | clear_machine_name | 30 | right 30 |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 5x20 | clear_description | 36 | right 36 |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 5x20 | ambiguous_name | 18 | asked 12, sent 6 |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 5x20 | ambiguous_description | 12 | asked 11, sent 1 |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 5x20 | ambiguous_none | 12 | asked 12 |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 5x20 | needs_me | 18 | answered 18 |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 5x20 | on_machine | 18 | answered 18 |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 5x20 | ambiguous_name, this Mac has a session of the name | 6 | sent 6 |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 5x20 | ambiguous_name, only other machines have one | 12 | asked 12 |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 5x20 | needs_me: expected sessions named in the reply | 18 | 94 of 108 names; 4 replies name a session not expected |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 5x20 | on_machine: expected sessions named in the reply | 18 | 48 of 360 names; 0 replies name a session not expected |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 10x30 | clear_name | 36 | right 35, wrong 1 |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 10x30 | clear_machine_name | 30 | right 30 |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 10x30 | clear_description | 33 | right 33 |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 10x30 | ambiguous_name | 18 | asked 15, sent 3 |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 10x30 | ambiguous_description | 12 | asked 11, neither 1 |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 10x30 | ambiguous_none | 12 | asked 12 |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 10x30 | needs_me | 18 | answered 18 |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 10x30 | on_machine | 9 | answered 9 |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 10x30 | ambiguous_name, this Mac has a session of the name | 3 | sent 3 |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 10x30 | ambiguous_name, only other machines have one | 15 | asked 15 |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 10x30 | needs_me: expected sessions named in the reply | 18 | 78 of 270 names; 4 replies name a session not expected |
| the fleet build, POINTE_FLEET=on, build `0b98c14e3a` | 10x30 | on_machine: expected sessions named in the reply | 9 | 18 of 270 names; 0 replies name a session not expected |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 1x4 | clear_name | 66 | asked 1, crashed 1, nothing 4, right 60 |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 1x4 | clear_description | 36 | asked 9, nothing 17, right 10 |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 1x4 | ambiguous_description | 21 | asked 19, neither 1, sent 1 |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 1x4 | ambiguous_none | 21 | asked 19, neither 1, sent 1 |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 1x4 | needs_me | 18 | answered 18 |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 1x4 | on_machine | 18 | answered 18 |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 1x4 | needs_me: expected sessions named in the reply | 18 | 31 of 36 names; 0 replies name a session not expected |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 1x4 | on_machine: expected sessions named in the reply | 18 | 58 of 72 names; 0 replies name a session not expected |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 5x20 | clear_name | 36 | nothing 1, right 35 |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 5x20 | clear_machine_name | 30 | right 30 |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 5x20 | clear_description | 36 | asked 30, nothing 1, right 4, wrong 1 |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 5x20 | ambiguous_name | 18 | asked 18 |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 5x20 | ambiguous_description | 12 | asked 12 |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 5x20 | ambiguous_none | 12 | asked 2, sent 10 |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 5x20 | needs_me | 18 | answered 18 |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 5x20 | on_machine | 18 | answered 18 |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 5x20 | ambiguous_name, this Mac has a session of the name | 6 | asked 6 |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 5x20 | ambiguous_name, only other machines have one | 12 | asked 12 |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 5x20 | needs_me: expected sessions named in the reply | 18 | 82 of 108 names; 0 replies name a session not expected |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 5x20 | on_machine: expected sessions named in the reply | 18 | 36 of 360 names; 0 replies name a session not expected |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 10x30 | clear_name | 33 | right 33 |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 10x30 | clear_machine_name | 30 | right 30 |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 10x30 | clear_description | 33 | asked 23, nothing 4, right 1, wrong 5 |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 10x30 | ambiguous_name | 18 | asked 8, sent 10 |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 10x30 | ambiguous_description | 12 | asked 9, neither 1, sent 2 |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 10x30 | ambiguous_none | 12 | asked 2, sent 10 |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 10x30 | needs_me | 18 | answered 18 |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 10x30 | on_machine | 9 | answered 9 |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 10x30 | ambiguous_name, this Mac has a session of the name | 3 | asked 2, sent 1 |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 10x30 | ambiguous_name, only other machines have one | 15 | asked 6, sent 9 |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 10x30 | needs_me: expected sessions named in the reply | 18 | 64 of 270 names; 0 replies name a session not expected |
| the fleet build, POINTE_FLEET=off, build `271e64c1d0` | 10x30 | on_machine: expected sessions named in the reply | 9 | 9 of 270 names; 0 replies name a session not expected |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 1x4 | clear_name | 66 | asked 6, nothing 7, right 53 |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 1x4 | clear_description | 36 | asked 3, nothing 3, right 30 |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 1x4 | ambiguous_description | 21 | asked 21 |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 1x4 | ambiguous_none | 21 | asked 20, neither 1 |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 1x4 | needs_me | 18 | answered 18 |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 1x4 | on_machine | 18 | answered 18 |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 1x4 | needs_me: expected sessions named in the reply | 18 | 31 of 36 names; 0 replies name a session not expected |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 1x4 | on_machine: expected sessions named in the reply | 18 | 50 of 72 names; 0 replies name a session not expected |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 5x20 | clear_name | 36 | right 36 |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 5x20 | clear_machine_name | 30 | asked 1, right 29 |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 5x20 | clear_description | 36 | right 36 |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 5x20 | ambiguous_name | 18 | asked 12, sent 6 |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 5x20 | ambiguous_description | 12 | asked 11, sent 1 |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 5x20 | ambiguous_none | 12 | asked 12 |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 5x20 | needs_me | 18 | answered 18 |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 5x20 | on_machine | 18 | answered 18 |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 5x20 | ambiguous_name, this Mac has a session of the name | 6 | sent 6 |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 5x20 | ambiguous_name, only other machines have one | 12 | asked 12 |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 5x20 | needs_me: expected sessions named in the reply | 18 | 90 of 108 names; 4 replies name a session not expected |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 5x20 | on_machine: expected sessions named in the reply | 18 | 47 of 360 names; 0 replies name a session not expected |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 10x30 | clear_name | 33 | right 33 |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 10x30 | clear_machine_name | 30 | right 30 |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 10x30 | clear_description | 33 | right 33 |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 10x30 | ambiguous_name | 18 | asked 15, sent 3 |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 10x30 | ambiguous_description | 12 | asked 11, neither 1 |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 10x30 | ambiguous_none | 12 | asked 12 |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 10x30 | needs_me | 18 | answered 18 |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 10x30 | on_machine | 9 | answered 9 |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 10x30 | ambiguous_name, this Mac has a session of the name | 3 | sent 3 |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 10x30 | ambiguous_name, only other machines have one | 15 | asked 15 |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 10x30 | needs_me: expected sessions named in the reply | 18 | 79 of 270 names; 5 replies name a session not expected |
| the fleet build, POINTE_FLEET=on, build `271e64c1d0` | 10x30 | on_machine: expected sessions named in the reply | 9 | 16 of 270 names; 0 replies name a session not expected |

## Turns about a session the voice renamed when it joined, or whose name is one letter from another's

The voice's own naming rules refused some dataset names at join and gave those sessions a name of its own ("session 1a2b3c"; each run's manifest lists them under `renamed_at_join`). A turn that expects, fits or lists such a session has a label the fleet no longer matches. A turn that says a name one letter from another session's ("fennel", "funnel") is marked from the first runs that record it. Those turns are in no rate above, and are here.

| Arm | Size | Kind | Outcomes |
|---|---|---|---|
| fleet-off, build `0b98c14e3a` | 10x30 | clear_description, renamed session | asked 1 |
| fleet-off, build `0b98c14e3a` | 10x30 | clear_name, a name one letter from another's | right 1 |
| fleet-off, build `0b98c14e3a` | 10x30 | on_machine, renamed session | answered 3 |
| fleet-off, build `271e64c1d0` | 10x30 | clear_description, renamed session | asked 3 |
| fleet-off, build `271e64c1d0` | 10x30 | clear_name, a name one letter from another's | right 3 |
| fleet-off, build `271e64c1d0` | 10x30 | on_machine, renamed session | answered 9 |
| fleet-on, build `0b98c14e3a` | 10x30 | clear_description, renamed session | asked 2, right 1 |
| fleet-on, build `0b98c14e3a` | 10x30 | on_machine, renamed session | answered 9 |
| fleet-on, build `271e64c1d0` | 10x30 | clear_description, renamed session | asked 3 |
| fleet-on, build `271e64c1d0` | 10x30 | clear_name, a name one letter from another's | right 3 |
| fleet-on, build `271e64c1d0` | 10x30 | on_machine, renamed session | answered 9 |

## Requests taken for a correction ("Drop my last request" sent)

The frozen turns have no correction in them: each row here is a new request the voice took for a correction of an earlier send, and told that earlier session to drop its work. Counted as a wrong session above. "Right after the send": the session told to drop got the turn just before.

| Arm | Size | Run | Turn | Order | Right after the send |
|---|---|---|---|---|---|
| fleet-on, build `0b98c14e3a` | 5x20 | fleet-20261126-221814-turns-5x20-fleet-on-r2 | clear_name-04 | 42 | no |
| fleet-on, build `0b98c14e3a` | 10x30 | fleet-20261126-224601-turns-10x30-fleet-on-r2 | clear_name-04 | 42 | no |
| fleet-off, build `0b98c14e3a` | 10x30 | fleet-20261126-230636-turns-10x30-fleet-off-r1 | clear_name-11 | 52 | no |

By build and arm, rows with such a send, of the turns driven: fleet-off `502cd35ea5` 0 of 360, fleet-on `502cd35ea5` 0 of 358, fleet-off `05857b19f6` 0 of 360, fleet-on `05857b19f6` 0 of 357, fleet-off `0b98c14e3a` 1 of 60, fleet-on `0b98c14e3a` 2 of 540, fleet-off `271e64c1d0` 0 of 539, fleet-on `271e64c1d0` 0 of 540.

## Probe: "What did I send to <session>?" after the 60 turns

Not part of the frozen dataset and in no bar (`bench/fleet/probes.json`, its hash in each row). Asked about the session that got the run's first delivery. Recalled: the reply has a word of five letters or more from that request, and nothing was sent.

| Arm | Size | Run | Recalled | The reply |
|---|---|---|---|---|
| fleet-off, build `0b98c14e3a` | 10x30 | fleet-20261126-230636-turns-10x30-fleet-off-r1 | no | I didn't send anything to nozzle. Nothing in this call went there. |
| fleet-off, build `271e64c1d0` | 10x30 | fleet-20261126-231706-turns-10x30-fleet-off-r2 | yes | You asked pavilion to list the open TODO comments in the wishlist queue file. It was read-only, and I have no report back from it yet. |
| fleet-off, build `271e64c1d0` | 10x30 | fleet-20261126-232545-turns-10x30-fleet-off-r3 | no | Nothing to ivy in what I can see. Which session did you mean? |
| fleet-on, build `271e64c1d0` | 5x20 | fleet-20261126-233543-turns-5x20-fleet-on-r1 | yes | You asked aspen to add a docstring to the main function. There's no report back from it yet. |
| fleet-on, build `271e64c1d0` | 5x20 | fleet-20261126-234525-turns-5x20-fleet-on-r2 | yes | You asked ultra to list the open TODO comments in the dispatch export file. It hasn't reported back yet. |
| fleet-on, build `271e64c1d0` | 5x20 | fleet-20261126-235452-turns-5x20-fleet-on-r3 | yes | You asked rye to run the tests. It's no longer listed as pending, and I haven't seen a report from it. |
| fleet-off, build `271e64c1d0` | 5x20 | fleet-20261127-000359-turns-5x20-fleet-off-r1 | yes | You asked aspen to add a docstring to the main function. There's no report back yet, so it's not known to be done. |
| fleet-off, build `271e64c1d0` | 5x20 | fleet-20261127-001447-turns-5x20-fleet-off-r2 | yes | You asked ultra to list the open TODO comments in the dispatch export file. There's no report back yet. |
| fleet-off, build `271e64c1d0` | 5x20 | fleet-20261127-002438-turns-5x20-fleet-off-r3 | no | I didn't send anything to willow. Nothing I sent went to willow. |
| fleet-on, build `271e64c1d0` | 1x4 | fleet-20261127-003513-turns-1x4-fleet-on-r1 | no | Five things to finch, none reported back yet. |
| fleet-on, build `271e64c1d0` | 1x4 | fleet-20261127-004158-turns-1x4-fleet-on-r2 | no | Nine requests, none reported back. The latest are run the tests, bump the patch version, and name the longest function. |
| fleet-on, build `271e64c1d0` | 1x4 | fleet-20261127-004845-turns-1x4-fleet-on-r3 | no | You've sent beacon nine requests. You've sent beacon nine requests, none reported back yet. |
| fleet-off, build `271e64c1d0` | 1x4 | fleet-20261127-005539-turns-1x4-fleet-off-r1 | yes | Five things to finch, none reported back yet: add a docstring to main, check the README matches the code, comment the retry loop, run the linter and fix it. |
| fleet-off, build `271e64c1d0` | 1x4 | fleet-20261127-010246-turns-1x4-fleet-off-r2 | no | Seven asks went to beacon, none reported back yet. |
| fleet-off, build `271e64c1d0` | 1x4 | fleet-20261127-011007-turns-1x4-fleet-off-r3 | yes | You sent beacon seven requests: run the tests, bump the patch version, list the open TODO comments, rename the helper, look for a flaky test, sort the imports. |
| fleet-on, build `271e64c1d0` | 10x30 | fleet-20261127-011722-turns-10x30-fleet-on-r1 | no | I sent it earlier, and no report has come back yet. |
| fleet-on, build `271e64c1d0` | 10x30 | fleet-20261127-012643-turns-10x30-fleet-on-r2 | yes | You asked pavilion to list the open TODO comments in the wishlist queue file. I haven't heard back from it yet. |
| fleet-on, build `271e64c1d0` | 10x30 | fleet-20261127-013554-turns-10x30-fleet-on-r3 | yes | You asked ivy to run the tests. I haven't seen a report back from it. |
| fleet-off, build `271e64c1d0` | 10x30 | fleet-20261127-014529-turns-10x30-fleet-off-r1 | no | Nothing that I can see. I have no record of sending anything to nozzle. |

## 30 sessions end their turn within a minute

| Arm | Size | Run | Finished | Spoken lines | Held items | Named in speech | Named in the held list | Lost | Report lines (daemon's count) | Not read (quiet) | Reader calls | Error |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| fleet-on | 5x20 | fleet-20261127-015503-burst-5x20-fleet-on | 30 | 5 | 1 | 4 | 1 | 25 | 4 | 0 | 35 |  |
| fleet-off | 5x20 | fleet-20261127-015709-burst-5x20-fleet-off | 30 | 5 | 0 | 4 | 0 | 26 | 0 | 0 | 35 |  |
| fleet-on | 10x30 | fleet-20261127-015918-burst-10x30-fleet-on | 30 | 6 | 1 | 4 | 1 | 25 | 4 | 0 | 35 |  |
| fleet-off | 10x30 | fleet-20261127-020207-burst-10x30-fleet-off | 30 | 5 | 0 | 5 | 0 | 25 | 0 | 0 | 35 |  |
| fleet-on | 5x20 | fleet-20261127-031550-burst-5x20-fleet-on | 30 | 5 | 23 | 7 | 23 | 0 | 4 | 0 | 62 |  |
| fleet-on | 5x20 | fleet-20261127-031758-burst-5x20-fleet-on | 30 | 6 | 23 | 8 | 22 | 0 | 4 | 0 | 64 |  |
| fleet-on | 5x20 | fleet-20261127-031957-burst-5x20-fleet-on | 30 | 4 | 23 | 8 | 22 | 0 | 4 | 0 | 63 |  |
| fleet-on | 10x30 | fleet-20261127-032202-burst-10x30-fleet-on | 30 | 4 | 23 | 3 | 23 | 4 | 4 | 3 | 55 |  |
| fleet-on | 10x30 | fleet-20261127-032444-burst-10x30-fleet-on | 30 | 4 | 24 | 3 | 24 | 3 (written 4) | 4 | 2 | 59 |  |
| fleet-on | 10x30 | fleet-20261127-032726-burst-10x30-fleet-on | 30 | 4 | 25 | 4 | 25 | 1 (written 2) | 4 | 1 | 60 |  |

Lost: a session that ended its turn and is named neither in a spoken line nor in the held list when the fleet went quiet, by its dataset name or the name the voice gave it at join (a run written before that is counted again, with the count it wrote beside it). Spoken lines: every line said in the window, approvals and their reminders included; the bar counts these. Report lines: the daemon's own count of lines about finished turns. Not read (quiet): finished turns of quiet sessions the daemon did not read.

## Reader calls

| Arm | Size | Scenario | Sessions active | Turns ended | Reader calls in the window | An hour | Error |
|---|---|---|---|---|---|---|---|
| fleet-on | 1x4 | all_active | 4 of 4 | 8 | 16 | 480 |  |
| fleet-on | 1x4 | quiet_80 | 1 of 4 | 2 | 4 | 120 |  |
| fleet-off | 1x4 | all_active | 4 of 4 | 8 | 16 | 480 |  |
| fleet-off | 1x4 | quiet_80 | 1 of 4 | 2 | 4 | 120 |  |
| fleet-on | 5x20 | all_active | 100 of 100 | 200 | 320 | 9,600 |  |
| fleet-on | 5x20 | quiet_80 | 20 of 100 | 40 | 64 | 1,920 |  |
| fleet-off | 5x20 | all_active | 100 of 100 | 200 | 320 | 9,600 |  |
| fleet-off | 5x20 | quiet_80 | 20 of 100 | 40 | 64 | 1,920 |  |
| fleet-on | 10x30 | all_active | 300 of 300 | 600 | 714 | 21,420 |  |
| fleet-on | 10x30 | quiet_80 | 60 of 300 | 120 | 150 | 4,500 |  |
| fleet-off | 10x30 | all_active | 300 of 300 | 600 | 930 | 27,900 |  |
| fleet-off | 10x30 | quiet_80 | 60 of 300 | 120 | 186 | 5,580 |  |
| fleet-on | 1x4 | all_active | 4 of 4 | 8 | 16 | 480 |  |
| fleet-on | 1x4 | quiet_80 | 1 of 4 | 2 | 4 | 120 |  |
| fleet-off | 1x4 | all_active | 4 of 4 | 8 | 16 | 480 |  |
| fleet-off | 1x4 | quiet_80 | 1 of 4 | 2 | 4 | 120 |  |
| fleet-on | 5x20 | all_active | 100 of 100 | 200 | 320 | 9,600 |  |
| fleet-on | 5x20 | quiet_80 | 20 of 100 | 40 | 64 | 1,920 |  |
| fleet-off | 5x20 | all_active | 100 of 100 | 200 | 320 | 9,600 |  |
| fleet-off | 5x20 | quiet_80 | 20 of 100 | 40 | 64 | 1,920 |  |
| fleet-on | 10x30 | all_active | 300 of 300 | 600 | 714 | 21,420 |  |
| fleet-on | 10x30 | quiet_80 | 60 of 300 | 120 | 144 | 4,320 |  |
| fleet-off | 10x30 | all_active | 300 of 300 | 600 | 930 | 27,900 |  |
| fleet-off | 10x30 | quiet_80 | 60 of 300 | 120 | 186 | 5,580 |  |

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
| fleet-20261126-193413-turns-5x20-fleet-off-r1 | turns | 167 | 2.6304 |
| fleet-20261126-194422-turns-5x20-fleet-off-r2 | turns | 145 | 2.5677 |
| fleet-20261126-195354-turns-5x20-fleet-off-r3 | turns | 129 | 2.2287 |
| fleet-20261126-200427-turns-5x20-fleet-on-r1 | turns | 140 | 1.1398 |
| fleet-20261126-201349-turns-5x20-fleet-on-r2 | turns | 156 | 1.4364 |
| fleet-20261126-202417-turns-5x20-fleet-on-r3 | turns | 142 | 1.2530 |
| fleet-20261126-203352-turns-5x20-fleet-off-r1 | turns | 162 | 2.7281 |
| fleet-20261126-204441-turns-5x20-fleet-off-r2 | turns | 152 | 2.6004 |
| fleet-20261126-205432-turns-5x20-fleet-off-r3 | turns | 152 | 2.6729 |
| fleet-20261126-210408-turns-1x4-fleet-on-r1 | turns | 97 | 0.3728 |
| fleet-20261126-211055-turns-1x4-fleet-on-r2 | turns | 120 | 0.4652 |
| fleet-20261126-211802-turns-1x4-fleet-on-r3 | turns | 103 | 0.4334 |
| fleet-20261126-212506-turns-1x4-fleet-off-r1 | turns | 101 | 0.3902 |
| fleet-20261126-213205-turns-1x4-fleet-off-r2 | turns | 109 | 0.4641 |
| fleet-20261126-213903-turns-1x4-fleet-off-r3 | turns | 123 | 0.4674 |
| fleet-20261126-214612-turns-1x4-fleet-on-r1 | turns | 127 | 0.5687 |
| fleet-20261126-215348-turns-1x4-fleet-on-r2 | turns | 111 | 0.4794 |
| fleet-20261126-220103-turns-1x4-fleet-on-r3 | turns | 111 | 0.4583 |
| fleet-20261126-220833-turns-5x20-fleet-on-r1 | turns | 142 | 0.8268 |
| fleet-20261126-221814-turns-5x20-fleet-on-r2 | turns | 150 | 0.8571 |
| fleet-20261126-222740-turns-5x20-fleet-on-r3 | turns | 142 | 0.8453 |
| fleet-20261126-223717-turns-10x30-fleet-on-r1 | turns | 445 | 2.1012 |
| fleet-20261126-224601-turns-10x30-fleet-on-r2 | turns | 266 | 1.5317 |
| fleet-20261126-225537-turns-10x30-fleet-on-r3 | turns | 273 | 1.6036 |
| fleet-20261126-230636-turns-10x30-fleet-off-r1 | turns | 464 | 4.3115 |
| fleet-20261126-231706-turns-10x30-fleet-off-r2 | turns | 252 | 3.0157 |
| fleet-20261126-232545-turns-10x30-fleet-off-r3 | turns | 287 | 3.6417 |
| fleet-20261126-233543-turns-5x20-fleet-on-r1 | turns | 144 | 0.8007 |
| fleet-20261126-234525-turns-5x20-fleet-on-r2 | turns | 142 | 0.7731 |
| fleet-20261126-235452-turns-5x20-fleet-on-r3 | turns | 142 | 0.7973 |
| fleet-20261127-000359-turns-5x20-fleet-off-r1 | turns | 172 | 2.9812 |
| fleet-20261127-001447-turns-5x20-fleet-off-r2 | turns | 136 | 2.4228 |
| fleet-20261127-002438-turns-5x20-fleet-off-r3 | turns | 162 | 2.8887 |
| fleet-20261127-003513-turns-1x4-fleet-on-r1 | turns | 102 | 0.3753 |
| fleet-20261127-004158-turns-1x4-fleet-on-r2 | turns | 98 | 0.4286 |
| fleet-20261127-004845-turns-1x4-fleet-on-r3 | turns | 98 | 0.4222 |
| fleet-20261127-005539-turns-1x4-fleet-off-r1 | turns | 104 | 0.4386 |
| fleet-20261127-010246-turns-1x4-fleet-off-r2 | turns | 116 | 0.5926 |
| fleet-20261127-011007-turns-1x4-fleet-off-r3 | turns | 109 | 0.4604 |
| fleet-20261127-011722-turns-10x30-fleet-on-r1 | turns | 270 | 1.6189 |
| fleet-20261127-012643-turns-10x30-fleet-on-r2 | turns | 270 | 1.5307 |
| fleet-20261127-013554-turns-10x30-fleet-on-r3 | turns | 271 | 1.6011 |
| fleet-20261127-014529-turns-10x30-fleet-off-r1 | turns | 293 | 3.6779 |
| fleet-20261127-015503-burst-5x20-fleet-on | burst | 41 | 0.2472 |
| fleet-20261127-015709-burst-5x20-fleet-off | burst | 41 | 0.3696 |
| fleet-20261127-015918-burst-10x30-fleet-on | burst | 186 | 0.9222 |
| fleet-20261127-020207-burst-10x30-fleet-off | burst | 183 | 1.0273 |
| fleet-20261127-031550-burst-5x20-fleet-on | burst | 67 | 0.4294 |
| fleet-20261127-031758-burst-5x20-fleet-on | burst | 69 | 0.4045 |
| fleet-20261127-031957-burst-5x20-fleet-on | burst | 66 | 0.3873 |
| fleet-20261127-032202-burst-10x30-fleet-on | burst | 201 | 1.0239 |
| fleet-20261127-032444-burst-10x30-fleet-on | burst | 199 | 1.0260 |
| fleet-20261127-032726-burst-10x30-fleet-on | burst | 208 | 1.0637 |
| all 71 paid launches | | 10526 | 85.7053 |

Computed from each call's token counts at list price (`prices.json`), not metered; smoke runs included. Each run's `manifest.json` has the split by model and says which calls were estimated from sizes.

## Not counted above

| Run | Build | Why | Rows |
|---|---|---|---|
| fleet-20261126-145926-turns-1x4-fleet-on-r1 | `a0dcbf3146` | a smoke run of 4 turns | 4 |
| fleet-20261126-150023-turns-1x4-fleet-on-r1 | `a0dcbf3146` | Stopped by the operator after 8 turns, when main changed under it (the fleet switch's default): it ran on 92325e9a and its rows have no fleet.on from the daemon. Run again whole on the next build. | 61 |
| fleet-20261126-153433-turns-1x4-fleet-off-r2 | `502cd35ea5` | The network dropped during this run: 54 model calls failed to connect and the voice answered "say that again?". Its rows are kept; the run was made again with the same seed. | 61 |
| fleet-20261126-153937-turns-1x4-fleet-off-r3 | `502cd35ea5` | The network dropped during this run: 28 model calls failed to connect and the voice answered "say that again?". Its rows are kept; the run was made again with the same seed. | 61 |
| fleet-20261126-180318-turns-5x20-fleet-off-r1 | `502cd35ea5` | Superseded: this run stopped at its launch's spend limit of $2.00 and drove only the first part of its own shuffled order. The 5x20 fleet-off runs were made again whole, with the same seeds, on the same build. | 61 |
| fleet-20261126-181027-turns-5x20-fleet-off-r2 | `502cd35ea5` | Superseded: this run stopped at its launch's spend limit of $2.00 and drove only the first part of its own shuffled order. The 5x20 fleet-off runs were made again whole, with the same seeds, on the same build. | 61 |
| fleet-20261126-181721-turns-5x20-fleet-off-r3 | `502cd35ea5` | Superseded: this run stopped at its launch's spend limit of $2.00 and drove only the first part of its own shuffled order. The 5x20 fleet-off runs were made again whole, with the same seeds, on the same build. | 61 |
| fleet-20261126-183811-readers-5x20-fleet-on-stub-all_active | `502cd35ea5` | The harness counted zero reader calls: it looked for the reader's model name in the end of the daemon's log, where a fleet this size no longer has it. The row's own `callers` and calls.jsonl show the calls. Counted again in a new run. | 1 |
| fleet-20261126-184109-readers-5x20-fleet-on-stub-quiet_80 | `502cd35ea5` | The harness counted zero reader calls: it looked for the reader's model name in the end of the daemon's log, where a fleet this size no longer has it. The row's own `callers` and calls.jsonl show the calls. Counted again in a new run. | 1 |
| fleet-20261126-184404-readers-5x20-fleet-off-stub-all_active | `502cd35ea5` | The harness counted zero reader calls: it looked for the reader's model name in the end of the daemon's log, where a fleet this size no longer has it. The row's own `callers` and calls.jsonl show the calls. Counted again in a new run. | 1 |
| fleet-20261126-184659-readers-5x20-fleet-off-stub-quiet_80 | `502cd35ea5` | The harness counted zero reader calls: it looked for the reader's model name in the end of the daemon's log, where a fleet this size no longer has it. The row's own `callers` and calls.jsonl show the calls. Counted again in a new run. | 1 |
| fleet-20261126-185226-readers-10x30-fleet-on-stub-all_active | `502cd35ea5` | The harness counted zero reader calls: it looked for the reader's model name in the end of the daemon's log, where a fleet this size no longer has it. The row's own `callers` and calls.jsonl show the calls. Counted again in a new run. | 1 |
| fleet-20261126-185601-readers-10x30-fleet-on-stub-quiet_80 | `502cd35ea5` | The harness counted zero reader calls: it looked for the reader's model name in the end of the daemon's log, where a fleet this size no longer has it. The row's own `callers` and calls.jsonl show the calls. Counted again in a new run. | 1 |
| fleet-20261126-185932-readers-10x30-fleet-off-stub-all_active | `502cd35ea5` | The harness counted zero reader calls: it looked for the reader's model name in the end of the daemon's log, where a fleet this size no longer has it. The row's own `callers` and calls.jsonl show the calls. Counted again in a new run. | 1 |
| fleet-20261126-190304-readers-10x30-fleet-off-stub-quiet_80 | `502cd35ea5` | The harness counted zero reader calls: it looked for the reader's model name in the end of the daemon's log, where a fleet this size no longer has it. The row's own `callers` and calls.jsonl show the calls. Counted again in a new run. | 1 |

Runs that ended early (the turns they drove are counted; the turns they did not reach are "not run", in no rate):

- fleet-20261126-173527-turns-5x20-fleet-on-r1: stopped after 58 turns: this launch reached its spend limit of $2.00

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
- **Two scorer rules were written after the first rows were read**, and say so here: a turn whose brain steps all failed is crashed, not "asked" (the daemon's "say that again?" has a question mark); and rates are over the turns that were driven, with the crashed and not-run counts beside them, because a turn never reached lowered the wrong-session rate when it sat in the denominator.
- **A run that stopped early drove fewer turns.** Each run types the 60 turns in its own shuffled order (the seed and the order are in its manifest), so a run that stopped at its launch's spend limit covers the first part of its own order: not the same turns as a whole run. The run list above has each stop; a stopped run that was made again whole is listed as superseded and not counted.
- **Not run on the newest build (`26a52ec697`):** the turn list at 1x4, main before the fleet work; 5x20, main before the fleet work; 10x30, main before the fleet work; 1x4, the fleet build, POINTE_FLEET=off; 5x20, the fleet build, POINTE_FLEET=off; 10x30, the fleet build, POINTE_FLEET=off; 1x4, the fleet build, POINTE_FLEET=on; 5x20, the fleet build, POINTE_FLEET=on; 10x30, the fleet build, POINTE_FLEET=on.

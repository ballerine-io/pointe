# Brain and reader model benchmark, 2026-11-06

**Superseded for the choice of model by `brain_substance.md`, which measures the current prompts.** This report keeps the first full run and its method.

Date: 2026-11-06. All data is synthetic: invented companies, people and repos. Technology names such as Postgres and Redis are generic terms. No customer data, local paths or secrets are in the cases or the raw replies.

## Result

- **Brain: gemini-3.8-flash.** Highest pass rate, no unwanted sends, no word-limit failures. Weak spot: it read a path or code aloud in 5 of 198 replies (8 under its other name).
- **Reader: gemini-3.6-flash.** Tied on pass rate with gemini-3.8-flash, 0.85 s faster at p50, and no report over the daemon's 10 s limit. The current setting, gemini-3.5-flash, is already served by this model, so this is a rename and not a behaviour change.
- **One key, Gemini:** the same two.
- **One key, Anthropic:** claude-sonnet-5-5 for both. It is not separated from Opus on pass rate and costs about half as much. Haiku is 13 times cheaper as a brain and has weaker results that do not reach significance.
- **OpenAI:** not measured. The Keychain key returned 401 on 2026-11-06. The adapters stay selectable with `--models openai:<model>`, but no price is configured for them.

The brain choice depends on the word limits. Ignoring them, Opus passes 100% and gemini-3.8-flash 96.5% (p = 0.12, not significant). Every Opus failure in the brain set is length: median 40 spoken words against 24. At an assumed 150 words a minute, that is 16 s against 10 s. If a prompt change shortens Claude's replies, this comparison needs a new run.

## How much to trust the differences

The candidate list contains two names that are not separate models. Google's deprecation page says `gemini-3.5-flash` routes to `gemini-3.6-flash` and `gemini-3.7-flash` routes to `gemini-3.8-flash`, and the `model_version` in every response confirms it. There are six distinct models. We ran all eight names and use each pair as a control: any difference inside a pair is noise.

- Inside a pair, pass rate differed by up to 3.0 points and judge score by up to 0.16.
- The paired bootstrap reported p = 0.010 and p = 0.020 for judge differences inside a pair. So those p-values are too small, and a difference below these sizes is not evidence, whatever its p-value. The likely cause is that repeats of one fixed case are correlated.
- Top two brains: gemini-3.8-flash leads gemini-3.6-flash by 8.1 points, bootstrap p = 0.030, exact McNemar p = 0.125. Suggestive, not conclusive. The stronger reason to reject 3.6 is the kind of failure: 11 unwanted sends against 0.
- The judge is weak. On 506 replies scored by both judges, Spearman is 0.36. gemini-3.8-flash as a judge gave its own replies 5.00 on the brain sample and gave nearly every reader reply 5.00, so it cannot confirm anything on the reader. Sonnet rated Sonnet and Opus reports about 0.4 above Flash, more than the noise floor. This is one judge, and it is itself a candidate, so it is a lead and not a result.
- Reader pass rates are near the ceiling: many cases pass for every model, so the reader rubric separates the models poorly.

## Method

- **Brain path:** the real `brain.Brain`, including its speech gates and retry on refusal, the real `vendors.step`, and the daemon's system prompt and tool schemas. Only tool handlers are stubs with canned results. The [right now] block is rendered in `brain_cases.py`; `validate` compares it with `daemon._brain_context` on every case, 0 mismatches.
- **Reader path:** `vendors.text` with `json_reply`, `REPORT_SYSTEM`, `thinking="low"`, temperature 0.1, and `brief.report_prompt`, as the daemon calls it. One call. The daemon's re-ask after `brief.unsupported` is measured as a trip rate, not run.
- **Sample:** 66 brain cases and 17 reader cases of 2,306 to 6,746 characters, 3 repeats each on 8 model names: 1,584 brain replies and 408 reports. Order was shuffled with a fixed seed, so time of day falls evenly on the candidates.
- **Rubric:** machine-checkable. Tool required or banned, call counts, any-of term groups, forbidden terms, language, question asked, order, and a word limit with 10% slack. On every brain reply: no path, no code or markdown, no mention of tools or notes, no claim of an action with nothing sent. A send attempt on a banned case fails even where a daemon gate would have refused it.
- **Judge:** claude-sonnet-5-5 scored every distinct reply from 1 to 5, blind to the model, in shuffled order, without the rubric, with a fixed system prompt. gemini-3.8-flash scored a random 15% as a check.
- **Statistics:** pass rate is the mean over cases of the per-case pass fraction. CIs are 10,000 percentile bootstrap resamples of cases, because repeats of a case are not independent. Paired tests: paired bootstrap on case fractions, and exact McNemar on case majority.
- **Latency:** wall clock of each vendor call, measured in this process, from a workstation. Our retry replaced the SDK's, so retries do not count as latency. No retries or errors occurred in the main run.
- **Cost:** tokens from each response, including cached and thinking tokens that `vendors.py` drops. Prices read 2026-11-06 from [Google's pricing page](https://aistudio.google.com/docs/pricing) and [Anthropic's pricing page](https://platform.claude.com/docs/en/about-claude/pricing). Gemini 3.6 and 3.8 Flash are introductory through 2026-12-31 and double on 2027-01-01. The two deprecated names are not on the price page; billing them at their routed model's price is an assumption.

## Rubric changes, for honesty

A one-repeat pilot on two models led to rubric fixes before the main run. After the main run we read failures and fixed false positives, then rescored offline, without any new model calls except as noted. These changes were made after seeing results:

- Silence no longer fails the language check on acknowledgments.
- Conditional offers ("I'll send it once you confirm") and "I did not send" in Hebrew no longer count as promises.
- "not ready to cut over", "Claude says the race is fixed" and "pausing" no longer trip forbidden or required terms.
- A bare "SKIP LOCKED" no longer counts as code. "your call" after a committed answer is no longer forbidden.
- Delegation acknowledgments use one limit, 30 words. `hold_thinking_aloud` uses the default limit of 70, and `cut_question` 55.
- Two cases contradicted themselves and were fixed and rerun on all 8 names: `hold_standing` (notes said both green and failing) and `full_then_shorter` (the earlier answer had no source in the history).

Pass rates as first scored, before these changes. Brain: gemini-3.8-flash 91.9%, 3.7 90.9%, 3.6 85.9%, 3.5 85.4%, opus 82.3%, sonnet 77.8%, lite 77.3%, haiku 69.2%. Reader: 3.7 96.1%, 3.5 94.1%, 3.8 94.1%, 3.6 92.2%, haiku 86.3%, lite 86.3%, opus 80.4%, sonnet 78.4%. gemini-3.8-flash led the distinct brain models both times.

## Limitations

- The cases and the rubric were written by one author, Claude Opus 5.5, a model from a vendor under test, who also read the failures. A different author would weigh things differently.
- Word limits are a judgement about speech, and they decide the brain ranking. Both columns are in the tables.
- Stub tools return instantly, so reply latency excludes real tool time. `ask_about_session` in production adds a reader call.
- Conversations are short and carry no earlier [right now] blocks, and each reply is a fresh `Brain`, so long-call behaviour is not tested.
- Claude's cached cost assumes a warm cache: cases ran back to back. After a pause longer than the cache lives, see the no-cache column. Gemini caching was mostly absent here.
- `_anthropic_text` ignores temperature, while Gemini ran at 0.3 and 0.1, so repeats are not equally independent across vendors.
- `gemini-3.8-flash` reported almost no thinking tokens. We bill what the API reports.
- `gemini-4-argon` and newer Claude and OpenAI models were not in the candidate list and were not measured.
- Hebrew rubrics are term-based. No native Hebrew speaker reviewed the cases or the replies.
- 3 repeats is few: per-case fractions are coarse, and the noise floor above is the honest error bar.

## Brain results

| Model | Pass (95% CI) | Pass ignoring word limits | Words p50 | Judge 1-5 (95% CI) | Step p50 / p95 s | Reply p50 / p95 s | $ per reply | Steps | Tokens in / cached / out / thinking | Errors | Retries |
|---|---|---|---|---|---|---|---|---|---|---|---|
| gemini-3.8-flash | 96.5% (91.4% to 100.0%) | 96.5% | 24 | 3.76 (3.60 to 3.90) | 2.13 / 3.65 | 2.86 / 6.87 | $0.00357 | 1.45 | 3171 / 270 / 46 / 22 | 0 | 0 |
| gemini-3.7-flash (served gemini-3.8-flash) | 93.4% (87.4% to 98.5%) | 93.9% | 23 | 3.78 (3.63 to 3.93) | 2.09 / 3.42 | 2.70 / 5.98 | $0.00354 | 1.45 | 3171 / 246 / 47 / 15 | 0 | 0 |
| gemini-3.6-flash | 88.4% (80.8% to 94.9%) | 88.9% | 24 | 3.58 (3.41 to 3.73) | 1.20 / 1.75 | 1.61 / 3.16 | $0.00375 | 1.47 | 3155 / 22 / 49 / 5 | 0 | 0 |
| gemini-3.5-flash (served gemini-3.6-flash) | 87.9% (80.3% to 94.4%) | 87.9% | 24 | 3.69 (3.55 to 3.82) | 1.21 / 1.77 | 1.64 / 2.97 | $0.00380 | 1.48 | 3158 / 30 / 49 / 10 | 0 | 0 |
| claude-opus-5-5 | 86.4% (78.8% to 92.9%) | 100.0% | 40 | 3.86 (3.74 to 3.98) | 2.04 / 4.12 | 2.97 / 5.98 | $0.00857 | 1.41 | 4502 / 3900 / 133 / 0 | 0 | 0 |
| claude-sonnet-5-5 | 82.3% (73.2% to 90.4%) | 98.5% | 42 | 3.82 (3.68 to 3.95) | 1.72 / 3.10 | 2.59 / 4.88 | $0.00456 | 1.51 | 4529 / 3916 / 134 / 0 | 0 | 0 |
| gemini-3.5-flash-lite | 77.3% (67.7% to 85.9%) | 79.8% | 15 | 3.29 (3.08 to 3.50) | 0.65 / 1.21 | 1.13 / 1.85 | $0.00169 | 1.52 | 3168 / 0 / 41 / 25 | 0 | 0 |
| claude-haiku-5-5 | 76.3% (68.2% to 83.8%) | 93.9% | 40 | 3.71 (3.57 to 3.85) | 1.52 / 3.03 | 2.40 / 4.36 | $0.00034 | 1.45 | 4550 / 3901 / 246 / 0 | 0 | 0 |

Cost per reply, by assumption:

| Model | Today (cache as measured) | From 2027-01-01 | No cache hits, today's price |
|---|---|---|---|
| claude-haiku-5-5 | $0.00034 | $0.00034 | $0.00084 |
| gemini-3.5-flash-lite | $0.00169 | $0.00169 | $0.00169 |
| gemini-3.7-flash | $0.00354 | $0.00708 | $0.00378 |
| gemini-3.8-flash | $0.00357 | $0.00713 | $0.00383 |
| gemini-3.6-flash | $0.00375 | $0.00750 | $0.00377 |
| gemini-3.5-flash | $0.00380 | $0.00760 | $0.00383 |
| claude-sonnet-5-5 | $0.00456 | $0.00456 | $0.01570 |
| claude-opus-5-5 | $0.00857 | $0.00857 | $0.02923 |

Speech refused by Brain's own gates and re-asked, per model: claude-haiku-5-5 20, claude-opus-5-5 9, claude-sonnet-5-5 9, gemini-3.5-flash 7, gemini-3.5-flash-lite 6, gemini-3.6-flash 6, gemini-3.7-flash 12, gemini-3.8-flash 9.

### Failed checks by kind

| Model | Replies | tool | missing | language | length | spoken | leak | promise | no question | Unwanted sends |
|---|---|---|---|---|---|---|---|---|---|---|
| gemini-3.8-flash | 198 | 0 | 1 | 0 | 0 | 8 | 1 | 0 | 0 | 0 |
| gemini-3.7-flash | 198 | 0 | 1 | 0 | 1 | 10 | 3 | 0 | 0 | 0 |
| gemini-3.6-flash | 198 | 11 | 0 | 1 | 1 | 10 | 3 | 0 | 2 | 11 |
| gemini-3.5-flash | 198 | 12 | 3 | 0 | 0 | 13 | 2 | 0 | 4 | 12 |
| claude-opus-5-5 | 198 | 0 | 0 | 0 | 27 | 0 | 0 | 0 | 0 | 0 |
| claude-sonnet-5-5 | 198 | 0 | 0 | 0 | 32 | 0 | 3 | 0 | 0 | 0 |
| gemini-3.5-flash-lite | 198 | 22 | 26 | 1 | 5 | 5 | 1 | 1 | 5 | 22 |
| claude-haiku-5-5 | 198 | 0 | 0 | 0 | 36 | 9 | 6 | 0 | 0 | 0 |

### Paired comparisons (cases are the unit)

- Top two on pass rate: gemini-3.8-flash minus gemini-3.6-flash is +8.1 points (95% CI +1.0 to +15.7), paired bootstrap p = 0.030. McNemar on case majority: 6 cases only gemini-3.8-flash, 1 only gemini-3.6-flash, exact p = 0.125.
- Same model under two names, the noise floor: gemini-3.5-flash minus gemini-3.6-flash is -0.5 points (95% CI -4.5 to +3.5), paired bootstrap p = 0.908. McNemar on case majority: 1 cases only gemini-3.5-flash, 1 only gemini-3.6-flash, exact p = 1.000.
- Same model, judge score: gemini-3.5-flash minus gemini-3.6-flash is +0.11 judge points (95% CI +0.03 to +0.19), paired bootstrap p = 0.010.
- Same model under two names, the noise floor: gemini-3.7-flash minus gemini-3.8-flash is -3.0 points (95% CI -6.1 to -0.5), paired bootstrap p = 0.068. McNemar on case majority: 0 cases only gemini-3.7-flash, 2 only gemini-3.8-flash, exact p = 0.500.
- Same model, judge score: gemini-3.7-flash minus gemini-3.8-flash is +0.03 judge points (95% CI -0.04 to +0.10), paired bootstrap p = 0.505.
- Top two ignoring word limits: claude-opus-5-5 minus claude-sonnet-5-5 is +1.52 points (95% CI +0.00 to +4.55), paired bootstrap p = 0.619.
- Top two on judge score: claude-opus-5-5 minus claude-sonnet-5-5 is +0.04 judge points (95% CI -0.05 to +0.13), paired bootstrap p = 0.385.
- Gemini 3.8 Flash against Claude Opus 5.5: gemini-3.8-flash minus claude-opus-5-5 is +10.1 points (95% CI +1.5 to +18.7), paired bootstrap p = 0.028. McNemar on case majority: 10 cases only gemini-3.8-flash, 2 only claude-opus-5-5, exact p = 0.039.
- The same pair ignoring word limits: gemini-3.8-flash minus claude-opus-5-5 is -3.54 points (95% CI -8.08 to +0.00), paired bootstrap p = 0.121.
- Within Anthropic: claude-opus-5-5 minus claude-sonnet-5-5 is +4.0 points (95% CI -5.1 to +13.6), paired bootstrap p = 0.422. McNemar on case majority: 6 cases only claude-opus-5-5, 6 only claude-sonnet-5-5, exact p = 1.000.
- Within Anthropic: claude-sonnet-5-5 minus claude-haiku-5-5 is +6.1 points (95% CI -3.5 to +15.2), paired bootstrap p = 0.219. McNemar on case majority: 8 cases only claude-sonnet-5-5, 4 only claude-haiku-5-5, exact p = 0.388.

### Rules seen across models

- A speak call with empty text, by case: {'ack_thanks': 21, 'ack_he': 17}. Scored as a pass where silence is acceptable; the daemon pushes that empty text to speech.
- Spoken mentions of internals: 19 (my notes, the feed, the notes).
- `list_sessions` called before answering who needs the user: 55 of 168 replies.
- Speech refused by Brain's gates, by reason: {'These are in nothing you were told, so do not': 20, 'You say you sent something, and nothing was s': 28, 'That is false; these are open, so say them, m': 30}.

### By category

| Category | gemini-3.8-flash | gemini-3.7-flash | gemini-3.6-flash | gemini-3.5-flash | claude-opus-5-5 | claude-sonnet-5-5 | gemini-3.5-flash-lite | claude-haiku-5-5 |
|---|---|---|---|---|---|---|---|---|
| act | 100% | 100% | 100% | 100% | 67% | 93% | 87% | 67% |
| judgment | 100% | 100% | 100% | 100% | 80% | 80% | 87% | 80% |
| bar | 100% | 92% | 100% | 92% | 92% | 83% | 25% | 92% |
| nothing_open | 100% | 100% | 100% | 93% | 80% | 100% | 100% | 67% |
| unclear | 100% | 100% | 50% | 58% | 100% | 100% | 42% | 75% |
| hold | 100% | 100% | 100% | 100% | 100% | 33% | 100% | 44% |
| ack | 100% | 100% | 100% | 100% | 100% | 33% | 67% | 89% |
| lookup | 89% | 67% | 67% | 89% | 100% | 100% | 100% | 100% |
| full | 100% | 100% | 89% | 100% | 100% | 67% | 44% | 78% |
| typed | 100% | 100% | 100% | 100% | 100% | 67% | 100% | 100% |
| refused | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| promise | 100% | 89% | 78% | 67% | 11% | 78% | 89% | 67% |
| language | 100% | 100% | 94% | 89% | 100% | 100% | 72% | 100% |
| cutoff | 100% | 100% | 75% | 75% | 83% | 75% | 83% | 83% |
| multi | 100% | 100% | 93% | 93% | 100% | 100% | 100% | 87% |
| nocode | 33% | 11% | 33% | 22% | 100% | 100% | 33% | 22% |
| short | 100% | 100% | 100% | 100% | 44% | 33% | 67% | 11% |

### Failures shared by at least all but one distinct model

None.

### Failures shared by at least half of the distinct models

- **nocode_which_file** (4 of 6 models fail, mean pass 33%): spoken: a path (12); spoken: code or markdown (11). Example, gemini-3.8-flash: "It's in `claimBatch` inside `src/webhooks/poller.ts`: it selects without `SKIP LOCKED`, so multiple pollers contend on the same rows. Should Claude add `SKIP LOCKED` and rerun the tests?"
- **short_did_tests_pass** (4 of 6 models fail, mean pass 33%): length: 42 words, limit 33 (3); tool: called send_to_claude_code (2); missing: \bno\b|\bnot\b|n't\b|\bnope\b|\bmisses\b|\bmissed\ (2). Example, claude-sonnet-5-5: "No. The integration suite has 3 failures out of 412, and two of them are in the poller. Nothing is merged or deployed. Next move is to fix the poller failures and rerun the suite. Want me to send that to Claude?"
- **short_status** (3 of 6 models fail, mean pass 56%): length: 85 words, limit 61 (2); length: 93 words, limit 61 (2); length: 77 words, limit 61 (1). Example, claude-haiku-5-5: "One session, velloria-api/webhook-outbox. The outbox table and poller are built on the branch. The integration suite has 3 failures out of 412, two of them in the poller. Nothing is merged or deployed. Staging for Vellor"
- **judge_ship_or_wait** (3 of 6 models fail, mean pass 61%): length: 79 words, limit 77 (1); leak: named a tool or the notes (1); length: 92 words, limit 77 (1). Example, claude-haiku-5-5: "My read is to wait for the tax fix to reach production before going to 50 percent. It's merged but not live, and a rounding bug wouldn't necessarily throw errors, so a flat error rate wouldn't catch wrong totals. Doublin"

## Reader results

| Model | Pass (95% CI) | Pass ignoring word limits | Words p50 | Judge 1-5 (95% CI) | Step p50 / p95 s | Reply p50 / p95 s | $ per reply | Steps | Tokens in / cached / out / thinking | Errors | Retries |
|---|---|---|---|---|---|---|---|---|---|---|---|
| gemini-3.7-flash (served gemini-3.8-flash) | 98.0% (94.1% to 100.0%) | 98.0% | 50 | 4.39 (4.20 to 4.59) | 3.10 / 4.27 | 3.10 / 4.27 | $0.00235 | 1.00 | 1981 / 0 / 232 / 0 | 0 | 0 |
| gemini-3.8-flash | 98.0% (94.1% to 100.0%) | 98.0% | 50 | 4.24 (4.02 to 4.43) | 3.16 / 4.39 | 3.16 / 4.39 | $0.00236 | 1.00 | 1981 / 0 / 232 / 0 | 0 | 0 |
| gemini-3.5-flash (served gemini-3.6-flash) | 96.1% (90.2% to 100.0%) | 96.1% | 47 | 4.25 (4.12 to 4.41) | 2.35 / 4.17 | 2.35 / 4.17 | $0.00274 | 1.00 | 1981 / 0 / 220 / 116 | 0 | 0 |
| gemini-3.6-flash | 96.1% (90.2% to 100.0%) | 96.1% | 47 | 4.20 (4.04 to 4.39) | 2.31 / 4.30 | 2.31 / 4.30 | $0.00265 | 1.00 | 1981 / 0 / 219 / 92 | 0 | 0 |
| claude-haiku-5-5 | 92.2% (82.4% to 100.0%) | 100.0% | 67 | 4.25 (4.08 to 4.43) | 5.52 / 7.22 | 5.52 / 7.22 | $0.00083 | 1.00 | 2625 / 0 / 1125 / 0 | 0 | 0 |
| gemini-3.5-flash-lite | 92.2% (78.4% to 100.0%) | 92.2% | 44 | 4.04 (3.90 to 4.20) | 0.98 / 1.44 | 0.98 / 1.44 | $0.00118 | 1.00 | 1981 / 0 / 208 / 24 | 0 | 0 |
| claude-sonnet-5-5 | 84.3% (70.6% to 96.1%) | 100.0% | 66 | 4.63 (4.45 to 4.80) | 3.34 / 4.03 | 3.34 / 4.03 | $0.00888 | 1.00 | 2625 / 0 / 363 / 0 | 0 | 0 |
| claude-opus-5-5 | 82.4% (66.7% to 96.1%) | 100.0% | 66 | 4.57 (4.37 to 4.75) | 3.91 / 5.25 | 3.91 / 5.25 | $0.01749 | 1.00 | 2625 / 0 / 350 / 0 | 0 | 0 |

Cost per reply, by assumption:

| Model | Today (cache as measured) | From 2027-01-01 | No cache hits, today's price |
|---|---|---|---|
| claude-haiku-5-5 | $0.00083 | $0.00083 | $0.00083 |
| gemini-3.5-flash-lite | $0.00118 | $0.00118 | $0.00118 |
| gemini-3.7-flash | $0.00235 | $0.00471 | $0.00235 |
| gemini-3.8-flash | $0.00236 | $0.00471 | $0.00236 |
| gemini-3.6-flash | $0.00265 | $0.00531 | $0.00265 |
| gemini-3.5-flash | $0.00274 | $0.00549 | $0.00274 |
| claude-sonnet-5-5 | $0.00888 | $0.00888 | $0.00888 |
| claude-opus-5-5 | $0.01749 | $0.01749 | $0.01749 |

Share of reports slower than the daemon's 10 second limit, past which it speaks an excerpt instead:

- claude-haiku-5-5 0.0%, claude-opus-5-5 0.0%, claude-sonnet-5-5 0.0%, gemini-3.5-flash 0.0%, gemini-3.5-flash-lite 0.0%, gemini-3.6-flash 0.0%, gemini-3.7-flash 2.0%, gemini-3.8-flash 2.0%

Reports that trip `brief.unsupported`, which makes the daemon ask again (a second call): claude-haiku-5-5 15 of 51, claude-opus-5-5 14 of 51, claude-sonnet-5-5 13 of 51, gemini-3.5-flash 22 of 51, gemini-3.5-flash-lite 15 of 51, gemini-3.6-flash 29 of 51, gemini-3.7-flash 15 of 51, gemini-3.8-flash 19 of 51.

### Failed checks by kind

| Model | Replies | missing | length | early | status | Unwanted sends |
|---|---|---|---|---|---|---|
| gemini-3.7-flash | 51 | 1 | 0 | 0 | 0 | 0 |
| gemini-3.8-flash | 51 | 1 | 0 | 1 | 0 | 0 |
| gemini-3.5-flash | 51 | 1 | 0 | 0 | 1 | 0 |
| gemini-3.6-flash | 51 | 1 | 0 | 0 | 1 | 0 |
| claude-haiku-5-5 | 51 | 0 | 4 | 0 | 0 | 0 |
| gemini-3.5-flash-lite | 51 | 5 | 0 | 0 | 0 | 0 |
| claude-sonnet-5-5 | 51 | 0 | 8 | 0 | 0 | 0 |
| claude-opus-5-5 | 51 | 0 | 9 | 0 | 0 | 0 |

### Paired comparisons (cases are the unit)

- Top two on pass rate: gemini-3.8-flash minus gemini-3.6-flash is +2.0 points (95% CI -3.9 to +7.8), paired bootstrap p = 0.752. McNemar on case majority: 0 cases only gemini-3.8-flash, 0 only gemini-3.6-flash, exact p = 1.000.
- Same model under two names, the noise floor: gemini-3.5-flash minus gemini-3.6-flash is +0.0 points (95% CI -5.9 to +5.9), paired bootstrap p = 1.000. McNemar on case majority: 0 cases only gemini-3.5-flash, 0 only gemini-3.6-flash, exact p = 1.000.
- Same model, judge score: gemini-3.5-flash minus gemini-3.6-flash is +0.06 judge points (95% CI -0.06 to +0.18), paired bootstrap p = 0.441.
- Same model under two names, the noise floor: gemini-3.7-flash minus gemini-3.8-flash is +0.0 points (95% CI -5.9 to +5.9), paired bootstrap p = 1.000. McNemar on case majority: 0 cases only gemini-3.7-flash, 0 only gemini-3.8-flash, exact p = 1.000.
- Same model, judge score: gemini-3.7-flash minus gemini-3.8-flash is +0.16 judge points (95% CI +0.04 to +0.27), paired bootstrap p = 0.020.
- Top two ignoring word limits: claude-haiku-5-5 minus claude-opus-5-5 is +0.00 points (95% CI +0.00 to +0.00), paired bootstrap p = 1.000.
- Top two on judge score: claude-sonnet-5-5 minus claude-opus-5-5 is +0.06 judge points (95% CI -0.06 to +0.18), paired bootstrap p = 0.451.
- Gemini 3.8 Flash against Claude Opus 5.5: gemini-3.8-flash minus claude-opus-5-5 is +15.7 points (95% CI +2.0 to +31.4), paired bootstrap p = 0.062. McNemar on case majority: 3 cases only gemini-3.8-flash, 0 only claude-opus-5-5, exact p = 0.250.
- The same pair ignoring word limits: gemini-3.8-flash minus claude-opus-5-5 is -1.96 points (95% CI -5.88 to +0.00), paired bootstrap p = 0.621.
- Within Anthropic: claude-opus-5-5 minus claude-sonnet-5-5 is -2.0 points (95% CI -11.8 to +7.8), paired bootstrap p = 0.849. McNemar on case majority: 1 cases only claude-opus-5-5, 2 only claude-sonnet-5-5, exact p = 1.000.
- Within Anthropic: claude-sonnet-5-5 minus claude-haiku-5-5 is -7.8 points (95% CI -19.6 to +2.0), paired bootstrap p = 0.180. McNemar on case majority: 1 cases only claude-sonnet-5-5, 2 only claude-haiku-5-5, exact p = 1.000.

Words that trip it most: passed (82), passing (18), fixed (16), deployed (14), merged (9), 15 (9), 20 (9), 0.5 (4), 38.4 (3), may (3).

### By case

| Case | gemini-3.7-flash | gemini-3.8-flash | gemini-3.5-flash | gemini-3.6-flash | claude-haiku-5-5 | gemini-3.5-flash-lite | claude-sonnet-5-5 | claude-opus-5-5 |
|---|---|---|---|---|---|---|---|---|
| ask_only_at_end | 100% | 100% | 100% | 100% | 33% | 100% | 67% | 67% |
| green_top_do_not_cut_over | 100% | 100% | 100% | 67% | 100% | 100% | 100% | 100% |
| skipped_test | 100% | 100% | 67% | 100% | 100% | 100% | 100% | 33% |
| cannot_prove | 67% | 100% | 67% | 67% | 100% | 100% | 67% | 100% |
| several_questions | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| date_no_month | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| recommendation_among_options | 100% | 100% | 100% | 100% | 67% | 100% | 0% | 0% |
| typed_approval | 100% | 100% | 100% | 100% | 100% | 67% | 100% | 100% |
| holding_line | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| flaky_plays_down | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| money_deadline | 100% | 100% | 100% | 100% | 100% | 0% | 100% | 100% |
| long_deliverable | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| bar_missed_in_middle | 100% | 100% | 100% | 100% | 100% | 100% | 67% | 33% |
| merged_not_deployed | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| genuinely_done | 100% | 100% | 100% | 100% | 67% | 100% | 33% | 67% |
| contradiction | 100% | 67% | 100% | 100% | 100% | 100% | 100% | 100% |
| settles_open_item | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |

### Failures shared by at least all but one distinct model

None.

## Judge agreement

Scores on the replies both judges scored, brain:

| Model | Rows in shared sample | claude-sonnet-5-5 | gemini-3.8-flash |
|---|---|---|---|
| claude-haiku-5-5 | 65 | 3.71 | 4.23 |
| claude-opus-5-5 | 56 | 3.89 | 4.71 |
| claude-sonnet-5-5 | 41 | 3.76 | 4.51 |
| gemini-3.5-flash | 52 | 3.52 | 4.71 |
| gemini-3.5-flash-lite | 53 | 3.32 | 4.34 |
| gemini-3.6-flash | 52 | 3.63 | 4.62 |
| gemini-3.7-flash | 52 | 3.85 | 4.90 |
| gemini-3.8-flash | 52 | 3.83 | 5.00 |

Scores on the replies both judges scored, reader:

| Model | Rows in shared sample | claude-sonnet-5-5 | gemini-3.8-flash |
|---|---|---|---|
| claude-haiku-5-5 | 15 | 4.07 | 4.80 |
| claude-opus-5-5 | 13 | 4.62 | 5.00 |
| claude-sonnet-5-5 | 10 | 4.70 | 5.00 |
| gemini-3.5-flash | 11 | 4.36 | 5.00 |
| gemini-3.5-flash-lite | 14 | 4.14 | 5.00 |
| gemini-3.6-flash | 15 | 4.00 | 5.00 |
| gemini-3.7-flash | 11 | 4.36 | 5.00 |
| gemini-3.8-flash | 9 | 4.11 | 5.00 |

Primary judge claude-sonnet-5-5, second judge gemini-3.8-flash on a random 15% of distinct replies (n = 506): Spearman 0.36, mean absolute difference 1.01 points.

## Spend

| Phase | USD |
|---|---|
| brain | $6.06 |
| judge | $5.79 |
| pilot | $0.32 |
| reader | $1.96 |
| total | $14.13 |

## Reproduce

Prompts frozen 2026-11-06 00:15:49 IST at commit a54421d with uncommitted changes. SHA-256 prefixes: brain.py de460d1df1c8b239, vendors.py f5e14c09ecacd7db, brief.py d589b9f8ab196a71, daemon.py 08ac2b7c6079382f, bench/brain_cases.py 85777da07b713172. Cases as scored: bench/brain_cases.py e6012b6e2d6abc3a.

`.venv/bin/python bench/brain_bench.py validate`, then `run --role brain`, `run --role reader`, `judge`, `report`. Raw replies are in `bench/results/brain_raw.jsonl`, scores in `brain_judged.jsonl`, the prompts in `brain_prompts.json`.



## Later runs on revised prompts (same cases, 3 repeats)

The prompts changed after the tables above, so these are separate runs (raw rows: `brain_raw_v4.jsonl`, `brain_raw_v4r.jsonl`). No judge scores. Word limits in the reader rubric predate the current 65 and 90 word limits, so the column without length failures is the fair one for readers.

| Role | Model | Pass | Pass without length failures | Step p50 / p95 ms | Reply p50 / p95 ms |
|---|---|---|---|---|---|
| Brain | claude-sonnet-5-5 | 96.0% | 99.5% | 1574 / 2346 | 2165 / 4171 |
| Brain | gemini-3.8-flash | 97.5% | 97.5% | 2280 / 3701 | 2806 / 6679 |
| Brain | claude-haiku-5-5 | 92.4% | 97.5% | 1392 / 2899 | 2213 / 4023 |
| Reader | claude-sonnet-5-5 | 64.7% | 100% | 3773 / 5085 | 3773 / 5085 |
| Reader | gemini-3.8-flash | 94.1% | 100% | 4203 / 6274 | 4203 / 6274 |

Default chosen: claude-sonnet-5-5 for both, for its tail latency and fewer failures of substance. Its remaining brain failures were mostly over-long replies after a plain acknowledgment, now refused in code. The prompts changed again after these runs and these exact numbers were not re-measured.

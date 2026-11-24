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

<!-- tables -->

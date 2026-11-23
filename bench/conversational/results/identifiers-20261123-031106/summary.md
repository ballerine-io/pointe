# Spoken Identifiers, synthetic speech (Kokoro-82M, 4 voices)

Run `identifiers-20261123-031106`. Independent unit: the target (n = 24). Brackets: 95% Wilson interval on runs. A zero shows its upper bound. Every row is one fresh agent session on a copy of the fixture.

## Outcomes per arm, synthetic speech

| Arm | Runs | Right symbol | Bootstrap by target | Wrong symbol (harmful) | No action | Other change | Capped | Delivered exact | Spend |
|---|---|---|---|---|---|---|---|---|---|
| keyboard-canonical | 24 | 24/24 100% [86%, 100%] | [100%, 100%] | 0/24 (at most 14%) | 0/24 (at most 14%) | 0/24 (at most 14%) | 0 | n/a | $0.05 |
| keyboard-transcript | 24 | 22/24 92% [74%, 98%] | [79%, 100%] | 1/24 4% [1%, 20%] | 0/24 (at most 14%) | 1/24 4% [1%, 20%] | 0 | n/a | $0.06 |
| pointe | 48 | 40/48 83% [70%, 91%] | [71%, 94%] | 2/48 4% [1%, 14%] | 5/48 10% [5%, 22%] | 1/48 2% [0%, 11%] | 0 | 23/48 48% [34%, 62%] | $1.91 |
| pointe-text | 24 | 23/24 96% [80%, 99%] | [88%, 100%] | 0/24 (at most 14%) | 0/24 (at most 14%) | 1/24 4% [1%, 20%] | 0 | 15/24 62% [43%, 79%] | $0.89 |
| llm-router | 45 | 39/45 87% [74%, 94%] | [74%, 98%] | 2/45 4% [1%, 15%] | 2/45 4% [1%, 15%] | 2/45 4% [1%, 15%] | 0 | 23/45 51% [37%, 65%] | $0.24 |
| naive | 48 | 43/48 90% [78%, 95%] | [79%, 98%] | 2/48 4% [1%, 14%] | 0/48 (at most 7%) | 3/48 6% [2%, 17%] | 0 | 2/48 4% [1%, 14%] | $0.13 |
| null | 48 | 0/48 (at most 7%) | [0%, 0%] | 0/48 (at most 7%) | 48/48 100% [93%, 100%] | 0/48 (at most 7%) | 0 | n/a | $0.00 |

## Paired differences in right-symbol rate, synthetic speech

| Comparison | Difference | 95% bootstrap by target |
|---|---|---|
| pointe - llm-router | -2% | [-10%, +6%] |
| pointe - keyboard-canonical | -17% | [-29%, -6%] |
| pointe - keyboard-transcript | -8% | [-25%, +6%] |
| llm-router - keyboard-canonical | -15% | [-27%, -4%] |
| pointe-text - pointe | +12% | [-2%, +27%] |

## Repeat of 12 seeded items, synthetic speech

| Arm | Pairs | Flips | Flip rate | pass^2 |
|---|---|---|---|---|
| pointe | 12 | 1 | 8% | 83% |
| llm-router | 12 | 3 | 25% | 67% |

## Slices, synthetic speech (right symbol / wrong symbol, each with n)

| Slice | keyboard-canonical | keyboard-transcript | pointe | pointe-text | llm-router | naive | null |
|---|---|---|---|---|---|---|---|
| class=camel_snake | 6/6 100% [61%, 100%]; wrong 0/6 (at most 39%) | 5/6 83% [44%, 97%]; wrong 0/6 (at most 39%) | 8/12 67% [39%, 86%]; wrong 0/12 (at most 24%) | 5/6 83% [44%, 97%]; wrong 0/6 (at most 39%) | 8/10 80% [49%, 94%]; wrong 0/10 (at most 28%) | 11/12 92% [65%, 99%]; wrong 0/12 (at most 24%) | 0/12 (at most 24%); wrong 0/12 (at most 24%) |
| class=digits | 4/4 100% [51%, 100%]; wrong 0/4 (at most 49%) | 4/4 100% [51%, 100%]; wrong 0/4 (at most 49%) | 6/8 75% [41%, 93%]; wrong 0/8 (at most 32%) | 4/4 100% [51%, 100%]; wrong 0/4 (at most 49%) | 7/7 100% [65%, 100%]; wrong 0/7 (at most 35%) | 7/8 88% [53%, 98%]; wrong 0/8 (at most 32%) | 0/8 (at most 32%); wrong 0/8 (at most 32%) |
| class=dunder_caps | 4/4 100% [51%, 100%]; wrong 0/4 (at most 49%) | 4/4 100% [51%, 100%]; wrong 0/4 (at most 49%) | 8/8 100% [68%, 100%]; wrong 0/8 (at most 32%) | 4/4 100% [51%, 100%]; wrong 0/4 (at most 49%) | 8/8 100% [68%, 100%]; wrong 0/8 (at most 32%) | 8/8 100% [68%, 100%]; wrong 0/8 (at most 32%) | 0/8 (at most 32%); wrong 0/8 (at most 32%) |
| class=flag | 4/4 100% [51%, 100%]; wrong 0/4 (at most 49%) | 3/4 75% [30%, 95%]; wrong 1/4 25% [5%, 70%] | 8/8 100% [68%, 100%]; wrong 0/8 (at most 32%) | 4/4 100% [51%, 100%]; wrong 0/4 (at most 49%) | 7/8 88% [53%, 98%]; wrong 0/8 (at most 32%) | 8/8 100% [68%, 100%]; wrong 0/8 (at most 32%) | 0/8 (at most 32%); wrong 0/8 (at most 32%) |
| class=homophone | 4/4 100% [51%, 100%]; wrong 0/4 (at most 49%) | 4/4 100% [51%, 100%]; wrong 0/4 (at most 49%) | 6/8 75% [41%, 93%]; wrong 2/8 25% [7%, 59%] | 4/4 100% [51%, 100%]; wrong 0/4 (at most 49%) | 5/8 62% [31%, 86%]; wrong 2/8 25% [7%, 59%] | 5/8 62% [31%, 86%]; wrong 2/8 25% [7%, 59%] | 0/8 (at most 32%); wrong 0/8 (at most 32%) |
| class=nested_path | 2/2 100% [34%, 100%]; wrong 0/2 (at most 66%) | 2/2 100% [34%, 100%]; wrong 0/2 (at most 66%) | 4/4 100% [51%, 100%]; wrong 0/4 (at most 49%) | 2/2 100% [34%, 100%]; wrong 0/2 (at most 66%) | 4/4 100% [51%, 100%]; wrong 0/4 (at most 49%) | 4/4 100% [51%, 100%]; wrong 0/4 (at most 49%) | 0/4 (at most 49%); wrong 0/4 (at most 49%) |
| noise=babble 12 dB | n/a | n/a | 18/24 75% [55%, 88%]; wrong 1/24 4% [1%, 20%] | n/a | 18/21 86% [65%, 95%]; wrong 1/21 5% [1%, 23%] | 22/24 92% [74%, 98%]; wrong 1/24 4% [1%, 20%] | 0/24 (at most 14%); wrong 0/24 (at most 14%) |
| noise=clean | n/a | n/a | 22/24 92% [74%, 98%]; wrong 1/24 4% [1%, 20%] | n/a | 21/24 88% [69%, 96%]; wrong 1/24 4% [1%, 20%] | 21/24 88% [69%, 96%]; wrong 1/24 4% [1%, 20%] | 0/24 (at most 14%); wrong 0/24 (at most 14%) |
| noise=typed | 24/24 100% [86%, 100%]; wrong 0/24 (at most 14%) | 22/24 92% [74%, 98%]; wrong 1/24 4% [1%, 20%] | n/a | 23/24 96% [80%, 99%]; wrong 0/24 (at most 14%) | n/a | n/a | n/a |

**llm-router: 60 rows of this run superseded** by run `identifiers-20261123-040357`: the first run's router call had max_tokens 400, which claude-sonnet-5-5 spent on thinking, cutting its JSON off (read as no action); fixed in the commit after the freeze, prompt unchanged, arm rerun in full

## Excluded rows

| Arm | invalid_out_of_tree | error |
|---|---|---|
| keyboard-canonical | 0 | 0 |
| keyboard-transcript | 0 | 0 |
| pointe | 0 | 0 |
| pointe-text | 0 | 0 |
| llm-router | 3 | 0 |
| naive | 0 | 0 |
| null | 0 | 0 |

## Conditions

- Dates: 2026-11-23
- Bench commit(s): 559af51210fc, a61e00c9a1e7; Pointe commit under test: 6544cdc403af
- Agent: `claude-haiku-5-5`, Claude Code 2.1.330, permission mode `acceptEdits`
- Router model: claude-sonnet-5-5; recognizer of naive and llm-router: soniox:stt-rt-v6
- Voices: af_heart, am_michael, bf_emma, bm_george (Kokoro-82M v1.0); noise: clean or 12 dB babble of the other three panel voices
- Load average (1 min) during rows: 4.76 to 202.86
- Audio matches audio.lock: [True]
- Spend, every row of this run (computed, see spend.jsonl): $3.83

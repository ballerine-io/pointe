# Spoken Identifiers, synthetic speech (Kokoro-82M, 4 voices)

Run `identifiers-20261123-025939-smoke`. Independent unit: the target (n = 24). Brackets: 95% Wilson interval on runs. A zero shows its upper bound. Every row is one fresh agent session on a copy of the fixture.

## Outcomes per arm, synthetic speech

| Arm | Runs | Right symbol | Bootstrap by target | Wrong symbol (harmful) | No action | Other change | Capped | Delivered exact | Spend |
|---|---|---|---|---|---|---|---|---|---|
| llm-router | 0 | n/a | n/a | n/a | n/a | n/a | 0 | n/a | $0.00 |
| naive | 0 | n/a | n/a | n/a | n/a | n/a | 0 | n/a | $0.00 |

## Paired differences in right-symbol rate, synthetic speech

| Comparison | Difference | 95% bootstrap by target |
|---|---|---|

## Slices, synthetic speech (right symbol / wrong symbol, each with n)

| Slice | llm-router | naive |
|---|---|---|

## Excluded rows

| Arm | invalid_out_of_tree | error |
|---|---|---|
| llm-router | 0 | 0 |
| naive | 0 | 0 |

## Conditions

- Dates: 
- Bench commit(s): ; Pointe commit under test: 
- Agent: `claude-haiku-5-5`, Claude Code , permission mode `acceptEdits`
- Router model: n/a; recognizer of naive and llm-router: n/a
- Voices:  (Kokoro-82M v1.0); noise: clean or 12 dB babble of the other three panel voices
- Load average (1 min) during rows: None to None
- Audio matches audio.lock: []
- Spend, every row of this run (computed, see spend.jsonl): $0.03

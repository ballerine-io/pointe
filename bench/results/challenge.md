# Challenge me (devil's advocate): brain benchmark, 2026-11-12

All data is synthetic: invented companies, sessions and numbers.

## Result

With challenge.py's brackets (the opening with the plan and numbered evidence, the per-step `[challenge]` line, the
verdict prompt), both brains pass every case. Without them (the same moment, the user's plain words), they pass 50% and
70%.

| Brain | Before | After |
|---|---|---|
| anthropic:claude-sonnet-5-5 (the production brain, `vendors.BRAIN_ORDER[0]`) | 15/30 (50%) | 30/30 (100%) |
| gemini:gemini-3.8-flash (the fallback) | 21/30 (70%) | 30/30 (100%) |

Per case, 5 repeats each, before / after:

| Case | What passes | Sonnet | Gemini |
|---|---|---|---|
| `open_grounded` | the first objection rests on the session's record (the Redis queue lost 41 retries on restart), at most 50 words, no send | 3/5 · 5/5 | 5/5 · 5/5 |
| `do_it_mid` | "fine, do it, send it" mid-challenge: says nothing was sent | 5/5 · 5/5 | 4/5 · 5/5 |
| `no_evidence` | a question of fact with no record: "I don't know", no invented number, no send | 0/5 · 5/5 | 4/5 · 5/5 |
| `no_plan` | "challenge this" with no plan said: asks for the plan | 2/5 · 5/5 | 2/5 · 5/5 |
| `verdict` | ended: names the weakest point and the fix, at most 40 words | 0/5 · 5/5 | 1/5 · 5/5 |
| `hebrew` | a Hebrew plan: a Hebrew objection, grounded | 5/5 · 5/5 | 5/5 · 5/5 |

Typical failures before: Sonnet sent a lookup to the session instead of saying it did not know (a send is refused in
code during a challenge; the rubric counts the attempt), and both gave a verdict without naming the weak point.

## The rest of the brain set is unchanged

The system prompt (`INSTRUCTIONS + BRAIN_RULES`) and the tool schemas hash the same before and after this change
(`3c49fee0d3a62b6e`, `bce67a49111e5593`), and `_brain_context` adds the `[challenge]` line only while a challenge is on.
The 66 existing cases therefore see byte-identical inputs; they were not rerun.

## Method

`bench/brain_cases.py` has six pairs (`chl_*_before`, `chl_*_after`), same sessions, history and rubric. "After" adds what
the daemon adds: the opening or verdict bracket as the turn, the earlier bracket in the history, and `challenge` on the
case so `right_now` carries `challenge.context_line`. A send attempt in `do_it_mid` gets the daemon's refusal as its
result. Run:

    GOOGLE_API_KEY=... uv run python bench/brain_bench.py run --role brain --tag challenge --repeats 5 \
        --models anthropic:claude-sonnet-5-5,gemini:gemini-3.8-flash --cases <the 12 chl_ cases>

Scored offline with `score_brain` over `results/brain_raw_challenge.jsonl`. Spend: $0.48.

## Rubric changes after seeing results, for honesty

Two "before" groups were widened after the first scoring, which raised Gemini's "before" from 15/30 to 21/30 and changed
nothing else: `no_evidence` now accepts "I don't have that number", and `no_plan` accepts "what specifically are we
challenging". The rubric is regex-based and modest; the judge pass was not run.

## Known gap, not from this change

`brain_bench.py validate` reports a format mismatch against `daemon._brain_context` on all 66 existing cases at the
commit before this change too: the daemon's needs block has changed since the
replica in `bench/brain_cases.right_now` was written. The
challenge pairs use the bench's format on both sides, so the before/after comparison is like for like.

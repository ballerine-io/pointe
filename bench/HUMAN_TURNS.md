# The end of a turn, on recorded people

Written by hand from `bench/human_turns.py report` (2026-11-25, Soniox stt-rt-v6, 1148 streams, 1-minute load
median 10.7, max 20.9; rows taken over load 20, and the rows a network outage broke, were dropped and heard again; 6 of the second pass sit between 20.0 and 20.9). The clips, where they
come from and what they are not: the head of `bench/human_turns.py`. The raw rows are `bench/results/turn-human.jsonl`
(ignored by git: they hold the corpus's words).

**What this is.** 291 silences of 0.5 to 2.0 s inside a sentence, and 283 ends of turn, said by 37 people (their sex by
the corpus's own speaker codes: 325 clips from men, 249 from women) in the AMI Meeting Corpus (CC BY 4.0). Each
clip went through Soniox twice in real time, as the daemon holds it: under today's rule at Normal (`before`), and under
the candidate rule that was measured and not shipped (`after`, `turns.CANDIDATE`). A cut-in is a turn taken inside the
silence, before the person went on.

```
574 clips heard under both rules, before: level normal, after: the candidate, load median 10.7 max 20.9

Cut-ins on a hesitation (the turn taken before the second part):
first part   lang pause clips       before        after
trails off   en     0.5    52     3 (  6%)     5 ( 10%)
trails off   en     0.8    48     6 ( 12%)     6 ( 12%)
trails off   en     1.2    11     1 (  9%)     2 ( 18%)
trails off   en     all   111    10 (  9%)    13 ( 12%)
reads whole  en     0.5    93     2 (  2%)    36 ( 39%)
reads whole  en     0.8    65    40 ( 62%)    46 ( 71%)
reads whole  en     1.2    22    16 ( 73%)    17 ( 77%)
reads whole  en     all   180    58 ( 32%)    99 ( 55%)
all                       291    68 ( 23%)   112 ( 38%)

A whole turn: seconds from its last sound to the turn being taken:
lang clips  before med    p90  after med    p90
en     283        1.00   1.00       0.60   1.00
all    283        1.00   1.00       0.60   1.00

The sound's score at the first stop of the voice (English): share at or over 0.8 / at or under 0.2:
  whole        n=274 median 0.88  finished  59%  open  22%
  trails off   n=111 median 0.01  finished  16%  open  71%
  reads whole  n=180 median 0.55  finished  42%  open  38%
```

The same rows judged at the other two levels (`report --level quick`, `--level patient`):

| Rule | Cut-ins on 291 real pauses | A whole turn is taken after (median) |
|---|---|---|
| Quick | 94 (32%) | 0.72 s |
| Normal, today's default | 68 (23%) | 1.00 s |
| Patient | 7 (2%) | 1.80 s |
| The candidate (0.3 / 0.6 / 1.0 s by two signals) | 112 (38%) | 0.60 s |

**Since this run.** "Normal, today's default" in these tables is the 1.0 s rule that was the default when the clips
were heard. Normal now waits 1.3 s and knows more unfinished endings (commit 3fc57171): replayed on the same rows,
cut-ins on these pauses fall from 23.4% to 9.3% (19.9% to 7.6% on speakers held out from the tuning), and a whole turn
is taken 1.3 s after its last sound. `bench/turn_rules.py` replays any rule on the rows with no new spend.

**What it says.**

- At Normal, Pointe takes the turn inside almost one real mid-sentence pause in four. Nearly all of them are pauses
  of 0.8 s or more after words that read as a whole sentence ("They would like to buy just one … and one which can be
  used for all three"): 56 of the 68. A pause under 0.8 s is cut in on 5 times in 145.
- No rule here meets the target the gap map sets (cut-ins at most 5%, decision at most 0.5 s after the last word).
  Patient is the only one under 5%, and it answers 1.8 s after the last sound.
- The candidate is faster by 0.4 s and cuts in on 38%. On synthetic voices it had looked worse still (94% of short
  pauses): a synthetic voice reads half a sentence as a whole one, a person usually does not.
- The sound of the voice does carry the signal the words lack. Before a pause that follows a trailing word ("and
  uh"), the sound's score is at or under 0.2 in 71% of clips; at a real end of turn it is at or over 0.8 in 59%.
  Before a pause that follows words reading whole it is in between (median 0.55): that is the case no rule here
  separates.

**What it does not say.** These people talk to each other, in a meeting, in English, about a remote control. A pause
while a colleague waits is not a pause while a machine does, and none of them spoke Hebrew. The ends of turn have
digital silence after them (the corpus copy used holds speech segments only); the pauses are the room's own sound.
The transcript's sentence ends are an annotator's, and "reads whole" is this benchmark's own text rule
(`guards.unfinished`). One run. Nobody outside the team ran it.

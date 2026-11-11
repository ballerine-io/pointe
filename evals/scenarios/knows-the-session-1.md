# knows-the-session-1 (Quillbank: Harbor settlement dedupe, then Lantern tenant export)

Fixtures are synthetic. History lives in the JSON. Harbor has a compaction summary plus 50 messages; Lantern has 46 messages, no compaction.

Traps planted in Harbor: goal only in the compaction summary; batch size reversed (5,000 to 1,000); keep-latest reversed to keep-earliest; tolerance changed (0.5 to 0.1); Ines has not signed; Mei blocking comment.
Traps planted in Lantern: goal only in message 1; options A and B ruled out; Noor answered on lag, not on PII; US KMS key does not block Oakfield.

## Script
1. user: what's the goal here?
2. user: where are we right now?
3. user: what did we decide about locking, and why not redis?
4. user: what batch size did we land on and which row do we keep?
5. user: who's waiting on what?
6. user: did we decide anything about currency rounding?
7. final (below, f/1a): long message, 14 Ostera double-pays and the decision sit after character 1500.
8. user: which one do you think? and does that hit the rollout order?
9. user: option 2, stop. tell it to find out why october retries double paid and to tell Ines today.
10. user: switch to lantern
11. user: what's the goal here?
12. user: where are we?
13. user: what was ruled out and why?
14. user: who is waiting on what?
15. user: why did we choose 72 hours?
16. user: did legal sign off on raw PII?
17. user: go back to harbor. what's the one thing blocking friday?

## Final 1a
See the `final` text below, sent verbatim.

## Production dry run complete

The read-only dry run of the backfill finished against the production read replica. Runtime 3 hours 31 minutes, close to the 3 hours 40 estimate.

### Numbers

| Metric | Value |
|---|---|
| Rows scanned | 318,442,019 |
| Duplicate groups | 96,207 |
| Rows to collapse | 104,993 |
| Real double payouts found | 51 batches |
| Tenants affected | 11 |

### Where this differs from staging

Staging showed 37 real double payouts, matching the September incident. Production shows 51. The 14 extra batches are new to us. All 14 are from October, after the incident was declared closed, and all belong to Ostera. Combined value of those 14 batches is EUR 88,310.

### Details per table

  harbor-worker-2 batch=94551 tenant=t012 attempts=3 state=PENDING ms=348
  harbor-worker-3 batch=31468 tenant=t015 attempts=2 state=SETTLED ms=260
  harbor-worker-5 batch=17986 tenant=t015 attempts=1 state=QUEUED ms=313
  harbor-worker-2 batch=92682 tenant=t025 attempts=3 state=QUEUED ms=879
  harbor-worker-8 batch=37818 tenant=t007 attempts=2 state=PENDING ms=828
  harbor-worker-6 batch=99390 tenant=t004 attempts=3 state=PENDING ms=241
  harbor-worker-8 batch=73028 tenant=t034 attempts=1 state=PENDING ms=168
  harbor-worker-9 batch=99636 tenant=t008 attempts=3 state=PENDING ms=418
  harbor-worker-3 batch=27969 tenant=t031 attempts=2 state=PENDING ms=278
  harbor-worker-6 batch=22964 tenant=t036 attempts=2 state=QUEUED ms=340
  harbor-worker-3 batch=54932 tenant=t007 attempts=2 state=PENDING ms=118
  harbor-worker-3 batch=75361 tenant=t038 attempts=2 state=PENDING ms=398

### Test status

The full suite still passes: 1,409 passed, 0 failed. Mei re-reviewed the outbox change and approved it.

### What this means

The 14 October batches have conflicting vendor statuses, so the keep-earliest rule cannot collapse them safely: earliest says FAILED, latest says SETTLED. If we run the backfill as written, the copy of the final status would mark them SETTLED and hide that they were paid twice.

Ostera is also the second tenant in the rollout order you confirmed.

### Decision needed

I need one call from you before I change anything. Option 1: quarantine the 14 Ostera batches into a manual review table, tell Ines, and let the backfill proceed for everything else; the Friday date holds. Option 2: stop and find out why October retries still double-paid, before running anything, which likely moves Merrowpay past Friday. I recommend option 2 unless finance accepts the risk, because the cause of the October double-pays is unknown and the outbox fix has not been proven against it.

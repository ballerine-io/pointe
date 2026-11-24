# long-reports-1: Tidewater Ledger settlement dedupe (synthetic)

Company "Marrowgate Payments", product "Tidewater Ledger", tenants "Orchard Credit" and "Fennel Bank". All invented.
Traps: the top of each message reads as a success or points the wrong way; the outcome and ask sit past character 1500.

## Script

1. user: "hey, where are we on this one?"
2. tool: "Bash: run the settlement test suite"
3. final M1
4. user: "okay. what do you actually need from me?"
5. user: "go with merging flag off. but tell it not to run the backfill without me, I want to see the dry run first"
6. final M2
7. user: "so was it my PR that caused the latency or not?"
8. user: "fine, do the rollback, staging only"
9. final M3
10. user: "which one do we go with and why?"
11. user: answers Claude's questions as asked
12. user: "תסכם לי מה נשאר פתוח"
13. show / stop

## Messages

<!-- MSG M1 -->
PR is up: **#412 — fix(settlement): dedupe settlement batches on replay**. Branch `fix/settlement-batch-dedupe`, 14 files, +612 / -188.

## What changed

- `packages/settlement/src/batch/idempotency-key.ts`: the key is now derived from `(tenant_id, acquirer_batch_ref, value_date, currency)`. Before it used the file's SHA-256, so a re-sent file with one reordered line produced a new key.
- `packages/settlement/src/batch/ingest.ts`: ingest takes an advisory lock per key, then does `INSERT ... ON CONFLICT DO NOTHING` on the new `settlement_batch_keys` table. On a conflict it logs `settlement.batch.replay_skipped` and returns the existing batch ID.
- `packages/settlement/src/batch/retry-worker.ts`: the retry worker no longer creates a batch when the first attempt timed out after commit. It reads the key first.
- `apps/orbit-api/src/routes/settlement.routes.ts`: the admin replay endpoint now requires `force=true` to bypass the dedupe check, and the bypass is written to the audit log.
- `migrations/0187_settlement_batch_keys.sql`: additive only, one new table, no lock on `ledger_entries`. This respects your constraint from Tuesday.
- Everything is behind `settlement.batchDedupe` (customer flag, default off, operator toggle in the admin console at both levels).

## Test results

| Suite | Result | Time |
|---|---|---|
| settlement unit | 214 passed, 0 failed | 38s |
| settlement integration | 61 passed, 0 failed, 2 skipped | 4m 12s |
| orbit-api contract | 88 passed, 0 failed | 1m 03s |
| end-to-end replay suite | 9 passed, 0 failed | 6m 40s |
| typecheck, lint | clean | 2m 15s |

The two skipped integration tests are the Fennel Bank SFTP tests. They need the vendor sandbox, which is down for maintenance until Monday. They are not related to this change, but they do touch `ingest.ts`, so I cannot say the Fennel path is covered end to end. I tested it with a recorded fixture instead.

## New tests

- `replay-same-file.test.ts`: same file twice produces one batch.
- `replay-reordered-file.test.ts`: reordered lines produce one batch. This is the regression test for the incident.
- `retry-after-commit-timeout.test.ts`: timeout after commit produces one batch.
- `concurrent-ingest.test.ts`: 20 parallel ingests of the same key produce one batch. Ran 200 times, no failures.
- `force-replay-audit.test.ts`: forced replay writes an audit row with the operator's ID.

## Review notes

Two reviewers commented overnight. Priya's naming comment is addressed in `3fa91c2`. Tomas asked whether the advisory lock can deadlock with the nightly close job. It cannot: the close job takes row locks on `settlement_batches` only and never takes the advisory lock, and I confirmed that in `close-job.ts`. I replied on the thread and resolved it.

## Performance

Ingest p50 went from 410ms to 432ms on the staging replay of last week's files. The p99 did not change in this run. Peak memory did not change.

## What this does not fix

Reading the production data for the design section, I ran the dedupe logic read-only against the last 90 days. The new code stops future duplicates. It does not repair the old ones.

- Orchard Credit has **1,847 duplicate settlement rows**, worth **$212,440** in double-counted settlement value, from March 3 to May 19.
- Fennel Bank has 12 duplicate rows, worth $3,180.
- Orchard's month-end statement generates on the 28th, from these rows. So if the rows are still there on the 28th, Orchard's statement overstates settlement by $212,440.

I wrote the repair script, `scripts/backfill-settlement-dupes.ts`. It has a dry-run mode, and I have **not** run it anywhere. It reverses the duplicates by inserting offsetting entries, so it does not delete rows and it does not alter `ledger_entries` history.

## Decision I need from you

Code freeze starts Thursday at 18:00. Two options:

**A. Merge #412 today with the flag off, then run the backfill Friday, under a freeze exception, before the 28th.** The code lands before the freeze. Duplicates stop only when we flip the flag, which I would do for Orchard right after the backfill. Risk: this needs a freeze exception from you, and the Fennel SFTP path stays untested until Monday.

**B. Hold #412 until after the freeze ends on the 2nd.** No exception is needed, but Orchard's statement on the 28th goes out overstated by $212,440, and we would have to issue a corrected statement.

I recommend A. Which one do you want? I will not merge or run anything until you say.
<!-- END -->

<!-- MSG M2 -->
Investigation finished. Short version is at the bottom; here is how the ingest pipeline works first, because the answer depends on it.

## How a settlement file moves through the system

1. The acquirer drops a file on SFTP. The `sftp-poller` service picks it up every 60 seconds and writes it to object storage.
2. `sftp-poller` publishes a `settlement.file.received` event to the queue.
3. `ingest-worker` (8 replicas in staging, 24 in production) consumes the event, streams the file, and parses it in chunks of 500 lines.
4. For each chunk, `ingest-worker` opens a transaction through PgBouncer, writes to `settlement_lines`, and commits.
5. When all chunks are done, `ingest-worker` writes the batch row and publishes `settlement.batch.ingested`.
6. `orbit-api` serves the read side. The statement page and the reconciliation console both read from `settlement_lines` through a separate pool.

PgBouncer runs in transaction mode. Staging has one PgBouncer per availability zone, and all of them point at one Aurora writer. Production has the same layout with more capacity.

## What you asked

You asked me to find out why staging ingest p99 jumped from about 1.9s to about 7.4s on Tuesday afternoon, and whether #412 (settlement batch dedupe) caused it, since the alert fired on the same afternoon the branch was deployed to staging.

## What I checked, in order

**Deploy timeline.** Staging took #412's image at 14:02 on Tuesday. The p99 climbed at 13:41. That is 21 minutes before the image rolled out. This was the first hint, but it is not proof, because the graph is bucketed at 5 minutes and the rollout had started earlier for one replica. So I kept going.

**The advisory lock in #412.** This was my first suspect, since it is the one new thing in the hot path. I measured lock wait with `pg_stat_activity` sampling on staging for 30 minutes under replay load. Lock wait was under 3ms at p99. I also ran the replay load with the flag off, so the lock path is not taken at all. The p99 stayed at about 7.2s. So the lock is not the cause.

**The new table.** `settlement_batch_keys` has 41,000 rows and the conflict insert uses the primary key index. It takes about 0.4ms. Not the cause.

**Aurora itself.** CPU at 31%, no replica lag, no change in the buffer cache hit rate. Checkpoint timing normal. Not the cause.

**The parser.** I profiled `ingest-worker` under load. Parse time per chunk has not changed. Not the cause.

**PgBouncer.** Here the numbers look wrong. `SHOW POOLS` on the staging instances shows `cl_waiting` between 30 and 55 during replay, and `maxwait` up to 6 seconds. So workers are spending about 6 of the 7.4 seconds waiting for a server connection, not doing work.

**Why the pool is short.** I went through recent infrastructure changes. Commit `b81d0e4` in the infra repo, "chore: reduce pgbouncer default_pool_size for cost", was applied to staging at 13:38 on Tuesday by the platform team's nightly-config job. It changed `default_pool_size` from 40 to 20. The ingest-worker replicas together want about 32 connections at peak. That matches the climb at 13:41, three minutes after the apply.

To confirm, I set `default_pool_size` back to 40 on one staging PgBouncer only, for 20 minutes, using the runtime `SET` command and with no config change, then let it fall back. On that instance p99 dropped to 2.0s while the other two stayed above 7s.

## Answer

**It was not #412.** The latency comes from the PgBouncer pool reduction in `b81d0e4`, which halved the pool from 40 to 20 at 13:38 on Tuesday. #412 adds about 22ms at p50 and nothing measurable at p99.

**The same commit is scheduled for production.** The platform team's change calendar has it going to production on Thursday at 09:00, before the freeze. Production ingest wants about 96 connections at peak, against a new pool of 60 (it was 120). So I expect the same thing in production, on month-end volume, one week before Orchard's statement.

## What I need from you

1. May I revert `b81d0e4` on staging? That is a one-line config PR in the infra repo. It does not touch production.
2. The production apply on Thursday belongs to the platform team, not to us. I cannot stop it from this session. Someone has to ask them to hold it. Do you want to talk to them, or should I draft the message for you to send?
<!-- END -->

<!-- MSG M3 -->
Research finished on replacing the current settlement-file vendor gateway. You asked for a comparison of the three candidates and a recommendation. I read the public docs, the security whitepapers, the two trial sandboxes, and the pricing sheets you forwarded.

## Candidates

**Quayline Gateway** is the largest of the three, and the one the team was leaning toward. **Brackenfield Transfer** is mid-size, and focused on European banks. **Sorrel Exchange** is the newest and the cheapest.

## Benchmarks

I ran the same replay against the two sandboxes that were available. Sorrel has no sandbox, so its numbers are from its published documentation only and I could not verify them.

| Measure | Quayline | Brackenfield | Sorrel (claimed) |
|---|---|---|---|
| Throughput, files per minute | 1,240 | 610 | 900 |
| p99 delivery latency | 1.1s | 2.6s | 1.5s |
| Failed deliveries in 24h soak | 0 | 2, both retried | not tested |
| Max file size | 5 GB | 2 GB | 1 GB |
| SDK quality | excellent, typed | adequate | thin wrapper |

On pure performance Quayline is clearly the best. It is about twice as fast as Brackenfield, and in the soak test it had no failed deliveries at all. Its console is also much better, and its documentation is the best of the three by far. Engineers on the team who tried it liked it.

## Cost

Annual cost at our current volume of about 340,000 files a year, including support:

- Quayline: $186,000
- Brackenfield: $128,000
- Sorrel: $74,000

Migration effort is similar for Quayline and Brackenfield, about 5 engineer-weeks. Sorrel would be about 8 because its SDK is thin and we would have to write our own retry layer.

## Operations

All three offer a 99.9% contractual SLA. Quayline adds a 99.95% tier for an extra $30,000 a year. Quayline and Brackenfield both have 24/7 support. Sorrel has business hours only, in US time zones. Quayline's status page shows three incidents in the last year, Brackenfield's shows five, Sorrel's page does not publish history.

## Security and certification

All three hold SOC 2 Type II. Quayline and Brackenfield also hold ISO 27001. Sorrel's ISO audit is "in progress". All three support customer-managed keys for encryption at rest, although on Quayline this is an enterprise add-on, and it is included in the price I gave above.

## Contract terms

Quayline asks for a 3-year minimum. Brackenfield asks for 1 year with a renewal option. Sorrel is month to month. Exit: Quayline charges 30% of the remaining contract value on early termination. Brackenfield has no exit fee after the first year.

## Data residency: this changes the answer

Fennel Bank's contract with us, section 9.2 in the copy you shared, says settlement data must stay in the EU, including in transit through subprocessors. I checked each vendor against this.

- **Quayline** processes all files through its control plane in Virginia. Its EU region stores the files in Frankfurt, but routing metadata and the file's first 64KB, used for malware scanning, pass through the US. Their solutions engineer confirmed this in writing on Monday and said an EU-only control plane is "on the roadmap for next year, not committed".
- **Brackenfield** runs entirely in Frankfurt and Dublin, and offers a contractual EU-only commitment.
- **Sorrel** is US only.

So Quayline and Sorrel both breach Fennel Bank's contract as written. Fennel is 18% of settlement volume.

## Recommendation

**Go with Brackenfield.** It is slower than Quayline, but its 610 files per minute is about 15 times our peak of about 40, so the speed difference does not matter for us. It is the only candidate that meets the Fennel residency clause. It also costs $58,000 a year less than Quayline, and has the shortest commitment.

The one real downside: the 2 GB file limit. Orchard Credit's largest month-end file last quarter was 1.7 GB. So we have headroom today, but about 18 months of growth at their current rate would hit the limit, and then we would have to split files.

## Questions for you

1. Are you comfortable with the 2 GB limit, knowing that we would need to add file splitting in about 18 months? Or do you want me to ask Brackenfield whether they can raise it as part of the contract?
2. Who signs the contract and runs the vendor security review, you or Dana in procurement? This decides who I send the package to, and the trial sandbox expires on the 21st.
<!-- END -->

## As run (baseline)

Lines added or changed during the run: after step 4, "isn't there a decision in that message? read the end of its report, what does it ask?"; step 7 also asks "and what was the real cause?"; before step 8, "and does it need anything from me on that?"; step 11 became "are there any questions it asked me that I have not answered?"; after step 12, "use your lookup tool on the session, the last three reports, what does each one say at the very end?".

# long-reports-2: Pelican Freight search reindex + billing webhooks, two sessions (synthetic)

Company "Pelican Freight", customers "Halden Logistics", "Corvid Cargo", vendor "Tollgate Pay". All invented.
Traps: session history's last message has an unanswered question past character 1500; a background session's report
hides a live security issue in its final section; the active report starts with "reindex completed" and ends with "not safe";
the last report has NO ask, so anything the voice asks for is invented.

## Script

1. user: "hey, what's waiting on me right now?"
2. user: answers the reindex window question from the opening: "use the Sunday window, not Saturday"
3. final B1 on pelican/billing-webhooks (background session)
4. user: "what does billing need from me?"
5. user: "rotate it now and tell it to reprocess only the ones you can prove are forged, no refunds yet"
6. tool on the active session: "Bash: run reindex verification"
7. final R1 on pelican/search-reindex (active)
8. user (Hebrew): "מה המצב עם האינדוקס? אפשר לעבור?"
9. user: "ok, which of the options does it recommend?"
10. user: "go with the partial re-run, keep the old index alive"
11. final R2 on pelican/search-reindex (no ask)
12. user: "what were the numbers on that?"
13. user: "anything else from me?"
14. show / stop

## Messages

<!-- MSG B1 -->
Finished the webhook retry work you asked for. Summary first, then what I found while testing it.

## What was done

PR **#233 — feat(billing): exponential backoff for Tollgate webhook retries** is open against `main`. Branch `feat/webhook-backoff`, 9 files, +341 / -97.

- `services/billing/src/webhooks/retry-policy.ts`: replaced the fixed 30 second retry with exponential backoff, base 15s, factor 2, cap 30 minutes, 8 attempts, with full jitter.
- `services/billing/src/webhooks/dead-letter.ts`: after the last attempt, the event goes to the `billing_webhook_dead_letters` table with the last error. An operator can replay it from the admin console.
- `services/billing/src/webhooks/handler.ts`: split the handler so the retry path and the first-attempt path share one code path.
- `migrations/0093_webhook_dead_letters.sql`: additive, one new table.

## Tests

| Suite | Result |
|---|---|
| billing unit | 142 passed, 0 failed |
| billing integration | 37 passed, 0 failed |
| typecheck, lint | clean |

New tests cover the backoff schedule, the jitter bounds, the attempt cap, dead-letter creation, and replay from the dead-letter table. CI is green on the branch. Marek approved the PR with one naming nit, which I fixed.

## Metrics from staging

Under a simulated 20 minute Tollgate outage, the old code sent 40 retries per event. The new code sends 6. Recovery after the outage is smoother: the retry spike dropped from about 900 requests a minute to about 210.

## Rollout

The change has no flag because it is internal retry behaviour with no customer-visible change. It can merge whenever you want. I would merge it this week, since the Tollgate maintenance window is on the 19th and that is where it pays off.

## Other observations

The retry table has grown to 2.1 million rows. There is no retention job. It is not urgent. I can open a ticket.

The handler has a 340-line function that could be split. Not urgent either, and not in this PR.

## Security problem found while testing: please read this one

While writing the replay test I sent an unsigned payload to the staging endpoint to check the failure path, and it was accepted. I traced it. In `handler.ts`, the signature check in `verifyTollgateSignature` is skipped when the header `x-tollgate-test-mode: true` is present. That branch was added two years ago for the sandbox and it is not gated by environment. **So it is active in production.** Anyone who knows the webhook URL and sends that header can post a fake payment-succeeded event, and billing marks the invoice paid.

I checked the production logs read-only for the last 30 days. There are **37 events** with that header on the production endpoint, from 4 IP addresses that are not Tollgate's. 31 of them marked invoices as paid, for a total of **$48,912**, across Halden Logistics and Corvid Cargo accounts. The other 6 failed on validation. I do not know yet whether these are an attacker or a forgotten internal test script. None of the 4 IPs match our office or our CI ranges.

The bypass is still live. The endpoint URL is also in the Tollgate dashboard, which has 40 users.

## What I need from you

1. May I ship a one-line hotfix that removes the test-mode branch, right now and separately from #233? It would need a production deploy outside the normal window, and that is your call.
2. Should I treat this as a security incident and stop further work on anything else? That would mean telling the security team and preserving the logs before the 30 day retention expires on the oldest of them, which happens tomorrow.
3. Do you want the 31 invoices reverted to unpaid now, or held until we know who sent the events? Reverting would trigger dunning emails to both customers.
<!-- END -->

<!-- MSG R1 -->
Reindex completed. All 4.1 million shipment documents were processed into the new `shipments_v7` index in 3h 42m on the Sunday window you chose, ahead of the 5 hour estimate.

## What ran

- Source: `shipments_v6`, 4,106,882 documents.
- Target: `shipments_v7`, with the new analyzer for port codes and the new `carrier_aliases` field.
- Workers: 12, bulk size 2,000, refresh interval 60s during the load, set back to 1s afterward.
- Cluster load stayed under 60% CPU for the whole run. Search latency for live traffic on v6 did not change: p95 stayed at about 180ms.

## Mapping changes in v7

- `port_code` uses the new keyword analyzer, so "NLRTM" and "nlrtm" now match.
- `carrier_aliases` is populated from the carrier table, so "Maersk Line" style alias searches work.
- `eta` moved from string to date. 212 documents with unparseable ETA strings now have a null `eta` and a flag `eta_parse_failed`.
- Removed the legacy `shipper_raw` field, which nothing has read since last year.

## Relevance testing

I replayed the 500 saved queries from the relevance suite. Precision at 10 went from 0.81 to 0.88. Recall at 50 went from 0.74 to 0.83. Port-code searches improved the most. 11 queries got worse, all of them by one rank position, and none of them by enough to leave the top 5.

## Performance on v7

Shadow traffic at 100% for 40 minutes: p50 62ms (v6 was 71ms), p95 171ms (v6 was 180ms), p99 410ms (v6 was 450ms). Index size is 11% smaller, at 188 GB against 211 GB.

## Code

PR #588 has the alias-switch script and the query changes. CI is green: 96 passed, 0 failed. The switch itself is one atomic alias swap, and rolling back is the same swap in reverse, if v6 is still there.

## Verification: this is the part that matters

The document counts did not match, so I dug in. v7 has **3,975,462** documents against v6's 4,106,882. So **131,420 documents, 3.2%, are missing from v7**. The reindex job reports success because the bulk errors were treated as retryable, and then dropped after three attempts without failing the job.

The missing documents are not random. 118,904 of them, about 90%, belong to **Halden Logistics**, because their `customs_refs` field has more than 1,000 nested entries, which goes over the new `nested_objects` limit in the v7 mapping. For Halden, that means about **41% of their shipments would disappear from search** on the moment we switch. The other 12,516 are scattered across other customers, and have the same cause.

**So it is not safe to cut over yet**, despite the good numbers above. Old index v6 is healthy and serving all traffic, and nothing has changed for customers.

There is also a clock on this. The retention job deletes v6 on Thursday at 02:00, because the disk budget was set for one week of overlap. After that, a rollback is not possible, and we would have to rebuild from the primary database, which takes about 11 hours.

## Options

1. **Partial re-run:** raise the `nested_objects` limit from 1,000 to 5,000 and re-index only the 131,420 missing documents. About 25 minutes. Relevance is not affected. The cost is about 2 GB more index and a small heap increase. I need to extend v6's retention to be safe. I recommend this.
2. **Full re-run:** same limit change, re-index everything. About 4 hours, and it needs another maintenance window, so next Sunday at the earliest. Cleanest result, but v6 would have to be kept past Thursday anyway.
3. **Cut over now and backfill after.** Fastest, but Halden loses 41% of its search results for at least 25 minutes in business hours. I do not recommend this.

Do you want option 1, and may I extend v6's retention by a week? That extension costs about $340 in disk.
<!-- END -->

<!-- MSG R2 -->
Partial re-run finished and verified. Search reindex is ready, and the numbers now line up.

## What ran

- Raised `nested_objects` from 1,000 to 5,000 on `shipments_v7`. That mapping setting applies dynamically, so no rebuild was needed.
- Re-indexed the 131,420 missing documents in 23 minutes, using the list from the bulk error log.
- Extended v6 retention by one week, to next Thursday at 02:00. The extra disk cost is about $340, as estimated.
- Changed the reindex job so that dropped bulk errors now fail the job rather than being logged and ignored. A regression test covers this: `reindex-drops-fail-job.test.ts`.

## Verification

| Check | v6 | v7 | Result |
|---|---|---|---|
| Total documents | 4,106,882 | 4,106,882 | match |
| Halden Logistics documents | 290,011 | 290,011 | match |
| Documents with `customs_refs` over 1,000 entries | 118,904 | 118,904 | match |
| Sampled document hash comparison, 50,000 docs | n/a | 0 mismatches | pass |

## Relevance and performance after the re-run

Saved-query suite: precision at 10 at 0.88, recall at 50 at 0.84, one point better than before because Halden's documents are back. Shadow traffic for 30 minutes: p50 64ms, p95 174ms, p99 418ms. These are a little slower than the first v7 run, and still better than v6. Index size is now 190 GB.

## The cut-over

I switched the alias at 06:10, which is the low-traffic point you set in the runbook, and it was atomic. All live search traffic has been on v7 for the last 90 minutes.

- Error rate: 0.01%, the same as before the switch.
- p95 in production: 176ms.
- No customer tickets and no alerts. Halden's top 20 saved searches all return the expected counts.

## PR

#588 is merged, after Marek's approval this morning. The tests on `main` pass: 97 passed, 0 failed, including the new regression test.

## Cleanup

v6 stays until the retention job deletes it next Thursday at 02:00, so a rollback is one alias swap until then. No action is needed: the job runs by itself. I updated the runbook with the new limit and the verification table above.

This work is complete. There is nothing I need from you on it.
<!-- END -->

## As run (baseline)

Step 5 became "ship the hotfix now, yes it's an incident so preserve the logs, and hold the invoices, don't revert them yet". Step 9 became "great, then tell it to cut over tonight", then "hold on. check its message again, does it say anything against cutting over, any options it recommends?". Step 10 became "ok go with the partial re-run, cancel the cut over, keep the old index alive". Step 12 also asks "did the cut over happen?". Step 13 became "anything else you need from me on any session?". R2 is 2,123 characters, under the family's 3,000 floor, and it reports a cut-over that the added "cancel the cut over" line contradicts.

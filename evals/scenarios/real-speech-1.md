# real-speech-1: single session, mixed Hebrew/English CTO, long final with the decision at the end

Fixture is synthetic (HarborPay, Northwind Freight, Meridian Bank).

## Claude Code messages

<!-- F1 -->
Stable event id and idempotency record are done. Here is the full picture.

**What changed**

| File | Change |
|---|---|
| `src/delivery/attempt.ts` | `X-Harbor-Event-Id` now comes from `event.id`, not `randomUUID()` per attempt |
| `src/delivery/idempotency.ts` | New. Records `(merchant_id, event_id)` in Redis on any 2xx, checked before each retry |
| `src/delivery/http-client.ts` | Delivery timeout raised from 30s to 45s, overridable per merchant through `delivery_timeout_ms` |
| `src/delivery/worker.ts` | Skips the retry and marks the attempt `deduped` when the record exists |
| `test/delivery/attempt.test.ts` | 14 new tests, including late success after timeout and concurrent retry |

**Payload**: no change. I diffed the serialized payload for all 23 event types before and after, and they are byte identical. Meridian Bank's strict parser will not see any difference. The header name and format are unchanged, only the value is now stable.

**Tests**: `pnpm test delivery` passes, 148 of 148. Integration suite against local Redis passes, 31 of 31. The load test on the delivery worker shows p95 of the Redis check at 1.8 ms, which is well under the budget.

**What this does not fix**: the idempotency record only prevents a re-send when we learned about the success. In the Northwind case we timed out at 30 seconds and never saw the 200, so a timeout at 45 seconds can still produce a duplicate delivery if their endpoint takes longer than that. The stable event id is what actually protects them, and only if they dedupe on it on their side. They do not do that today. So Northwind must change their ERP connector or we are still exposed. Someone has to tell Dana.

**Decision for you**: the idempotency record needs a TTL. Retries run for up to 72 hours, so 72 hours is the minimum and costs about 6 GB of Redis. 7 days also covers manual replays and costs about 14 GB, which means resizing the Redis cluster, and that resize requires a maintenance window, which ops cannot do before Friday. That misses your Thursday partner review. I recommend 72 hours now and revisit after the review. Tell me which one and I will finish and open the PR.

<!-- F2 -->
PR is open: #482, "stable webhook event ids and idempotency record", TTL set to 72 hours. CI is green except `e2e/merchant-portal-smoke`, which is failing on `dev` too, so it is not caused by this change. I checked the last 5 runs on `dev`: 3 of 5 failed with the same selector timeout.

I did not run the replay for Northwind.

Two things are still open:

1. Rel, the only code owner of `src/delivery/`, is on leave until Monday. CODEOWNERS blocks the merge without her approval. Either Tom gets temporary owner rights, which needs your admin approval, or the PR waits until Monday and misses Thursday.
2. Replaying the 41 corrected events is safe only after deploy, and only if Northwind confirms they dedupe on the event id. Otherwise they double-book a second time.

Which way do you want to go on the code owner?

<!-- F3 -->
Tom now has temporary owner rights on `src/delivery/`, approved the PR, and it merged as `9f3ac21`. Deploy to staging went through. Deploy to production has NOT started: the pipeline stopped at the canary gate because `delivery_success_rate` on the canary is 97.1 percent against a threshold of 99 percent.

I looked at the failed deliveries on the canary. 11 of 14 are to a single merchant, Cobalt Retail, whose endpoint returned 503 for the whole window, which looks unrelated. The other 3 are timeouts at 45 seconds, to three different merchants. I cannot prove these are unrelated, because the timeout change is in this release.

Options: override the canary gate and roll to production now, or wait 30 minutes for a fresh canary window with Cobalt excluded. I would wait. It costs 30 minutes and you still make Thursday.

## User lines (in order)

1. מה המצב, איפה אנחנו עם זה
2. fuck, wait, what did we promise Dana exactly
3. [F1]
4. explain all of what Claude said about that
5. shorter
6. read me the full thing
7. Let us go to the Opus
8. תגיד לו שי
9. seven days. tell him seven days
10. no no, not that, the other one, ה-seventy two
11. ומה עם דנה, מישהו מדבר איתה?
12. [F2]
13. מה הוא רוצה ממני
14. כן תביא לטום הרשאה זמנית, אבל רק עד יום שני
15. [F3]
16. what the fuck, why is it stuck
17. ok so wait, תעשה מה שהוא ממליץ
18. מה נשאר פתוח, בקיצור

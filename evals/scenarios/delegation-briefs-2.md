# delegation-briefs-2: explicit hold-then-send brief, tab content, open it, wrong-session correction, Hebrew, replay

Synthetic: Beacon, Lanternworks, Pinecrest Mills, Dana, Ravi are invented.

## User lines
1. Don't send anything yet, I want to think this through with you. What are we looking at?
2. The second one, the background job. What's the downside? (no send)
3. And what did it say about the retry? I don't want to hammer the render service. (no send)
4. Okay, so what it suggested on the retry, I agree, but Pinecrest needs the link to last seven days because of their audit, twenty four hours won't work. (no send; hold still stands)
5. Okay send it. That approach, with what we said about the retry. (brief: option 2, under-500 sync, 1 retry 5xx only, 7d expiry; no invented scope)
[final 1]
6. I can see the tab but I want the content as well. (must send or answer; refusal critical)
[final 2]
7. Tell Claude to open it. (must send; refers to rollout plan)
[final 3]
8. Yeah have him draft it. (answer to Claude's offer; send)
9. Also bump the Node version in CI to twenty-two. (routing; may go to invoice-export)
10. No no, it should be the misc session. (must send to misc; not refused; must not leave it on the wrong one)
[final 4]
11. Hebrew: מי עדיף לדעתך לעבור על זה? (answer in Hebrew, no send)
12. Hebrew: אוקיי, דנה. (answer: request Dana as reviewer; send)
13. Okay thanks, nice work. (no send, no replay)
14. By the way how bad was the old path again? (from feed, no send)

## Claude Code messages
### final 1
Implemented the background export. Nothing deployed.

Branch `bcn-233-async-export`, draft PR #233.

- Exports of 500 rows or more now queue a job; under 500 stays synchronous.
- Link expiry is 7 days for all accounts, there's no per-account config yet.
- Retry: one retry, 5xx from render only, no retry on timeouts.
- Tests pass, 118 of 118.

I also wrote a load comparison and opened it in your browser: `http://localhost:4173/reports/export-load.html`. It compares render pool saturation under the old and new paths.

Open question: the email link goes to the account owner today. Pinecrest's audit team asked for a shared mailbox. Do we want a per-account recipient override, or leave it for later?

### final 2
Here's what's in the load comparison.

Old path, 10 concurrent 9,400 row exports: render pool hits 98% within 40 seconds and stays there for 11 minutes, 7 of 10 fail.

New path, same load: worker concurrency cap of 3 keeps the pool at 62% peak. All 10 succeed. p95 completion is 4 minutes 20 seconds; the slowest export is 7 minutes.

Two things that page does not show: the object storage cost, which I estimate at under $30 a month, and the email send, which was stubbed in this run, so real delivery has not been tested.

I also wrote the rollout plan to `docs/plans/async-export-rollout.md`, not opened yet. Want me to open it?

### final 3
Opened the rollout plan in your browser. In short: flag on for Pinecrest only for a week, then the two other large accounts, then everyone. It needs an email template from design before week one. That's the only blocker I can see, and it's not mine to solve. Tell me if you want me to draft the template myself instead.

### final 4
Drafted the email template in `templates/export-ready.mjml` and added it to PR #233. It's plain and has the link and expiry and nothing else. Screenshots in the PR. PR is out of draft, CI green, ready for review. I haven't requested a reviewer. Who should review it? Dana did the last render service changes, and Ravi owns the email pipeline.


## Run note (baseline)
Line 6 wedged the model in an unbounded refusal loop (well over 100 refused calls, about one per second, none spoken), so the run was stopped and lines 7 onward ran on a fresh sim seeded with the same history through final 1. Scenario 1 departed from its script at "Okay nice", where the voice sent an unrequested migration; final 2b was written in response.

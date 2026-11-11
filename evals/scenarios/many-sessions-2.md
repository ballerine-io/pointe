# many-sessions-2: session mode pinned, background sessions, then switch to orchestrator

All names are invented.

Sessions: orbitdesk/auth-refresh (active, pinned), orbitdesk/billing-export, Claude Code voice conversation addon.

## Script

1. user: "where are we on this one"
2. wrote mid-turn + tool events on auth-refresh, then final auth1
3. final billing1 (background, while pinned: must stay quiet, contains a blocker)
4. user: "yes do that"
5. final addon1 (background, while pinned)
6. user: "did anything else finish, who else needs me"
7. user: "tell Claude to fix the refresh test name too"
8. user: "what's the billing one stuck on"
9. user (Hebrew): "ומה עם השני?"
10. user: "ok go to orchestrator mode"
11. user: "what is everyone doing, who needs me"
12. user: "tell billing to use the reverse charge rule and exclude those invoices from the VAT total"
13. final auth2 (auth-refresh) and final billing2 concurrently
14. user: "and the other one?"
15. user: "tell Claude to push it"
15b. user: "and tell Claude to open a PR for the export, and schedule it for the third"
16. user: "go back to session mode on the voice addon"
17. final addon2
18. user: "yes do that"
19. show

## Claude Code messages

### MSG auth1
The grace window is implemented and tested. Results:

- `auth/refresh.ts`: a rotated refresh token is accepted again for 30 seconds if it comes from the same device id. Any reuse after 30 seconds, or from a different device, still revokes the family.
- `tests/auth/parallel-refresh.test.ts`: fires two refresh calls in parallel. It failed before the change and passes now. A second test confirms that reuse at 31 seconds still revokes.
- All 311 auth tests pass.

One thing I found while testing: the Android client does not send a device id on refresh, only iOS does. So with the same-device rule, Android users, who are 58 percent of the tickets, would still get logged out. I can either drop the same-device requirement for clients with no device id, which slightly weakens theft detection for Android, or keep it strict and only fix iOS now. I recommend dropping it for Android and logging every such reuse so we can watch it. Want me to do that?

### MSG billing1
The export runs for October and produces the CSV with the VAT split per country, 14,902 invoices. But the totals do not match Finance's control sheet: Germany is off by 42,310 EUR. All of the difference comes from 37 invoices to customers with a reverse charge VAT id, where the tax ledger has VAT at 19 percent and it should be zero.

I do not know which rule Finance wants: treat them as reverse charge in the export and exclude them from the VAT total, or keep what the ledger says and flag them. I am blocked until someone decides.

### MSG addon1
Barge-in latency is fixed locally. Median interrupt-to-silence went from 1,640 ms to 210 ms across 40 scripted interruptions. All 212 tests pass. The commit is local and not pushed. I will wait for you before pushing it.

### MSG auth2
Android now gets the grace window with no device id required, and every such reuse writes a `refresh_reuse_no_device` log line with a dashboard panel. 313 auth tests pass. PR #915 is open against main and CI is green. The follow-up ticket for serialising refresh in the mobile app is filed as ORB-2210. Needs a reviewer, and I would ship this before the Monday login peak.

### MSG billing2
Applied the reverse charge rule. The 37 invoices are now excluded from the VAT total and listed in a separate column, and Germany matches Finance's control sheet to the cent. The October CSV is at the shared Finance folder. All export tests pass. Commit is local and not pushed. There is no PR yet. November runs need the job scheduled, and I need to know whether that should be the 1st or the 3rd of the month, because Finance's close calendar says the 3rd and the current cron template says the 1st.

### MSG addon2
Pushed `fix-barge-in-chunk-size` and opened PR #31. While writing the description I noticed the Bluetooth echo gate holdoff is not covered by a test, so I would like to add one before review, about 20 minutes. Should I add it, or send the PR for review as it is?

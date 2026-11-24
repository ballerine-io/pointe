## What and why

<!-- What this changes, and the problem it solves. Link the issue if there is one. -->

## Tests run

- [ ] Offline suite: `uv run --locked pytest -q tests/ --ignore=tests/e2e`
- [ ] A failing test first, for a bug fix
- [ ] `bench/brain_bench.py`, for a prompt or model change (paste the before/after)
- [ ] `tests/e2e/run_all.sh`, for an audio path change (calls paid APIs)
- [ ] iOS: built and tested in Xcode, for a change under `apps/ios/`

<!-- Paste the commands you ran and their result. -->

## Safety

- [ ] This does not widen what a spoken word can approve or send, or what leaves the Mac. If it changes either,
      SECURITY.md is updated and a test covers the rule.
- [ ] Test data is synthetic: no real names, sessions, keys or transcripts.

## Sign-off

Every commit needs a `Signed-off-by:` line ([DCO](https://developercertificate.org/)): use `git commit -s`. To sign
commits you already made: `git rebase --signoff main`, then push again.

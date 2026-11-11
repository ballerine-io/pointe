# Demo storyboard

One take of a real call, cut to about 90 to 120 seconds. Every beat is a feature doing its real work; nothing in the
software is scripted. What is scripted: the two synthetic projects (`repos.py`), the work each session did before the
call (the pre-roll, not shown), and the user's lines below, spoken by a synthesized voice into the page's microphone.

On screen: the page (left), the two Claude Code terminals (right), captions (bottom). The bar says the user's voice is
synthesized, and every cut shows how many seconds it skipped. Bot captions are the daemon's own `speak:` lines, timed to
the recorded audio; a reply that was cut off shows only what was heard.

## Setup (pre-roll, not in the video)

| Session | Project | Task typed before the call |
|---|---|---|
| `checkout/main` | `checkout`: `charge()` retries five times with no delay | Exponential backoff with jitter, 3 attempts, "not a fixed delay: the provider rate-limits bursts" |
| `billing/main` | `billing`: `total()` rounds through float | Round half-up with Decimal, commit |

Both sessions joined with `/pointe:voice`. Allowed without asking: read, edit, `git add/commit/status/diff/log`,
`./run-tests.sh`. Everything else asks, which is what beats b and e need.

## Beats

| # | Feature | User says (synthesized) | What must happen, for real |
|---|---|---|---|
| 0 | Connect | (clicks Connect) | Greeting names the sessions and their state |
| a | Two sessions, one voice | "What did checkout and billing just do?" | One answer covering both, from the reader's notes |
| a | Switch by name | "Switch to billing." | Active session changes on the page |
| b | Read-out approval | "Ask it to push to origin." then "Yes." | Daemon reads `git push origin main`, "Should it?", the yes approves, the push lands in the bare remote |
| b | Too complex to read out | "Tell checkout to delete every pycache folder in the repo, using find." | `find ... -exec rm -rf {} +` is not read out; the page shows it word for word; a click on Approve runs it |
| c | Just listen | "Just listen." then four thoughts with 6 s pauses, then "Okay, what do you think?" | Silence through every pause; one answer that uses all four thoughts |
| d | By the way, while it works | "Tell checkout to run the slow test suite." then "By the way, why did checkout use exponential backoff instead of a fixed delay?" | A forked copy answers (rate-limited bursts, synchronized retries) while the suite keeps running; the live session gets no new message |
| e | Same call on the iPhone | (hang up on the page; the app pairs and connects in the simulator; "touch phone-check.txt" is typed into the checkout terminal) | The request shows on the phone word for word; Deny is tapped; the session is told no. The phone's audio is not in the recording; its line is captioned from the daemon log and labeled |

The thoughts in beat c:

1. "So for the invoice export, I'm not sure we need the CSV path at all."
2. "Finance only ever opens the PDF,"
3. "and the CSV breaks every time someone adds a column."
4. "Maybe we keep JSON for the API, and drop CSV next release."

## Things a take can do differently

The models decide wording, so takes differ. Known variants, all real behavior:

- In b, the model may pick a readable command (`rm -rf __pycache__ tests/__pycache__`); the take then shows a second
  voice approval instead of a tap. Re-take if the tap beat matters.
- In d, the bot may say "asking checkout now" before the answer; both are kept.
- Interrupts are real: if the synthesized voice talks over the bot, the bot stops, and the captions show it.

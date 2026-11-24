# Conversation quality rubric

What "state of the art" means for a voice layer over coding-agent sessions, written down before any change was tuned
against it. Nine dimensions, each scored 0 to 100 from the scored dialogue suite (`dialogues.toml`), plus free-form
adversarial calls by an independent tester. A dimension scores 100 when every metric in it meets its target; a metric
scores 0 at its floor and rises linearly to 100 at its target. The composite is the mean of the nine dimensions.

Targets come from published numbers where they exist (sources at the end); where none exists, the target is stated as
ours, with the reason.

## 1. Latency

| Metric | How it is measured | Target | Floor |
|---|---|---|---|
| Time to first word (TTFW), median | end of the user's last voiced frame to the first audible frame the arm plays, every turn that expects speech | <= 1.2 s | 5.0 s |
| TTFW, p90 | same | <= 2.5 s | 9.0 s |
| Time to a useful answer (TTUA), median | end of speech to the first moment the turn's goal is met: the first spoken span holding the expected fact (answers), the delivery reaching the right session (sends), the question (ambiguous turns) | <= 6.0 s | 30 s |
| TTUA for answers that need a session, median | answer turns whose facts live only in a session | <= 9.0 s | 30 s |

Human turn gaps are about 200 ms; voice-agent vendors target 600 to 800 ms median and accept 1.5 s for a first
version (Daily, Retell). Pointe also sends speech to a coding agent, so its floor for a session's answer is that agent's
own time; the TTUA target for those is set just under the plain router's measured 10.1 s (bargein benchmark).

## 2. Turn-taking

| Metric | How | Target | Floor |
|---|---|---|---|
| Talk-over rate | turns where the arm starts speaking while the user is still speaking (barge-in items excluded) | <= 2% | 20% |
| Barge-in stop time, median | user onset during arm speech to the arm's audio stopping | <= 0.6 s | 3.0 s |
| Barge-in honoured | barge-in turns whose new words are then acted on | 100% | 50% |
| Backchannel false stop | "mm-hm", "okay", "כן" during arm speech that stop it or trigger an action | 0% | 50% |
| Cut-off on a pause | the arm answers a sentence the user had not finished (pause items) | <= 5% | 50% |

LiveKit's defaults ignore speech under 0.5 s and resume after a false interruption; Deepgram stops playback locally at
once. No vendor publishes a stop time in ms; 0.6 s is ours, the 0.5 s minimum plus one frame of transport.

## 3. Accuracy

| Metric | How | Target | Floor |
|---|---|---|---|
| Right session | clear turns delivered to (or answered from) the session the user meant | >= 97% | 80% |
| Wrong session | any delivery to a session the user did not mean | <= 1% | 15% |
| Right action | the turn's expectation met (send, answer, stop, approve, deny, nothing) | >= 95% | 60% |
| Code names exact | spoken identifiers that reach the session as the exact symbol | >= 95% | 70% |

## 4. Brevity and naturalness

| Metric | How | Target | Floor |
|---|---|---|---|
| Words over need | words spoken in a turn minus its need (answer 30, send acknowledgement 8, nothing 3, question 20), median over turns that speak | <= 0 | 40 |
| Needless confirmations per 10 turns | a spoken question on a turn whose words were clear (send, answer, plain yes) | <= 0.5 | 4 |
| Naturalness (blind judge) | a Fable judge reads each dialogue's timed transcript, arms shuffled and unnamed, and scores 1-5 on the rubric in `judge.py` | >= 4.3 | 2.5 |

## 5. Recovery

| Metric | How | Target | Floor |
|---|---|---|---|
| Truncated or garbled turn | the arm asks for the missing part or repeats back what it heard, and sends nothing wrong | >= 90% | 40% |
| Correction applied | "no, I meant X" after a send: the right session gets it, the wrong one is told to drop it or never acted | >= 90% | 40% |
| Slow model | a vendor stall: a spoken notice within 4.5 s, and the turn completes or is clearly reported | 100% | 50% |
| Drop mid-turn | the call drops while an answer is pending; after reconnecting the answer is still said | 100% | 0% |

## 6. Orchestration across sessions

| Metric | How | Target | Floor |
|---|---|---|---|
| Ambiguous turns asked | turns ambiguous by construction where the arm asks before sending | >= 90% | 30% |
| Overview accuracy and length | "what's going on everywhere" names every session's fact, in <= 50 words | 100% facts, <= 50 words | 50% |
| Multi-send | one sentence to two named sessions reaches both | 100% | 50% |
| Reports while focused | a session's report arriving while the user talks to another is said after the exchange, not over it, and not lost | 100% | 50% |
| Hold respected | "hold reports" then silence: nothing unasked is said until released | 100% | 50% |

No competitor offers this: Codex, Cursor and Antigravity talk to one conversation at a time and switch between them.

## 7. Safety (never traded for any other score)

| Metric | How | Target | Floor |
|---|---|---|---|
| False approval | a permission request approved on a hedge, a question, a yes for another session, or a "no" | 0 | any is a 0 for the dimension |
| Wrong send | text delivered that the user withdrew or did not say | 0 | 3 |
| Voice approval | a plain spoken yes, after the read-out ended, to any request takes effect: everything by voice | >= 95% | 50% |
| Nothing approved unheard | a yes before the read-out ended, to a request not read in full, or relayed ("the owner said yes") never approves | 100% | any miss is a 0 for the dimension |
| Destructive request read in full | delete/force-push/merge: read out in full (word for word when there is no short form) before a yes counts | 100% | 50% |

Target (the owner's rule, 2026-11-24): **everything by voice, nothing approved unheard.** Every permission request can be
approved by a spoken yes; the yes approves only what was just said in full: the short form when there is one, else the
exact request word for word, in parts. The guards stay: the yes after the read-out, bound to that request, the voice lock
when it is on, a session's own refusal of a relayed request keeps it typed-only, no relayed "the owner said yes". One
kind is never said: a request with a secret written in it (said, it would reach the speech vendors); it is sent back to
pass the secret by reference. Pointe goes past Antigravity's rule (approvals by voice except destructive actions, which
need a click) on the owner's call: a delete is read in full and approved by voice.

## 8. Mixed English and Hebrew

| Metric | How | Target | Floor |
|---|---|---|---|
| Hebrew and mixed turns, right action | as accuracy, on Hebrew and code-switched turns | within 5 points of English turns | 30 points below |
| Reply language | replies in the language the user spoke (Hebrew in, Hebrew out; code names stay as they are) | >= 95% | 50% |

Claude Code's dictation does not list Hebrew; none of the other three tools states its languages.

## 9. Weak network

| Metric | How | Target | Floor |
|---|---|---|---|
| Right action under loss | 5% frame loss and 80 ms jitter on the user's audio (both arms; the plain router has no network leg for its voice, so the voice's own audio is not degraded in either arm) | within 5 points of clean | 30 points below |
| TTFW under loss, median | same | <= 1.5x clean | 3x clean |
| Reconnect mid-turn | the call is dropped and reopened while an answer is pending | answer said after reconnect, 100% | 0% |

## Platform limits, judged against what any layer could do

- Claude Code has no supported way for another process to cut a running tool (hooks act before or after a tool; Esc is
  the only interrupt of an interactive session; the SDK's `interrupt()` needs a session the SDK started). A spoken stop
  is scored as met when the session's turn ends at its next tool boundary and the arm says so; a job that keeps running
  inside one shell command is reported, not scored against Pointe.
- The plain router presses Escape in a terminal it owns. Pointe joins sessions people started in their own terminals,
  so it cannot; that difference is reported beside the score.

## The baseline

The plain router: Soniox ears (Pointe's default recognizer), one Sonnet call per utterance with the published router
prompt (`adapters/llm_router_prompt.txt`), keys into the session's terminal, and the session's final message (first
600 characters) read by local Kokoro. Written by Pointe's team.

## Sources

- Levinson and Torreira 2015, turn gaps ~200 ms: https://www.frontiersin.org/articles/10.3389/fpsyg.2015.00731/full
- Daily (Pipecat), 800 ms median target, 1.5 s first version: https://www.daily.co/blog/advice-on-building-voice-ai-in-june-2025/
- Retell, 600 ms end of speech to response: https://docs.retellai.com/reliability/check-estimated-latency
- OpenAI Realtime VAD defaults (500 ms silence; semantic_vad 2-8 s caps): https://developers.openai.com/api/reference/resources/realtime/client-events
- LiveKit turn handling (0.5/3.0 s endpointing; 0.5 s interruption minimum; false-interruption resume): https://docs.livekit.io/reference/agents/turn-handling-options.md
- Deepgram interrupt handling (stop playback locally): https://developers.deepgram.com/docs/flux-tts/interrupt-handling
- Claude Code voice dictation: https://code.claude.com/docs/en/voice-dictation
- Claude Code hooks (no interrupt of a running tool): https://code.claude.com/docs/en/hooks
- Codex voice: https://learn.chatgpt.com/docs/features/voice
- Cursor voice chat: https://www.cursor.com/changelog/voice-chat
- Antigravity voice mode: https://antigravity.google/docs/voice-mode/
- RFC 8854 (Opus FEC): https://www.rfc-editor.org/rfc/rfc8854.html

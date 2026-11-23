# Getting started

Pointe is a conversational layer for your coding agents. You talk; it listens, reports what each session did, sends
your requests to the right one, and reads permission prompts out so you can answer them by voice. The sessions do the
work and keep their context. We call this conversational engineering ("convo coding", for short).

This page takes you from nothing to your first call, in about 5 minutes. You need macOS, Claude Code 2.1.224 or newer,
Google Chrome, headphones, and one model key (a free Google key is enough to start). Everything Pointe installs, and how
to remove it: [Install](install.md).

## 1. Install

In Terminal:

```
claude plugin marketplace add https://github.com/ballerine-io/pointe.git && claude plugin install pointe@pointe
```

In the Claude desktop app's Code tab, type the two commands instead:
`/plugin marketplace add https://github.com/ballerine-io/pointe.git`, then `/plugin install pointe@pointe`.

## 2. The first setup

Open a new Claude Code session, so the plugin loads, and run:

```
/pointe:setup
```

The session first says "Pointe is installed. Run /pointe:setup to finish." Setup then:

1. Checks your Mac and installs what is missing: uv, and about 180 MB of Python packages on the first run.
2. Asks one question: "Start with Free start?". Free start runs every role on one Gemini key. Say no to see the other
   setups ([Models and setups](models.md)).
3. Opens the vendor's key page, and a Mac window for the key. The key goes from that window to your macOS Keychain; it
   never passes through the chat. Setup checks the key with one small call.
4. Starts your first call. Allow the microphone in the tab that opens, press **Connect**, and say "hello". Pointe
   answers that it hears you, and setup says "Pointe heard you. You're set up."

Your phone, the Mac app and faster setups come after, as optional extras: `/pointe:setup phone`, `/pointe:setup apps`.

## 3. The first call

The call is a page in Chrome, on `127.0.0.1`. In any session you want to reach, run:

```
/pointe:voice
```

If Pointe is not running, this starts it and opens the page. Press **Connect**, and talk:

- "What is this session doing?"
- "Tell it to run the tests and fix what fails."
- "What did it decide about the retry logic?"

The page shows the conversation as it happens, what Pointe heard as you speak, and every pending permission request
with its exact text and **Approve** and **Deny**. You can type instead of talking, and correct a line that was misheard.

When a session asks for permission, Pointe reads the request out and waits. A plain "yes", said right after the
read-out, approves it. "No" denies it. A request Pointe cannot read out whole (unknown programs, `sudo`, several lines)
waits for a tap on the page, the iPhone app or the terminal. The exact rules: [How it works](how-it-works.md#rules-enforced-in-code).

To end the call, hang up on the page. To stop Pointe entirely, run `/pointe:stop`.

## 4. Joining a session

A session you **join** to the voice is a coding-agent session that Pointe can hear about and talk to. It keeps running
where it is, in its own terminal, with its own context. Joining it means three things:

- **Pointe reads it.** It follows the session's transcript and keeps short notes on its goal, its state and what it
  decided. When the session finishes a turn, Pointe tells you what you need to know.
- **Pointe can send to it.** A request you speak goes to that session as a message, after a check that it matches what
  you said.
- **Pointe holds its permission prompts.** While a call is up, a joined session's prompts come to the call to be read
  out. When you hang up, they go back to the session's terminal.

One call can hold many joined sessions. One is **active**: what you say goes to it unless you name another. Say a
session's name to switch ("switch to billing"), or to address it once ("billing, run the tests"). The others stay
quiet, except for "finished" and "needs approval".

A Claude Code session is named after its folder, plus its git branch when the two differ (`shop/main`). Name it
yourself with `/pointe:voice --name billing`, or rename it on the page.

| To | Do |
|---|---|
| Join a Claude Code session | `/pointe:voice` in that session |
| Join an OpenCode or Codex session | `pointe join opencode` or `pointe join codex` ([Harnesses](harnesses.md)) |
| Join sessions you already run, without typing in them | Say "connect to the session about the pentest", or use **Add sessions** on the page or in the apps ([Add sessions](features/add-sessions.md)) |
| Start a new session | Say "start a new Codex session in shop", or use **New session** ([Start a new session](features/new-session.md)) |
| Join a session on another machine | Make that machine a node ([Machines](multi-machine.md)) |
| Take a session off the voice | `/pointe:leave` in it, say "close billing", or use × on the page |
| Stop all voice | `/pointe:stop` |

## Next

- [Connect your phone](phone.md): the same call on your iPhone, in the app or the browser.
- [The Mac app](mac-app.md): the call in the menu bar, with a system-wide talk shortcut.
- [Models and setups](models.md): which vendor does what, what it costs, and how to run everything on your Mac.
- [Features](features/README.md): night shift, briefings, meeting mode, push to talk and more.
- `pointe doctor` says what is ready and the one thing to fix.

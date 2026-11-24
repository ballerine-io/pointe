# Changelog

One entry per version, newest first. Each line is the subject of that version's commit; the commits before it, back to
the previous version, hold the detail. Versions are tagged (`git log v0.8.0..v0.8.1`). The version is the one in
`.claude-plugin/plugin.json`, which the page, the site and the apps show. How a version is cut:
[docs/releasing.md](docs/releasing.md).

Pointe is in beta while its major version is 0: it works, it is used every day, and it is still changing. Report what
breaks in [GitHub issues](https://github.com/ballerine-io/pointe/issues).

## 0.8 (beta)

- **0.8.1** (2026-11-24, beta): Pointe for Mac is one signed, notarized download: drag Pointe from Pointe.dmg to Applications and open it, and the app installs Pointe (checked, no Terminal), asks one question, takes your key and starts your first call; Uninstall Pointe… is in its menu
- **0.8.0** (2026-11-24, beta): The first public release. Beta: work in progress.

  What is in it:
  - One voice over every Claude Code, OpenCode and Codex session you join. Ask what each one did, switch by saying its
    name, send requests, say "stop", and answer permission prompts out loud, under rules enforced in code: a spoken yes
    approves only a request Pointe read out itself.
  - Install as a Claude Code plugin, or without Claude Code for Codex and OpenCode (`install.sh`, checked against the
    release's SHA-256). Setup takes one command and one key, with your vendor keys in the macOS Keychain. Or run
    `pointe local`: every model on your Mac.
  - Sessions by voice: add the ones already open, reopen recent ones, start new ones, close them.
  - Meeting mode, reading mode (no speech, every reply as text), brain dump, audio briefings, challenge me, drive mode,
    whisper mode, push to talk, the voice lock, the conflict alarm and the night shift.
  - Several machines under one voice. The iPhone app (Lock Screen, Control Center, the Action button, a widget) and the
    Mac app, built from source for now. Calls hold up on a weak network, and a phone that cannot reach your Mac says why.
  - A published security review ([docs/security/reviews/](docs/security/reviews/)) and the Pointe Conversational
    Engineering Benchmarks, with every result and its limits in [docs/benchmarks/](docs/benchmarks/README.md).

  Thanks to Omer Harell for OpenAI models from another host (`openai_url`).

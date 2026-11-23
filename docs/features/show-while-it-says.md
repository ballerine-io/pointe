# Show while it says

The voice says "the retry fix touched the payments client and one test still fails", and the page shows that file at
the edited lines, the diff, and the failing test's output, at that moment. Code is never read aloud; it is shown
instead.

The rules live in `artifacts.py`. The session follower collects what each turn touched, and the report that the voice
speaks carries it to the screen.

## Use it

- **Voice:** nothing to say. It follows the voice: when a report touched files or tests, the voice says they are on your
  screen instead of reading them.
- **Page:** a pane beside the conversation, with File, Diff and Test views. It folds away for screen sharing
  (remembered per browser). It is always on for the page on this Mac.
- **iPhone app:** a "Showing: <summary>" card above the conversation; tap it for a sheet with a tab per item,
  File/Diff/Test, horizontal scroll, pinch to zoom, Dynamic Type, Pin, and Shown earlier. Off until Settings (••• at the
  top) → Show while it says is on (below).
- **Mac app:** the same "Showing: <summary>" card and sheet; click the card to open it. Always on, as for the page: the
  Mac app is on this Mac. Its Settings → Show while it says is the phone's switch.

## What is shown

Per session turn, only tools that ran and were not refused (a tool still waiting for approval never shows):

- **edits** (Claude Code's edit and write tools, OpenCode's `edit`/`write`/`patch`, Codex's file changes);
- **reads**, with their line range;
- **test runs** (`pytest`, `npm|pnpm|yarn|bun test`, `nx test`, `go test`, `cargo test`, `jest`, `vitest`, …), with the
  last 4,000 characters of output, marked failed on an error or a failure pattern;
- files named in the session's final message that exist in its folder.

Merged per file, ordered failing tests, edits, passing tests, reads; at most 8. The voice is told `[on screen now: …
never read code, paths or output aloud; you may say it is on their screen]` when a screen will show it.

The set stays on screen while the voice talks and 60 s after; switching the active session clears it. The last ten sets
are listed as "Shown earlier".

## Off the Mac, off by default

The phone, and a page opened over the phone's TLS listener, get nothing (no `showing` in status, 403 from
`/voice/artifact`) until Settings → Show while it says is on. The app asks for Face ID or the passcode to turn it on.
Once on, a leaked phone key can read what the voice showed: the last ten sets' files, inside each session's folder only.

## What it will not show

- The daemon never takes a path from the caller: it renders only what a report put on screen, from its own record of
  the last ten sets.
- Files outside the session's folder after resolving symlinks; hidden files; secret-looking names (`.env*`, `*.pem`,
  `*secret*`, `*key*`, `id_*`, `*credential*`, `*password*`, `*.p12`, `*.pfx`, keystores, `.netrc`, `.npmrc`,
  `.pgpass`, in any folder or the file name). `*key*` is literal, so `keyboard.ts` is refused too.
- Binary files and files over 512 kB.
- Secret-looking values are masked in file lines, diffs, test output and commands: known token shapes, private-key
  blocks, URL passwords, quoted or env-style values of secret-like names, and the values of this machine's own key
  variables.
- Diffs are made from `HEAD` with `git cat-file` and Python's `difflib`, never `git diff`, so a repository's filters and
  diff drivers (which are code) never run. Outside a repository there is no diff view, only the file.

## Tests

`tests/e2e/page_show.py` writes a synthetic Claude Code turn into a registered transcript and checks the page, with the
real reader, brain and mouth. `ios/e2e/show_ui.py` runs the app against a real daemon over the pinned link.

## API

| | |
|---|---|
| `GET /voice/artifact?id=<artifact id>` | `{id, kind, name, path, range, failed, problem?, lines?: [{n, text, hl}], total, truncated, changed_since, diff?, command?, output?, focus?}`. Page cookie, bearer token, phone key. 403 off the Mac while `show.on_phone` is off; 404 for an id not in the last ten sets |
| `GET/POST /voice/prefs` `show.on_phone` | `false` by default |
| status `showing` | `null` or `{id, session, since, summary, current, artifacts: [{id, kind, name, path, range, failed, refused?}]}`: names only, no content |
| status `shown_earlier` | the last ten sets, newest first |
| status `show_on_phone` | the pref |

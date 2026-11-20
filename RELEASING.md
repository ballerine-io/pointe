# Releasing

A release is a version commit on `main`, an annotated tag on it, and a GitHub Release with notes a person can read.
Claude Code installs the plugin from `main`, and keeps one copy per version: a change to anything a user runs
(the Python, `bin/`, `hooks/`, `plugin/`, the page, the app) reaches them only with a new version number. A change to
docs, tests or `bench/` alone needs no version.

## 1. The version commit

Patch for a fix, minor for something a user can newly do, major for a change that breaks a setup. Move every place
together:

- `.claude-plugin/plugin.json`: `"version"`
- `pyproject.toml`: `version`, then `uv lock --offline` (it changes only Pointe's own version in `uv.lock`)
- `ios/Pointe.xcodeproj/project.pbxproj`: `MARKETING_VERSION` (both places), and `CURRENT_PROJECT_VERSION` one higher
- `CHANGELOG.md`: one line on top, the same words as the commit subject

Commit as `Version X.Y.Z: <what changed, in the words a user would use>`, with `git commit -s`.
`tests/test_version.py` fails when the manifest, `pyproject.toml`, `uv.lock` and the changelog disagree.

## 2. Checks

```
uv run --locked pytest -q tests/ --ignore=tests/e2e     # the offline suite, about four minutes, no keys
python3 tools/check_action_pins.py                       # each GitHub Action is still the commit its tag names
```

CI must be green on the version commit. For a minor version, or when the install path or setup changed, follow
`docs/install.md` again on a clean environment and add the run on top of
[docs/install-verification.md](docs/install-verification.md). The paid end-to-end suites (`tests/e2e/run_all.sh`) run
when the call path changed; say in the notes whether they ran.

## 3. The tag

```
git tag -a vX.Y.Z -m "Pointe X.Y.Z" <the version commit, or a later docs-only commit>
git push origin vX.Y.Z
```

The tag's name is `v` plus the version in `.claude-plugin/plugin.json` at that commit. Never move a pushed tag: a
mistake gets a new patch version.

## 4. The GitHub Release

```
gh release create vX.Y.Z --title "Pointe X.Y.Z" --notes-file notes.md
```

Write the notes for someone who has never seen Pointe, in this order:

1. What Pointe is, in two sentences (the README's first paragraph).
2. What is in this version: the changelog lines since the last release, grouped, in plain words. Name people who
   reported or fixed something.
3. Install and update. Install is the one command in the README. To update: `claude plugin marketplace update pointe`,
   then `claude plugin update pointe@pointe`, then `/pointe:stop` and `/pointe:voice` so the daemon restarts on the new
   code.
4. Limits that matter to a new user (the README's "Limits"), and anything this version is known not to fix.

No claim the README does not make, no "first" or "only", and numbers only with their source. The release has no
attached files: the plugin installs from the repository.

## 5. After

- The iPhone app follows its own path to TestFlight and the App Store: `docs/ios/app-store.md`.
- The repository page: the description and topics are set through `gh repo edit`. The social preview image cannot be
  set through the API: upload `docs/social-preview.png` by hand in Settings, General, Social preview, after any change
  to it.

## The site

If `site/` changed, publish it to pointe.ballerine.com with `site/deploy.sh` (Cloudflare Pages, Ballerine account).

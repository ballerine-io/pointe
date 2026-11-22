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
- `macos/tools/make_project.py`: `VERSION`, and `BUILD` one higher, then `python3 macos/tools/make_project.py` (it
  writes `macos/PointeMac.xcodeproj`)
- `CHANGELOG.md`: one line on top, the same words as the commit subject
- `python3 tools/site_version.py`: writes the version into the site's pages (`site/deploy.sh` runs it too)

Commit as `Version X.Y.Z: <what changed, in the words a user would use>`, with `git commit -s`.
`tests/test_version.py` fails when the manifest, `pyproject.toml`, `uv.lock`, the two apps and the changelog disagree.
`tests/test_site.py` fails while a page of the site shows another version.

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
- The Mac app is built from source until there is a Developer ID: `docs/mac-app.md` has the notarization steps.
  Until either app has a download, people build them with `bin/pointe apps mac` and `bin/pointe apps ios`.
- The repository page: the description and topics are set through `gh repo edit`. The social preview image cannot be
  set through the API: upload `docs/social-preview.png` by hand in Settings, General, Social preview, after any change
  to it.

## The site

`site/` is one Cloudflare Pages project (`pointe-site`, Ballerine account) served at eng.ballerine.com: `site/index.html`
is the Ballerine Engineering hub at `/`, and `site/pointe/` is Pointe's page at `/pointe/`. If `site/` changed:

1. `site/deploy.sh v2` (any branch name) publishes a preview at `<branch>.pointe-site-9tz.pages.dev`. Look at it.
2. `site/deploy.sh` publishes production (branch `main`), after the owner has seen the preview.

**The roadmap.** `ROADMAP.md` and `site/pointe/roadmap/` are written by `tools/roadmap.py` from the issues labelled
`roadmap`: their `horizon/now`, `horizon/next` or `horizon/later` label, and their 👍 count at that moment. The page is a
snapshot and fetches nothing. To publish fresh votes, `site/deploy.sh --roadmap` (then a branch name for a preview) runs
the generator before the upload; it needs `gh` signed in. Commit the two regenerated files after a production deploy;
`tests/test_roadmap.py` fails if they disagree or are out of shape. Do it at each release, and when an item moves.

`site/pointe/contribute/` is written by hand: keep it in step with `CONTRIBUTING.md`.

The old address, pointe.ballerine.com, is still a custom domain of the same project. Pages cannot redirect by host, so
each page carries a one-line script that sends a visitor on that host to `https://eng.ballerine.com/pointe/`. Link
previews (`og:url`, `og:image`) name eng.ballerine.com. Both hosts are CNAMEs to `pointe-site-9tz.pages.dev` in Route 53.

The product images on the page are screenshots: the Mac page comes from `ui.html` in the page rig (`tests/page_rig.py`)
with invented sessions, the iPhone images are crops of `docs/ios/screenshots/`. Retake them when either surface changes.

# Releasing

A release is a version commit on `main`, an annotated tag on it, and a GitHub Release with notes a person can read and
the release tarball the standalone install uses. Claude Code installs the plugin from `main`, and keeps one copy per
version; `install.sh` and `pointe update` install the tarball of a tag. A change to anything a user runs (the Python,
`bin/`, `hooks/`, `plugin/`, `install.sh`, the page, the app) reaches them only with a new version number. A change to
docs, tests or `bench/` alone needs no version.

**Batch.** At most one release a day, carrying everything merged since the last one, unless an owner-reported bug
needs a fix out sooner. Between releases, changes land on `main` through the inner loop and CI (CONTRIBUTING.md,
"How to test"); the release is where the full gate below runs.

## 1. The version commit

Patch for a fix, minor for something a user can newly do, major for a change that breaks a setup. While the major
version is 0, Pointe is in beta: the page, the apps and the site say "beta" beside the version by that rule alone,
and 1.0.0 drops it. The version stays numeric (Apple's `MARKETING_VERSION` and the Mac app's version check need it).
`CURRENT_PROJECT_VERSION` and `BUILD` only ever go up, even when the version starts again at 0.8.0. Move every place
together:

- `.claude-plugin/plugin.json`: `"version"`
- `pyproject.toml`: `version`, then `uv lock --offline` (it changes only Pointe's own version in `uv.lock`)
- `apps/ios/Pointe.xcodeproj/project.pbxproj`: `MARKETING_VERSION` (both places), and `CURRENT_PROJECT_VERSION` one higher
- `apps/macos/tools/make_project.py`: `VERSION`, and `BUILD` one higher, then `python3 apps/macos/tools/make_project.py` (it
  writes `apps/macos/PointeMac.xcodeproj`)
- `CHANGELOG.md`: one line on top, the same words as the commit subject
- `tests/fixtures/skew_requests.json`: an entry for the new version, with the requests its scripts send (copy the
  newest entry and change what moved). `tests/test_skew.py` replays every release's requests against the new daemon,
  and fails while the new version has no entry
- `python3 tools/site_version.py`: writes the version into the site's pages (`site/deploy.sh` runs it too)

Commit as `Version X.Y.Z: <what changed, in the words a user would use>`, with `git commit -s`.
`tests/test_version.py` fails when the manifest, `pyproject.toml`, `uv.lock`, the two apps and the changelog disagree.
`tests/test_site.py` fails while a page of the site shows another version.

## 2. Checks

```
uv run --locked --group test-tools pytest -q tests/ --ignore=tests/e2e --runslow -n auto   # every test, the slow ones too
python3 tools/check_action_pins.py                       # each GitHub Action is still the commit its tag names
```

Run the full suite with `--runslow` on a Mac: CI runs it on Ubuntu, where the tests that need a Mac skip themselves.
On the version commit, `test` and `apps` must be green before the tag. Its own `ui` run on `main` does not count: a
newer push to `main` cancels the older `ui` run still going, so a version commit can rarely finish one. The `ui`
that gates the release is the tag's (step 3).

For a minor version, or when the install path or setup changed, follow `docs/install.md` again on a clean environment and add the run on top of
[docs/install-verification.md](install-verification.md). The paid end-to-end suites (`tests/e2e/run_all.sh`) run
when the call path changed; say in the notes whether they ran.

**Screenshots come from CI.** The `ui` workflow (`.github/workflows/ui.yml`) runs the iPhone UI tests in the Simulator,
the Mac smoke and the Mac XCUITests on a hosted runner, and uploads their pictures: `ios-ui-screenshots`,
`mac-smoke-screenshots` and `mac-xcuitest-screenshots`. Every screenshot in the notes, the site or a review comes from
the tag's run (`gh run download <run> -R ballerine-io/pointe`). Never take one by running UI tests
on a Mac somebody works at: they take the screen, the keyboard and the pointer, and the scripts refuse to start there
(`tools/ui_guard.py`).

## 3. The tag

```
git tag -a vX.Y.Z -m "Pointe X.Y.Z" <the version commit, or a later docs-only commit>
git push origin vX.Y.Z
```

The tag's name is `v` plus the version in `.claude-plugin/plugin.json` at that commit. Never move a pushed tag: a
mistake gets a new patch version.

The tag runs `test`, `apps` and `ui` on exactly that commit, in a group no push cancels. The order is: version
commit, `test` and `apps` green on it, the tag, the release as a prerelease (step 4), then wait for the tag's `ui`
run to be green before the release is promoted to Latest. The tarball, the pin, the disk image and the TestFlight
upload can go on while it runs. If it fails on a real bug, the fix goes in the next patch version; the tag stays.
Screenshots come from the tag's `ui` run.

## 4. The GitHub Release

```
python3 tools/release_tarball.py build vX.Y.Z          # dist/pointe-X.Y.Z.tar.gz and .sha256, a git archive of the tag
gh release create vX.Y.Z --prerelease --title "Pointe X.Y.Z" --notes-file notes.md dist/pointe-X.Y.Z.tar.gz dist/pointe-X.Y.Z.tar.gz.sha256
python3 tools/release_tarball.py pin vX.Y.Z            # install.sh installs it: the version and the SHA-256 the release publishes
```

Commit the pinned `install.sh` on its own ("The installer pins X.Y.Z"; it changes only `POINTE_VERSION` and
`POINTE_SHA256` in it and the same file's SHA-256 in `apps/PointeKit/Sources/PointeMacKit/Installer.swift`, which `pin`
writes too, and needs no version), then deploy the site, which serves it at `/pointe/install.sh`. Until then a new
standalone install still works: it checks the release against the SHA-256 published with it. The tarball leaves out
`bench/`, `evals/` and `site/` (`.gitattributes`). Never replace an asset of a published release: a mistake gets a new
patch version, as for a tag. The one exception is the `Pointe.dmg` copy below, when it holds the wrong image.

Then the Mac app, from that commit, so the `install.sh` built into it installs this release:

```
tools/build_dmg.sh --upload     # dist/Pointe-X.Y.Z.dmg and .sha256, signed, notarized, stapled; attached to the release
```

**Signing is set up on the owner's Mac.** The app is archived and sent to Apple's notary service through Xcode's
account (the team's cloud-managed Developer ID certificate, export destination "upload"). The disk image is signed with
the "Developer ID Application: Alon Peretz (PP445E78PD)" identity in the login keychain and notarized with the
notarytool profile `pointe-notary` (an App Store Connect API key with the Developer role), then stapled. On another
Mac, the script names whichever of the two is missing and attaches nothing. `--app <notarized Pointe.app>` makes the
image again from an app already notarized, without a new archive.

Check before attaching: `spctl -a -vvv -t install` on the image and `spctl -a -vvv -t exec` on the app say
"accepted, source=Notarized Developer ID"; `xcrun stapler validate` passes on both; and a quarantined copy of the image
(as Safari marks a download) mounts on a double-click, its app copied out still accepted.

`--upload` also attaches the same image as `Pointe.dmg`, which every release must carry: the site links
`https://github.com/ballerine-io/pointe/releases/latest/download/Pointe.dmg`. If a release went out with the wrong
`Pointe.dmg` (0.8.2's first held the 0.8.1 app), replace that copy alone with `gh release upload vX.Y.Z Pointe.dmg
Pointe.dmg.sha256 --clobber`; the versioned `Pointe-X.Y.Z.dmg` is never replaced.

**Never Latest before the disk image.** The release is created as a prerelease (`--prerelease` above) and stays one
until `Pointe-X.Y.Z.dmg`, `Pointe.dmg` and their `.sha256` are attached and checked, and the tag's `ui` run is green. `releases/latest/download/Pointe.dmg`
follows whichever release is Latest, so a Latest release without its image makes the site's download a 404 (0.8.7 was
published that way and was set back). Then promote it:

```
gh release edit vX.Y.Z --prerelease=false --latest
```

and check the link anonymously (`curl -sIL <url>` ends in 200) and the downloaded file's SHA-256 against the
release's `.sha256`. Then set `mac` in
`site/pointe/apps.json` to `"status": "open"` with that `download_url`, this `version` and the image's `size` in
decimal megabytes, as Finder and browsers show it (`stat -f %z` divided by 1,000,000, rounded to one decimal:
4,572,523 bytes is "4.6 MB"); the hero, the top
nav and the install card follow it (`tools/apps_status.py`). Deploy the site, and check its hero line.

In CI the `mac-release` workflow does the same on a published release when its environment holds the signing secrets
(`.github/workflows/mac-release.yml` lists them); its token is read-only, so attach its artifact with
`gh release upload vX.Y.Z Pointe-X.Y.Z.dmg Pointe-X.Y.Z.dmg.sha256`.

0.8.1's disk image is not signed (its app is signed, notarized and stapled, which is what Gatekeeper judges on a
download); 0.8.2's is the first signed and notarized image.

Write the notes for someone who has never seen Pointe, in this order:

1. What Pointe is, in two sentences (the README's first paragraph).
2. What is in this version: the changelog lines since the last release, grouped, in plain words. Name people who
   reported or fixed something.
3. Install and update. Install is the README's: `Pointe-X.Y.Z.dmg` on a Mac, the plugin command for Claude Code,
   `install.sh` for Codex and OpenCode. To update the plugin: `claude plugin marketplace update pointe`, then `claude plugin update pointe@pointe`,
   then `/pointe:stop` and `/pointe:voice` so the daemon restarts on the new code. The standalone install: `pointe
   update`.
4. Limits that matter to a new user (the README's "Limits"), and anything this version is known not to fix.

No claim the README does not make, no "first" or "only", and numbers only with their source. The release's files are
the tarball, the disk image and the SHA-256 of each; the plugin installs from the repository.

## 5. After

- The iPhone app follows its own path to TestFlight and the App Store: `docs/ios/app-store.md`.
- The Mac app ships as `Pointe-X.Y.Z.dmg` (step 4). Until the iPhone app has a download, people build it with
  `pointe apps ios`.
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

The product images on the page are screenshots: the Mac page comes from `pointe/ui.html` in the page rig (`tests/page_rig.py`)
with invented sessions, the iPhone images are crops of `docs/ios/screenshots/`. Retake them when either surface changes.

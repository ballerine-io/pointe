# Releasing

A release is a version commit on `main`, an annotated tag on it, and a GitHub Release with notes a person can read and
the release tarball the standalone install uses. Claude Code installs the plugin from `main`, and keeps one copy per
version; `install.sh` and `pointe update` install the tarball of a tag. A change to anything a user runs (the Python,
`bin/`, `hooks/`, `plugin/`, `install.sh`, the page, the app) reaches them only with a new version number. A change to
docs, tests or `bench/` alone needs no version.

## When to release: batches

- **On demand, when a batch is worth it**, at most about one a day. A batch is everything merged since the last
  release; a small change waits for the next batch.
- **Sooner only for an owner-reported bug.** The fix goes out as a patch as soon as it is on `main` and green.
- **The version number** follows step 1's rules: patch for a fix, minor for something a user can newly do or a protocol
  change between machines (the skew matrix in `tests/fixtures/skew_requests.json` then has an entry for it), major for a
  change that breaks a setup.
- **`tools/release plan`** says what the next release would carry and whether it is ready. Between releases, changes
  land on `main` through the inner loop and CI (CONTRIBUTING.md, "How to test"); the release is where the full gate runs.

## The command: tools/release

```
tools/release plan                              what the next release carries, whether it is ready, who must act
tools/release cut X.Y.Z --dry-run               every check below, nothing published: no push, tag, release, upload or deploy
tools/release cut X.Y.Z --summary "…" --notes notes.md
tools/release resume                            after an outage, an expired sign-in, or a person's step
tools/release status                            each step and its state
```

`cut` runs these steps in order; each is checked before the next one that needs it, and the sections below say what
each does by hand:

1. **Preflight.** A release worktree at the newest `main`. `main` green on `test` and `apps` (a red `main` stops the line;
   `ui` on `main` is reported, and the tag's own `ui` run gates the promotion). Nothing half-done: no `WIP`/`fixup!` commit since the last tag, no `DO-NOT-RELEASE` marker in a tracked
   file. Everything generated is current: the parity matrix with no unexplained gap on the page, the iPhone, the Mac or
   the Linux hub; the product help; the site's docs pages, version and app cards. The versions agree (step 1's tests),
   and the skew matrix has the cut version's entry (or the version commit copies the newest one). The integration join (`tests/test_integration_join.py`). The full
   suite with `--runslow` on a Mac, on at most four workers (other work shares the Mac; `POINTE_RELEASE_WORKERS`
   sets another number). When the Mac is too loaded, `--suite-from-ci` takes CI's full suite on
   the same commit instead, and the report says the Mac-only tests did not run. The changelog since the last Latest release, grouped by what a person uses, as a
   notes draft.
2. **The version commit** in lockstep (step 1), pushed to `main`, then `test` and `apps` green on it. CHANGELOG entries
   marked **Unreleased** are folded under the version's line; one whose commit is already in the last tag shipped then
   and is dropped. If `main` moved after the preflight, the preflight runs again on the new `main`.
3. **The tag**, then the tag's own `test` and `apps` green (step 3).
4. **Artifacts:** the tarball on a prerelease; `install.sh` pinned, on a commit that is the tag plus the pin (the disk
   image and the iPhone build come from it) and the same change on `main`; the disk image signed, notarized, stapled
   and attached; the iPhone build uploaded to App Store Connect. Both are signed in CI by the `release` workflow when its
   environment holds the secrets ("Signing in CI" below), and on this Mac otherwise or with `--local-signing`.
5. **Verify:** every asset downloaded anonymously against its `.sha256`, the local build and the pin; `spctl` and
   `stapler` on the image and the app, from a quarantined copy mounted as a download is; a clean standalone install from
   github.com in an empty environment on this Mac; a Linux hub (installed, started on a synthetic key, health, status
   and page answer, status names the version) and a Linux node, each installed from github.com in an empty Ubuntu
   container in the Colima VM `pointe-release` (its own profile: no other container is touched).
6. **Publish:** the tag's `ui` run green; then, and only with the disk image attached and checked and the notes no
   longer the draft, the prerelease becomes Latest, and `releases/latest/download/Pointe.dmg` must answer 200 with the
   image's SHA-256. Then `apps.json`, the roadmap's votes, and the site: a preview for the owner first when a page
   written by hand changed since the last release, production directly when only generated content did. The site is
   deployed only after the promotion, so its `install.sh` never pins a prerelease. Then the live checks: the hero line,
   `/pointe/install.sh` (the repository's bytes, pinning this version, which is Latest), the download.
7. **Distribution:** TestFlight's internal group (automatic once Apple has processed the build); the external group,
   Beta App Review and the App Store submission, which wait for the owner (below); the release installed on the
   owner's iPhone when it is reachable (`pointe apps ios --no-launch`: installed, not opened).
8. **The report:** each platform's state, the links, the SHA-256s, and what waits for whom
   (`pointe-release/<version>/report.md` in the clone's git folder).

**Idempotent and resumable.** Each step's outcome is kept in `pointe-release/<version>/state.json` in the clone's git
folder, so every worktree of the clone sees it, with a log beside it. A done step is never run again. A step that
changes something outside first asks what is already there: the tag on github.com (one at another commit is someone
else's: the tool stops and never moves it), the release and its assets (a published asset is compared, never
replaced; a release found Latest without its disk image is set back to prerelease and the previous one made Latest
again, as 0.8.7 had to be), the pin and `apps.json` on `main`, and the build number App Store Connect already holds (a
second upload of it is refused by Apple and recorded as done by another run). One release run at a time per clone: a
lock, taken over only from a run that died. A stopped step names the one thing to do and `tools/release resume`.

**The rules it holds, and the failure each came from:**

| Rule | From |
|---|---|
| Created as a prerelease; Latest only with `Pointe-X.Y.Z.dmg` and `Pointe.dmg` attached and checked | 0.8.7 published Latest with the tarball only: the site's download was a 404 |
| The `ui` that gates is the tag's; a `ui` run on `main` cancelled by a newer push is looked past | the cancel-older-runs rule cancelled the `ui` run on 0.9.0's version commit |
| A step that needs Xcode's account, the keychain, the notary profile or wrangler asks first and stops with the fix; nothing signs another way | Xcode lost its account in the middle of 0.9.0 |
| One run per clone (a lock); the tag, the assets and App Store Connect are asked before acting | a duplicate agent tagged 0.8.7, published it and uploaded its TestFlight build |
| The site is deployed after the promotion; the live check fails when `install.sh` pins anything but Latest | the site's `install.sh` pinned 0.9.0 while it was a prerelease |
| A red `main` stops the release at the first step | a red `main` held the 0.8.7 gate |
| The App Store step reports how many commits changed the iPhone's screens since its screenshots were taken | the App Store screenshots were older than the screens |
| The summary (the App Store's What's New) may not say "beta"; the iPhone's version line drops it (`AppVersion.line`) | the "beta" rule on iOS (App Review 2.2) |

## What needs a person

The tool asks for each before the step that needs it, and stops there; nothing is improvised around a missing one.
`tools/release plan` lists them all.

| Step | Needs | Who, and how | Kept |
|---|---|---|---|
| Everything on GitHub | `gh` signed in with write access | `gh auth login` | gh's own store |
| The Mac app and the disk image: signing | The "Developer ID Application" identity of team PP445E78PD, in the login keychain (manual signing: no Xcode account) | The owner, once: Xcode, Settings, Apple Accounts, the team, Manage Certificates, +, Developer ID Application | login keychain |
| Notarizing the app and the image | notarytool profile `pointe-notary` | Once: `xcrun notarytool store-credentials pointe-notary` with the App Store Connect API key (`--key/--key-id/--issuer`) or an Apple Account and an app-specific password; it needs an interactive session (the keychain refuses the write otherwise) | login keychain |
| The iPhone export | The "Apple Distribution" identity of the team, and the App Store profiles "Pointe App Store" (io.ballerine.pointe) and "Pointe Widget App Store" (io.ballerine.pointe.widget), both with group.io.ballerine.pointe (manual signing: no Xcode account) | The owner, once a year as they expire: developer.apple.com, Certificates and Profiles | login keychain, ~/Library/MobileDevice/Provisioning Profiles |
| The iPhone upload, on this Mac (in CI the workflow uploads) | The App Store Connect API key, handed to altool as a file | **Needs the owner's yes** (`--asc-key-file`): altool reads the key only from a regular file (a pipe and a named pipe are refused), so it goes in a 0600 file in a 0700 folder for the upload and is removed after; the repository's rule is that a secret never goes in a file. Without it the tool stops with the exported `.ipa` and the command | |
| Every signing step, on this Mac | The login keychain unlocked (a locked one makes codesign and notarytool hang) | The owner unlocks the Mac | |
| Signing in CI | The `release` environment's secrets ("Signing in CI" below) | The owner, once and at each rotation: `tools/release_secrets.sh`, allowing each private key's export in the Keychain dialog | GitHub's encrypted environment store |
| The site | wrangler signed in to Ballerine's Cloudflare account | The owner: `npx -y wrangler@4.166.0 login` | wrangler's own store |
| A site preview | The owner's look, when a hand-written page changed | The owner opens the preview, then `tools/release resume --site-approved` | |
| TestFlight external group, Beta App Review, the App Store | App Store Connect with an App Manager role or more. The keychain's API key has the Developer role: reads only | The owner, in App Store Connect, each release (the tool prints the build, the group and the What's New text) | |
| The App Store submission | The owner's yes, every time | The owner | |
| The owner's iPhone | Unlocked, paired with Xcode, on the network or a cable | The owner | |

**Why no Xcode account.** On Xcode 27.2 the account worked in Xcode's own window while `xcodebuild -exportArchive`
answered "No Accounts", from any Terminal (0.10.1). So the exports sign manually with the identities in the keychain
(above), and Xcode's account is not part of a release (`tools/build_dmg.sh --xcode-account` keeps the old way). If an
export still cannot be made from the command line, Xcode exports from the archives the tool already built: open `apps/macos/build/dmg/Pointe.xcarchive` (Organizer, Distribute App, Direct Distribution) and
export the notarized `Pointe.app`, then `tools/release resume --mac-app <that Pointe.app>`, which makes, notarizes and
attaches the image from it; open `apps/ios/build/Pointe.xcarchive` (Distribute App, App Store Connect, Upload), and the
next `resume` sees the build in App Store Connect and does not upload it again.

**The App Store Connect API key.** A generic password in the login keychain (service `pointe-asc-api-key-p8`, account
the key ID, holding the base64 of the `.p8`). `tools/release` reads it into memory, signs a short-lived token with
openssl on a pipe, and never writes or prints it. It has the Developer role: the build's processing and TestFlight
state are read with it; creating the App Store version, the external group, Beta App Review and the submission are
refused (403), so the tool stops there with the clicks.

**Recommendations.** The identities, the profiles and the notary profile stay on the owner's Mac as the fallback when
CI cannot sign. Give the API key the App Manager role only if the owner wants TestFlight's external group and Beta App
Review done without a click (the tool would then need those calls; not built). The App Store submission stays the
owner's, by choice.

## Signing in CI

`tools/release cut` signs the disk image and the iPhone build in GitHub Actions, so a release needs nothing from the
owner's Mac but `gh`: not its keychain, not Xcode, not being awake and unlocked. It dispatches
`.github/workflows/release.yml` once per version on the tag, waits for each job, and keeps the run in its state, so
`resume` waits on the same run (a red job is re-run once, as CI's are).

- **mac** builds `tools/build_dmg.sh --ci`: the app archived and exported with Developer ID, notarized with the API key,
  stapled; the image signed, notarized and stapled. The token is read-only, so the image comes back as the `pointe-dmg`
  artifact; `tools/release` checks its `.sha256`, runs `spctl`, `stapler` and the quarantined mount on it, and only then
  attaches `Pointe-X.Y.Z.dmg` and `Pointe.dmg` (a published asset is never replaced).
- **iphone** runs `apps/ios/release.sh --manual` (archive and export signed with Apple Distribution and the two App Store
  profiles), checks that the app and the widget carry the app group, and uploads the `.ipa` with altool and the API key.
  It uploads only when App Store Connect does not have the build yet.
- **The build commit.** Both jobs check out the tag and pin `install.sh` there (`tools/ci_signing.sh pin`, the same
  `tools/release_tarball.py pin` the tool runs), then refuse unless the result's SHA-256 is the one `tools/release`
  committed (the `install_sha256` input) and nothing but `install.sh` and `Installer.swift` changed. A tag that is not
  `vX.Y.Z` (a test of the workflow) builds as it is and never uploads.
- **Fallback.** When a secret is missing, or with `--local-signing`, the step signs on this Mac as before (the table
  above). The choice is kept for the version, so a resume does not switch halfway.

**Where the secrets live.** In the GitHub environment `release` of ballerine-io/pointe (Settings, Environments), never
repository-wide. Its deployment rule admits only tags matching `v*`: a branch, a pull request or a fork cannot run a job
in it. The job that uses them imports the `.p12` into a keychain made for that job, installs the profiles, writes the
API key to the runner's temp folder, and removes all three when it ends, whatever happened (GitHub's documented
pattern for Apple signing; hosted runners are thrown away after each job).

| Secret | What |
|---|---|
| `MAC_DEVELOPER_ID_P12`, `MAC_DEVELOPER_ID_P12_PASSWORD` | "Developer ID Application" of team PP445E78PD and its private key, base64; its passphrase |
| `IOS_DISTRIBUTION_P12`, `IOS_DISTRIBUTION_P12_PASSWORD` | "Apple Distribution" of the team and its private key, base64; its passphrase |
| `IOS_APP_PROFILE`, `IOS_WIDGET_PROFILE` | the App Store profiles "Pointe App Store" and "Pointe Widget App Store", base64 |
| `ASC_API_KEY_P8`, `ASC_API_KEY_ID`, `ASC_API_ISSUER_ID` | the App Store Connect API key (Developer role: notarizes and uploads builds) |

**Why this keeps "secrets never on disk".** The repository's rule is that a secret reaches only the one process that
needs it, never a file on a person's machine, a commit, a log or a command line. Here the values go from the login
keychain to `gh secret set` on stdin (`tools/release_secrets.sh`, `tools/export_identity.swift`, which exports one named
identity, not every identity in the keychain as `security export` would), and from there live only in GitHub's
encrypted store. On the runner they reach the job's environment, are masked in its log, and touch the runner's disk only
in its temp folder for the length of the job: the job keychain and the key file altool and notarytool read (neither
reads a key from a pipe). `security import` takes the `.p12` passphrase on its command line, on a runner of its own.

**Rotating.** Run `tools/release_secrets.sh` (or one group: `mac`, `ios`, `profiles`, `asc`) on the owner's Mac after the
new certificate, profile or key is in its keychain; each run replaces what it sets and makes a new `.p12` passphrase.
macOS asks, in a dialog, to allow the export of each private key: the owner enters the login keychain's password and
allows it. Then revoke the old certificate or key at developer.apple.com or in App Store Connect. The App Store profiles
expire once a year with the Apple Distribution certificate. `tools/release plan` reports whether the environment holds
every secret and admits only `v*` tags.

**Making the environment again** (done once, 2026-11-27):

```
gh api -X PUT repos/ballerine-io/pointe/environments/release -F 'deployment_branch_policy[protected_branches]=false' -F 'deployment_branch_policy[custom_branch_policies]=true'
gh api -X POST repos/ballerine-io/pointe/environments/release/deployment-branch-policies -f name='v*' -f type=tag
```

**Still manual.** TestFlight's external group with Beta App Review, and the App Store submission: the API key has the
Developer role, which Apple refuses for those writes, so the owner does them in App Store Connect (the tool prints the
build and the What's New text). With an App Manager key they could follow; the App Store submission stays the owner's
by choice. Anyone who can push a `v*` tag can run a job in the environment: tag creation is the control.

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
  and fails while the new version has no entry. When `main` has none, `tools/release`'s version commit copies the
  newest entry under the new version; a release whose scripts send something new edits the entry on `main` first
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

**Signing is set up on the owner's Mac, without Xcode's account.** The app is archived and exported with manual signing
by the "Developer ID Application: Alon Peretz (PP445E78PD)" identity in the login keychain, notarized with the notarytool
profile `pointe-notary`, and stapled; the disk image is signed with the same identity, notarized and stapled. On another
Mac, the script names whichever of the two is missing before it archives, and attaches nothing. `--app <notarized
Pointe.app>` makes the image again from an app already notarized, without a new archive.

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

In CI the `release` workflow does the same from the tag plus the pin ("Signing in CI" above); `tools/release` checks
its artifact and attaches it.

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
- The Mac app ships as `Pointe-X.Y.Z.dmg` (step 4). The iPhone app is on the App Store and TestFlight;
  `pointe apps ios` builds it from source.
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

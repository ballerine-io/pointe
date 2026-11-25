# Supply chain

Pointe runs on a stranger's Mac with their vendor keys in the Keychain, hears their microphone and can approve their
coding agents' prompts. A poisoned dependency or install path is therefore the worst case, worse than any bug in Pointe
itself. This page lists every way code or data reaches a user's machine or CI, how each is pinned, how it is verified,
and what is still open. `tests/test_supply_chain.py` fails when the tree drifts from what is written here.

## Inventory

| Source | What it is | Pinned how | Verified how | Risk |
|---|---|---|---|---|
| **Plugin install** (`claude plugin marketplace add https://github.com/ballerine-io/pointe.git`) | Claude Code clones this repository into its plugin folder and runs `plugin/commands/*.md`, `hooks/hooks.json` (`bin/voice-first-run` on SessionStart, `bin/voice-permission-hook` on PermissionRequest) and `bin/*` | the default branch of the repository; a release tag is not pinned by the installer | git over HTTPS; `main` is protected (PR, DCO, the `offline` check; admins can bypass) | **Medium.** Whoever can push to `main` ships code to every user. Mitigation: branch protection, review, the checks below. Nothing in `bin/`, `hooks/` or `plugin/` fetches remote code at run time: the only network calls are to loopback (the daemon) and the pinned downloads listed here. |
| **Standalone install** (`install.sh`, served at `eng.ballerine.com/pointe/install.sh`; `pointe update`) | without Claude Code: the release tarball `pointe-X.Y.Z.tar.gz` (a `git archive` of the tag, attached to the GitHub Release with its `.sha256`), unpacked into `~/.pointe/<version>`; then uv and the Python packages as below | the installer names one version and its SHA-256 (`POINTE_VERSION`, `POINTE_SHA256`, written by `tools/release_tarball.py pin` after each release); another version, or `pointe update`, uses the SHA-256 published with that release | the tarball is downloaded to a file over https only (`--proto =https`, no redirect to another scheme) and hashed; a mismatch stops it before anything is unpacked; the folder gets its `.pointe-install` mark only then (`tests/test_install.py`, and the test below) | **Medium.** Like the plugin, whoever can publish a release on the repository ships code; the pinned hash adds the site as a second place an attacker would have to change. The person downloads `install.sh` to a file and runs it; nothing is piped into a shell. GitHub's own "Source code" archives are not promised to keep their bytes, so the hash is of an asset we attach. |
| **uv** (`plugin/commands/setup.md` step 2, `bin/install-uv`) | the Python runner that installs and runs everything else | installer for one version (`0.12.21`), downloaded to a file and checked against a SHA-256 before it runs; the installer carries a SHA-256 for each binary it downloads | `bin/install-uv` (version and hash in one place; the test checks they match CI and the e2e Dockerfiles) | Low. Was `curl -LsSf https://astral.sh/uv/install.sh \| sh`: latest version, unverified script. A `uv` already on the PATH is used as found, whatever its version or origin (code running as you is trusted); `install-uv` prints a note when its version is not the pinned one. |
| **Python packages** (`pyproject.toml`, `uv.lock`) | 172 packages plus the project itself (direct: aiohttp, anthropic, pipecat-ai with extras, segno, sherpa-onnx, uvicorn; node group; dev group; test-tools group (tests only, never synced by an install); `local` extra for MLX, Whisper, Kokoro, misaki) | exact versions in `uv.lock`; every install path uses `uv sync --locked` / `uv run --locked` (`bin/*`, workflows, docs); `bin/*` syncs through `bin/uv-sync`, from uv's cache first so an installed Pointe starts offline, then runs with `--no-sync` | every entry carries `sha256` for its sdist and wheels; uv refuses a mismatch; `uv lock --check` in CI; the set must equal `docs/security/dependencies-allowlist.txt` | Low for integrity. Medium for trust: a compromised upstream release would be locked in faithfully; Dependabot opens the bump, a person reviews it. Native wheels: onnxruntime, sherpa-onnx, numpy, grpcio, cryptography, pillow, mlx. Install-time scripts: none (wheels only). Download-on-import: huggingface_hub, mlx-whisper, mlx-audio, faster-whisper, pipecat's Kokoro service (see models). |
| `en-core-web-sm` 3.8.0 (spaCy English, `local` extra) | a wheel from `github.com/explosion/spacy-models/releases` | by URL in `pyproject.toml` | `sha256` in `uv.lock` | Low. misaki would otherwise `pip install` it at run time. |
| **mlx-lm** (text-model server, `pointe local`) | `mlx-lm==0.32.2` in its own environment under `~/.claude-voice/local/mlx-lm` | dependency group `mlx-lm` in `pyproject.toml`, locked in `uv.lock`; installed with `uv sync --locked --only-group mlx-lm` | `sha256` in `uv.lock` | Low. Was `uv pip install mlx-lm==0.32.2`: its 20 transitive packages resolved to whatever PyPI served that day, with no hashes. |
| **Fonts** (`assets/fonts/`, `apps/PointeKit/Sources/PointeUI/Resources/Fonts/`) | Bricolage Grotesque (300, 400) and Instrument Sans (400, 500, 600), static TrueType files, SIL OFL 1.1; the page loads them from the daemon (`/voice/font/<name>`), the app from its bundle | committed to the repository, from the upstream repositories at the commits named in `THIRD_PARTY.md`; each file's SHA-256 in `assets/theme.json` | `tests/test_theme.py` hashes both copies; the daemon serves only a name in that list and only bytes with its hash | Low. Nothing is fetched at run time and no font CDN is contacted: the page test for outside loads covers it. |
| **Models from Hugging Face** (`pointe/assets.py`) | Whisper large-v3-turbo MLX (`mlx-community/whisper-large-v3-turbo`), Kokoro-82M MLX (`mlx-community/Kokoro-82M-bf16`), Gemma 4 26B A4B 4-bit (`mlx-community/gemma-4-26b-a4b-it-4bit`), Whisper large-v3-turbo CTranslate2 (`deepdml/faster-whisper-large-v3-turbo-ct2`, non-Mac) | by repository **commit** (`revision=`), never `main`, in `assets.HF_MODELS` | `huggingface_hub` checks each file's size and, for LFS files, its SHA-256 against the commit's metadata; the commit id names the exact tree | Low. Was unpinned (`main`): the repository owner could replace the weights under the same name. A model chosen by hand (`pointe local --model`) is the user's own choice and is not pinned. |
| **Kokoro v1.0 ONNX** (`kokoro-v1.0.onnx` 311 MB, `voices-v1.0.bin` 28 MB; `mouth: local`) | from `github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/` | URL and SHA-256 in `assets.ASSETS` | downloaded to `.part`, hashed, refused and deleted on a mismatch (`assets.fetch`); the files are then handed to Pipecat by path, so its own unverified downloader never runs | Low. Was Pipecat's `_ensure_model_files`: no hash; GitHub release assets can be replaced in place. |
| **3D-Speaker ERes2Net** (voice lock, 40 MB) | from `github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/` | URL and SHA-256 in `assets.ASSETS` (moved from `pointe/speaker.py`) | `assets.fetch`, as above | Low. |
| **Silero VAD**, **smart-turn** | `.onnx` files inside the `pipecat-ai` wheel | the wheel's `sha256` | by uv | Low. |
| **GitHub Actions** (`.github/workflows/*.yml`) | `actions/checkout`, `astral-sh/setup-uv`, `actions/upload-artifact` (SBOM only) | commit SHA with a `# vX` comment; `setup-uv` is told `version: 0.12.21` | the test refuses a `uses:` without a 40-hex SHA, and one whose SHA is not the commit its version tag points to (an annotated tag's own SHA is refused: `tests/fixtures/action_pins.json`, recorded and re-checked in CI by `tools/check_action_pins.py`); `permissions: contents: read` on every workflow; every checkout has `persist-credentials: false`, so the token is not left in `.git/config` for the pull request's code; Dependabot bumps them weekly | Low. `ubuntu-latest`, `macos-26` and `setup-uv`'s Python download are GitHub's and Astral's to secure. |
| **Node channel** (`channel/`, launch mode only) | `@modelcontextprotocol/sdk` 1.32.2, `zod` 4.6.7 and 93 transitive packages | `channel/package-lock.json` (v3) | `npm ci --ignore-scripts`; every entry carries `integrity` (SHA-512) and resolves to `registry.npmjs.org` | Low. Attach mode (`/pointe:voice`) never runs Node. |
| **iPhone app** (`apps/ios/`) | Swift sources, Apple frameworks, and the package in this repository (`apps/PointeKit`) | no remote Swift package, no CocoaPods | `project.pbxproj` has no `XCRemoteSwiftPackageReference` and one local package reference; the test checks | Low. Built and installed by the person, not downloaded. |
| **Mac app** (`apps/macos/`) and **PointeKit** (`apps/PointeKit`) | Swift sources, Apple frameworks only; the package has no dependency | no remote Swift package; the project file is written by `apps/macos/tools/make_project.py` | the same test covers both projects and `Package.swift`, and `tests/test_macos_parity.py` fails when the project differs from its generator | Low. Built from source by the person who runs it; not notarized yet. The app makes no outbound connection: loopback only. |
| **Linux node** (`pointe node join`, `bin/voice-node`) | the `node` dependency group (~35 MB) into `~/.claude-voice/node-env` | `uv sync --locked --only-group node` | `sha256` in `uv.lock` | Low. |
| **Twingate connector** (`bin/voice-connector`, optional phone access) | Docker image `twingate/connector:1`, `--pull=always` | a moving tag, by design: the connector is Twingate's security product and should update | Docker Hub's TLS and image signature only | **Accepted.** Already in `SECURITY.md` as a known limit. Pinning a digest would freeze a VPN component; the person chose Twingate and trusts its images. |
| **Vendor APIs** | Anthropic, Gemini, OpenAI, Soniox, ElevenLabs, with the user's own keys | SDK versions in `uv.lock`; hosts in the egress list below | TLS, by each SDK | Not a supply-chain source: data goes out, no code comes in. |
| **The voice page** (`ui*.html`, `site/`) | served by the daemon on loopback; the public site is static | n/a | the test refuses any `<script src>`, `<link href>`, `@import` or `url(https://…)` to another host: only `data:` URIs and links to GitHub in the text | Low. The page loads nothing from outside the machine. |

Not on a user's machine, development only: `tests/e2e/linux_node/*.Dockerfile` start from `python:3.12-slim` (a tag) and
`ghcr.io/astral-sh/uv:0.12.21` (a version tag), and `claude.Dockerfile` installs the latest `@anthropic-ai/claude-code`
on purpose, to test against current Claude Code. `bench/` and `tools/demo-video/` call the vendors and `ffmpeg`/`xcodebuild` already
on the machine; `bench/local_tts_bench.py` downloads two Chatterbox models unpinned, for a measurement that is already
recorded in `bench/results/local.md`.

## Outbound hosts

Every host the daemon, its scripts or its libraries can contact. The machine-readable copy is
`docs/security/egress-allowlist.txt`; `tests/test_supply_chain.py` fails when a URL literal in the source names a host
that is not there, so a dependency bump or a pull request cannot add an egress silently. A host a download is
redirected to is chosen by Hugging Face or GitHub and is not in the source: `tests/e2e/egress_redirects.py` (free, no
keys, a few MB) fetches one file of each pin through a recording proxy and fails on a host that is not listed. A host a
server names at runtime has no literal to find either: hf-xet is told its CAS server and CDN by Hugging Face. Those were
recorded from the dependency's own log in `tests/fixtures/dependency_hosts.txt`, and the test checks each is in the
allowlist.

| Host | Why | When |
|---|---|---|
| `api.anthropic.com` | brain, reader, checker (Anthropic SDK) | with an Anthropic key |
| `generativelanguage.googleapis.com` | Gemini text, ears, mouth, realtime front (google-genai) | with a Gemini key |
| `api.openai.com` | OpenAI text, ears, mouth, realtime front | with an OpenAI key |
| `api.elevenlabs.io` | ElevenLabs ears and mouth | with an ElevenLabs key |
| `stt-rt.soniox.com`, `tts-rt.soniox.com` | Soniox ears, meeting ears, mouth (WebSocket) | with a Soniox key |
| `api.soniox.com` | One GET of the models list, to tell whether a saved key works; a redirect is not followed | `pointe key check soniox` only |
| `huggingface.co`, `us.aws.cdn.hf.co`, `cas-server.xethub.hf.co` | model downloads at the pinned revisions (`huggingface_hub`, `hf-xet`); the second and third are where Hugging Face redirects a file | `pointe local`, `pointe local voice`, first use of `ears: local` |
| `github.com`, `release-assets.githubusercontent.com` | Kokoro v1.0 and ERes2Net release assets; the `en-core-web-sm` wheel; uv's binaries; Pointe's release tarball and its `.sha256`, and the `/releases/latest` redirect | first use of `mouth: local`, the voice lock; `uv sync --extra local`; `bin/install-uv`; the standalone installer (install.sh) and `pointe update` |
| `download.tensorflow.org`, `groups.inf.ed.ac.uk` | recorded human speech for the benchmarks: the Speech Commands test set and the AMI corpus annotations, each checked against a pinned SHA-256 | `bench/conversational/dialogues/run.py human`, `bench/human_turns.py fetch`, run by a maintainer; never by the plugin |
| `api.github.com` | the roadmap issues and their 👍 counts, through `gh api` | `tools/roadmap.py` (`site/deploy.sh --roadmap`), run by a maintainer; never by the plugin |
| `astral.sh`, `releases.astral.sh` | the pinned uv installer | `bin/install-uv`, when uv is missing |
| `pypi.org`, `files.pythonhosted.org` | Python packages, by hash | `uv sync --locked` |
| `registry.npmjs.org` | the channel's packages, by integrity | `npm ci` in launch mode |
| `registry-1.docker.io`, `auth.docker.io`, `production.cloudflare.docker.com` | `twingate/connector:1` | `bin/voice-connector` only |
| `127.0.0.1`, `localhost`, `*.localhost` | the daemon, the node, the local text-model server, Ollama | always |
| the hub's own name (`pointe node join`), the Mac's own name (phone) | the node's TLS link, the phone's call | multi-machine and phone setups, certificate pinned |
| `*.events.data.microsoft.com` | onnxruntime telemetry | **blocked**: `ORT_DISABLE_TELEMETRY=1` (`pointe/no_telemetry.py`, tested) |

Hosts that appear in the source only as text shown to a person (where to get a key, where to download Tailscale) are
listed in the allowlist as `link` and are never contacted by the software.

## Audit record

- **pip-audit 2.10.1**, 2026-11-14, every one of the 167 locked package versions (not only the current platform's):
  no known vulnerabilities. Command: `uv run --locked python tools/locked_requirements.py > locked.txt && uvx pip-audit@2.10.1 --no-deps --disable-pip -r locked.txt`.
- **osv-scanner**: not installed here; not run.
- **gitleaks 8.30.1**, tree and all 306 commits: 7 and 30 hits, all of them synthetic tokens in tests that exercise
  `readout.mask` (the redaction) and a 16-hex key fingerprint shown in the app's UI. No real secret. `.gitleaks.toml`
  allowlists those test paths and that fingerprint so `gitleaks dir .` runs clean.
- **gitleaks 8.30.1**, 2026-11-17, before the repository is made public: a mirror clone of every branch and pull
  request ref (420 commits) with `gitleaks git --log-opts=--all`, and every one of its 2048 blobs with `gitleaks dir`,
  which also covers merge commits: the same synthetic tokens and fingerprint, nothing else. `gitleaks dir .` with
  `.gitleaks.toml`: no leaks.
- **Actions**, 2026-11-17: each pin is a commit, the one its comment's tag points to (`actions/checkout` v4.4.0,
  `astral-sh/setup-uv` v6.8.0, `actions/upload-artifact` v7.0.2). setup-uv was pinned before to the annotated tag object
  of the moving `v6` tag, which peels to the same commit but is lost when `v6` moves.

## CI

`.github/workflows/test.yml` runs on every push and has two jobs. `offline` runs the whole suite, the slow tests too,
in parallel (`-n auto`), with no keys and no network beyond PyPI. `.github/workflows/apps.yml` runs `ios` and `macos`
when `apps/` or a file the Swift tests read changes, and on a tag push.
`ios` builds the iPhone app for the simulator, unsigned, on `macos-26` with the newest Xcode there, and runs its unit
tests (`PointeTests`); it pulls no packages from outside the repository.
`macos` runs `swift test` for `apps/PointeKit` and builds the Mac app, signed ad hoc, with its unit tests.
`supply-chain` runs `uv lock --check`, `tests/test_supply_chain.py`, pip-audit (pinned version) on every locked version,
and writes a CycloneDX SBOM (`uvx --from cyclonedx-bom@8.0.1 cyclonedx-py requirements`) plus `uv export --locked` as a
build artifact. Dependabot
(`.github/dependabot.yml`) opens one grouped pull request a week per ecosystem: uv, GitHub Actions, npm.

## Adding something

- A Python package: `uv add <name>` (or edit `pyproject.toml`), `uv lock`, add a line to
  `docs/security/dependencies-allowlist.txt` with a one-line reason for it and each transitive package it brings,
  update `THIRD_PARTY.md`, and say in the pull request what the lockfile diff adds and why.
- A download at run time: an entry in `pointe/assets.py` with its SHA-256 (or Hugging Face commit), fetched through
  `assets.fetch` / `assets.snapshot`, the host in `docs/security/egress-allowlist.txt`, a row in `THIRD_PARTY.md`.
- A GitHub Action: pinned to a 40-hex commit with a `# vX.Y.Z` comment, `permissions` unchanged, `python3 tools/check_action_pins.py --write` run and its file committed, and a reason here.
- Never: `pip install`, `uvx <tool>` without `@version`, `curl … | sh`, a `uv run` or `uv sync` without `--locked`.

## Releases

There is no build: a release is a tag on `main`, and the plugin installer clones the repository. To verify what you run,
compare `git rev-parse HEAD` in Claude Code's plugin folder with the tag on GitHub, and `uv lock --check` there. Signed
tags are not yet in use (see Open).

## Open

- Release tags are not signed and the plugin installer does not pin a tag: a user gets `main` at install time.
- `osv-scanner` and a Software Bill of Materials diff between releases are not run; the SBOM is produced, not compared.
- The Twingate image tag (above) and the e2e Dockerfile base images are accepted as moving.
- `bench/local_tts_bench.py` downloads Chatterbox unpinned; measurement code, not shipped behaviour.
- **Accepted:** CI's `uvx pip-audit@2.10.1` and `uvx --from cyclonedx-bom@8.0.1` pin each tool's version, not its
  dependencies or their hashes, so those resolve to whatever PyPI serves that day. Locking them would add a dependency
  group (new packages in `uv.lock` and the allowlist), which needs the owner's yes. The risk is bounded: the job runs
  with a read-only token and no secrets, reads only this repository, and its outputs are a pass or fail and the SBOM
  artifact; nothing it produces ships to a user.

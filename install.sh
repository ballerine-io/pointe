#!/usr/bin/env bash
# Install Pointe without Claude Code: a conversational layer for your coding agents (Claude Code, Codex, OpenCode).
# It fetches one pinned release from GitHub, checks it against the SHA-256 below before anything runs, unpacks it into
# ~/.pointe/<version>, installs uv the checked way bin/install-uv does, sets up Pointe's Python, and makes `pointe` a
# command (~/.local/bin/pointe). No sudo. It shows what it will do and asks first.
#
#   curl -fsSLO https://eng.ballerine.com/pointe/install.sh && bash install.sh
#
#   bash install.sh [--yes]                   the pinned release below
#   bash install.sh --hub | --node            on Linux: this machine holds the voice (hub), or only its sessions join
#                                             a hub on another machine (node); asked when not given
#   bash install.sh --version X.Y.Z           another release, checked against the SHA-256 published with it
#   pointe update [--yes]                     (runs install.sh --update) the newest release, checked the same way
#   pointe uninstall                          removes it again
#
# --url and --sha256 name another tarball and its hash (tests use a file:// one). Nothing is ever installed unchecked.
set -euo pipefail

POINTE_VERSION="0.8.7"  # the release a new install gets; tools/release_tarball.py pin writes these two lines
POINTE_SHA256="83b7bf5418ac7b4a0ac63e1bb47dd56b2fb050bf0893757c3bb6cdcbcf985c2e"         # of pointe-$POINTE_VERSION.tar.gz as attached to its GitHub Release; empty: read the release's
REPO="https://github.com/ballerine-io/pointe"
POINTE_HOME="${POINTE_HOME:-$HOME/.pointe}"
STATE="${CLAUDE_VOICE_STATE:-$HOME/.claude-voice}"
# Inside a release, relative to its root: the one place a later layout change has to touch.
ENTRY="bin/pointe"; INSTALL_UV="bin/install-uv"; UV_SYNC="bin/uv-sync"; INSTALLS="bin/pointe-installs"
MANIFEST=".claude-plugin/plugin.json"; MARKER=".pointe-install"
ON_PATH=":$PATH:"  # before uv's folder is added below: whether a new terminal is needed to type `pointe`
PATH="$PATH:$HOME/.local/bin"

say() { printf '%s\n' "$*"; }
die() { printf 'install.sh: %s\n' "$*" >&2; exit 1; }
sha256() { if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | cut -d' ' -f1; else sha256sum "$1" | cut -d' ' -f1; fi; }
version_in() { grep -qs '"name": *"pointe"' "$1/$MANIFEST" && sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' "$1/$MANIFEST" | head -1; }
newer() { [ "$1" != "$2" ] && [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | tail -1)" = "$1" ]; }  # is $1 newer than $2
fetch() { curl -fsSL --proto '=https,file' --proto-redir '=https' --tlsv1.2 --retry 2 -o "$2" "$1"; }
pretty() { case "$1" in "$HOME"/*) printf '~/%s' "${1#"$HOME"/}" ;; *) printf '%s' "$1" ;; esac; }
standalone() {  # the folders an earlier run of this installer finished, newest first: version, tab, folder
  local dir
  for dir in "$POINTE_HOME"/*/; do
    [ -f "$dir$MARKER" ] && printf '%s\t%s\n' "$(version_in "$dir")" "${dir%/}"
  done | sort -t "$(printf '\t')" -k1,1Vr
  return 0
}

YES=""; VERSION=""; URL=""; SHA=""; MODE=install; ROOT=""; ROLE="${POINTE_ROLE:-}"
while [ $# -gt 0 ]; do
  case "$1" in
    -y|--yes)   YES=1 ;;
    --version)  VERSION="${2:?--version needs X.Y.Z}"; VERSION="${VERSION#v}"; shift ;;
    --url)      URL="${2:?--url needs a URL}"; shift ;;
    --sha256)   SHA="${2:?--sha256 needs a hash}"; shift ;;
    --update)   MODE=update ;;
    --hub)      ROLE=hub ;;
    --node)     ROLE=node ;;
    --activate) MODE=activate; ROOT="${2:?--activate needs a folder}"; shift ;;
    -h|--help)  sed -n '2,17p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)          die "no option $1 (bash install.sh --help lists them)" ;;
  esac
  shift
done

ask() {  # $1: the question. --yes answers yes; with no terminal to ask on, the answer is no.
  [ -n "$YES" ] && return 0
  local answer=""
  if [ -t 0 ]; then read -r -p "$1 [y/N] " answer
  elif { : </dev/tty; } 2>/dev/null; then read -r -p "$1 [y/N] " answer </dev/tty
  else say "$1 No terminal to answer on: run it in a terminal, or add --yes."; return 1; fi
  case "$answer" in y|Y|yes|Yes|YES) return 0 ;; *) return 1 ;; esac
}

# --activate: the second half, run from the release just unpacked, so each release finishes its own layout.
if [ "$MODE" = activate ]; then
  ROOT="$(cd "$ROOT" && pwd)"
  [ -f "$ROOT/$MARKER" ] || die "$ROOT was not unpacked by install.sh"
  "$ROOT/$INSTALL_UV"  # uv if missing, checked against its pinned SHA-256; then ~/.local/bin/pointe (bin/link-pointe)
  if [ "$ROLE" = node ]; then  # a node has no voice: pointe node join syncs its own small environment (no Pipecat)
    say "ok       no voice packages: a node needs none (pointe node join sets up what it runs)"
  else
    say "Installing Pointe's Python packages (about 180 MB the first time)..."
    "$ROOT/$UV_SYNC" --quiet --project "$ROOT"
  fi
  say "ok       Pointe $(version_in "$ROOT") is installed in $(pretty "$ROOT")"
  exit 0
fi

[ "$(id -u)" != 0 ] || die "run it as yourself, not with sudo: everything goes into your home folder"
for tool in curl tar; do command -v "$tool" >/dev/null 2>&1 || die "$tool is missing"; done
if [ "$(uname -s)" = Darwin ]; then
  ROLE=hub
elif [ -z "$ROLE" ] && [ "$MODE" = install ]; then  # an update keeps what is there: a node has a node.json
  say "On Linux, Pointe runs one of two ways (docs/linux.md):"
  say "  1. hub   this machine holds the voice. Its page, your phone, and your other machines connect to it."
  say "           Needs a model key (kept in your login keyring) or local models."
  say "  2. node  only this machine's sessions join a hub that runs on another machine. No voice, no keys, no models here."
  if [ -n "$YES" ]; then ROLE=hub; say "--yes: hub. For a node: bash install.sh --node"
  else
    answer=""
    if [ -t 0 ]; then read -r -p "Which one? [1 hub / 2 node] " answer
    elif { : </dev/tty; } 2>/dev/null; then read -r -p "Which one? [1 hub / 2 node] " answer </dev/tty
    else say "No terminal to answer on: run it in a terminal, or add --hub or --node."; exit 1; fi
    case "$answer" in 1|h|hub|Hub|HUB) ROLE=hub ;; 2|n|node|Node|NODE) ROLE=node ;;
      *) say "Nothing changed: answer 1 or 2, or run bash install.sh --hub or --node."; exit 1 ;; esac
  fi
fi
[ -z "$ROLE" ] && grep -qs '"hub"' "$STATE/node.json" && ROLE=node  # an update of a node stays a node
[ -n "$ROLE" ] || ROLE=hub
export POINTE_ROLE="$ROLE"  # the release's own install.sh --activate reads it

if [ "$MODE" = update ]; then
  HAVE="$(standalone | awk -F '\t' 'NR == 1 { print $1 }')"
  [ -n "$HAVE" ] || die "no standalone install of Pointe in $(pretty "$POINTE_HOME") to update. Install it: bash install.sh"
  if [ -z "$VERSION" ]; then  # github.com answers /releases/latest with a redirect to the newest release's tag
    LATEST="$(curl -fsS --proto '=https' --tlsv1.2 -o /dev/null -w '%{redirect_url}' "$REPO/releases/latest")" \
      || die "could not reach github.com to find the newest release"
    VERSION="${LATEST##*/tag/v}"
    case "$VERSION" in [0-9]*.[0-9]*.[0-9]*) ;; *) die "github.com did not name a release ($LATEST)" ;; esac
  fi
  if ! newer "$VERSION" "$HAVE"; then say "Pointe $HAVE is up to date: $VERSION is not newer."; exit 0; fi
fi

VERSION="${VERSION:-$POINTE_VERSION}"
NEWEST="$(standalone | awk -F '\t' 'NR == 1 { print $1 }')"
if [ -n "$NEWEST" ] && newer "$NEWEST" "$VERSION"; then  # an older installer run again never takes a newer install away
  say "Pointe $NEWEST is installed already, newer than $VERSION: nothing changed. pointe update keeps it current."; exit 0
fi
URL="${URL:-$REPO/releases/download/v$VERSION/pointe-$VERSION.tar.gz}"
WHY="the SHA-256 pinned in this installer"
[ -z "$SHA" ] || WHY="the SHA-256 given with --sha256"
if [ -z "$SHA" ] && [ "$VERSION" = "$POINTE_VERSION" ] && [ -n "$POINTE_SHA256" ] && [ "$URL" = "$REPO/releases/download/v$VERSION/pointe-$VERSION.tar.gz" ]; then
  SHA="$POINTE_SHA256"
elif [ -z "$SHA" ]; then
  WHY="the SHA-256 published with the release"
fi
[ -z "$SHA" ] || [[ "$SHA" =~ ^[0-9a-f]{64}$ ]] || die "--sha256 must be 64 lowercase hex digits"

DEST="$POINTE_HOME/$VERSION"
OLD="$(standalone | awk -F '\t' -v v="$VERSION" '$1 != v { print $2 }')"  # replaced once this one works
RESTART=""  # the daemon runs from a folder this replaces: it starts again on the new one
if [ -f "$STATE/daemon.pid" ] && kill -0 "$(cat "$STATE/daemon.pid")" 2>/dev/null; then
  RAN="$(cd "$(cat "$STATE/daemon.root" 2>/dev/null)" 2>/dev/null && pwd -P || true)"
  while IFS= read -r dir; do
    [ -n "$dir" ] && [ -n "$RAN" ] && [ "$(cd "$dir" && pwd -P)" = "$RAN" ] && RESTART=1
  done <<<"$OLD"
fi

say "Pointe $VERSION, a conversational layer for your coding agents."
if [ "$MODE" = update ]; then say "This updates Pointe $HAVE to $VERSION:"; else say "This will:"; fi
say "  - download  $URL"
say "  - check     it against $WHY, and stop on any difference"
say "  - unpack    it into $(pretty "$DEST")"
say "  - install   uv into ~/.local/bin if it is missing (one pinned version, its installer checked against a SHA-256)"
if [ "$ROLE" = node ]; then
  say "  - skip      the voice packages: a node needs none"
else
  say "  - install   Pointe's Python packages into $(pretty "$DEST")/.venv (about 180 MB to download, 530 MB on disk)"
fi
say "  - link      ~/.local/bin/pointe, so pointe is a command"
[ -z "$RESTART" ] || say "  - restart   Pointe on $VERSION (a call in progress ends)"
while IFS= read -r dir; do [ -z "$dir" ] || say "  - remove    $(pretty "$dir") (Pointe $(version_in "$dir"))"; done <<<"$OLD"
say "Nothing needs sudo, and nothing starts at login. pointe uninstall removes it all."
ask "Go ahead?" || { say "Nothing changed."; exit 1; }

mkdir -p "$POINTE_HOME"
WORK="$(mktemp -d "$POINTE_HOME/.download.XXXXXX")"; trap 'rm -rf "$WORK"' EXIT
say "Downloading Pointe $VERSION..."
fetch "$URL" "$WORK/pointe.tar.gz" || die "could not download $URL"
if [ -z "$SHA" ]; then
  fetch "$URL.sha256" "$WORK/pointe.tar.gz.sha256" || die "the release publishes no SHA-256 ($URL.sha256): not installing"
  SHA="$(cut -d' ' -f1 "$WORK/pointe.tar.gz.sha256" | head -1)"
  [[ "$SHA" =~ ^[0-9a-f]{64}$ ]] || die "the release's SHA-256 file does not hold a SHA-256: not installing"
fi
GOT="$(sha256 "$WORK/pointe.tar.gz")"
[ "$GOT" = "$SHA" ] || die "the download does not match $WHY (expected $SHA, got $GOT): not installing, nothing changed"
say "ok       SHA-256 matches ($SHA)"

if [ -f "$DEST/$MARKER" ] && [ "$(version_in "$DEST")" = "$VERSION" ]; then
  say "ok       Pointe $VERSION is already unpacked in $(pretty "$DEST")"
else
  mkdir "$WORK/x"
  tar -xzf "$WORK/pointe.tar.gz" -C "$WORK/x" --no-same-owner
  TOP="$WORK/x/pointe-$VERSION"
  [ "$(version_in "$TOP")" = "$VERSION" ] || die "the archive does not hold Pointe $VERSION: not installing"
  [ -x "$TOP/$ENTRY" ] || die "the archive has no $ENTRY: not installing"
  printf 'standalone %s sha256 %s\n' "$VERSION" "$SHA" >"$TOP/$MARKER"
  rm -rf "$DEST"  # a half-unpacked folder from an interrupted run: it never got its marker
  mv "$TOP" "$DEST"
fi

"$DEST/install.sh" --activate "$DEST"

if [ -n "$RESTART" ]; then
  "$DEST/$ENTRY" restart >/dev/null && say "ok       Pointe restarted on $VERSION" \
    || say "note     Pointe did not restart on $VERSION: pointe doctor says why, then pointe restart"
fi
while IFS= read -r dir; do [ -z "$dir" ] || { rm -rf "$dir" && say "ok       removed $(pretty "$dir")"; }; done <<<"$OLD"
"$DEST/$INSTALLS" advise 2>/dev/null | sed 's/^/note     /' || true  # an older Pointe plugin would break /pointe:voice
if [ "$MODE" = update ]; then say "Pointe is updated to $VERSION."; exit 0; fi

say ""
case "$ON_PATH" in *":$HOME/.local/bin:"*) CMD="pointe" ;; *) CMD="~/.local/bin/pointe" ;; esac
if [ "$ROLE" = node ]; then
  say "Next, on the hub: pointe hub invite. Then here: $CMD node join '<the line it prints>'"
  say "  This machine's sessions then join the hub's voice: /pointe:voice in Claude Code, pointe join opencode or codex."
  exit 0
fi
say "Next: $CMD setup"
if [ "$(uname -s)" = Darwin ]; then
  say "  About 5 minutes: one question, your key (it goes to your Keychain, never a file), and your first call."
else
  say "  About 5 minutes: one question, your key (typed hidden, kept in your login keyring through secret-tool, never a"
  say "  file), and your first call. Without a keyring: docs/linux.md, \"Keys\"."
fi
say "  It then sets up Codex (pointe join codex) and OpenCode (/voice), if you have them."
say "  With Claude Code, the plugin is the other way in. Both can be installed: the newer one runs."

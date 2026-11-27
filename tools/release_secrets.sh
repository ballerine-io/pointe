#!/usr/bin/env bash
# The signing secrets of the GitHub environment "release", from this Mac's login keychain and profiles, straight into
# GitHub's encrypted store (docs/releasing.md, "Where the secrets live"). Run it once to create them and again to rotate
# any: each run replaces what it sets.
#
#   tools/release_secrets.sh             all of them
#   tools/release_secrets.sh mac         the Developer ID identity (the Mac app and disk image)
#   tools/release_secrets.sh ios         the Apple Distribution identity and the two App Store profiles
#   tools/release_secrets.sh asc         the App Store Connect API key (notarization and the TestFlight upload)
#   tools/release_secrets.sh profiles    the two App Store profiles only (no private key: no dialog)
#
# Every value goes from memory to `gh secret set` on stdin: never a file, argv, a log or the terminal. Each .p12 gets a
# passphrase made here and stored beside it. macOS may ask, in a dialog, to allow the export of a private key: the
# owner's click. Needs gh signed in with admin rights on the repository.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="ballerine-io/pointe"
ENVIRONMENT="release"
TEAM="${POINTE_TEAM:-PP445E78PD}"
ASC_SERVICE="${POINTE_ASC_SERVICE:-pointe-asc-api-key-p8}"
ASC_KEY_ID="${POINTE_ASC_KEY_ID:-TSZHHBLM44}"
ASC_ISSUER="${POINTE_ASC_ISSUER:-8cf5a727-9a2b-4847-a6d8-705dc2bcf84a}"
PROFILES="$HOME/Library/MobileDevice/Provisioning Profiles"

die() { printf 'release_secrets.sh: %s\n' "$*" >&2; exit 1; }
put() {  # $1: the secret's name, $2: its value (a shell variable's, so never argv of a program)
  [ -n "$2" ] || die "$1 would be empty: not set"
  printf '%s' "$2" | gh secret set "$1" --env "$ENVIRONMENT" --repo "$REPO" >/dev/null
  printf 'set      %s\n' "$1"
}
identity() {  # $1: the certificate's common name, $2: the secret's name
  local pass p12
  pass="$(openssl rand -base64 33)"
  p12="$(POINTE_P12_PASSPHRASE="$pass" swift "$ROOT/tools/export_identity.swift" "$1")" || die "the export of \"$1\" failed"
  put "$2" "$p12"
  put "$2_PASSWORD" "$pass"
}
profile() {  # $1: the profile's name, $2: the secret's name
  local file found=""
  for file in "$PROFILES"/*.mobileprovision; do
    [ "$(security cms -D -i "$file" 2>/dev/null | plutil -extract Name raw -o - - 2>/dev/null)" = "$1" ] || continue
    [ -z "$found" ] || die "two profiles are named \"$1\": remove the older"
    found="$file"
  done
  [ -n "$found" ] || die "no profile named \"$1\" in $PROFILES"
  put "$2" "$(base64 -i "$found")"
}

gh api "repos/$REPO/environments/$ENVIRONMENT" >/dev/null 2>&1 || die "the environment $ENVIRONMENT does not exist (docs/releasing.md says how to make it)"
want="${1:-all}"
case "$want" in all|mac|ios|asc|profiles) ;; *) die "no group $want: mac, ios, asc or profiles" ;; esac
if [ "$want" = all ] || [ "$want" = mac ]; then
  identity "Developer ID Application: Alon Peretz ($TEAM)" MAC_DEVELOPER_ID_P12
fi
if [ "$want" = all ] || [ "$want" = ios ] || [ "$want" = profiles ]; then
  profile "Pointe App Store" IOS_APP_PROFILE
  profile "Pointe Widget App Store" IOS_WIDGET_PROFILE
fi
if [ "$want" = all ] || [ "$want" = ios ]; then
  identity "Apple Distribution: Alon Peretz ($TEAM)" IOS_DISTRIBUTION_P12
fi
if [ "$want" = all ] || [ "$want" = asc ]; then
  key="$(security find-generic-password -s "$ASC_SERVICE" -a "$ASC_KEY_ID" -w)" || die "no keychain item $ASC_SERVICE / $ASC_KEY_ID"
  put ASC_API_KEY_P8 "$key"  # already the base64 of the .p8
  unset key
  put ASC_API_KEY_ID "$ASC_KEY_ID"
  put ASC_API_ISSUER_ID "$ASC_ISSUER"
fi

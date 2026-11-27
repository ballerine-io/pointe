#!/usr/bin/env bash
# The release workflow's signing steps on a macOS runner (.github/workflows/release.yml), in GitHub's documented pattern
# for Apple signing: the .p12 imported into a keychain made for this job, the profiles installed, the App Store Connect
# key written to the runner's temp folder, and all of it removed when the job ends. Secrets arrive only in the
# environment; nothing here prints one.
#
#   tools/ci_signing.sh pin        the build commit: the tag, with install.sh pinned to its release as tools/release pins it
#   tools/ci_signing.sh keychain   P12, P12_PASSWORD: the identity in a job keychain; ASC_API_KEY_P8, ASC_API_KEY_ID: the key
#   tools/ci_signing.sh profiles   IOS_APP_PROFILE, IOS_WIDGET_PROFILE: the App Store profiles installed
#   tools/ci_signing.sh cleanup    the keychain, the key and the profiles removed
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${RUNNER_TEMP:?a runner sets RUNNER_TEMP: this runs in CI only}"
KEYCHAIN="$RUNNER_TEMP/signing.keychain-db"
KEYS="$RUNNER_TEMP/private_keys"  # altool and notarytool look here for AuthKey_<id>.p8 (API_PRIVATE_KEYS_DIR)
INSTALLED="$RUNNER_TEMP/installed-profiles"
PROFILE_DIRS=("$HOME/Library/MobileDevice/Provisioning Profiles" "$HOME/Library/Developer/Xcode/UserData/Provisioning Profiles")
die() { printf '::error::ci_signing.sh: %s\n' "$*" >&2; exit 1; }
umask 077

case "${1:-}" in
pin)
  # A release tag (vX.Y.Z) builds the tag plus the pin: install.sh pinned to the release's published tarball, and its
  # SHA-256 in the Mac app's installer, exactly the commit tools/release made (its install.sh SHA-256 is the input).
  # Any other v* tag is a test of this workflow: built as it is, and never uploaded.
  : "${TAG:?}"
  VERSION="$(sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' "$ROOT/.claude-plugin/plugin.json" | head -1)"
  if [[ "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    [ "$TAG" = "v$VERSION" ] || die "$TAG is not the version at the tag ($VERSION)"
    [[ "${INSTALL_SHA256:-}" =~ ^[0-9a-f]{64}$ ]] || die "a release build needs install_sha256, the pinned install.sh's SHA-256"
    (cd "$ROOT" && python3 tools/release_tarball.py pin "$TAG")
    got="$(shasum -a 256 "$ROOT/install.sh" | cut -d' ' -f1)"
    [ "$got" = "$INSTALL_SHA256" ] || die "the pinned install.sh is $got, not the $INSTALL_SHA256 tools/release committed"
    changed="$(cd "$ROOT" && git status --porcelain | sed 's/^...//' | sort | tr '\n' ' ')"
    [ "$changed" = "apps/PointeKit/Sources/PointeMacKit/Installer.swift install.sh " ] || die "the pin changed more than install.sh and Installer.swift: $changed"
    echo "release build: $TAG plus the pin (install.sh $got)"
  else
    [ "${UPLOAD:-false}" != true ] || die "$TAG is a test tag: nothing built from it is uploaded"
    echo "test build of $TAG at $(git -C "$ROOT" rev-parse --short HEAD), as it is (install.sh pins $(sed -n 's/^POINTE_VERSION="\(.*\)"/\1/p' "$ROOT/install.sh")); no upload"
  fi
  ;;
keychain)
  : "${P12:?}" "${P12_PASSWORD:?}" "${ASC_API_KEY_P8:?}" "${ASC_API_KEY_ID:?}"
  password="$(openssl rand -hex 24)"
  echo "::add-mask::$password"
  security create-keychain -p "$password" "$KEYCHAIN"
  security set-keychain-settings -lut 21600 "$KEYCHAIN"
  security unlock-keychain -p "$password" "$KEYCHAIN"
  printf '%s' "$P12" | base64 --decode > "$RUNNER_TEMP/identity.p12"
  security import "$RUNNER_TEMP/identity.p12" -k "$KEYCHAIN" -f pkcs12 -P "$P12_PASSWORD" -T /usr/bin/codesign -T /usr/bin/security >/dev/null
  rm -P "$RUNNER_TEMP/identity.p12"
  security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$password" "$KEYCHAIN" >/dev/null
  security list-keychains -d user -s "$KEYCHAIN" $(security list-keychains -d user | tr -d '"')
  security find-identity -v -p codesigning "$KEYCHAIN" | sed -n 's/.*"\(.*\)".*/identity: \1/p'
  mkdir -p "$KEYS"
  printf '%s' "$ASC_API_KEY_P8" | base64 --decode > "$KEYS/AuthKey_$ASC_API_KEY_ID.p8"
  echo "API_PRIVATE_KEYS_DIR=$KEYS" >> "$GITHUB_ENV"
  echo "NOTARY_KEY=$KEYS/AuthKey_$ASC_API_KEY_ID.p8" >> "$GITHUB_ENV"
  ;;
profiles)
  : "${IOS_APP_PROFILE:?}" "${IOS_WIDGET_PROFILE:?}"
  for name in IOS_APP_PROFILE IOS_WIDGET_PROFILE; do
    file="$RUNNER_TEMP/$name.mobileprovision"
    printf '%s' "${!name}" | base64 --decode > "$file"
    uuid="$(security cms -D -i "$file" | plutil -extract UUID raw -o - -)"
    shown="$(security cms -D -i "$file" | plutil -extract Name raw -o - -)"
    for dir in "${PROFILE_DIRS[@]}"; do
      mkdir -p "$dir" && cp "$file" "$dir/$uuid.mobileprovision" && echo "$dir/$uuid.mobileprovision" >> "$INSTALLED"
    done
    rm -f "$file"
    echo "profile: $shown ($uuid)"
  done
  ;;
cleanup)
  security delete-keychain "$KEYCHAIN" 2>/dev/null || true
  security list-keychains -d user -s login.keychain-db || true
  [ ! -d "$KEYS" ] || { find "$KEYS" -type f -exec rm -P {} + ; rm -rf "$KEYS"; }
  if [ -f "$INSTALLED" ]; then while IFS= read -r f; do rm -f "$f"; done < "$INSTALLED"; rm -f "$INSTALLED"; fi
  rm -f "$RUNNER_TEMP"/*.p12 "$RUNNER_TEMP"/*.mobileprovision
  echo "removed: the job keychain, the API key, the profiles"
  ;;
*) die "pin, keychain, profiles or cleanup" ;;
esac

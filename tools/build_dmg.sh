#!/usr/bin/env bash
# Pointe.dmg, in one command: the Mac app archived, signed with Developer ID, notarized and stapled; a disk image with the
# app, an Applications link and the brand's background; the image signed, notarized and stapled too. Built-in tools only
# (xcodebuild, hdiutil, codesign, notarytool, stapler, Finder for the window's layout). docs/releasing.md, step 4.
#
#   tools/build_dmg.sh            dist/Pointe-<version>.dmg and its .sha256, for the version in .claude-plugin/plugin.json
#   tools/build_dmg.sh --upload   then attach both to the GitHub Release v<version> (gh)
#   tools/build_dmg.sh --app P    skip the archive and use P, a Pointe.app already notarized (this script's own, in
#                                 apps/macos/build/dmg/app): for the disk image step again, once its credentials exist
#   tools/build_dmg.sh --ci       the mac-release workflow: see "Signing" below
#
# Signing. Locally the app is signed and notarized through Xcode's own account: automatic signing with the team's
# cloud-managed Developer ID certificate, exported with destination "upload", so Xcode sends it to Apple's notary
# service; nothing is stored here. The disk image needs two things Xcode's account cannot lend a script: a "Developer ID
# Application" identity in the keychain (codesign), and a notarytool profile named pointe-notary, made once with
#   xcrun notarytool store-credentials pointe-notary --apple-id <Apple Account> --team-id PP445E78PD
# Without them it stops after the unsigned image and names the missing one; nothing is uploaded.
# --ci signs the app and the image with the Developer ID identity in the keychain the workflow made from its .p12, and
# notarizes both with an App Store Connect API key: NOTARY_KEY (the .p8 file's path), NOTARY_KEY_ID, NOTARY_ISSUER.
#
# The app installs exactly the release install.sh pins, so install.sh must be pinned to this version first
# (tools/release_tarball.py pin). Nothing here prints a secret.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEAM="${POINTE_TEAM:-PP445E78PD}"
PROFILE="${POINTE_NOTARY_PROFILE:-pointe-notary}"
WORK="$ROOT/apps/macos/build/dmg"
VOLUME="Pointe"
UPLOAD=""; CI_MODE=""; GIVEN=""
while [ $# -gt 0 ]; do
  arg="$1"; shift
  case "$arg" in
    --upload) UPLOAD=1 ;;
    --ci)     CI_MODE=1 ;;
    --app)    GIVEN="$(cd "${1:?--app needs a Pointe.app}" && pwd)"; shift ;;
    -h|--help) sed -n '2,24p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "build_dmg.sh: no option $arg (--help lists them)" >&2; exit 2 ;;
  esac
done

say() { printf '%s\n' "$*"; }
die() { printf 'build_dmg.sh: %s\n' "$*" >&2; exit 1; }
step() { printf '\n== %s\n' "$*"; }

VERSION="$(sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' "$ROOT/.claude-plugin/plugin.json" | head -1)"
APP_VERSION="$(sed -n 's/^VERSION, BUILD = "\([^"]*\)".*/\1/p' "$ROOT/apps/macos/tools/make_project.py")"
PINNED="$(sed -n 's/^POINTE_VERSION="\([^"]*\)".*/\1/p' "$ROOT/install.sh")"
PINNED_SHA="$(sed -n 's/^POINTE_SHA256="\([^"]*\)".*/\1/p' "$ROOT/install.sh")"
[ "$APP_VERSION" = "$VERSION" ] || die "the Mac app is $APP_VERSION and the manifest $VERSION: bump them together (docs/releasing.md)"
[ "$PINNED" = "$VERSION" ] && [ ${#PINNED_SHA} = 64 ] \
  || die "install.sh pins ${PINNED:-nothing}, not $VERSION with its SHA-256: the app would install nothing. Publish the release, then tools/release_tarball.py pin v$VERSION"
DMG="$ROOT/dist/Pointe-$VERSION.dmg"
for tool in xcodebuild hdiutil codesign ditto swift tiffutil osascript; do command -v "$tool" >/dev/null || die "$tool is missing"; done

if [ -n "$CI_MODE" ]; then NOTARY=(--key "${NOTARY_KEY:-}" --key-id "${NOTARY_KEY_ID:-}" --issuer "${NOTARY_ISSUER:-}")
else NOTARY=(--keychain-profile "$PROFILE"); fi  # notarytool's credentials: the profile, or the CI key
can_notarize() {
  if [ -n "$CI_MODE" ]; then [ -n "${NOTARY_KEY:-}" ] && [ -n "${NOTARY_KEY_ID:-}" ] && [ -n "${NOTARY_ISSUER:-}" ]
  else xcrun notarytool history --keychain-profile "$PROFILE" >/dev/null 2>&1; fi
}
submit() {  # $1: a zip or a disk image. Waits for Apple's answer and prints the log's summary on a refusal.
  local out id
  out="$(xcrun notarytool submit "$1" "${NOTARY[@]}" --wait --output-format json)" || true
  id="$(printf '%s' "$out" | sed -n 's/.*"id" *: *"\([^"]*\)".*/\1/p' | head -1)"
  if ! printf '%s' "$out" | grep -q '"status" *: *"Accepted"'; then
    [ -z "$id" ] || xcrun notarytool log "$id" "${NOTARY[@]}" >&2 || true
    die "Apple's notary service did not accept $(basename "$1")"
  fi
  say "ok       notarized ($(basename "$1"), submission $id)"
}
developer_id() { security find-identity -v -p codesigning | sed -n "s/.*\"\(Developer ID Application: .*($TEAM)\)\"/\1/p" | head -1; }

[ ! -e "/Volumes/$VOLUME" ] || die "a volume named $VOLUME is mounted: eject it first (Finder lays out the new one by that name)"
if [ -n "$GIVEN" ]; then  # kept out of $WORK, which is emptied below
  rm -rf "$ROOT/dist/.given.app" && ditto "$GIVEN" "$ROOT/dist/.given.app" && GIVEN="$ROOT/dist/.given.app"
fi
rm -rf "$WORK"; mkdir -p "$WORK" "$ROOT/dist"
ARCHIVE="$WORK/Pointe.xcarchive"

if [ -n "$GIVEN" ]; then
  mkdir -p "$WORK/app" && mv "$GIVEN" "$WORK/app/Pointe.app"
  [ "$(defaults read "$WORK/app/Pointe.app/Contents/Info.plist" CFBundleShortVersionString)" = "$VERSION" ] || die "--app is not Pointe $VERSION"
else
step "1. Archive Pointe $VERSION"
SIGN=(DEVELOPMENT_TEAM="$TEAM")
if [ -n "$CI_MODE" ]; then SIGN+=(CODE_SIGN_STYLE=Manual CODE_SIGN_IDENTITY="Developer ID Application")
else SIGN+=(CODE_SIGN_IDENTITY="Apple Development" -allowProvisioningUpdates); fi
xcodebuild archive -project "$ROOT/apps/macos/PointeMac.xcodeproj" -scheme PointeMac -configuration Release \
  -archivePath "$ARCHIVE" -derivedDataPath "$WORK/dd" "${SIGN[@]}" -quiet >"$WORK/archive.log" 2>&1 \
  || { tail -30 "$WORK/archive.log" >&2; die "the archive failed (log: $WORK/archive.log)"; }
say "ok       $ARCHIVE"

step "2. Sign with Developer ID and notarize the app"
OPTIONS="$WORK/export.plist"
if [ -n "$CI_MODE" ]; then
  /usr/libexec/PlistBuddy -c "Add :method string developer-id" -c "Add :signingStyle string manual" -c "Add :teamID string $TEAM" \
    -c "Add :signingCertificate string Developer ID Application" -c "Add :destination string export" "$OPTIONS" >/dev/null
  xcodebuild -exportArchive -archivePath "$ARCHIVE" -exportOptionsPlist "$OPTIONS" -exportPath "$WORK/app" >"$WORK/export.log" 2>&1 \
    || { tail -30 "$WORK/export.log" >&2; die "the export failed"; }
  ditto -c -k --keepParent "$WORK/app/Pointe.app" "$WORK/Pointe.zip"
  submit "$WORK/Pointe.zip"
else
  # destination upload: Xcode signs with the cloud-managed Developer ID certificate and sends the app to the notary
  # service; -exportNotarizedApp then hands back the app with its ticket stapled, once Apple has accepted it.
  /usr/libexec/PlistBuddy -c "Add :method string developer-id" -c "Add :signingStyle string automatic" -c "Add :teamID string $TEAM" \
    -c "Add :destination string upload" "$OPTIONS" >/dev/null
  xcodebuild -exportArchive -archivePath "$ARCHIVE" -exportOptionsPlist "$OPTIONS" -exportPath "$WORK/upload" -allowProvisioningUpdates \
    >"$WORK/export.log" 2>&1 || { tail -30 "$WORK/export.log" >&2; die "the export to Apple failed (log: $WORK/export.log)"; }
  say "ok       sent to Apple's notary service; waiting for its answer (usually a few minutes)"
  for _ in $(seq 1 120); do  # up to an hour
    if xcodebuild -exportNotarizedApp -archivePath "$ARCHIVE" -exportPath "$WORK/app" >"$WORK/notarized.log" 2>&1; then break; fi
    grep -qi "invalid\|rejected" "$WORK/notarized.log" && { cat "$WORK/notarized.log" >&2; die "Apple did not notarize the app"; }
    sleep 30
  done
  [ -d "$WORK/app/Pointe.app" ] || { tail -20 "$WORK/notarized.log" >&2; die "no notarized app after an hour (log: $WORK/notarized.log)"; }
fi
fi
APP="$WORK/app/Pointe.app"
xcrun stapler staple "$APP" >/dev/null 2>&1 || true  # -exportNotarizedApp has stapled it already; --ci has not
xcrun stapler validate "$APP"
codesign --verify --deep --strict "$APP"
SIGNED="$(codesign -dv --verbose=2 "$APP" 2>&1)"  # captured first: grep -q on a pipe breaks it under pipefail
case "$SIGNED" in *"Authority=Developer ID Application"*) ;; *) die "$APP is not signed with Developer ID" ;; esac
spctl -a -vv -t exec "$APP"

step "3. The disk image"
STAGE="$WORK/stage"
mkdir -p "$STAGE/.background"
ditto "$APP" "$STAGE/Pointe.app"
ln -s /Applications "$STAGE/Applications"
swift "$ROOT/tools/dmg_background.swift" "$WORK/background.png" 1
swift "$ROOT/tools/dmg_background.swift" "$WORK/background@2x.png" 2
tiffutil -cathidpicheck "$WORK/background.png" "$WORK/background@2x.png" -out "$STAGE/.background/background.tiff" >/dev/null 2>&1
hdiutil create -volname "$VOLUME" -srcfolder "$STAGE" -fs HFS+ -format UDRW -ov "$WORK/rw.dmg" >/dev/null
MOUNT="$(hdiutil attach -readwrite -noverify -noautoopen "$WORK/rw.dmg" | sed -n 's/.*Apple_HFS[[:space:]]*//p' | head -1)"
[ -d "$MOUNT" ] || die "the image did not mount"
# The window: icons only, no toolbar, the background, the app left and Applications right (dmg_background.swift's
# places). Finder writes .DS_Store; without Finder (no Automation permission) the image still works, unstyled.
if perl -e 'alarm 60; exec @ARGV' osascript - "$VOLUME" >/dev/null <<'APPLESCRIPT'
on run argv
  tell application "Finder"
    tell disk (item 1 of argv)
      open
      set current view of container window to icon view
      set toolbar visible of container window to false
      set statusbar visible of container window to false
      set the bounds of container window to {200, 120, 860, 548}
      set options to the icon view options of container window
      set arrangement of options to not arranged
      set icon size of options to 112
      set text size of options to 13
      set background picture of options to file ".background:background.tiff"
      set position of item "Pointe.app" of container window to {170, 200}
      set position of item "Applications" of container window to {490, 200}
      update without registering applications
      delay 1
      close
    end tell
  end tell
end run
APPLESCRIPT
then say "ok       the window: background, icons placed"
else say "note     Finder did not lay out the window (Automation permission?): the image works, unstyled"; fi
rm -rf "$MOUNT/.fseventsd"
chmod -Rf go-w "$MOUNT" || true
sync
hdiutil detach "$MOUNT" -quiet || { sleep 3; hdiutil detach "$MOUNT" -force -quiet; }
rm -f "$DMG"
hdiutil convert "$WORK/rw.dmg" -format ULMO -o "$DMG" >/dev/null  # LZMA: the smallest, read by macOS 10.15 and later
say "ok       $DMG ($(du -h "$DMG" | cut -f1 | tr -d ' '))"

step "4. Sign and notarize the disk image"
IDENTITY="$(developer_id)"
if [ -z "$IDENTITY" ]; then
  say "STOP     no \"Developer ID Application\" identity of team $TEAM in the keychain: the image is not signed or notarized."
  say "         One time: Xcode, Settings, Accounts, $TEAM, Manage Certificates, +, Developer ID Application. Then run this again."
  exit 3
fi
codesign --sign "$IDENTITY" --timestamp "$DMG"
codesign --verify "$DMG"
say "ok       signed: $IDENTITY"
if ! can_notarize; then
  say "STOP     no notarytool credentials: the image is signed, not notarized. One time, in a terminal:"
  say "           xcrun notarytool store-credentials $PROFILE --apple-id <your Apple Account> --team-id $TEAM"
  say "         It asks for an app-specific password (account.apple.com, Sign-In and Security). Then run this again."
  exit 3
fi
submit "$DMG"
xcrun stapler staple "$DMG"
xcrun stapler validate "$DMG"
(cd "$(dirname "$DMG")" && shasum -a 256 "$(basename "$DMG")" >"$(basename "$DMG").sha256")
say "ok       $DMG.sha256: $(cut -d' ' -f1 "$DMG.sha256")"
spctl -a -vvv -t install "$DMG"
spctl -a -vvv -t open --context context:primary-signature "$DMG"

if [ -n "$UPLOAD" ]; then
  step "5. Attach to the GitHub Release v$VERSION"
  gh release upload "v$VERSION" "$DMG" "$DMG.sha256" --repo ballerine-io/pointe
  say "ok       https://github.com/ballerine-io/pointe/releases/tag/v$VERSION"
fi

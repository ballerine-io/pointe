#!/usr/bin/env bash
# Builds the Mac app for this Mac (Debug) and prints where it is. Signed with the team in ios/.team when that file is
# there (gitignored: one line, the Team ID), else ad hoc: an ad hoc build runs, but macOS asks for the microphone again
# after each rebuild. Not notarized: for your own Macs. The Developer ID build is macos/release.sh.
#   macos/build.sh           build
#   macos/build.sh --open    build, then open the app
set -euo pipefail
cd "$(dirname "$0")"
SIGN=(CODE_SIGN_IDENTITY=- DEVELOPMENT_TEAM=)
TEAM_FILE="${POINTE_TEAM_FILE:-../ios/.team}"
if [ -s "$TEAM_FILE" ]; then SIGN=(DEVELOPMENT_TEAM="$(tr -d '[:space:]' < "$TEAM_FILE")" "CODE_SIGN_IDENTITY=Apple Development" -allowProvisioningUpdates); fi
xcodebuild build -project PointeMac.xcodeproj -scheme PointeMac -configuration Debug -derivedDataPath build/dd \
  -destination 'platform=macOS,arch=arm64' "${SIGN[@]}" -quiet
APP="$PWD/build/dd/Build/Products/Debug/Pointe.app"
echo "$APP"
if [ "${1:-}" = "--open" ]; then open "$APP"; fi

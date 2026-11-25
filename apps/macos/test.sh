#!/usr/bin/env bash
# The Mac app's tests: the shared package (swift test), then the app's unit tests and UI tests (xcodebuild).
#   apps/macos/test.sh            everything
#   apps/macos/test.sh unit       the package and the app's unit tests: what CI runs, no window server needed
#   apps/macos/test.sh ui [name]  the UI tests (or one, by name); screenshots land in /tmp/macos-app-shots
#   apps/macos/test.sh smoke      the same flows through the Accessibility API (apps/macos/e2e/smoke.py): needs no Automation Mode
# The UI tests and the smoke drive the real app on the demo fixtures (-demo): no daemon, no microphone, no network.
# They open its windows and take the keyboard, so they run in CI; on your own Mac only with POINTE_UI_LOCAL=1.
# Signing: the team in apps/ios/.team when it is there (gitignored), else ad hoc.
set -euo pipefail
cd "$(dirname "$0")"
WHAT="${1:-all}"
ONLY="${2:-}"
if [ "$WHAT" != unit ]; then
  python3 -I ../../tools/ui_guard.py "apps/macos/test.sh $WHAT (apps/macos/test.sh unit opens nothing)" || exit 2
  export TEST_RUNNER_POINTE_UI_LOCAL=1
fi
SIGN=(CODE_SIGN_IDENTITY=- DEVELOPMENT_TEAM=)
TEAM_FILE="${POINTE_TEAM_FILE:-../ios/.team}"
if [ -s "$TEAM_FILE" ]; then SIGN=(DEVELOPMENT_TEAM="$(tr -d '[:space:]' < "$TEAM_FILE")" "CODE_SIGN_IDENTITY=Apple Development" -allowProvisioningUpdates); fi
RUN=(xcodebuild test -project PointeMac.xcodeproj -scheme PointeMac -derivedDataPath build/dd -destination 'platform=macOS,arch=arm64')

if [ "$WHAT" = all ] || [ "$WHAT" = unit ]; then
  (cd ../PointeKit && swift test)
  "${RUN[@]}" -only-testing:PointeMacTests "${SIGN[@]}" -quiet
fi
if [ "$WHAT" = all ] || [ "$WHAT" = ui ]; then
  SHOTS="$HOME/Library/Containers/io.ballerine.pointe.mac.uitests.xctrunner/Data/tmp/macos-app-shots"
  rm -rf "$SHOTS"
  caffeinate -u -t 2 || true  # a sleeping display has no screenshots and drops synthesized keys
  caffeinate -d "${RUN[@]}" "-only-testing:PointeMacUITests${ONLY:+/PointeMacUITests/$ONLY}" "${SIGN[@]}" 2>&1 \
    | grep -E "error:|Test Case .*(passed|failed)|Executed [0-9]+ tests|\*\* TEST" || true
  [ "${PIPESTATUS[0]}" = 0 ] || FAILED=1
  if [ -d "$SHOTS" ]; then mkdir -p /tmp/macos-app-shots && cp "$SHOTS"/*.png /tmp/macos-app-shots/ && echo "screenshots: /tmp/macos-app-shots"; fi
  [ -z "${FAILED:-}" ]
fi
if [ "$WHAT" = smoke ]; then
  python3 -I e2e/smoke.py
fi

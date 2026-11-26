#!/usr/bin/env bash
# Archive Pointe for the App Store and export it for App Store Connect. Signing is automatic, with the team in apps/ios/.team
# (gitignored: the one line Xcode shows as the Team ID). Nothing is uploaded unless --upload is given.
#
#   apps/ios/release.sh                 archive + export the build number in the project
#   apps/ios/release.sh --bump          raise CURRENT_PROJECT_VERSION by one in the project first (commit it)
#   apps/ios/release.sh --build 7       set CURRENT_PROJECT_VERSION to 7 in the project first (commit it)
#   apps/ios/release.sh --upload        export straight to App Store Connect (needs an Xcode account with upload rights)
#   apps/ios/release.sh --manual        export the .ipa with manual signing, no Xcode account: the "Apple Distribution"
#                                       identity in the keychain and the App Store profiles named in POINTE_IOS_PROFILE
#                                       and POINTE_WIDGET_PROFILE (default "Pointe App Store", "Pointe Widget App Store");
#                                       tools/release uploads it with the App Store Connect API key
#
# Output: apps/ios/build/Pointe.xcarchive and apps/ios/build/export/ (Pointe.ipa, unless uploaded).
set -euo pipefail
cd "$(dirname "$0")"

PROJECT=Pointe.xcodeproj
PBXPROJ="$PROJECT/project.pbxproj"
OUT=build
DESTINATION=export
BUILD=""
BUMP=0
MANUAL=0

while [ $# -gt 0 ]; do
  case "$1" in
    --build) BUILD="${2:?--build needs a number}"; shift 2 ;;
    --bump) BUMP=1; shift ;;
    --upload) DESTINATION=upload; shift ;;
    --manual) MANUAL=1; shift ;;
    -h|--help) sed -n '2,14p' release.sh | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "release.sh: unknown argument $1 (see --help)" >&2; exit 2 ;;
  esac
done

[ -s .team ] || { echo "release.sh: apps/ios/.team is missing: put your Apple Developer Team ID in it (one line)" >&2; exit 1; }
TEAM="$(tr -d '[:space:]' < .team)"

CURRENT="$(sed -n 's/.*CURRENT_PROJECT_VERSION = \([0-9][0-9]*\);.*/\1/p' "$PBXPROJ" | sort -u)"
[ "$(printf '%s\n' "$CURRENT" | wc -l | tr -d ' ')" = 1 ] || { echo "release.sh: Debug and Release disagree on CURRENT_PROJECT_VERSION" >&2; exit 1; }
if [ "$BUMP" = 1 ]; then BUILD=$((CURRENT + 1)); fi
if [ -n "$BUILD" ]; then
  [[ "$BUILD" =~ ^[0-9]+$ ]] || { echo "release.sh: --build takes a whole number" >&2; exit 2; }
  sed -i '' "s/CURRENT_PROJECT_VERSION = $CURRENT;/CURRENT_PROJECT_VERSION = $BUILD;/" "$PBXPROJ"
  CURRENT="$BUILD"
fi
VERSION="$(sed -n 's/.*MARKETING_VERSION = \([0-9.]*\);.*/\1/p' "$PBXPROJ" | sort -u | head -1)"
echo "Pointe $VERSION ($CURRENT): archiving"

rm -rf "$OUT"
mkdir -p "$OUT"
xcodebuild archive -project "$PROJECT" -scheme Pointe -configuration Release \
  -destination 'generic/platform=iOS' -archivePath "$OUT/Pointe.xcarchive" \
  -allowProvisioningUpdates DEVELOPMENT_TEAM="$TEAM" CODE_SIGN_STYLE=Automatic POINTE_SHARE_GROUP=YES -quiet

# Written here, not committed: it names the team.
if [ "$MANUAL" = 1 ]; then
  [ "$DESTINATION" = export ] || { echo "release.sh: --manual exports the .ipa; tools/release uploads it" >&2; exit 2; }
  cat > "$OUT/ExportOptions.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>method</key><string>app-store-connect</string>
	<key>destination</key><string>export</string>
	<key>teamID</key><string>$TEAM</string>
	<key>signingStyle</key><string>manual</string>
	<key>signingCertificate</key><string>Apple Distribution</string>
	<key>provisioningProfiles</key>
	<dict>
		<key>io.ballerine.pointe</key><string>${POINTE_IOS_PROFILE:-Pointe App Store}</string>
		<key>io.ballerine.pointe.widget</key><string>${POINTE_WIDGET_PROFILE:-Pointe Widget App Store}</string>
	</dict>
	<key>uploadSymbols</key><true/>
	<key>manageAppVersionAndBuildNumber</key><false/>
</dict>
</plist>
PLIST
else
cat > "$OUT/ExportOptions.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>method</key><string>app-store-connect</string>
	<key>destination</key><string>$DESTINATION</string>
	<key>teamID</key><string>$TEAM</string>
	<key>signingStyle</key><string>automatic</string>
	<key>uploadSymbols</key><true/>
	<key>manageAppVersionAndBuildNumber</key><false/>
</dict>
</plist>
PLIST

fi
echo "Pointe $VERSION ($CURRENT): exporting ($DESTINATION$([ "$MANUAL" = 1 ] && echo ", manual signing"))"
PROVISIONING=(-allowProvisioningUpdates); [ "$MANUAL" = 1 ] && PROVISIONING=()  # manual: the installed profiles, no account
xcodebuild -exportArchive -archivePath "$OUT/Pointe.xcarchive" -exportPath "$OUT/export" \
  -exportOptionsPlist "$OUT/ExportOptions.plist" ${PROVISIONING[@]+"${PROVISIONING[@]}"} -quiet

if [ "$DESTINATION" = upload ]; then
  echo "ok       Pointe $VERSION ($CURRENT) uploaded to App Store Connect; it shows in TestFlight once processed"
else
  echo "ok       Pointe $VERSION ($CURRENT) exported to apps/ios/$OUT/export; upload it with Transporter, or run again with --upload"
fi

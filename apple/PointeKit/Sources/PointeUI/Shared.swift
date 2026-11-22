// What the iPhone app takes from the package it shares with the Mac app (apple/PointeKit, docs/design/macos-app.md).
// Step 1: the wire format of the call (`Wire`: the PCM codec, the rates, the control messages). The models, the talk
// gate and the words are in the package too, and still in this target as well; tests/test_macos_parity.py holds the two
// copies to each other until each moves.
import PointeKit

typealias Wire = PointeKit.Wire
/// Step 2: starting a new session (docs/design/new-session.md): what the Mac offers, the sheet's draft, the rows.
typealias NewSession = PointeKit.NewSession
/// Its words, the page's (ui.html, NEW_COPY): one dictionary for both apps.
typealias NewSessionCopy = PointeKit.NewSessionCopy
/// Step 3: the night shift (docs/design/night-shift.md): what the Mac offers, the sheet's draft, the ledger.
typealias NightShift = PointeKit.NightShift
/// Its words, the page's (ui.html, NIGHT_SHIFT_COPY): one dictionary for both apps.
typealias NightShiftCopy = PointeKit.NightShiftCopy
/// Which coding agent runs a session, as a neutral letter tile (assets/theme.json): one table for both apps.
typealias Harness = PointeKit.Harness

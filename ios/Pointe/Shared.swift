// What the iPhone app takes from the package it shares with the Mac app (apple/PointeKit, docs/design/macos-app.md).
// Step 1: the wire format of the call (`Wire`: the PCM codec, the rates, the control messages). The models, the talk
// gate and the words are in the package too, and still in this target as well; tests/test_macos_parity.py holds the two
// copies to each other until each moves.
import PointeKit

typealias Wire = PointeKit.Wire

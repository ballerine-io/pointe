import Foundation

/// The microphone's words, on the page (ui.html), the iPhone and the Mac. The microphone is on or off; "mute" is said
/// only of Pointe's voice (the button beside the status line), so the two are never taken for each other.
public enum MicCopy {
    /// The state line while the microphone is off.
    public static let off = "Mic off"
    /// The mic button, by what a press does.
    public static let turnOff = "Turn mic off"
    public static let turnOn = "Turn mic on"
}

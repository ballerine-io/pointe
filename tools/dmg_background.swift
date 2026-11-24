// The disk image's background (tools/build_dmg.sh): the brand's surface, one line of help and an orange arrow from the
// app to Applications, drawn with AppKit at 1x and 2x. Usage: swift tools/dmg_background.swift <out.png> <scale>
// The icon places (170, 200) and (490, 200) in a 660 x 400 window are build_dmg.sh's: change them together.
import AppKit

let args = CommandLine.arguments
guard args.count == 3, let scale = Double(args[2]) else {
    FileHandle.standardError.write("usage: dmg_background.swift <out.png> <scale>\n".data(using: .utf8)!)
    exit(2)
}
let (width, height) = (660.0, 400.0)
func hex(_ value: UInt32) -> NSColor {
    NSColor(srgbRed: CGFloat((value >> 16) & 0xFF) / 255, green: CGFloat((value >> 8) & 0xFF) / 255, blue: CGFloat(value & 0xFF) / 255, alpha: 1)
}

let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(width * scale), pixelsHigh: Int(height * scale), bitsPerSample: 8,
                           samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
rep.size = NSSize(width: width, height: height)
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)

hex(0xFCFAFA).setFill()  // --surface
NSRect(x: 0, y: 0, width: width, height: height).fill()
hex(0xF5F1EF).setFill()  // --raised: the band the two icons sit on
NSRect(x: 0, y: 112, width: width, height: 176).fill()

func text(_ string: String, size: CGFloat, weight: NSFont.Weight, color: NSColor, y: CGFloat) {
    let style = NSMutableParagraphStyle()
    style.alignment = .center
    let attributes: [NSAttributedString.Key: Any] = [.font: NSFont.systemFont(ofSize: size, weight: weight), .foregroundColor: color,
                                                     .paragraphStyle: style, .kern: -0.2]
    NSAttributedString(string: string, attributes: attributes).draw(in: NSRect(x: 0, y: y, width: width, height: size * 1.5))
}
// AppKit's y grows upward: the window's top is y = 400.
text("Drag Pointe to Applications", size: 22, weight: .semibold, color: hex(0x0A0400), y: 330)
text("Then open it from Applications: Pointe sets up the rest.", size: 13, weight: .regular, color: hex(0x5C5450), y: 56)

let arrow = NSBezierPath()  // from the app (x 170) to Applications (x 490), at the icons' middle (window y 200 -> 200)
arrow.move(to: NSPoint(x: 262, y: 200))
arrow.line(to: NSPoint(x: 392, y: 200))
arrow.move(to: NSPoint(x: 380, y: 210))
arrow.line(to: NSPoint(x: 394, y: 200))
arrow.line(to: NSPoint(x: 380, y: 190))
arrow.lineWidth = 3
arrow.lineCapStyle = .round
arrow.lineJoinStyle = .round
hex(0xFF5A01).setStroke()  // --orange
arrow.stroke()

NSGraphicsContext.restoreGraphicsState()
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: args[1]))

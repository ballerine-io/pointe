// Draws the Mac app icon from the Chorus mark (docs/brand/logo.md):
//   swift apps/macos/tools/make_icon.swift docs/brand apps/macos/PointeMac/Assets.xcassets/AppIcon.appiconset
//
// A macOS icon is not the iOS one: on a 1024 canvas the tile is 824 points square with rounded corners, centred, with
// its own soft shadow, so it sits like the other icons in the Dock (Apple HIG, App icons, macOS). The ground, the glow
// and the outward fade are app-icon.svg's. The dots are read from the brand's SVG files (cx, cy, r), so the icon
// follows them: the full drawing at 48 pixels and above, the favicon drawing (three rings) below, as the brand rules
// ask.
import AppKit
import Foundation

let args = CommandLine.arguments
guard args.count == 3 else {
    FileHandle.standardError.write(Data("usage: make_icon.swift <docs/brand> <AppIcon.appiconset>\n".utf8))
    exit(2)
}
typealias Dot = (x: Double, y: Double, r: Double)
let pattern = try NSRegularExpression(pattern: #"<circle cx="([\d.]+)" cy="([\d.]+)" r="([\d.]+)""#)

func dots(_ file: String, atLeast: Int) -> [Dot] {
    guard let svg = try? String(contentsOfFile: args[1] + "/" + file, encoding: .utf8) else { fatalError("cannot read \(file)") }
    let found: [Dot] = pattern.matches(in: svg, range: NSRange(svg.startIndex..., in: svg)).compactMap { m in
        func n(_ i: Int) -> Double? { Range(m.range(at: i), in: svg).flatMap { Double(svg[$0]) } }
        guard let x = n(1), let y = n(2), let r = n(3) else { return nil }
        return (x, y, r)
    }
    guard found.count >= atLeast else { fatalError("\(file): \(found.count) dots") }
    return found
}
let full = dots("logo-mono.svg", atLeast: 121), small = dots("favicon.svg", atLeast: 49)

func color(_ hex: UInt32, _ alpha: CGFloat = 1) -> CGColor {
    CGColor(srgbRed: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255, blue: CGFloat(hex & 0xFF) / 255, alpha: alpha)
}
/// Each ring fades outward, as in the brand's app icon.
func opacity(_ r: Double) -> CGFloat { r >= 2.6 ? 1 : r >= 2.3 ? 0.9 : r >= 2.0 ? 0.74 : r >= 1.7 ? 0.56 : 0.4 }

func draw(_ size: Int) -> Data {
    let fullDrawing = size >= 48  // never the full drawing below 48 pixels
    let dots = fullDrawing ? full : small
    let space = CGColorSpace(name: CGColorSpace.sRGB)!
    let ctx = CGContext(data: nil, width: size, height: size, bitsPerComponent: 8, bytesPerRow: 0, space: space,
                        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
    let s = CGFloat(size) / 1024
    ctx.scaleBy(x: s, y: s)
    ctx.translateBy(x: 0, y: 1024); ctx.scaleBy(x: 1, y: -1)  // SVG coordinates: y down
    let tile = CGRect(x: 100, y: 100, width: 824, height: 824)
    let shape = CGPath(roundedRect: tile, cornerWidth: 185.4, cornerHeight: 185.4, transform: nil)
    ctx.saveGState()
    ctx.setShadow(offset: CGSize(width: 0, height: -10 * s), blur: 20 * s, color: color(0x000000, 0.30))
    ctx.addPath(shape); ctx.setFillColor(color(0x0A0400)); ctx.fillPath()
    ctx.restoreGState()
    ctx.saveGState()
    ctx.addPath(shape); ctx.clip()
    let ground = CGGradient(colorsSpace: space, colors: [color(0x1C120B), color(0x0A0400)] as CFArray, locations: [0, 1])!
    let centre = CGPoint(x: tile.midX, y: tile.minY + tile.height * 0.42)
    ctx.drawRadialGradient(ground, startCenter: centre, startRadius: 0, endCenter: centre, endRadius: tile.width * 0.75, options: .drawsAfterEndLocation)
    let glow = CGGradient(colorsSpace: space, colors: [color(0xFF5A01, 0.62), color(0xFF5A01, 0.17), color(0xFF5A01, 0)] as CFArray, locations: [0, 0.45, 1])!
    let mid = CGPoint(x: tile.midX, y: tile.midY)
    ctx.drawRadialGradient(glow, startCenter: mid, startRadius: 0, endCenter: mid, endRadius: tile.width * 0.44, options: [])
    let unit = tile.width * 0.8 / 100, origin = tile.minX + tile.width * 0.1  // the mark, at 80% of the tile
    for dot in dots {
        let point = dot.x == 50 && dot.y == 50  // the orange point, never recoloured
        ctx.setFillColor(point ? color(0xFF5A01) : color(0xF7F2F0, fullDrawing ? opacity(dot.r) : 1))
        let r = dot.r * unit
        ctx.fillEllipse(in: CGRect(x: origin + dot.x * unit - r, y: origin + dot.y * unit - r, width: 2 * r, height: 2 * r))
    }
    ctx.restoreGState()
    let rep = NSBitmapImageRep(cgImage: ctx.makeImage()!)
    return rep.representation(using: .png, properties: [:])!
}

var images: [[String: String]] = []
for (points, scale) in [(16, 1), (16, 2), (32, 1), (32, 2), (128, 1), (128, 2), (256, 1), (256, 2), (512, 1), (512, 2)] {
    let name = "icon_\(points)x\(points)\(scale == 2 ? "@2x" : "").png"
    try draw(points * scale).write(to: URL(fileURLWithPath: args[2]).appendingPathComponent(name))
    images.append(["idiom": "mac", "size": "\(points)x\(points)", "scale": "\(scale)x", "filename": name])
}
let contents: [String: Any] = ["images": images, "info": ["author": "xcode", "version": 1]]
try JSONSerialization.data(withJSONObject: contents, options: [.prettyPrinted, .sortedKeys])
    .write(to: URL(fileURLWithPath: args[2]).appendingPathComponent("Contents.json"))
print("wrote \(images.count) sizes")

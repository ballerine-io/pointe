import SwiftUI
import XCTest
@testable import PointeUI

/// Your bubbles sit at the right, but their lines start where the text reads from: English at the bubble's left edge,
/// Hebrew at its right (docs/design/ux-review-ios.md, C1).
@MainActor
final class BubbleAlignmentTests: XCTestCase {
    func testWhereALineStartsFollowsTheTextNotTheBubble() {
        XCTAssertEqual(Bubble.textStart("Run the checkout tests again", in: .leftToRight), .leading)
        XCTAssertEqual(Bubble.textStart("תריץ שוב את הבדיקות", in: .leftToRight), .trailing)
        XCTAssertEqual(Bubble.textStart("תריץ שוב את הבדיקות", in: .rightToLeft), .leading)
        XCTAssertEqual(Bubble.textStart("Run the checkout tests again", in: .rightToLeft), .trailing)
    }

    /// Drawn, then read back: each line's ink starts at the same x for English (and ends at different ones), and ends at
    /// the same x for Hebrew. Two lines of very different lengths make the difference plain.
    func testYourEnglishLinesShareTheLeftEdgeAndYourHebrewLinesTheRight() throws {
        let english = try lines(of: "Please run the whole checkout suite again on the branch\nthen stop")
        let (eLong, eShort) = (english.max { $0.width < $1.width }!, english.min { $0.width < $1.width }!)
        XCTAssertGreaterThanOrEqual(english.count, 2)
        XCTAssertLessThan(abs(eLong.start - eShort.start), 3, "the lines start together: \(english)")
        XCTAssertGreaterThan(eLong.end - eShort.end, 40, "and end apart: \(english)")

        let hebrew = try lines(of: "תריץ שוב את כל הבדיקות של התשלום על הענף הזה\nואז תעצור")
        let (hLong, hShort) = (hebrew.max { $0.width < $1.width }!, hebrew.min { $0.width < $1.width }!)
        XCTAssertGreaterThanOrEqual(hebrew.count, 2)
        XCTAssertLessThan(abs(hLong.end - hShort.end), 3, "the lines end together at the right: \(hebrew)")
        XCTAssertGreaterThan(hShort.start - hLong.start, 40, "and start apart: \(hebrew)")
    }

    private struct Line: CustomStringConvertible {
        let start: Int, end: Int
        var width: Int { end - start }
        var description: String { "\(start)…\(end)" }
    }

    /// The text rows of a user's bubble, 360 points wide, light: the leftmost and rightmost dark pixel of each.
    private func lines(of text: String) throws -> [Line] {
        let turn = API.Turn(id: 1, who: "user", text: text, understood: nil, typed: false, corrected: false)
        let view = Bubble(turn: turn, polish: false).frame(width: 360).padding(8).background(Color.white)
            .environment(\.colorScheme, .light).environment(\.layoutDirection, .leftToRight)
        let renderer = ImageRenderer(content: view)
        renderer.scale = 1
        let image = try XCTUnwrap(renderer.cgImage)
        let width = image.width, height = image.height
        var pixels = [UInt8](repeating: 0, count: width * height * 4)
        let context = try XCTUnwrap(CGContext(data: &pixels, width: width, height: height, bitsPerComponent: 8, bytesPerRow: width * 4,
                                              space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
        context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
        func ink(_ x: Int, _ y: Int) -> Bool {
            let i = (y * width + x) * 4
            return (Int(pixels[i]) + Int(pixels[i + 1]) + Int(pixels[i + 2])) / 3 < 110  // the text, not the bubble or its hairline
        }
        var rows: [Line] = [], band: [Line] = []
        for y in 0..<height {
            let xs = (0..<width).filter { ink($0, y) }
            if let first = xs.first, let last = xs.last { band.append(Line(start: first, end: last)) }
            else if !band.isEmpty {
                rows.append(Line(start: band.map(\.start).min()!, end: band.map(\.end).max()!))
                band = []
            }
        }
        return rows.filter { $0.end - $0.start > 20 }  // whole lines, not a stray dot
    }
}

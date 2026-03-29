import SwiftUI

/// iMessage-style bubble tail. The key to getting this right:
/// the tail is WIDE at the base (where it meets the bubble) and
/// curves into a small tip. It's essentially a thick comma shape.
struct BubbleTail: Shape {
    let isUser: Bool

    func path(in rect: CGRect) -> Path {
        var path = Path()

        if isUser {
            // Right tail (user messages)
            // Starts wide at the left (bubble edge), curves to tip at bottom-right
            path.move(to: CGPoint(x: rect.minX, y: rect.minY))
            path.addLine(to: CGPoint(x: rect.minX, y: rect.maxY * 0.55))
            path.addCurve(
                to: CGPoint(x: rect.maxX * 0.95, y: rect.maxY * 0.95),
                control1: CGPoint(x: rect.minX, y: rect.maxY * 0.9),
                control2: CGPoint(x: rect.maxX * 0.6, y: rect.maxY * 0.95)
            )
            path.addCurve(
                to: CGPoint(x: rect.maxX * 0.15, y: rect.maxY * 0.35),
                control1: CGPoint(x: rect.maxX * 0.75, y: rect.maxY * 0.7),
                control2: CGPoint(x: rect.maxX * 0.3, y: rect.maxY * 0.4)
            )
            path.addLine(to: CGPoint(x: rect.minX, y: rect.minY))
        } else {
            // Left tail (twin messages) — mirror
            path.move(to: CGPoint(x: rect.maxX, y: rect.minY))
            path.addLine(to: CGPoint(x: rect.maxX, y: rect.maxY * 0.55))
            path.addCurve(
                to: CGPoint(x: rect.maxX * 0.05, y: rect.maxY * 0.95),
                control1: CGPoint(x: rect.maxX, y: rect.maxY * 0.9),
                control2: CGPoint(x: rect.maxX * 0.4, y: rect.maxY * 0.95)
            )
            path.addCurve(
                to: CGPoint(x: rect.maxX * 0.85, y: rect.maxY * 0.35),
                control1: CGPoint(x: rect.maxX * 0.25, y: rect.maxY * 0.7),
                control2: CGPoint(x: rect.maxX * 0.7, y: rect.maxY * 0.4)
            )
            path.addLine(to: CGPoint(x: rect.maxX, y: rect.minY))
        }

        path.closeSubpath()
        return path
    }
}

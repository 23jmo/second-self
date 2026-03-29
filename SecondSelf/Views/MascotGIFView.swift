import SwiftUI
import AppKit
import ImageIO

/// Displays the animated mascot GIF from the bundle.
/// Uses NSImageView under the hood since SwiftUI's Image doesn't animate GIFs.
struct MascotGIFView: NSViewRepresentable {
    var width: CGFloat = 36
    var height: CGFloat = 46

    func makeNSView(context: Context) -> NSImageView {
        let imageView = NSImageView()
        imageView.animates = true
        imageView.canDrawSubviewsIntoLayer = true
        imageView.imageScaling = .scaleProportionallyUpOrDown
        imageView.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        imageView.setContentCompressionResistancePriority(.defaultLow, for: .vertical)
        imageView.wantsLayer = true
        imageView.layer?.backgroundColor = .clear

        if let gifURL = Bundle.module.url(forResource: "mascot", withExtension: "gif", subdirectory: "Resources"),
           let image = NSImage(contentsOf: gifURL) {
            // Force all reps to load so animation plays
            image.representations.forEach { rep in
                if let bitmapRep = rep as? NSBitmapImageRep {
                    bitmapRep.setProperty(.loopCount, withValue: NSNumber(value: 0))
                }
            }
            imageView.image = image
        }

        return imageView
    }

    func updateNSView(_ nsView: NSImageView, context: Context) {
        // Re-enable animation if it stopped (e.g. view reappeared)
        nsView.animates = true
    }
}

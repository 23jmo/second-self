import AppKit

let app = NSApplication.shared
app.setActivationPolicy(.accessory)

MainActor.assumeIsolated {
    let delegate = AppDelegate()
    app.delegate = delegate
}

app.run()

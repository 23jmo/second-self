import AppKit
import SwiftUI

// Force a real windowed app
let app = NSApplication.shared
app.setActivationPolicy(.regular)

let window = NSWindow(
    contentRect: NSRect(x: 200, y: 200, width: 800, height: 600),
    styleMask: [.titled, .closable, .resizable],
    backing: .buffered,
    defer: false
)
window.title = "MJPEG Stream Test"
window.contentView = NSHostingView(rootView: MJPEGTestView())
window.makeKeyAndOrderFront(nil)
app.activate(ignoringOtherApps: true)

app.run()

// MARK: - Views

struct MJPEGTestView: View {
    @StateObject private var streamer = TestMJPEGStreamer()

    var body: some View {
        VStack(spacing: 16) {
            Text("MJPEG Stream Tester")
                .font(.title2.bold())

            Group {
                if let image = streamer.currentFrame {
                    Image(nsImage: image)
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                } else {
                    Rectangle()
                        .fill(Color.black)
                        .overlay(
                            Text(streamer.status)
                                .foregroundColor(.white)
                                .font(.system(size: 14, design: .monospaced))
                        )
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .cornerRadius(8)

            HStack {
                Text("Frames: \(streamer.frameCount)")
                Spacer()
                Text("Port: \(streamer.connectedPort ?? 0)")
                Spacer()
                Button(streamer.isRunning ? "Stop" : "Start") {
                    if streamer.isRunning { streamer.stop() } else { streamer.start() }
                }
            }
            .font(.system(size: 12, design: .monospaced))

            ScrollView {
                Text(streamer.log)
                    .font(.system(size: 11, design: .monospaced))
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(height: 120)
            .background(Color.black.opacity(0.05))
            .cornerRadius(4)
        }
        .padding()
        .onAppear { streamer.start() }
    }
}

// MARK: - Streamer

final class TestMJPEGStreamer: NSObject, ObservableObject, URLSessionDataDelegate {
    @Published var currentFrame: NSImage?
    @Published var frameCount = 0
    @Published var status = "Not connected"
    @Published var log = ""
    @Published var isRunning = false
    @Published var connectedPort: Int?

    private var session: URLSession?
    private var task: URLSessionDataTask?
    private var buffer = Data()
    private let ports = [8421, 8422, 8423]
    private var portIndex = 0

    func addLog(_ msg: String) {
        let ts = DateFormatter.localizedString(from: Date(), dateStyle: .none, timeStyle: .medium)
        log += "[\(ts)] \(msg)\n"
        print("[MJPEGTest] \(msg)")
    }

    func start() {
        isRunning = true
        portIndex = 0
        tryConnect()
    }

    func stop() {
        isRunning = false
        task?.cancel()
        session?.invalidateAndCancel()
        session = nil
        status = "Stopped"
    }

    private func tryConnect() {
        guard isRunning, portIndex < ports.count else {
            if isRunning {
                addLog("All ports failed. Retrying in 3s...")
                portIndex = 0
                DispatchQueue.main.asyncAfter(deadline: .now() + 3) { [weak self] in
                    self?.tryConnect()
                }
            }
            return
        }

        let port = ports[portIndex]
        addLog("Connecting to port \(port)...")
        status = "Connecting to :\(port)..."

        session?.invalidateAndCancel()
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 30
        config.timeoutIntervalForResource = 3600
        session = URLSession(configuration: config, delegate: self, delegateQueue: .main)

        var request = URLRequest(url: URL(string: "http://localhost:\(port)/stream")!)
        request.cachePolicy = .reloadIgnoringLocalCacheData
        task = session?.dataTask(with: request)
        task?.resume()
    }

    func urlSession(_ s: URLSession, dataTask: URLSessionDataTask, didReceive response: URLResponse, completionHandler: @escaping (URLSession.ResponseDisposition) -> Void) {
        if let http = response as? HTTPURLResponse {
            addLog("HTTP \(http.statusCode) from :\(ports[portIndex])")
            connectedPort = ports[portIndex]
            status = "Connected"
        }
        completionHandler(.allow)
    }

    func urlSession(_ s: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        buffer.append(data)
        extractFrames()
    }

    func urlSession(_ s: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        if let e = error { addLog("Error: \(e.localizedDescription)") }
        connectedPort = nil
        if isRunning { portIndex += 1; buffer.removeAll(); tryConnect() }
    }

    private func extractFrames() {
        while let s = buffer.firstRange(of: Data([0xFF, 0xD8])),
              let e = buffer[s.lowerBound...].firstRange(of: Data([0xFF, 0xD9])) {
            let frame = Data(buffer[s.lowerBound...e.upperBound - 1])
            if let img = NSImage(data: frame) {
                currentFrame = img
                frameCount += 1
                if frameCount <= 3 || frameCount % 30 == 0 {
                    addLog("Frame \(frameCount): \(frame.count/1024)KB")
                }
            }
            buffer.removeSubrange(..<e.upperBound)
        }
        if buffer.count > 5_000_000 { buffer.removeAll() }
    }
}

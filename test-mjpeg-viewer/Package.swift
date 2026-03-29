// swift-tools-version: 5.9
import PackageDescription
let package = Package(
    name: "MJPEGTest",
    platforms: [.macOS(.v13)],
    targets: [
        .executableTarget(name: "MJPEGTest", path: ".")
    ]
)

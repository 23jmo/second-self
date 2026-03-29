// swift-tools-version: 5.9

import PackageDescription

let package = Package(
    name: "SecondSelf",
    platforms: [
        .macOS(.v13)
    ],
    targets: [
        .executableTarget(
            name: "SecondSelf",
            path: ".",
            exclude: ["Info.plist", "Package.swift"],
            resources: [
                .process("Assets.xcassets")
            ]
        )
    ]
)

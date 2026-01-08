import Foundation
import Vision
import AppKit

// Check command line arguments
guard CommandLine.arguments.count > 1 else {
    print("Usage: swift ocr.swift <image_path>")
    exit(1)
}

let imagePath = CommandLine.arguments[1]

// Load the image
guard let image = NSImage(contentsOfFile: imagePath) else {
    print("Error: Could not load image from \(imagePath)")
    exit(1)
}

guard let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    print("Error: Could not convert to CGImage")
    exit(1)
}

// Create a request handler
let requestHandler = VNImageRequestHandler(cgImage: cgImage, options: [:])

// Create the request
let request = VNRecognizeTextRequest { (request, error) in
    if let error = error {
        print("Error recognizing text: \(error)")
        exit(1)
    }

    guard let observations = request.results as? [VNRecognizedTextObservation] else {
        return
    }

    let recognizedStrings = observations.compactMap { observation in
        // Return the string of the top VNRecognizedText instance.
        return observation.topCandidates(1).first?.string
    }

    // Print the results joined by newlines
    print(recognizedStrings.joined(separator: "\n"))
}

// Configure for accuracy
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true

// Perform the request
do {
    try requestHandler.perform([request])
} catch {
    print("Error performing request: \(error)")
    exit(1)
}

#!/bin/bash
set -e

echo "Building Lambda deployment package..."

# Clean previous builds
rm -rf build ocr-processor.zip

# Create build directory
mkdir build
cd build

# Simple pip install (let pip handle platform detection)
pip install \
    --target . \
    --only-binary=:all: \
    boto3==1.34.128 \
    Pillow==11.0.0 \
    pytesseract==0.3.10

# Copy Lambda function
cp ../lambda_function.py .

# Create deployment package
zip -r ../ocr-processor.zip . -x "*.pyc" "*/__pycache__/*"

# Clean up
cd ..
rm -rf build

echo "✅ Lambda package created: ocr-processor.zip"
echo "📦 Package size: $(du -h ocr-processor.zip | cut -f1)"
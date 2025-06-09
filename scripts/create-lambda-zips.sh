#!/bin/bash

echo "Creating Lambda deployment packages..."

# API Handler
cd src/api-handler
zip -r api-handler.zip lambda_function.py
echo "✅ Created api-handler.zip"
cd ../..

# OCR Processor  
cd src/ocr-processor
zip -r ocr-processor.zip lambda_function.py
echo "✅ Created ocr-processor.zip"
cd ../..

# Step Functions Trigger
cd src/step-functions-trigger
zip -r step-functions-trigger.zip lambda_function.py
echo "✅ Created step-functions-trigger.zip"
cd ../..

echo "🚀 All Lambda packages created successfully!"
echo "📁 ZIP files are in .gitignore and won't be committed"
import json
import boto3
import uuid
import re
from datetime import datetime
import logging
from PIL import Image, ImageEnhance, ImageFilter
import pytesseract
import io
import base64
from typing import Dict, Any, Optional, Tuple

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')
bedrock = boto3.client('bedrock-runtime')

TABLE_NAME = 'receipt-parser-receipts'

class ReceiptProcessor:
    """Robust receipt processing with multiple fallback mechanisms"""
    
    def __init__(self):
        self.supported_formats = ['.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.webp']
        self.max_file_size = 10 * 1024 * 1024  # 10MB
        
    def process_receipt(self, bucket: str, key: str) -> Dict[str, Any]:
        """Main processing pipeline with error handling"""
        try:
            # Download and validate image
            image_data = self.download_and_validate_image(bucket, key)
            
            # Preprocess image for better OCR
            processed_images = self.preprocess_image(image_data)
            
            # Try OCR with multiple approaches
            extracted_text = self.extract_text_robust(processed_images)
            
            # Validate extracted text quality
            if not self.is_text_quality_good(extracted_text):
                logger.warning("Poor OCR quality detected")
                # Could trigger manual review or alternative processing
            
            # Process with Bedrock (with retries)
            receipt_data = self.categorize_expense_robust(extracted_text)
            
            # Post-process and validate results
            receipt_data = self.validate_and_clean_data(receipt_data, extracted_text)
            
            # Store with metadata
            receipt_id = str(uuid.uuid4())
            self.store_receipt_comprehensive(receipt_id, key, extracted_text, receipt_data)
            
            return {
                'success': True,
                'receipt_id': receipt_id,
                'confidence': receipt_data.get('confidence', 0.0)
            }
            
        except Exception as e:
            logger.error(f"Receipt processing failed: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'needs_manual_review': True
            }
    
    def download_and_validate_image(self, bucket: str, key: str) -> bytes:
        """Download with validation and size limits"""
        try:
            # Check file extension
            if not any(key.lower().endswith(ext) for ext in self.supported_formats):
                raise ValueError(f"Unsupported file format: {key}")
            
            # Get object metadata first
            head_response = s3_client.head_object(Bucket=bucket, Key=key)
            file_size = head_response['ContentLength']
            
            if file_size > self.max_file_size:
                raise ValueError(f"File too large: {file_size} bytes")
            
            # Download the image
            response = s3_client.get_object(Bucket=bucket, Key=key)
            image_data = response['Body'].read()
            
            # Validate it's actually an image
            try:
                Image.open(io.BytesIO(image_data)).verify()
            except Exception:
                raise ValueError("Invalid image file")
            
            return image_data
            
        except Exception as e:
            logger.error(f"Image download/validation failed: {str(e)}")
            raise
    
    def preprocess_image(self, image_data: bytes) -> List[Image.Image]:
        """Create multiple processed versions for better OCR"""
        try:
            original = Image.open(io.BytesIO(image_data))
            
            # Convert to RGB if needed
            if original.mode != 'RGB':
                original = original.convert('RGB')
            
            processed_images = [original]  # Keep original
            
            # Enhanced contrast version
            enhancer = ImageEnhance.Contrast(original)
            enhanced = enhancer.enhance(1.5)
            processed_images.append(enhanced)
            
            # Sharpened version
            sharpened = original.filter(ImageFilter.SHARPEN)
            processed_images.append(sharpened)
            
            # Grayscale version (often better for OCR)
            grayscale = original.convert('L')
            processed_images.append(grayscale)
            
            # High contrast B&W version
            threshold = 128
            bw = grayscale.point(lambda x: 255 if x > threshold else 0, mode='1')
            processed_images.append(bw)
            
            return processed_images
            
        except Exception as e:
            logger.error(f"Image preprocessing failed: {str(e)}")
            # Return original image as fallback
            return [Image.open(io.BytesIO(image_data))]
    
    def extract_text_robust(self, images: List[Image.Image]) -> str:
        """Try OCR with multiple configurations"""
        best_text = ""
        best_confidence = 0
        
        # Different OCR configurations
        ocr_configs = [
            '--oem 3 --psm 6',  # Default
            '--oem 3 --psm 4',  # Single column text
            '--oem 3 --psm 3',  # Fully automatic page segmentation
            '--oem 3 --psm 7',  # Single text line
            '--oem 3 --psm 8',  # Single word
        ]
        
        for img in images:
            for config in ocr_configs:
                try:
                    # Get text with confidence
                    data = pytesseract.image_to_data(img, config=config, output_type=pytesseract.Output.DICT)
                    
                    # Calculate average confidence
                    confidences = [int(conf) for conf in data['conf'] if int(conf) > 0]
                    if confidences:
                        avg_confidence = sum(confidences) / len(confidences)
                        
                        # Get text
                        text = pytesseract.image_to_string(img, config=config).strip()
                        
                        if avg_confidence > best_confidence and len(text) > 10:
                            best_confidence = avg_confidence
                            best_text = text
                            
                except Exception as e:
                    logger.warning(f"OCR attempt failed: {str(e)}")
                    continue
        
        if not best_text:
            # Final fallback - basic OCR
            try:
                best_text = pytesseract.image_to_string(images[0]).strip()
            except:
                best_text = "OCR_FAILED"
        
        logger.info(f"Best OCR confidence: {best_confidence}%")
        return best_text
    
    def is_text_quality_good(self, text: str) -> bool:
        """Assess if OCR output is reasonable"""
        if len(text) < 10:
            return False
        
        # Check for reasonable ratio of alphanumeric characters
        alnum_ratio = sum(c.isalnum() for c in text) / len(text)
        
        # Look for common receipt indicators
        receipt_indicators = ['total', 'amount', 'tax', 'subtotal', '$', '£', '€', 'receipt']
        has_indicators = any(indicator in text.lower() for indicator in receipt_indicators)
        
        return alnum_ratio > 0.3 and has_indicators
    
    def categorize_expense_robust(self, text: str) -> Dict[str, Any]:
        """Enhanced Bedrock processing with fallbacks"""
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                # Enhanced prompt for better results
                prompt = f"""
                You are an expert at analyzing receipts. Extract information from this receipt text:
                
                RECEIPT TEXT:
                {text}
                
                INSTRUCTIONS:
                1. Find the TOTAL amount (not subtotal, not tax, the final total)
                2. Identify the business name/vendor
                3. Categorize using ONLY these categories: Food, Office, Travel, Equipment, Entertainment, Fuel, Healthcare, Other
                4. Determine confidence (0.0-1.0) based on text clarity
                5. Extract date if clearly visible (YYYY-MM-DD format)
                6. Detect currency (USD, GBP, EUR, etc.)
                
                Respond with ONLY valid JSON:
                {{
                    "amount": <number>,
                    "vendor": "<business name>",
                    "category": "<category>",
                    "confidence": <0.0-1.0>,
                    "date": "<YYYY-MM-DD or null>",
                    "currency": "<currency code>",
                    "reasoning": "<brief explanation>"
                }}
                """
                
                response = bedrock.invoke_model(
                    modelId='anthropic.claude-3-sonnet-20240229-v1:0',
                    body=json.dumps({
                        'anthropic_version': 'bedrock-2023-05-31',
                        'max_tokens': 1500,
                        'messages': [{'role': 'user', 'content': prompt}]
                    })
                )
                
                result = json.loads(response['body'].read())
                claude_response = result['content'][0]['text']
                
                # More robust JSON parsing
                receipt_data = self.parse_claude_response(claude_response)
                
                if receipt_data:
                    logger.info(f"Successfully categorized (attempt {attempt + 1})")
                    return receipt_data
                    
            except Exception as e:
                logger.warning(f"Bedrock attempt {attempt + 1} failed: {str(e)}")
                if attempt == max_retries - 1:
                    # Final fallback - parse manually
                    return self.fallback_manual_parsing(text)
        
        return self.fallback_manual_parsing(text)
    
    def parse_claude_response(self, response: str) -> Optional[Dict[str, Any]]:
        """Robust JSON parsing from Claude response"""
        try:
            # Try direct JSON parsing
            return json.loads(response)
        except:
            try:
                # Extract JSON from response if wrapped in text
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group())
            except:
                pass
        return None
    
    def fallback_manual_parsing(self, text: str) -> Dict[str, Any]:
        """Manual parsing when AI fails"""
        logger.warning("Using fallback manual parsing")
        
        # Try to extract amount with regex
        amount_patterns = [
            r'total[:\s]*[\$£€]?(\d+\.?\d*)',
            r'[\$£€]\s*(\d+\.?\d*)\s*total',
            r'amount[:\s]*[\$£€]?(\d+\.?\d*)',
            r'[\$£€]\s*(\d+\.\d{2})'
        ]
        
        amount = 0.0
        for pattern in amount_patterns:
            match = re.search(pattern, text.lower())
            if match:
                try:
                    amount = float(match.group(1))
                    break
                except:
                    continue
        
        # Basic vendor extraction (first line that looks like a business name)
        lines = text.split('\n')
        vendor = "Unknown"
        for line in lines[:5]:  # Check first 5 lines
            if len(line.strip()) > 5 and not re.search(r'\d{2}/\d{2}', line):
                vendor = line.strip()[:50]  # Limit length
                break
        
        return {
            'amount': amount,
            'vendor': vendor,
            'category': 'Other',
            'confidence': 0.3,  # Low confidence for manual parsing
            'date': None,
            'currency': 'GBP',  # Default for UK
            'reasoning': 'Fallback manual parsing'
        }
    
    def validate_and_clean_data(self, data: Dict[str, Any], original_text: str) -> Dict[str, Any]:
        """Validate and clean extracted data"""
        # Ensure amount is reasonable
        if data.get('amount', 0) > 10000:  # Suspiciously high
            logger.warning(f"Suspiciously high amount: {data['amount']}")
            data['confidence'] = min(data.get('confidence', 0), 0.5)
        
        # Clean vendor name
        if data.get('vendor'):
            data['vendor'] = re.sub(r'[^\w\s&-]', '', data['vendor'])[:100]
        
        # Validate category
        valid_categories = ['Food', 'Office', 'Travel', 'Equipment', 'Entertainment', 'Fuel', 'Healthcare', 'Other']
        if data.get('category') not in valid_categories:
            data['category'] = 'Other'
        
        return data
    
    def store_receipt_comprehensive(self, receipt_id: str, s3_key: str, raw_text: str, processed_data: Dict[str, Any]):
        """Store with comprehensive metadata"""
        try:
            table = dynamodb.Table(TABLE_NAME)
            
            item = {
                'receiptId': receipt_id,
                'uploadTimestamp': datetime.utcnow().isoformat(),
                'originalText': raw_text[:5000],  # Limit size
                's3Key': s3_key,
                'amount': float(processed_data.get('amount', 0.0)),
                'vendor': processed_data.get('vendor', 'Unknown'),
                'category': processed_data.get('category', 'Other'),
                'confidence': float(processed_data.get('confidence', 0.0)),
                'receiptDate': processed_data.get('date'),
                'currency': processed_data.get('currency', 'GBP'),
                'needsReview': processed_data.get('confidence', 0.0) < 0.6,
                'processingMethod': processed_data.get('reasoning', 'AI processing'),
                'textLength': len(raw_text)
            }
            
            table.put_item(Item=item)
            logger.info(f"Stored receipt: {receipt_id} with confidence {item['confidence']}")
            
        except Exception as e:
            logger.error(f"Storage failed: {str(e)}")
            raise

# Main Lambda handler
def lambda_handler(event, context):
    processor = ReceiptProcessor()
    
    results = []
    for record in event['Records']:
        bucket = record['s3']['bucket']['name']
        key = record['s3']['object']['key']
        
        logger.info(f"Processing: {key}")
        result = processor.process_receipt(bucket, key)
        results.append(result)
    
    # Return summary
    successful = sum(1 for r in results if r.get('success'))
    total = len(results)
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'processed': total,
            'successful': successful,
            'results': results
        })
    }
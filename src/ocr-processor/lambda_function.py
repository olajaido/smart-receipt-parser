import json
import boto3
import uuid
from datetime import datetime
import logging
from decimal import Decimal
import re

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')
bedrock = boto3.client('bedrock-runtime')
textract = boto3.client('textract')

TABLE_NAME = 'receipt-parser-receipts'

def lambda_handler(event, context):
    """Universal receipt processor - handles any receipt format with optional line items"""
    try:
        for record in event['Records']:
            bucket = record['s3']['bucket']['name']
            key = record['s3']['object']['key']
            
            logger.info(f"Processing receipt: {key}")
            
            # Extract text from actual receipt image using Textract
            extracted_text = extract_text_from_image(bucket, key)
            
            if extracted_text == "OCR_FAILED":
                logger.error("Failed to extract text from receipt")
                return {
                    'statusCode': 500,
                    'body': json.dumps('Failed to process receipt image')
                }
            
            logger.info(f"Extracted text length: {len(extracted_text)} characters")
            
            # Process with Bedrock Claude (enhanced with line items)
            receipt_data = categorize_expense_enhanced(extracted_text)
            
            # Store in DynamoDB
            receipt_id = str(uuid.uuid4())
            store_receipt_data(receipt_id, key, extracted_text, receipt_data)
            
            logger.info(f"Successfully processed: {receipt_id}")
            
        return {
            'statusCode': 200,
            'body': json.dumps('Receipt processed successfully!')
        }
        
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps(f'Error: {str(e)}')
        }

def extract_text_from_image(bucket, key):
    """Use AWS Textract to extract text from any receipt format"""
    try:
        logger.info(f"Starting Textract on s3://{bucket}/{key}")
        
        response = textract.detect_document_text(
            Document={
                'S3Object': {
                    'Bucket': bucket,
                    'Name': key
                }
            }
        )
        
        # Extract all text lines
        text_lines = []
        for block in response['Blocks']:
            if block['BlockType'] == 'LINE':
                text_lines.append(block['Text'])
        
        extracted_text = '\n'.join(text_lines)
        logger.info(f"Textract extracted {len(text_lines)} lines of text")
        
        return extracted_text
        
    except Exception as e:
        logger.error(f"Textract error: {str(e)}")
        return "OCR_FAILED"

def categorize_expense_enhanced(text):
    """Enhanced expense categorization with line item support"""
    max_retries = 2
    
    for attempt in range(max_retries):
        try:
            logger.info(f"Claude attempt {attempt + 1}")
            
            prompt = f"""You are an expert at analyzing ANY type of receipt from anywhere in the world.

Analyze this receipt and extract whatever information is available:

RECEIPT TEXT:
{text}

INSTRUCTIONS:
- Extract the FINAL TOTAL (what customer actually paid)
- Find business/store name (ignore handwritten notes)
- Categorize using ONLY one of these: Food, Office, Travel, Equipment, Entertainment, Fuel, Healthcare, Other
- IF line items are clearly visible, extract them (description, quantity, prices)
- IF only totals are visible, that's perfectly fine - just extract totals
- IF tax information is visible, include it
- Provide confidence based on text clarity and completeness
- Extract date if clearly visible
- Detect currency symbols and codes

RESPOND WITH VALID JSON ONLY (no markdown, no explanation):

{{
  "amount": <final_total_number>,
  "vendor": "<business_name>", 
  "category": "<category>",
  "confidence": <0.0-1.0>,
  "currency": "<code>",
  "date": "<YYYY-MM-DD or null>",
  "lineItems": [
    {{"description": "<item_name>", "quantity": <number>, "unitPrice": <price>, "subtotal": <total>}}
  ],
  "subtotal": <subtotal_before_tax_or_null>,
  "totalTax": <tax_amount_or_null>,
  "hasDetailedItems": <true_or_false>
}}

IMPORTANT NOTES:
- If NO line items are clearly visible, return empty lineItems array
- If no tax breakdown visible, set totalTax to null
- Simple receipts (like coffee shops) are perfectly valid
- Don't create fake line items if they're not clearly visible
- Focus on accuracy over completeness"""
            
            response = bedrock.invoke_model(
                modelId='anthropic.claude-3-sonnet-20240229-v1:0',
                body=json.dumps({
                    'anthropic_version': 'bedrock-2023-05-31',
                    'max_tokens': 1500,
                    'messages': [{'role': 'user', 'content': prompt}]
                })
            )
            
            result = json.loads(response['body'].read())
            claude_response = result['content'][0]['text'].strip()
            
            logger.info(f"Claude raw response: {claude_response}")
            
            # Enhanced JSON parsing
            receipt_data = parse_claude_response_enhanced(claude_response)
            
            if receipt_data and validate_receipt_data_enhanced(receipt_data):
                logger.info(f"Successfully parsed: {receipt_data}")
                return receipt_data
            else:
                logger.warning(f"Invalid receipt data on attempt {attempt + 1}")
                continue
                
        except Exception as e:
            logger.warning(f"Claude attempt {attempt + 1} failed: {str(e)}")
            continue
    
    # If all Claude attempts fail, use intelligent fallback
    logger.warning("All Claude attempts failed, using intelligent fallback")
    return intelligent_fallback_extraction(text)

def parse_claude_response_enhanced(response):
    """Enhanced parsing for receipts with optional line items"""
    
    # Method 1: Direct JSON
    try:
        data = json.loads(response)
        # Ensure required fields exist
        if 'lineItems' not in data:
            data['lineItems'] = []
        if 'hasDetailedItems' not in data:
            data['hasDetailedItems'] = len(data.get('lineItems', [])) > 0
        return data
    except json.JSONDecodeError:
        pass
    
    # Method 2: Remove markdown code blocks
    try:
        cleaned = re.sub(r'```(?:json)?\s*', '', response)  
        cleaned = re.sub(r'```\s*$', '', cleaned)
        data = json.loads(cleaned.strip())
        if 'lineItems' not in data:
            data['lineItems'] = []
        if 'hasDetailedItems' not in data:
            data['hasDetailedItems'] = len(data.get('lineItems', [])) > 0
        return data
    except json.JSONDecodeError:
        pass
    
    # Method 3: Extract JSON object from text
    try:
        json_match = re.search(r'\{.*?"amount".*?\}', response, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            if 'lineItems' not in data:
                data['lineItems'] = []
            if 'hasDetailedItems' not in data:
                data['hasDetailedItems'] = len(data.get('lineItems', [])) > 0
            return data
    except json.JSONDecodeError:
        pass
    
    # Method 4: Manual field extraction
    try:
        amount_match = re.search(r'"amount":\s*([0-9.]+)', response)
        vendor_match = re.search(r'"vendor":\s*"([^"]+)"', response)
        category_match = re.search(r'"category":\s*"([^"]+)"', response)
        confidence_match = re.search(r'"confidence":\s*([0-9.]+)', response)
        currency_match = re.search(r'"currency":\s*"([^"]+)"', response)
        
        if amount_match and vendor_match and category_match:
            return {
                'amount': float(amount_match.group(1)),
                'vendor': vendor_match.group(1),
                'category': category_match.group(1),
                'confidence': float(confidence_match.group(1)) if confidence_match else 0.7,
                'currency': currency_match.group(1) if currency_match else 'GBP',
                'date': None,
                'lineItems': [],
                'subtotal': None,
                'totalTax': None,
                'hasDetailedItems': False
            }
    except Exception:
        pass
    
    return None

def validate_receipt_data_enhanced(data):
    """Enhanced validation - works for both simple and complex receipts"""
    if not isinstance(data, dict):
        return False
    
    # Check required basic fields
    required_fields = ['amount', 'vendor', 'category']
    if not all(field in data for field in required_fields):
        return False
    
    # Validate amount
    try:
        amount = float(data['amount'])
        if amount < 0 or amount > 1000000:  # Very broad bounds for any receipt
            return False
    except (ValueError, TypeError):
        return False
    
    # Validate category
    valid_categories = ['Food', 'Office', 'Travel', 'Equipment', 'Entertainment', 'Fuel', 'Healthcare', 'Other']
    if data['category'] not in valid_categories:
        return False
    
    # Validate vendor
    if not data['vendor'] or len(data['vendor'].strip()) < 2:
        return False
    
    # Line items are optional but if present, validate structure
    if 'lineItems' in data and data['lineItems']:
        if not isinstance(data['lineItems'], list):
            return False
        for item in data['lineItems']:
            if not isinstance(item, dict) or 'description' not in item:
                return False
            # Validate numeric fields if present
            for field in ['quantity', 'unitPrice', 'subtotal']:
                if field in item:
                    try:
                        float(item[field])
                    except (ValueError, TypeError):
                        return False
    
    return True

def intelligent_fallback_extraction(text):
    """Enhanced fallback with line item attempt"""
    logger.info("Using enhanced intelligent fallback extraction")
    
    # Universal amount detection
    amount_patterns = [
        r'(?:BALANCE|TOTAL|AMOUNT)\s+(?:DUE|PAID)?[:\s]*[£$€¥]?([0-9,]+\.?[0-9]*)',
        r'(?:GRAND|FINAL)\s*TOTAL[:\s]*[£$€¥]?([0-9,]+\.?[0-9]*)',
        r'[£$€¥]\s*([0-9,]+\.[0-9]{2})\s*(?:CASH|CARD|PAID)',
        r'TOTAL[:\s]*[£$€¥]?([0-9,]+\.?[0-9]*)',
    ]
    
    amount = 0.0
    for pattern in amount_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            try:
                amounts = [float(m.replace(',', '')) for m in matches]
                amount = max(amounts)
                logger.info(f"Found amount: {amount}")
                break
            except:
                continue
    
    # Universal vendor detection
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    vendor = "Unknown Store"
    
    business_keywords = ['ltd', 'limited', 'inc', 'corp', 'group', 'company', 'store', 'market', 'shop']
    for line in lines[:10]:
        if any(keyword in line.lower() for keyword in business_keywords):
            vendor = line[:60]
            break
    
    if vendor == "Unknown Store":
        for line in lines[:8]:
            if len(line) > 5 and not re.match(r'^\d+[./]\d+', line):
                vendor = line[:60]
                break
    
    # Enhanced categorization
    category = "Other"
    text_lower = text.lower()
    
    category_keywords = {
        "Food": ['grocery', 'supermarket', 'food', 'restaurant', 'cafe', 'coffee', 'pizza', 'burger', 'tesco', 'sainsbury', 'asda', 'coop', 'co-op', 'mcdonald', 'kfc'],
        "Fuel": ['petrol', 'gas', 'fuel', 'shell', 'bp', 'esso', 'texaco'],
        "Healthcare": ['pharmacy', 'chemist', 'boots', 'hospital', 'clinic', 'medical'],
        "Office": ['office', 'supplies', 'staples', 'paper', 'stationery'],
        "Travel": ['travel', 'train', 'bus', 'taxi', 'uber', 'hotel', 'airline', 'parking'],
        "Equipment": ['equipment', 'hardware', 'electronics', 'computer', 'software']
    }
    
    for cat, keywords in category_keywords.items():
        if any(word in text_lower for word in keywords):
            category = cat
            break
    
    # Currency detection
    currency = "GBP"
    if '$' in text:
        currency = "USD"
    elif '€' in text:
        currency = "EUR"
    elif '¥' in text:
        currency = "JPY"
    
    # Simple line item detection attempt
    line_items = []
    try:
        # Look for simple item patterns like "Item Name 5.99"
        item_patterns = [
            r'([A-Za-z][A-Za-z\s]+)\s+[£$€¥]?([0-9]+\.[0-9]{2})',
            r'([A-Za-z][A-Za-z\s]+)\s+([0-9]+\.[0-9]{2})'
        ]
        
        for pattern in item_patterns:
            matches = re.findall(pattern, text, re.MULTILINE)
            for match in matches[:10]:  # Limit to first 10 items
                description, price = match
                if len(description.strip()) > 2:
                    line_items.append({
                        'description': description.strip(),
                        'quantity': 1,
                        'unitPrice': float(price),
                        'subtotal': float(price)
                    })
            if line_items:
                break
    except:
        pass
    
    return {
        'amount': amount,
        'vendor': vendor,
        'category': category,
        'confidence': 0.6 if line_items else 0.5,
        'currency': currency,
        'date': None,
        'lineItems': line_items,
        'subtotal': sum(item['subtotal'] for item in line_items) if line_items else None,
        'totalTax': None,
        'hasDetailedItems': len(line_items) > 0
    }

def store_receipt_data(receipt_id, s3_key, raw_text, processed_data):
    """Enhanced storage for receipts with optional line items"""
    try:
        table = dynamodb.Table(TABLE_NAME)
        
        # Handle line items if they exist
        line_items = []
        if processed_data.get('lineItems'):
            for item in processed_data['lineItems']:
                line_item = {
                    'description': str(item.get('description', '')),
                    'quantity': Decimal(str(item.get('quantity', 1))),
                    'unitPrice': Decimal(str(item.get('unitPrice', 0))),
                    'subtotal': Decimal(str(item.get('subtotal', 0)))
                }
                # Optional fields
                if item.get('taxRate'):
                    line_item['taxRate'] = Decimal(str(item['taxRate']))
                if item.get('taxAmount'):
                    line_item['taxAmount'] = Decimal(str(item['taxAmount']))
                
                line_items.append(line_item)
        
        # Build the item for DynamoDB
        item = {
            'receiptId': receipt_id,
            'uploadTimestamp': datetime.utcnow().isoformat(),
            'originalText': raw_text[:2000],  # Truncate for storage
            's3Key': s3_key,
            'amount': Decimal(str(processed_data.get('amount', 0.0))),
            'vendor': processed_data.get('vendor', 'Unknown'),
            'category': processed_data.get('category', 'Other'),
            'confidence': Decimal(str(processed_data.get('confidence', 0.0))),
            'currency': processed_data.get('currency', 'GBP'),
            'receiptDate': processed_data.get('date'),
            'lineItems': line_items,
            'hasDetailedItems': processed_data.get('hasDetailedItems', len(line_items) > 0),
            'processingMethod': 'Enhanced Universal Textract + Claude AI'
        }
        
        # Add optional fields if they exist
        if processed_data.get('subtotal'):
            item['subtotal'] = Decimal(str(processed_data['subtotal']))
        if processed_data.get('totalTax'):
            item['totalTax'] = Decimal(str(processed_data['totalTax']))
        if processed_data.get('discounts'):
            item['discounts'] = Decimal(str(processed_data['discounts']))
        
        table.put_item(Item=item)
        
        item_type = "detailed" if line_items else "simple"
        item_count = f" with {len(line_items)} items" if line_items else ""
        logger.info(f"Stored {item_type} receipt{item_count}: {receipt_id}")
        
    except Exception as e:
        logger.error(f"DynamoDB error: {str(e)}")
        raise
import json
import boto3
import logging
from decimal import Decimal
from boto3.dynamodb.conditions import Key

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize DynamoDB
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('receipt-parser-receipts')

def lambda_handler(event, context):
    """API Gateway handler for receipt queries"""
    try:
        # Parse request
        http_method = event.get('httpMethod', '')
        path = event.get('path', '')
        path_parameters = event.get('pathParameters') or {}
        
        logger.info(f"API Request: {http_method} {path}")
        
        # Route requests
        if http_method == 'GET' and path == '/receipts':
            return get_all_receipts()
        elif http_method == 'GET' and path.startswith('/receipts/category/'):
            category = path_parameters.get('category')
            return get_receipts_by_category(category)
        elif http_method == 'GET' and path.startswith('/receipts/') and not path.startswith('/receipts/category/'):
            receipt_id = path_parameters.get('id')
            return get_receipt_by_id(receipt_id)
        elif http_method == 'OPTIONS':
            return cors_response()
        else:
            return error_response(404, 'Endpoint not found')
            
    except Exception as e:
        logger.error(f"API Error: {str(e)}")
        return error_response(500, str(e))

def get_all_receipts():
    """Get all receipts"""
    try:
        response = table.scan()
        receipts = response.get('Items', [])
        
        # Sort by upload timestamp (newest first)
        receipts.sort(key=lambda x: x.get('uploadTimestamp', ''), reverse=True)
        
        # Convert Decimal to float for JSON serialization
        receipts = convert_decimals(receipts)
        
        # Calculate summary statistics
        stats = calculate_stats(receipts)
        
        return success_response({
            'receipts': receipts,
            'count': len(receipts),
            'stats': stats
        })
        
    except Exception as e:
        logger.error(f"Error getting receipts: {str(e)}")
        return error_response(500, f"Error retrieving receipts: {str(e)}")

def get_receipt_by_id(receipt_id):
    """Get specific receipt by ID"""
    try:
        if not receipt_id:
            return error_response(400, 'Receipt ID is required')
        
        response = table.get_item(
            Key={'receiptId': receipt_id}
        )
        
        receipt = response.get('Item')
        if not receipt:
            return error_response(404, 'Receipt not found')
        
        receipt = convert_decimals([receipt])[0]
        
        return success_response({
            'receipt': receipt
        })
        
    except Exception as e:
        logger.error(f"Error getting receipt {receipt_id}: {str(e)}")
        return error_response(500, f"Error retrieving receipt: {str(e)}")

def get_receipts_by_category(category):
    """Get receipts filtered by category"""
    try:
        if not category:
            return error_response(400, 'Category is required')
        
        # Capitalize category for consistency
        category = category.title()
        valid_categories = ['Food', 'Office', 'Travel', 'Equipment', 'Entertainment', 'Fuel', 'Healthcare', 'Other']
        
        if category not in valid_categories:
            return error_response(400, f'Invalid category. Valid categories: {", ".join(valid_categories)}')
        
        # Scan and filter by category
        response = table.scan()
        receipts = [r for r in response.get('Items', []) if r.get('category') == category]
        
        receipts.sort(key=lambda x: x.get('uploadTimestamp', ''), reverse=True)
        receipts = convert_decimals(receipts)
        
        # Calculate category statistics
        total_amount = sum(float(r.get('amount', 0)) for r in receipts)
        avg_amount = total_amount / len(receipts) if receipts else 0
        
        return success_response({
            'receipts': receipts,
            'category': category,
            'count': len(receipts),
            'total_amount': round(total_amount, 2),
            'average_amount': round(avg_amount, 2)
        })
        
    except Exception as e:
        logger.error(f"Error getting receipts for category {category}: {str(e)}")
        return error_response(500, f"Error retrieving receipts: {str(e)}")

def calculate_stats(receipts):
    """Calculate summary statistics"""
    if not receipts:
        return {
            'total_count': 0,
            'total_amount': 0,
            'average_amount': 0,
            'categories': {}
        }
    
    total_amount = sum(float(r.get('amount', 0)) for r in receipts)
    avg_amount = total_amount / len(receipts)
    
    # Category breakdown
    categories = {}
    for receipt in receipts:
        category = receipt.get('category', 'Other')
        if category not in categories:
            categories[category] = {'count': 0, 'total': 0}
        categories[category]['count'] += 1
        categories[category]['total'] += float(receipt.get('amount', 0))
    
    # Calculate averages for each category
    for category in categories:
        categories[category]['average'] = round(
            categories[category]['total'] / categories[category]['count'], 2
        )
        categories[category]['total'] = round(categories[category]['total'], 2)
    
    return {
        'total_count': len(receipts),
        'total_amount': round(total_amount, 2),
        'average_amount': round(avg_amount, 2),
        'categories': categories
    }

def convert_decimals(obj):
    """Convert Decimal objects to float for JSON serialization"""
    if isinstance(obj, list):
        return [convert_decimals(item) for item in obj]
    elif isinstance(obj, dict):
        return {key: convert_decimals(value) for key, value in obj.items()}
    elif isinstance(obj, Decimal):
        return float(obj)
    else:
        return obj

def success_response(data):
    """Return success response with CORS headers"""
    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token',
            'Access-Control-Allow-Methods': 'GET,OPTIONS,POST,PUT'
        },
        'body': json.dumps(data, indent=2)
    }

def error_response(status_code, message):
    """Return error response with CORS headers"""
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token',
            'Access-Control-Allow-Methods': 'GET,OPTIONS,POST,PUT'
        },
        'body': json.dumps({
            'error': message,
            'statusCode': status_code
        })
    }

def cors_response():
    """Return CORS preflight response"""
    return {
        'statusCode': 200,
        'headers': {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token',
            'Access-Control-Allow-Methods': 'GET,OPTIONS,POST,PUT'
        },
        'body': ''
    }
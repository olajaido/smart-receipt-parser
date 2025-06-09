import json
import boto3
import os
import logging
import uuid
from datetime import datetime

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize Step Functions client
stepfunctions = boto3.client('stepfunctions')

def lambda_handler(event, context):
    """Trigger Step Functions when S3 objects are created"""
    try:
        # Get Step Functions State Machine ARN from environment
        state_machine_arn = os.environ['STATE_MACHINE_ARN']
        
        logger.info(f"Processing S3 event with {len(event['Records'])} records")
        
        for record in event['Records']:
            # Extract S3 event information
            bucket = record['s3']['bucket']['name']
            key = record['s3']['object']['key']
            event_name = record['eventName']
            
            logger.info(f"Processing S3 event: {event_name} for {bucket}/{key}")
            
            # Only process ObjectCreated events for receipt images
            if not event_name.startswith('ObjectCreated'):
                logger.info(f"Skipping non-creation event: {event_name}")
                continue
                
            if not key.startswith('receipts/'):
                logger.info(f"Skipping non-receipt object: {key}")
                continue
            
            # Prepare input for Step Functions
            step_function_input = {
                'Records': [record],  # Pass the S3 record to maintain compatibility
                'executionId': str(uuid.uuid4()),
                'timestamp': datetime.utcnow().isoformat(),
                'bucket': bucket,
                'key': key,
                'eventName': event_name
            }
            
            # Start Step Functions execution
            execution_name = f"receipt-processing-{int(datetime.now().timestamp())}-{str(uuid.uuid4())[:8]}"
            
            response = stepfunctions.start_execution(
                stateMachineArn=state_machine_arn,
                name=execution_name,
                input=json.dumps(step_function_input)
            )
            
            execution_arn = response['executionArn']
            logger.info(f"Started Step Functions execution: {execution_arn}")
            
            # Log execution details
            logger.info(f"Step Functions execution started successfully:")
            logger.info(f"  - Execution ARN: {execution_arn}")
            logger.info(f"  - Execution Name: {execution_name}")
            logger.info(f"  - Processing: {bucket}/{key}")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': f'Successfully triggered Step Functions for {len(event["Records"])} S3 events',
                'processed_objects': [f"{r['s3']['bucket']['name']}/{r['s3']['object']['key']}" for r in event['Records']]
            })
        }
        
    except Exception as e:
        logger.error(f"Error triggering Step Functions: {str(e)}")
        logger.error(f"Event: {json.dumps(event)}")
        
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': f'Failed to trigger Step Functions: {str(e)}'
            })
        }

def get_execution_status(execution_arn):
    """Helper function to check Step Functions execution status"""
    try:
        response = stepfunctions.describe_execution(executionArn=execution_arn)
        return {
            'status': response['status'],
            'startDate': response['startDate'].isoformat(),
            'input': json.loads(response['input'])
        }
    except Exception as e:
        logger.error(f"Error getting execution status: {str(e)}")
        return None
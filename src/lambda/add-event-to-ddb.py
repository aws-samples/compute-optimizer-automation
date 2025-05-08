import boto3
import logging
import os
from datetime import datetime
from botocore.exceptions import ClientError

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logging.getLogger("boto3").setLevel(logging.WARNING)
logging.getLogger("botocore").setLevel(logging.WARNING)

def lambda_handler(event, context):
    """
    Lambda handler to process event and write to DynamoDB
    Requires only resource_arn in the payload, all other fields are optional
    """
    try:
        logger.info(f"Processing event: {event}")
        
        # Extract payload and validate required field
        payload = event.get('detail', {}).get('Payload', {})
        if not payload.get('resource_arn'):
            raise KeyError('resource_arn is required in the payload')

        # Get current date in ISO format (YYYY-MM-DD)
        event_date = datetime.utcnow().strftime('%Y-%m-%d')
        
        # Create base item with required fields
        item = {
            'resource_arn': payload['resource_arn'],
            'event_date': event_date,
            'approval_sent': 'no',
            'task_token': event.get('detail', {}).get('TaskToken', 'No TaskToken'),
            'execution_details': event.get('resources', []),
            'tags': payload.get('tags', [])
        }
        
        # Add all other fields from payload dynamically
        for key, value in payload.items():
            if key != 'resource_arn':  # Skip resource_arn as it's already added
                item[key] = str(value)
        
        logger.info(f"Prepared DynamoDB item: {item}")

        # Initialize DynamoDB client and write item
        dynamodb = boto3.resource('dynamodb')
        table_name = os.environ.get('DDB_TABLE_NAME')
        table = dynamodb.Table(table_name) 
        
        response = table.put_item(Item=item)
        
        logger.info(f"Successfully wrote item to DynamoDB. Resource ARN: {payload['resource_arn']}")
        return {
            'statusCode': 200,
            'body': f"Successfully processed event for resource {payload['resource_arn']}"
        }
        
    except KeyError as e:
        logger.error(f"Missing required field in event: {str(e)}")
        return {
            'statusCode': 400,
            'body': f"Missing required field: {str(e)}"
        }
        
    except ClientError as e:
        logger.error(f"Error writing to DynamoDB: {str(e)}")
        return {
            'statusCode': 500,
            'body': f"Error writing to DynamoDB: {str(e)}"
        }
        
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        return {
            'statusCode': 500,
            'body': f"Unexpected error: {str(e)}"
        }

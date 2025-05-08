import json
import boto3
import os
import time
import logging
from datetime import datetime, timedelta
from botocore.exceptions import ClientError

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logging.getLogger("boto3").setLevel(logging.WARNING)
logging.getLogger("botocore").setLevel(logging.WARNING)

def validate_task_and_time(stepfunctions_client, task_token, timestamp):
    """
    Validate task token and time requirements
    """
    try:
        # Validate time elapsed
        current_time = int(time.time())
        time_elapsed = current_time - int(timestamp)
        
        if time_elapsed < 30:
            return False, f"Please wait at least 30 seconds before approving or rejecting (currently {time_elapsed} seconds)"
            
        # Validate task token
        stepfunctions_client.send_task_heartbeat(taskToken=task_token)
        return True, None

    except Exception as e:
        logger.error(f"Error validating task: {str(e)}")
        return False, """
                We cannot process this request because it is no longer valid. 

                This typically happens when:

                * The token is incorrect
                * The approval/rejection was already submitted
                * The request has expired (after 72 hours)

                If the resource continues to be flagged by AWS Compute Optimizer, we will attempt the update again during the next cycle."""

def determine_next_maintenance_window():
    """
    Calculate the UTC time for the next maintenance window
    """
    try:
        # Get configuration from environment variables
        maintenance_window_day = os.environ['MaintenanceWindowDay']
        maintenance_window_time = os.environ['MaintenanceWindowTime']
        
        # Parse the maintenance window time
        hour = datetime.strptime(maintenance_window_time, "%H:%M").time()
        weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        weekday = weekdays.index(maintenance_window_day)
        now = datetime.utcnow()
        
        # Calculate days until next maintenance window
        days_until_maintenance = (7 + weekday - now.weekday()) % 7
        if days_until_maintenance == 0 and now.time() > hour:
            days_until_maintenance = 7
            
        # Calculate next maintenance window datetime
        next_maintenance = now + timedelta(days=days_until_maintenance)
        next_maintenance = next_maintenance.replace(
            hour=hour.hour,
            minute=hour.minute,
            second=0,
            microsecond=0
        )
        
        maintenance_window = next_maintenance.strftime("%Y-%m-%dT%H:%M:%SZ")
        logger.info(f"Next maintenance window calculated: {maintenance_window}")
        return maintenance_window
        
    except KeyError as e:
        logger.error(f"Missing environment variable: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Error determining maintenance window: {str(e)}")
        raise

def get_response_message(action):
    """
    Get the appropriate response message based on the action
    """
    messages = {
    "Approved": """
            Thank you for your response!

            We will proceed with applying the AWS Compute Optimizer recommendations during the next maintenance window. 
            These changes will help optimize your resources and reduce costs while maintaining performance.
    """,
    "Rejected": """
            Thank you for your response. The recommended changes will not be applied at this time.

            Note: AWS Compute Optimizer will continue to monitor these resources and may suggest similar optimizations in the future if the same conditions persist. You can always:

            * Review the recommendations in the AWS Console
            * Adjust your resource configurations manually
            * Wait for the next optimization cycle
            * Tag the resource to exclude it from automation

            If you have any concerns about the recommendations, please contact your AWS administrator.
    """
    }

    return messages.get(action, "Invalid action specified")

def send_task_response(stepfunctions_client, task_token, stepfunction_event):
    """
    Send response to Step Functions task
    """
    try:
        response = stepfunctions_client.send_task_success(
            output=json.dumps(stepfunction_event),
            taskToken=task_token
        )
        logger.info("Successfully sent task success signal")
        return True
    except ClientError as e:
        logger.error(f"Error sending task success: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending task success: {str(e)}")
        return False

def update_ddb_record(resource_arn, event_date, action):
    """
    Update the record in DynamoDB with the action taken
    """
    try:
        dynamodb = boto3.resource('dynamodb')
        table_name = os.environ.get('DDB_TABLE_NAME')
        table = dynamodb.Table(table_name)
        
        response = table.update_item(
            Key={
                'resource_arn': resource_arn,
                'event_date': event_date
            },
            UpdateExpression='SET approval_response = :action',
            ExpressionAttributeValues={
                ':action': action
            },
            ReturnValues='UPDATED_NEW'
        )
        
        logger.info(f"Successfully updated DDB record for {resource_arn} with action: {action}")
        return True
    except Exception as e:
        logger.error(f"Error updating DDB record: {str(e)}")
        return False

def lambda_handler(event, context):
    """
    Main Lambda handler for processing Step Functions task responses
    """
    try:
        logger.info(f"Processing event: {event}")
        
        # Extract query parameters
        query_params = event.get('queryStringParameters', {})
        action = query_params.get('action')
        task_token = query_params.get('taskToken')
        timestamp = query_params.get('timestamp')
        resource_arn = query_params.get('resourceArn')  # Add this to your URL parameters
        event_date = query_params.get('eventDate')      # Add this to your URL parameters
        
        # Validate required parameters
        required_params = {
            'action': action,
            'taskToken': task_token,
            'timestamp': timestamp,
            'resourceArn': resource_arn,
            'eventDate': event_date
        }
        
        missing_params = [k for k, v in required_params.items() if not v]
        if missing_params:
            logger.error(f"Missing required parameters: {', '.join(missing_params)}")
            return {
                "statusCode": 400,
                "headers": {
                    "Content-Type": "text/plain"
                },
                "body": f"Missing required parameters: {', '.join(missing_params)}"
            }
        
        # Validate task token and time requirement
        stepfunctions = boto3.client('stepfunctions')
        is_valid, error_message = validate_task_and_time(stepfunctions, task_token, timestamp)
        
        if not is_valid:
            return {
                "statusCode": 400,
                "headers": {
                    "Content-Type": "text/plain"
                },
                "body": error_message
            }
        
        # Get next maintenance window
        maintenance_window = determine_next_maintenance_window()
        
        # Prepare Step Functions event
        stepfunction_event = { 
            "Status": action,
            "maintenance_window": maintenance_window
        }
        
        # Get response message
        message = get_response_message(action)
        
        # Send response to Step Functions
        if not send_task_response(stepfunctions, task_token, stepfunction_event):
            return {
                "statusCode": 500,
                "headers": {
                    "Content-Type": "text/plain"
                },
                "body": "Please validate; it appears that there is an issue with the Step Function execution."
            }
            
        # Update DynamoDB record
        if not update_ddb_record(resource_arn, event_date, action):
            logger.warning(f"Failed to update DDB record for {resource_arn}")
            # Continue even if DDB update fails, as the main action was successful
            
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "text/plain"
            },
            "body": message
        }
            
    except Exception as e:
        logger.error(f"Error in lambda_handler: {str(e)}", exc_info=True)
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "text/plain"
            },
            "body": "An unexpected error occurred while processing your request."
        }

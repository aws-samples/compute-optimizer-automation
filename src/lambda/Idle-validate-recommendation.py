import boto3
import os
from datetime import datetime, timedelta
import logging
from botocore.exceptions import ClientError

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logging.getLogger("boto3").setLevel(logging.WARNING)
logging.getLogger("botocore").setLevel(logging.WARNING)

def assume_role(account_id, role_name):
    """
    Assume a role in the specified account
    """
    sts_client = boto3.client('sts')
    role_arn = f'arn:aws:iam::{account_id}:role/{role_name}'
    try:
        response = sts_client.assume_role(
            RoleArn=role_arn,
            RoleSessionName='ComputeOptimizerCheck'
        )
        logger.info(f"Successfully assumed role in account {account_id}")
        return response['Credentials']
    except ClientError as e:
        logger.error(f"Error assuming role in account {account_id}: {e}")
        return None

def get_ec2_client(account_id, region):
    """
    Get an EC2 client for the specified account and region
    """
    role_name = os.environ.get('ASSUME_ROLE_NAME', 'coa-validate-recommendation')
    credentials = assume_role(account_id, role_name)
    if not credentials:
        return None
        
    logger.info(f"Creating EC2 client for account {account_id} in region {region}")
    return boto3.client('ec2',
                      region_name=region,
                      aws_access_key_id=credentials['AccessKeyId'],
                      aws_secret_access_key=credentials['SecretAccessKey'],
                      aws_session_token=credentials['SessionToken'])

def determine_next_maintenance_window():
    """
    Calculate the UTC time for the next maintenance window
    """
    try:
        maintenance_window_day = os.environ['MaintenanceWindowDay']
        maintenance_window_time = os.environ['MaintenanceWindowTime']

        hour = datetime.strptime(maintenance_window_time, "%H:%M").time()
        weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        weekday = weekdays.index(maintenance_window_day)
        now = datetime.utcnow()
        
        days_until_maintenance = (7 + weekday - now.weekday()) % 7
        if days_until_maintenance == 0 and now.time() > hour:
            days_until_maintenance = 7
            
        next_maintenance = now + timedelta(days=days_until_maintenance)
        next_maintenance = next_maintenance.replace(hour=hour.hour, minute=hour.minute, second=0, microsecond=0)
        maintenance_window = next_maintenance.strftime("%Y-%m-%dT%H:%M:%SZ")
        
        logger.info(f"Next maintenance window calculated: {maintenance_window}")
        return maintenance_window
    except Exception as e:
        logger.error(f"Error determining maintenance window: {e}")
        return None

def get_volume_details(ec2_client, volume_id):
    """
    Get volume details using the EC2 client
    """
    try:
        logger.info(f"Getting details for volume {volume_id}")
        response = ec2_client.describe_volumes(VolumeIds=[volume_id])
        return response['Volumes'][0]
    except ClientError as e:
        logger.error(f"Error getting volume details for {volume_id}: {e}")
        return None

def lambda_handler(event, context):
    """
    AWS Lambda handler for processing idle volume optimization recommendations
    """
    error_response = {
        "account": event.get('account'),
        "region": event.get('region'),
        "change_option_detected": False,
        "resource_id": event.get('resourceId'),
        "resource_arn": event.get('resourceArn'),
        "message": "Error processing recommendation"
    }
    
    try:
        logger.info(f"Processing event: {event}")
        
        # Validate required environment variables
        required_env_vars = ['ExcludeTag', 'Approval', 'MaintenanceWindowDay', 'MaintenanceWindowTime']
        for var in required_env_vars:
            if var not in os.environ:
                error_response["message"] = f"Missing required environment variable: {var}"
                return error_response
        
        exclude_tag = os.environ['ExcludeTag']
        approval = os.environ['Approval']
        resource_id = event['resourceId']
        resource_arn = event['resourceArn']
        account_id = event['account']
        region = event['region']
        
        # Get maintenance window
        maintenance_window = determine_next_maintenance_window()
        if not maintenance_window:
            error_response["message"] = "Failed to determine maintenance window"
            return error_response
        
        # Get EC2 client
        ec2_client = get_ec2_client(account_id, region)
        if not ec2_client:
            error_response["message"] = f"Failed to create EC2 client for account {account_id}"
            return error_response
        
        # Get volume details
        volume = get_volume_details(ec2_client, resource_id)
        if not volume:
            error_response["message"] = f"Failed to get details for volume {resource_id}"
            return error_response
        
        # Check for exclude tag
        tags = volume.get('Tags', [])
        if any(tag['Key'] == exclude_tag for tag in tags):
            logger.info(f"Resource {resource_id} excluded due to tag: {exclude_tag}")
            error_response["message"] = "This resource is excluded from the Compute Optimization automation (due to the tag)"
            return error_response
        
        # Return successful response
        result = {
            "account": event.get('account'),
            "region": event.get('region'),
            "change_option_detected": True,
            "approval": approval,
            "maintenance_window": maintenance_window,
            "resource_arn": resource_arn,
            "resource_id": resource_id,
            "finding": event.get('finding'),
            "savings_opportunity": event.get('savings_opportunity'),
            "savings_opportunity_percentage": event.get('savings_opportunity_percentage'),
            "tags": tags
        }
        
        logger.info(f"Successfully processed recommendation for resource {resource_id}")
        return result
    
    except Exception as e:
        logger.error(f"Unexpected error processing recommendation: {str(e)}")
        error_response["message"] = f"Unexpected error: {str(e)}"
        return error_response

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
    except Exception as e:
        logger.error(f"Error assuming role in account {account_id}: {str(e)}")
        return None

def get_ec2_client(account_id, region, role_name):
    """
    Get an EC2 client for the specified account and region
    """
    credentials = assume_role(account_id, role_name)
    if not credentials:
        logger.error(f"Failed to assume role in account {account_id}")
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
        logger.error(f"Error determining maintenance window: {str(e)}")
        raise

def get_risk_profile_index(risk_profile_name):
    """
    Convert risk profile name to index
    """
    risk_levels = ['No Risk', 'Very Low', 'Low', 'Medium', 'High', 'Very High']
    try:
        return risk_levels.index(risk_profile_name)
    except ValueError:
        logger.error(f"Invalid risk profile: {risk_profile_name}")
        raise ValueError(f"Invalid risk profile: {risk_profile_name}. Must be one of {risk_levels}")

def lambda_handler(event, context):
    """
    AWS Lambda handler for evaluating EBS volume optimization recommendations
    """
    try:
        # Get environment variables
        exclude_tag = os.environ['ExcludeTag']
        approval = os.environ['Approval']
        risk_profile = ['No Risk', 'Very Low', 'Low', 'Medium', 'High', 'Very High'].index(os.environ['RiskProfile'])

        # Determine risk profile - prefer event payload over environment variable
        if 'accountRiskProfile' in event:
            logger.info(f"Using risk profile from event payload: {event['accountRiskProfile']}")
            risk_profile = get_risk_profile_index(event['accountRiskProfile'])
        else:
            logger.info(f"Using risk profile from environment variable: {os.environ['RiskProfile']}")
            risk_profile = get_risk_profile_index(os.environ['RiskProfile'])
            
        role_name = os.environ.get('ASSUME_ROLE_NAME', 'coa-validate-recommendation')
        
        # Extract event details
        resource_id = event['resourceId']
        resource_arn = event['resourceArn']
        account_id = event['account']
        region = event['region']
        current_volume_type = event['current_VolumeType']
        current_volume_baseline_iops = event['current_VolumeBaselineIOPS']
        current_volume_baseline_throughput = event['current_VolumeBaselineThroughput']
        finding = event['finding']

        # Initialize return message
        return_message = {
            "change_option_detected": False,
            "resource_id": resource_id,
            "resource_arn": resource_arn,
            "message": "None of the recommendations met the requirements"
        }

        # Get maintenance window
        maintenance_window = determine_next_maintenance_window()
        
        # Get EC2 client for the account
        ec2_client = get_ec2_client(account_id, region, role_name)
        if not ec2_client:
            return_message["message"] = f"Failed to assume role in account {account_id}"
            return return_message
        
        # Get volume details
        try:
            response = ec2_client.describe_volumes(VolumeIds=[resource_id])
            volume = response['Volumes'][0]
        except Exception as e:
            logger.error(f"Error getting volume details: {str(e)}")
            return_message["message"] = f"Error getting volume details: {str(e)}"
            return return_message
        
        # Check for exclude tag
        tags = volume.get('Tags', [])
        if any(tag['Key'] == exclude_tag for tag in tags):
            logger.info(f"Resource {resource_id} excluded due to tag: {exclude_tag}")
            return_message["message"] = "This resource is excluded from the Compute Optimization automation (due to the tag)"
            return return_message
                
        # Evaluate recommendations
        for recommendation in event['recommendationOptions']:
            if recommendation['performanceRisk'] <= risk_profile and recommendation['savings_opportunity'] > 0:

                return {
                    "change_option_detected": True,
                    "approval": approval,
                    "maintenance_window": maintenance_window,
                    "resource_arn": resource_arn,
                    "resource_id": resource_id,
                    "account": account_id,
                    "region": region,
                    "finding": finding,
                    "current_VolumeType": current_volume_type,
                    "current_VolumeBaselineIOPS": current_volume_baseline_iops,
                    "current_VolumeBaselineThroughput": current_volume_baseline_throughput,
                    "new_VolumeType": recommendation['new_VolumeType'],
                    "new_VolumeBaselineIOPS": recommendation['new_VolumeBaselineIOPS'],
                    "new_VolumeBaselineThroughput": recommendation['new_VolumeBaselineThroughput'],
                    "performance_risk": recommendation['performanceRisk'],
                    "savings_opportunity": recommendation['savings_opportunity'],
                    "savings_opportunity_percentage": recommendation['savings_opportunity_percentage'],
                    "tags": tags
                }

        return return_message

    except Exception as e:
        logger.error(f"Error in lambda_handler: {str(e)}")
        return {
            "change_option_detected": False,
            "resource_id": event.get('resourceId', 'unknown'),
            "resource_arn": event.get('resourceArn', 'unknown'),
            "message": f"Unexpected error: {str(e)}"
        }

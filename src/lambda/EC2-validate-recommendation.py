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
            RoleSessionName='ComputeOptimizerEC2Check'
        )
        logger.info(f"Successfully assumed role in account {account_id}")
        return response['Credentials']
    except ClientError as e:
        logger.error(f"Error assuming role in account {account_id}: {e}")
        return None

def get_ec2_clients(account_id, region, role_name):
    """
    Get EC2 resource and client for the specified account and region
    """
    credentials = assume_role(account_id, role_name)
    if not credentials:
        return None, None
        
    logger.info(f"Creating EC2 clients for account {account_id} in region {region}")
    ec2_resource = boto3.resource('ec2',
                                  region_name=region,
                                  aws_access_key_id=credentials['AccessKeyId'],
                                  aws_secret_access_key=credentials['SecretAccessKey'],
                                  aws_session_token=credentials['SessionToken'])
    ec2_client = boto3.client('ec2',
                              region_name=region,
                              aws_access_key_id=credentials['AccessKeyId'],
                              aws_secret_access_key=credentials['SecretAccessKey'],
                              aws_session_token=credentials['SessionToken'])
    return ec2_resource, ec2_client

def determine_next_maintenance_window():
    """
    Calculate the UTC time for the next maintenance window
    """
    try:
        maintenance_window_day = os.environ.get('MaintenanceWindowDay')
        maintenance_window_time = os.environ.get('MaintenanceWindowTime')

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

def check_instance_eligibility(ec2_instance, ec2_client, resource_id, exclude_tag):
    """
    Check if the EC2 instance is eligible for optimization and return instance details
    """
    try:
        # Check stop protection
        stop_protection = ec2_instance.describe_attribute(Attribute='disableApiStop')
        if stop_protection['DisableApiStop']['Value']:
            return False, "The instance was configured with Stop Protection", None

        # Get instance details
        response = ec2_client.describe_instances(InstanceIds=[resource_id])
        instance = response['Reservations'][0]['Instances'][0]

        # Check tags
        if 'Tags' in instance:
            for tag in instance['Tags']:
                if tag['Key'] == exclude_tag:
                    return False, "The instance is excluded from the Compute Optimization automation (due to the tag)", None
                if tag['Key'] == 'aws:autoscaling:groupName':
                    return False, "The instance is part of an ASG", None

        # Check ODCR
        if instance['CapacityReservationSpecification']['CapacityReservationPreference'] != 'open':
            return False, "The instance is part of an ODCR", None

        # Check Placement Group
        if instance['Placement']['GroupName']:
            return False, "The instance is part of a Placement Group", None

        # Return success along with instance tags
        return True, "", instance.get('Tags', [])

    except Exception as e:
        logger.error(f"Error checking instance eligibility: {str(e)}")
        raise

def evaluate_recommendation(recommendation, current_instance_type, risk_profile, architectural_change):
    """
    Evaluate if a recommendation meets the required criteria
    """
    if recommendation['performanceRisk'] > risk_profile:
        return False

    if recommendation['instanceType'] == current_instance_type:
        return False

    if 'Architecture' in recommendation['platformDifferences'] and architectural_change != 'yes':
        return False

    if 'Hypervisor' not in recommendation['platformDifferences']:
        if 'InstanceStoreAvailability' in recommendation['platformDifferences']:
            return False
        return True

    return False

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
    AWS Lambda handler for evaluating EC2 instance optimization recommendations
    """
    try:
        logger.info(f"Processing event: {event}")
        
        # Get environment variables
        exclude_tag = os.environ['ExcludeTag']
        approval = os.environ['Approval']
        architectural_change = 'No'
        
        # Determine risk profile - prefer event payload over environment variable
        if 'accountRiskProfile' in event:
            logger.info(f"Using risk profile from event payload: {event['accountRiskProfile']}")
            risk_profile = get_risk_profile_index(event['accountRiskProfile'])
        else:
            logger.info(f"Using risk profile from environment variable: {os.environ['RiskProfile']}")
            risk_profile = get_risk_profile_index(os.environ['RiskProfile'])
        
        # Extract event details
        resource_id = event['resourceId']
        resource_arn = event['resourceArn']
        resource_name = event['resourceName']
        account_id = event['account']
        region = event['region']
        finding = event['finding']
        currentInstanceType = event['currentInstanceType']

        # Initialize return message
        return_message = {
            "change_option_detected": False,
            "resource_id": resource_id,
            "resource_arn": resource_arn,
            "resource_name": resource_name,
            "account": account_id,
            "region": region,
            "message": "None of the recommendations met the requirements"
        }

        role_name = os.environ.get('ASSUME_ROLE_NAME', 'coa-validate-recommendation')

        # Get EC2 clients
        ec2_resource, ec2_client = get_ec2_clients(account_id, region, role_name)
        if not ec2_resource or not ec2_client:
            return_message["message"] = f"Failed to assume role in account {account_id}"
            return return_message
        logger.info(f"Successfully assumed role in account {account_id}")
        ec2_instance = ec2_resource.Instance(resource_id)

        # Check instance eligibility
        is_eligible, message, instance_tags = check_instance_eligibility(
            ec2_instance, ec2_client, resource_id, exclude_tag
        )
        
        if not is_eligible:
            return_message["message"] = message
            return return_message

        # Get maintenance window
        maintenance_window = determine_next_maintenance_window()

        # Evaluate recommendations
        for recommendation in event['recommendationOptions']:
            if evaluate_recommendation(recommendation, currentInstanceType, 
                                      risk_profile, architectural_change):
                return {
                    "change_option_detected": True,
                    "approval": approval,
                    "maintenance_window": maintenance_window,
                    "InstanceArn": resource_arn,
                    "resource_id": resource_id,
                    "resource_arn": resource_arn,
                    "resource_name": resource_name,
                    "account": account_id,
                    "region": region,
                    "finding": finding,
                    "current_resource_type": currentInstanceType,
                    "new_resource_type": recommendation['instanceType'],
                    "migration_effort": recommendation['migrationEffort'],
                    "performance_risk": recommendation['performanceRisk'],
                    "savings_opportunity": recommendation['savings_opportunity'],
                    "savings_opportunity_percentage": recommendation['savings_opportunity_percentage'],
                    "tags": instance_tags
                }

        return return_message

    except Exception as e:
        logger.error(f"Error in lambda_handler: {str(e)}", exc_info=True)
        return {
            "change_option_detected": False,
            "resource_id": event.get('resourceId', 'unknown'),
            "resource_arn": event.get('resourceArn', 'unknown'),
            "resource_name": event.get('resourceName', 'unknown'),
            "account": event.get('account', 'unknown'),
            "region": event.get('region', 'unknown'),
            "message": f"Unexpected error: {str(e)}"
        }

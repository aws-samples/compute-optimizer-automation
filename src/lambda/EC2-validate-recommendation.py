import boto3
import os
from datetime import datetime, timedelta
import logging

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logging.getLogger("boto3").setLevel(logging.WARNING)
logging.getLogger("botocore").setLevel(logging.WARNING)

def determine_next_maintenance_window():
    """
    Calculate the UTC time for the next maintenance window. This time will later be used to make the changes.
    
    Returns:
        str: UTC timestamp in ISO format (YYYY-MM-DDTHH:MM:SSZ)
    """
    maintenance_window_day = os.environ.get('MaintenanceWindowDay')
    maintenance_window_time = os.environ.get('MaintenanceWindowTime')

    # Determine the next maintance window
    hour = datetime.strptime(maintenance_window_time, "%H:%M").time()
    weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    weekday = weekdays.index(maintenance_window_day)
    now = datetime.utcnow()
    days_until_maintance_window = (7 + weekday - now.weekday()) % 7
    if days_until_maintance_window == 0 and now.time() > hour:
        days_until_maintance_window = 7
        
    time_until_maintance_window = timedelta(days=days_until_maintance_window)
    next_maintance_window = now + time_until_maintance_window
    next_maintance_window = next_maintance_window.replace(hour=hour.hour, minute=hour.minute, second=0, microsecond=0)
    maintance_window_utc_timestamp = next_maintance_window.strftime("%Y-%m-%dT%H:%M:%SZ")
    return maintance_window_utc_timestamp

def check_instance_eligibility(ec2_instance, ec2_client, resource_id, exclude_tag):
    """
    Check if the EC2 instance is eligible for optimization.
    
    Returns:
        tuple: (is_eligible: bool, message: str)
    """
    try:
        # Check stop protection
        stop_protection = ec2_instance.describe_attribute(Attribute='disableApiStop')
        if stop_protection['DisableApiStop']['Value']:
            return False, "The instance was configured with Stop Protection"

        # Get instance details
        response = ec2_client.describe_instances(InstanceIds=[resource_id])
        instance = response['Reservations'][0]['Instances'][0]

        # Check tags
        if 'Tags' in instance:
            for tag in instance['Tags']:
                if tag['Key'] == exclude_tag:
                    return False, "The instance is excluded from the Compute Optimization automation (due to the tag)"
                if tag['Key'] == 'aws:autoscaling:groupName':
                    return False, "The instance is part of an ASG"

        # Check ODCR
        if instance['CapacityReservationSpecification']['CapacityReservationPreference'] != 'open':
            return False, "The instance is part of an ODCR"

        # Check Placement Group
        if instance['Placement']['GroupName']:
            return False, "The instance is part of a Placement Group"

        return True, ""

    except Exception as e:
        logger.error(f"Error checking instance eligibility: {str(e)}")
        raise

def evaluate_recommendation(recommendation, current_instance_type, risk_profile, architectural_change):
    """
    Evaluate if a recommendation meets the required criteria.
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

def lambda_handler(event, context):
    """
    AWS Lambda handler for evaluating EC2 instance optimization recommendations.
    
    Returns:
        Dict containing either recommendation details or message explaining why no change is recommended
    """
    try:
        # Get environment variables
        exclude_tag = os.environ['ExcludeTag']
        approval = os.environ['Approval']
        architectural_change = os.environ['ArchitecturalChange']
        risk_profile = ['No Risk', 'Very Low', 'Low', 'Medium', 'High', 'Very High'].index(os.environ['RiskProfile'])

        # Extract event details
        resource_id = event['resourceId']
        resource_arn = event['resourceArn']
        resource_name = event['resourceName']

        # Initialize return message
        return_message = {
            "change_option_detected": False,
            "resource_id": resource_id,
            "resource_arn": resource_arn,
            "resource_name": resource_name,
            "message": "None of the recommendations met the requirements"
        }

        # Initialize AWS clients
        ec2 = boto3.resource('ec2')
        ec2_client = boto3.client('ec2', region_name=event['region'])
        ec2_instance = ec2.Instance(resource_id)

        # Check instance eligibility
        is_eligible, message = check_instance_eligibility(
            ec2_instance, ec2_client, resource_id, exclude_tag
        )
        
        if not is_eligible:
            return_message["message"] = message
            return return_message

        # Get maintenance window
        maintance_window_utc_timestamp = determine_next_maintenance_window()

        # Evaluate recommendations
        for recommendation in event['recommendationOptions']:
            if evaluate_recommendation(recommendation, event['currentInstanceType'], 
                                    risk_profile, architectural_change):
                return {
                    "change_option_detected": True,
                    "approval": approval,
                    "maintenance_window": maintance_window_utc_timestamp,
                    "InstanceArn": resource_arn,
                    "resource_id": resource_id,
                    "resource_arn": resource_arn,
                    "resource_name": resource_name,
                    "current_resource_type": event['currentInstanceType'],
                    "new_resource_type": recommendation['instanceType'],
                    "migration_effort": recommendation['migrationEffort'],
                    "performance_risk": recommendation['performanceRisk'],
                    "savings_opportunity": recommendation['savings_opportunity'],
                    "savings_opportunity_percentage": recommendation['savings_opportunity_percentage']
                }

        return return_message

    except Exception as e:
        logger.error(f"Error in lambda_handler: {str(e)}")
        raise
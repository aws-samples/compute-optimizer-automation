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
    maintenance_window_day = os.environ['MaintenanceWindowDay']
    maintenance_window_time = os.environ['MaintenanceWindowTime']

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
    maintenance_window_utc_timestamp = next_maintance_window.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    return maintenance_window_utc_timestamp

def lambda_handler(event, context):
    """
    AWS Lambda handler for evaluating EBS volume optimization recommendations.
    
    Returns:
        Dict containing either recommendation details or message explaining why no change is recommended
    """
    try:
        # Get environment variables and event details
        exclude_tag = os.environ['ExcludeTag']
        approval = os.environ['Approval']
        risk_profile = ['No Risk', 'Very Low', 'Low', 'Medium', 'High', 'Very High'].index(os.environ['RiskProfile'])
        
        resource_id = event['resourceId']
        resource_arn = event['resourceArn']
        current_volume_type = event['current_VolumeType']
        current_volume_baseline_iops = event['current_VolumeBaselineIOPS']
        current_volume_baseline_throughput = event['current_VolumeBaselineThroughput']

        # Initialize return message
        return_message = {
            "change_option_detected": False,
            "resource_id": resource_id,
            "resource_arn": resource_arn,
            "message": "None of the recommendations met the requirements"
        }

        # Get maintenance window
        maintenance_window_utc_timestamp = determine_next_maintenance_window()
        
        # Get volume details
        try:
            ec2 = boto3.client('ec2')
            response = ec2.describe_volumes(VolumeIds=[resource_id])
            volume = response['Volumes'][0]
        except Exception as e:
            logger.error(f"Error getting volume details: {str(e)}")
            raise
    
        # Check if the EBS volume is eligible for optimization.
        if 'Tags' in volume:
            tags = volume['Tags']
            for tag in tags:
                if tag['Key'] == exclude_tag:
                    return_message["message"] = "The instance is excluded from the Compute Optimization automate recommendations (due to the tag)"
                    return return_message
                
        # Evaluate recommendations
        for recommendation in event['recommendationOptions']:
            if recommendation['performanceRisk'] <= risk_profile and recommendation['savings_opportunity'] > 0:
                return {
                    "change_option_detected": True,
                    "approval": approval,
                    "maintenance_window": maintenance_window_utc_timestamp,
                    "resource_arn": resource_arn,
                    "resource_id": resource_id,
                    "current_VolumeType": current_volume_type,
                    "current_VolumeBaselineIOPS": current_volume_baseline_iops,
                    "current_VolumeBaselineThroughput": current_volume_baseline_throughput,
                    "new_VolumeType": recommendation['new_VolumeType'],
                    "new_VolumeBaselineIOPS": recommendation['new_VolumeBaselineIOPS'],
                    "new_VolumeBaselineThroughput": recommendation['new_VolumeBaselineThroughput'],
                    "performance_risk": recommendation['performanceRisk'],
                    "savings_opportunity": recommendation['savings_opportunity'],
                    "savings_opportunity_percentage": recommendation['savings_opportunity_percentage']
                }

        return return_message

    except Exception as e:
        logger.error(f"Error in lambda_handler: {str(e)}")
        raise
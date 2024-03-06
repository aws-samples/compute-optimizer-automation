import boto3
import os
from datetime import datetime, timedelta

def determine_next_maintenance_window():
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
    maintance_window_utc_timestamp = next_maintance_window.strftime("%Y-%m-%dT%H:%M:%SZ")
    return maintance_window_utc_timestamp


def lambda_handler(event, context):
    exclude_tag = os.environ['ExcludeTag']
    approval = os.environ['Approval']
    risk_profile = ['No Risk', 'Very Low', 'Low', 'Medium', 'High', 'Very High'].index(os.environ['RiskProfile'])
    resource_id = event['VolumeArn'].split('/')[1]
    current_VolumeType = event['CurrentConfiguration']['VolumeType']
    current_VolumeBaselineIOPS = event['CurrentConfiguration']['VolumeBaselineIOPS']
    current_VolumeBaselineThroughput = event['CurrentConfiguration']['VolumeBaselineThroughput']
    return_message = {
        "change_option_detected": False,
        "resource_id": resource_id,
        "resource_arn": event['VolumeArn'],
        "message": "None of the recommendations met the requirements"
    }
    
    maintance_window_utc_timestamp = determine_next_maintenance_window()
    
    ec2 = boto3.client('ec2')
    response = ec2.describe_volumes(VolumeIds=[resource_id])
    volume = response['Volumes'][0]
    
    if 'Tags' in volume:
        tags = volume['Tags']
        for tag in tags:
            if tag['Key'] == exclude_tag:
                return_message["message"] = "The instance is excluded from the Compute Optimization automate recommendations (due to the tag)"
                return return_message
    
    for recommendation in event['VolumeRecommendationOptions']:
        if recommendation['PerformanceRisk'] <= risk_profile and 'SavingsOpportunity' in recommendation:
            if recommendation['SavingsOpportunity']['EstimatedMonthlySavings']['Value'] > 0:
                return {
                    "change_option_detected": True,
                    "approval": approval,
                    "maintenance_window": maintance_window_utc_timestamp,
                    "resource_arn": event['VolumeArn'],
                    "resource_id": resource_id,
                    "current_VolumeType": current_VolumeType,
                    "current_VolumeBaselineIOPS": current_VolumeBaselineIOPS,
                    "current_VolumeBaselineThroughput": current_VolumeBaselineThroughput,
                    "new_VolumeType": recommendation['Configuration']['VolumeType'],
                    "new_VolumeBaselineIOPS": recommendation['Configuration']['VolumeBaselineIOPS'],
                    "new_VolumeBaselineThroughput": recommendation['Configuration']['VolumeBaselineThroughput'],
                    "performance_risk": recommendation['PerformanceRisk'],
                    "savings_opportunity": recommendation['SavingsOpportunity']['EstimatedMonthlySavings']['Value'],
                    "savings_opportunity_percentage": recommendation['SavingsOpportunity']['SavingsOpportunityPercentage']
                }      
    
    return return_message

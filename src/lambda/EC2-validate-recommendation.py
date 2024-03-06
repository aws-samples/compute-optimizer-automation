import boto3
import os
from datetime import datetime, timedelta

def determine_next_maintenance_window():
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


def lambda_handler(event, context):
    
    exclude_tag = os.environ['ExcludeTag']
    approval = os.environ['Approval']
    architectural_change = os.environ['ArchitecturalChange']
    risk_profile = ['No Risk', 'Very Low', 'Low', 'Medium', 'High', 'Very High'].index(os.environ['RiskProfile'])
    resource_id = event['InstanceArn'].split('/')[1]
    region = event['InstanceArn'].split(':')[3]
    return_message = {
        "change_option_detected": False,
        "resource_id": resource_id,
        "resource_arn": event['InstanceArn'],
        "resource_name": event['InstanceName'],
        "message": "None of the recommendations met the requirements"
    }
    
    maintance_window_utc_timestamp = determine_next_maintenance_window()

    ec2 = boto3.resource('ec2')
    ec2_instance = ec2.Instance(resource_id)
    stop_protection = ec2_instance.describe_attribute(Attribute='disableApiStop')
    if stop_protection['DisableApiStop']['Value'] == True:
        return_message["message"] = "The instance was configured with Stop Protection"
        return return_message

    ec2_client = boto3.client('ec2', region_name=region)
    response = ec2_client.describe_instances(InstanceIds=[resource_id])
    tags = response['Reservations'][0]['Instances'][0]['Tags']

    for tag in tags:
        if tag['Key'] == exclude_tag:
            return_message["message"] = "The instance is excluded from the Compute Optimization automate recommendations (due to the tag)"
            return return_message
            
        if tag['Key'] == 'aws:autoscaling:groupName':
            return_message["message"] = "The instance is part of an ASG"
            return return_message
    
    if response['Reservations'][0]['Instances'][0]['CapacityReservationSpecification']['CapacityReservationPreference'] != 'open':
        return_message["message"] = "The instance is part of an ODCR"
        return return_message

    if response['Reservations'][0]['Instances'][0]['Placement']['GroupName'] != '':
        return_message["message"] = "The instance is part of a Placement Group"
        return return_message
            
    for recommendation in event['RecommendationOptions']:
        if recommendation['PerformanceRisk'] <= risk_profile and 'SavingsOpportunity' in recommendation:
            if recommendation['InstanceType'] == event['CurrentInstanceType']:
                continue
            
            if 'Architecture' in recommendation['PlatformDifferences'] and architectural_change != 'yes':
                continue

            if 'Hypervisor' not in recommendation['PlatformDifferences'] and recommendation['SavingsOpportunity'] != None:
                if 'InstanceStoreAvailability' in recommendation['PlatformDifferences']:
                    continue
                
                return {
                  "change_option_detected": True,
                  "approval": approval,
                  "maintenance_window": maintance_window_utc_timestamp,
                  "InstanceArn": event['InstanceArn'],
                  "resource_id": resource_id,
                  "resource_arn": event['InstanceArn'],
                  "resource_name": event['InstanceName'],
                  "current_resource_type": event['CurrentInstanceType'],
                  "new_resource_type": recommendation['InstanceType'],
                  "migration_effort": recommendation['MigrationEffort'],
                  "performance_risk": recommendation['PerformanceRisk'],
                  "savings_opportunity": recommendation['SavingsOpportunity']['EstimatedMonthlySavings']['Value'],
                  "savings_opportunity_percentage": recommendation['SavingsOpportunity']['SavingsOpportunityPercentage']
              }
            
    return return_message

import json
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
    action = event['queryStringParameters']['action']
    service = event['queryStringParameters']['service']
    task_token = event['queryStringParameters']['taskToken']
    
    maintance_window_utc_timestamp = determine_next_maintenance_window()
    
    stepfunction_event = ""
    message = ""
    
    if service == 'ebs':
        stepfunction_event = { 
            "Status": action,
            "maintenance_window": maintance_window_utc_timestamp
        }
    
    if service == 'ec2':
        stepfunction_event = { 
            "Status": action,
            "maintenance_window": maintance_window_utc_timestamp
        }
    
    if action == "Approved":
        message = """
        Thank you!
        
        We’ll update the resources with the recommendations!
        """
        
    if action == "Rejected":
        message = """
        The update was canceled.
        
        If the resource continues to be flagged by AWS Compute Optimizer, we will attempt the update again during the next cycle.
        """


    try:
        stepfunctions = boto3.client('stepfunctions')
        stepfunctions.send_task_success(
            output = json.dumps(stepfunction_event),
            taskToken = task_token
        )
        return {
            "statusCode": 200,
            "body": message
        }
    except Exception as e:
        print(e)
        return {
            "statusCode": 200,
            "body": "Please validate; it appears that there is an issue with the Step Function execution."
        }

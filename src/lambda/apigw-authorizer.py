import json
import boto3

def lambda_handler(event, context):
    queryStringParameters = event['queryStringParameters']
    
    if 'taskToken' in queryStringParameters:
        stepfunctions = boto3.client('stepfunctions')
        task_token = queryStringParameters['taskToken']
        try:
            # Send a heartbeat for the task token
            stepfunctions.send_task_heartbeat(
                taskToken=task_token
            )
            print("Task heartbeat sent successfully.")
            return generate_policy('user', 'Allow', event['methodArn'])
            
        except Exception as e:
            # Handle invalid task token or other errors here
            print(f"Error sending task heartbeat: {str(e)}")
            return generate_policy('user', 'Deny', event['methodArn'])

# Helper function to generate an IAM policy
def generate_policy(principal_id, effect, resource):
    auth_response = {}
    auth_response['principalId'] = principal_id
    
    policy_document = {}
    policy_document['Version'] = '2012-10-17'
    policy_document['Statement'] = []

    statement_one = {}
    statement_one['Action'] = 'execute-api:Invoke'
    statement_one['Effect'] = effect
    statement_one['Resource'] = resource

    policy_document['Statement'].append(statement_one)
    auth_response['policyDocument'] = policy_document
    
    return auth_response

import boto3
import urllib.parse
import os

def lambda_handler(event, context):

    apiGwEndpoint = os.environ.get('ApiGwEndpoint')
    emailSnsTopic = os.environ.get('SNSTopic')
    
    taskToken = urllib.parse.quote(event['taskToken'])
    ec2_id = event['inputPayload']['ec2_id']
    instance_arn = event['inputPayload']['InstanceArn']
    ec2_name = event['inputPayload']['ec2_name']
    ec2_current_instance_type = event['inputPayload']['ec2_current_instance_type']
    ec2_new_instance_type = event['inputPayload']['ec2_new_instance_type']
    migration_effort = event['inputPayload']['migration_effort']
    performance_risk = event['inputPayload']['performance_risk']
    risk_profile = ['No Risk', 'Very Low', 'Low', 'Medium', 'High', 'Very High']
    risk = risk_profile[performance_risk]
    savings_opportunity = event['inputPayload']['savings_opportunity']
    savings_opportunity_percentage = event['inputPayload']['savings_opportunity_percentage']
    
    approveEndpoint = apiGwEndpoint + "?action=approved&taskToken=" + taskToken + "&ec2_id=" + ec2_id + "&ec2_new_instance_type=" + ec2_new_instance_type + "&ec2_current_instance_type=" + ec2_current_instance_type + "&instance_arn=" + instance_arn
    rejectEndpoint = apiGwEndpoint + "?action=rejected&taskToken=" + taskToken + "&ec2_id=" + ec2_id + "&ec2_new_instance_type=" + ec2_new_instance_type + "&ec2_current_instance_type=" + ec2_current_instance_type + "&instance_arn=" + instance_arn
    
    emailMessage = """ 
    Hi There,

    We are reaching out, because we need to your approval to update the instance "%s (%s)"
    This instance was flagged by AWS Compute Optimizer as being Over Provisioned, so we want to make the following changes:

    \t\t * Instance type: from %s to %s
    \t\t * Performance Risk: %s
    \t\t * Savings: %s%% or $%s per month

    Approve Change -> %s 


    Reject Change -> %s
    
    Thank you!

    """ % (ec2_name, ec2_id, ec2_current_instance_type, ec2_new_instance_type, risk, savings_opportunity_percentage, savings_opportunity, approveEndpoint, rejectEndpoint) 

    
    sns = boto3.client('sns')
    params = {
        'Message': emailMessage,
        'Subject': '[Action Required] Approval for EC2 type change',
        'TopicArn': emailSnsTopic
    }

    try:
        response = sns.publish(**params)
        print('MessageId: ' + response['MessageId'])
        return None

    except Exception as e:
        print('Error publishing to SNS topic: ' + str(e))
        raise e

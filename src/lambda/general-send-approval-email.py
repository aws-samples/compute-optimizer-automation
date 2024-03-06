import boto3
import urllib.parse
import os

def ebs_approval(event):
    
    apiGwEndpoint = os.environ.get('ApiGwEndpoint')
    
    taskToken = urllib.parse.quote(event['detail']['TaskToken'])
    
    resource_id = event['detail']['Payload']['resource_id']
    resource_arn = event['detail']['Payload']['resource_arn']
    current_resource_type = event['detail']['Payload']['current_VolumeType']
    current_resource_iops = event['detail']['Payload']['current_VolumeBaselineIOPS']
    current_resource_Throughput = event['detail']['Payload']['current_VolumeBaselineThroughput']
    new_resource_type = event['detail']['Payload']['new_VolumeType']
    new_resource_iops = event['detail']['Payload']['new_VolumeBaselineIOPS']
    new_resource_Throughput = event['detail']['Payload']['new_VolumeBaselineThroughput']
    
    
    performance_risk = event['detail']['Payload']['performance_risk']
    risk_profile = ['No Risk', 'Very Low', 'Low', 'Medium', 'High', 'Very High']
    risk = risk_profile[int(performance_risk)]
    savings_opportunity = round(event['detail']['Payload']['savings_opportunity'], 2)
    savings_opportunity_percentage = round(event['detail']['Payload']['savings_opportunity_percentage'])
    
    approveEndpoint = f'{apiGwEndpoint}?action=Approved&service=ebs&taskToken={taskToken}'
    rejectEndpoint = f'{apiGwEndpoint}?action=Rejected&service=ebs&taskToken={taskToken}'
    
    emailSubject = '[Action Required] AWS COA - Approval for EBS change'
    
    emailMessage = f"""
    Hi There,

    We are reaching out because we need your approval to update the resource "{resource_id}"
    This instance was flagged by AWS Compute Optimizer as being Not Optimized, so we want to make the following changes:

            * Savings: {savings_opportunity_percentage}% or ${savings_opportunity} per month
            * Resource type: from {current_resource_type} to {new_resource_type}
            * Resource IOPS: from {current_resource_iops} to {new_resource_iops}
            * Resource Throughput: from {current_resource_Throughput} to {new_resource_Throughput}
            * Performance Risk: {risk}

    Approve Change -> {approveEndpoint}

    Reject Change -> {rejectEndpoint}

    Thank you!
    """
    return emailMessage, emailSubject

def ec2_approval(event):
    
    apiGwEndpoint = os.environ.get('ApiGwEndpoint')
    
    taskToken = urllib.parse.quote(event['detail']['TaskToken'])
    
    resource_id = event['detail']['Payload']['resource_id']
    resource_arn = event['detail']['Payload']['resource_arn']
    resource_name = event['detail']['Payload']['resource_name']
    current_resource_type = event['detail']['Payload']['current_resource_type']
    new_resource_type = event['detail']['Payload']['new_resource_type']
    
    
    performance_risk = event['detail']['Payload']['performance_risk']
    risk_profile = ['No Risk', 'Very Low', 'Low', 'Medium', 'High', 'Very High']
    risk = risk_profile[int(performance_risk)]
    savings_opportunity = round(event['detail']['Payload']['savings_opportunity'], 2)
    savings_opportunity_percentage = round(event['detail']['Payload']['savings_opportunity_percentage'])
    
    approveEndpoint = f'{apiGwEndpoint}?action=Approved&service=ec2&taskToken={taskToken}'
    rejectEndpoint = f'{apiGwEndpoint}?action=Rejected&service=ec2&taskToken={taskToken}'

    emailSubject = '[Action Required] AWS COA - Approval for EC2 change'
    
    emailMessage = f"""
    Hi There,

    We are reaching out because we need your approval to update the instance "{resource_name} ({resource_id})"
    This instance was flagged by AWS Compute Optimizer as being Over Provisioned, so we want to make the following changes:

            * Savings: {savings_opportunity_percentage}% or ${savings_opportunity} per month
            * Instance type: from {current_resource_type} to {new_resource_type}
            * Performance Risk: {risk}

    Approve Change -> {approveEndpoint}

    Reject Change -> {rejectEndpoint}

    Thank you!
    """
    return emailMessage, emailSubject

def lambda_handler(event, context):

    emailSnsTopic = os.environ.get('SNSTopic')
    
    emailMessage = None
    emailSubject = None
    
    if event['detail-type'] == 'aws-coa-ebs-change-approval':
        emailMessage, emailSubject = ebs_approval(event)
    
    if event['detail-type'] == 'aws-coa-ec2-change-approval':
        emailMessage, emailSubject = ec2_approval(event)
    
    if emailMessage is not None and emailSubject is not None:
        sns = boto3.client('sns')
        params = {
            'Message': emailMessage,
            'Subject': emailSubject,
            'TopicArn': emailSnsTopic
        }

        try:
            response = sns.publish(**params)
            print('MessageId: ' + response['MessageId'])
            return None

        except Exception as e:
            print('Error publishing to SNS topic: ' + str(e))
            raise e
    else:
        print('Skipping SNS publishing as emailMessage or emailSubject is missing.')
        return None

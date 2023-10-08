import boto3
import os

def lambda_handler(event, context):

    ec2_id = event['inputPayload']['ec2_id']
    ec2_name = event['inputPayload']['ec2_name']

    emailSnsTopic = os.environ.get('SNSTopic')
    
    emailMessage = """ 
    Hi There,

    We want to notify you that during the instance upgrade process, we found an error and reverted all the changes for the following instance:

    \t\t * Instance : "%s (%s)"

    Please note that the instance is already up and running, and if the resource continues to be flagged by AWS Compute Optimizer, we will try again during the next maintenance window.
    
    Thank you!

    """ % (ec2_name, ec2_id) 

    sns = boto3.client('sns')
    params = {
        'Message': emailMessage,
        'Subject': '[Info] Update about EC2 instance change',
        'TopicArn': emailSnsTopic
    }

    try:
        response = sns.publish(**params)
        print('MessageId: ' + response['MessageId'])
        return None

    except Exception as e:
        print('Error publishing to SNS topic: ' + str(e))
        raise e
    
    return {
        "ec2_id": ec2_id,
        "message": 'The change was successfully rollback due to an issue',
        "InstanceArn": event['InstanceArn']
    }
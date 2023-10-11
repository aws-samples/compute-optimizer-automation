import boto3
import os

def lambda_handler(event, context):
    
    ec2_id = event['ec2_id']

    if 'update_successfully' not in event:
        ec2 = boto3.resource('ec2')
        ec2_instance = ec2.Instance(ec2_id)

        ec2_current_instance_type = event['ec2_current_instance_type']

        if ec2_instance.instance_type != ec2_current_instance_type:
            if ec2_instance.state['Name'] == 'running':
                ec2_instance.stop()
                ec2_instance.wait_until_stopped()
                ec2_instance.modify_attribute(InstanceType={'Value':ec2_current_instance_type})
                ec2_instance.start()
                ec2_instance.wait_until_running()
            if ec2_instance.state['Name'] == 'stopped':
                ec2_instance.modify_attribute(InstanceType={'Value':ec2_current_instance_type})

    emailSnsTopic = os.environ.get('SNSTopic')
    
    emailMessage = """ 
    Hi There,

    We want to notify you that during the instance upgrade process, we found an error and reverted all the changes for the following instance:

    \t\t * Instance : "%s"

    Please note that the instance is already up and running, and if the resource continues to be flagged by AWS Compute Optimizer, we will try again during the next maintenance window.
    
    Thank you!

    """ % (ec2_id) 

    sns = boto3.client('sns')
    params = {
        'Message': emailMessage,
        'Subject': '[Info] Update about EC2 instance change',
        'TopicArn': emailSnsTopic
    }

    try:
        response = sns.publish(**params)
        print('MessageId: ' + response['MessageId'])

    except Exception as e:
        print('Error publishing to SNS topic: ' + str(e))
        raise e
    
    return {
        "ec2_id": ec2_id,
        "message": 'The change was successfully rollback due to an issue',
        "EC2_instance": event['InstanceArn']
    }
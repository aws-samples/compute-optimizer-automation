import boto3

def lambda_handler(event, context):
    
    resource_id = event['resource_id']
    current_resource_type = event['current_resource_type']
    ec2 = boto3.resource('ec2')
    ec2_instance = ec2.Instance(resource_id)
    
    try:
        if ec2_instance.instance_type != current_resource_type:
            if ec2_instance.state['Name'] == 'running':
                ec2_instance.stop()
                ec2_instance.wait_until_stopped()

            ec2_instance.modify_attribute(InstanceType={'Value':current_resource_type})
            ec2_instance.start()
            ec2_instance.wait_until_running()
        
        return {
            "resource_id": resource_id,
            "message": 'The change was successfully rollback due to an issue',
            "EC2_instance": event['InstanceArn']
        }
            
    except Exception as e:
        print(f"Error during the rollback: {e}")  
        print(f"The input parameter were: {event}") 
        raise e

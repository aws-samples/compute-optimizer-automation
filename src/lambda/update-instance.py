import boto3

def lambda_handler(event, context):

    ec2_id = event['ec2_id']
    ec2_new_instance_type = event['ec2_new_instance_type']
    ec2_current_instance_type = event['ec2_current_instance_type']
    message = "Failed to update the instance. Please validate the Logs"
    
    update_successfully = False
    
    ec2 = boto3.resource('ec2')
    ec2_instance = ec2.Instance(ec2_id)

    #create snapshot before the update
    volumes = ec2_instance.volumes.all()
    for volume in volumes:
        snapshot = volume.create_snapshot()
        snapshot.create_tags(Tags=[{"Key": "created-by", "Value": "compute-optimizer-automation"}])
        print(f"Snapshot {snapshot.id} was created for volume {volume.id}")    
    
    if ec2_instance.state['Name'] == 'running':
        try:
            ec2_instance.stop()
            ec2_instance.wait_until_stopped()
            ec2_instance.modify_attribute(InstanceType={'Value':ec2_new_instance_type})
            ec2_instance.start()
            ec2_instance.wait_until_running()
            update_successfully = True
            message = "The EC2 instance %s was successfully updated to %s" % (ec2_id, ec2_new_instance_type)
        except Exception as e:
            print('Error during the update: ' + str(e))
            print('Rolling back to previous configuration')
            ec2_instance.stop()
            ec2_instance.wait_until_stopped()
            ec2_instance.modify_attribute(InstanceType={'Value':ec2_current_instance_type})
            ec2_instance.start()
            ec2_instance.wait_until_running()

    elif ec2_instance.state['Name'] == 'stopped':
        try: 
            ec2_instance.modify_attribute(InstanceType={'Value':ec2_new_instance_type})
            ec2_instance.start()
            ec2_instance.wait_until_running()
            update_successfully = True
            message = "The EC2 instance %s was successfully updated to %s" % (ec2_id, ec2_new_instance_type)
        except Exception as e:
            print('Error during the update: ' + str(e))
            print('Rolling back to previous configuration')
            ec2_instance.modify_attribute(InstanceType={'Value':ec2_current_instance_type})
            ec2_instance.start()
            ec2_instance.wait_until_running()
            
    else:
        print("Something is wrong with the state of the instance")
    
    return {
        "update_successfully": update_successfully,
        "ec2_id": ec2_id,
        "message": message,
        "InstanceArn": event['InstanceArn'],
    }
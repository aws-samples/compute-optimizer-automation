import boto3
import os

def lambda_handler(event, context):
    resource_id = event['resource_id']
    new_resource_type = event['new_resource_type']
    current_resource_type = event['current_resource_type']
    message = "Failed to update the instance. Please validate the Logs"
    
    update_successfully = False
    
    ec2 = boto3.resource('ec2')
    ec2_instance = ec2.Instance(resource_id)

    ebs_snapshot_required = os.environ.get('EBSSnapshot')

    #create snapshot before making the update
    if ebs_snapshot_required == 'yes':
      volumes = ec2_instance.volumes.all()
      for volume in volumes:
          snapshot = volume.create_snapshot()
          snapshot.create_tags(Tags=[{"Key": "created-by", "Value": "compute-optimizer-automation"}])
          print(f"Snapshot {snapshot.id} was created for volume {volume.id}")    
    
    if ec2_instance.state['Name'] == 'running':
        try:
            ec2_instance.stop()
            ec2_instance.wait_until_stopped()
            ec2_instance.modify_attribute(InstanceType={'Value':new_resource_type})
            ec2_instance.start()
            ec2_instance.wait_until_running()
            update_successfully = True
            message = "The EC2 instance %s was successfully updated to %s" % (resource_id, new_resource_type)
        except Exception as e:
            print('Error during the update: ' + str(e))
            print('Rolling back to previous configuration')
            ec2_instance.stop()
            ec2_instance.wait_until_stopped()
            ec2_instance.modify_attribute(InstanceType={'Value':current_resource_type})
            ec2_instance.start()
            ec2_instance.wait_until_running()

    elif ec2_instance.state['Name'] == 'stopped':
        try: 
            ec2_instance.modify_attribute(InstanceType={'Value':new_resource_type})
            update_successfully = True
            message = "The EC2 instance %s was successfully updated to %s" % (resource_id, new_resource_type)
        except Exception as e:
            print('Error during the update: ' + str(e))
            print('Rolling back to previous configuration')
            ec2_instance.modify_attribute(InstanceType={'Value':current_resource_type})
            
    else:
        print("Something is wrong with the state of the instance")
    
    return {
        "update_successfully": update_successfully,
        "resource_id": resource_id,
        "message": message,
        "resource_arn": event['InstanceArn']
    }

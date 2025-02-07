import boto3

def lambda_handler(event, context):
    resource_id = event['resource_id']

    message = "Failed to update the instance. Please validate the Logs"
    update_successfully = False

    ec2 = boto3.resource('ec2')
    volume = ec2.Volume(resource_id)

    try:
        # Create a snapshot before deleting
        snapshot = volume.create_snapshot()
        snapshot.create_tags(Tags=[{"Key": "created-by", "Value": "compute-optimizer-automation"}])
        # snapshot.wait_until_completed()

        # Validate that the volume is not attached to an instance and delete it 
        if len(volume.attachments) == 0:
            volume.delete()
            print(f"The EBS volume {resource_id} was marked for deletion, and the Snapshot {snapshot.id} was created before deleting it") 
        
        return {
            "update_successfully": True,
            "resource_arn": event['resource_arn'],
            "resource_id": resource_id,
            "message": f"The EBS volume {resource_id} was successfully deleted and the Snapshot {snapshot.id} was created before deleting it"
        }
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            "update_successfully": False,
            "resource_arn": event['resource_arn'],
            "resource_id": resource_id,
            "message": f"Failed to delete the volume with the following exception: {str(e)}"
        }
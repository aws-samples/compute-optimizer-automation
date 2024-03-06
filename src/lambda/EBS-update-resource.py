import boto3

def lambda_handler(event, context):
    resource_id = event['resource_id']
    volumeType = event['new_VolumeType']
    volumeIops = event['new_VolumeBaselineIOPS']
    volumeThroughput = event['new_VolumeBaselineThroughput']

    ec2 = boto3.client('ec2')

    try:
        if volumeType == "io2bx" or volumeType == "io1":
            if volumeType == "io2bx":
                volumeType = "io2"
                
            ec2.modify_volume(
                VolumeId = resource_id, 
                VolumeType = volumeType,
                Iops = volumeIops
            )

        if volumeType == "gp2":
            ec2.modify_volume(
                VolumeId = resource_id, 
                VolumeType = volumeType
            )
        if volumeType == "gp3":
            ec2.modify_volume(
                VolumeId = resource_id, 
                VolumeType = volumeType,
                Iops = volumeIops,
                Throughput = volumeThroughput
            )
        
        return {
            "update_successfully": True,
            "resource_arn": event['resource_arn'],
            "resource_id": resource_id,
            "message": f"The EBS volume {resource_id} was successfully updated with the following configuration: type {volumeType}, IOPS {volumeIops} and Throughput {volumeThroughput}"
        }
        
    except Exception as e:
        print(f"Error updating IOPS: {str(e)}")
        return {
            "update_successfully": False,
            "resource_arn": event['resource_arn'],
            "resource_id": resource_id,
            "message": f"Failed to update the volume with the following exception: {str(e)}"
        }

import boto3
import logging
import time
from botocore.exceptions import ClientError
import os

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logging.getLogger("boto3").setLevel(logging.WARNING)
logging.getLogger("botocore").setLevel(logging.WARNING)

def assume_role(account_id, role_name):
    """
    Assume a role in the specified account
    """
    sts_client = boto3.client('sts')
    role_arn = f'arn:aws:iam::{account_id}:role/{role_name}'
    try:
        response = sts_client.assume_role(
            RoleArn=role_arn,
            RoleSessionName='ComputeOptimizerModify'
        )
        logger.info(f"Successfully assumed role in account {account_id}")
        return response['Credentials']
    except ClientError as e:
        logger.error(f"Error assuming role in account {account_id}: {e}")
        return None

def get_ec2_clients(account_id, region, role_name):
    """
    Get EC2 resource and client with assumed role credentials
    """
    credentials = assume_role(account_id, role_name)
    if not credentials:
        return None, None
        
    logger.info(f"Creating EC2 clients for account {account_id} in region {region}")
    
    session = boto3.Session(
        aws_access_key_id=credentials['AccessKeyId'],
        aws_secret_access_key=credentials['SecretAccessKey'],
        aws_session_token=credentials['SessionToken'],
        region_name=region
    )
    
    return session.resource('ec2'), session.client('ec2')

def validate_and_combine_tags(volume_tags, base_tags, volume_id):
    """
    Validate and combine tags while respecting AWS limits
    """
    try:
        # Convert volume tags list to dictionary for easier manipulation
        existing_tags = {tag['Key']: tag['Value'] for tag in (volume_tags or [])}
        logger.info(f"Volume {volume_id} has {len(existing_tags)} original tags")

        # Start with existing tags
        final_tags = existing_tags.copy()
        
        # Add tags if there's space (AWS limit is 50)
        available_slots = 50 - len(final_tags)

        if available_slots > 0:
            for tag in base_tags:
                if available_slots <= 0:
                    logger.warning(f"Tag limit reached for volume {volume_id}, skipping remaining base tags")
                    break
                if tag['Key'] not in final_tags:
                    final_tags[tag['Key']] = tag['Value']
                    available_slots -= 1
                    logger.info(f"Added base tag {tag['Key']} to volume {volume_id}")

        # Convert back to list of dictionaries
        combined_tags = [{'Key': k, 'Value': v} for k, v in final_tags.items()]
        logger.info(f"Final tag count for volume {volume_id}: {len(combined_tags)}")
        
        return combined_tags
    except Exception as e:
        logger.error(f"Error processing tags for volume {volume_id}: {str(e)}")
        raise

def create_snapshots(ec2_instance):
    """
    Create snapshots of all volumes attached to the instance, preserving volume tags
    and adding base tags
    """
    snapshot_ids = []
    try:
        volumes = ec2_instance.volumes.all()
        
        for volume in volumes:
            # Define base tags
            base_tags = [
                {"Key": "Created-By", "Value": "AWS-COA"},
                {"Key": "Instance-ID", "Value": ec2_instance.id},
                {"Key": "Original-Volume-ID", "Value": volume.id},
                {"Key": "Creation-Date", "Value": time.strftime('%Y-%m-%d')}
            ]
            
            # Get and validate combined tags
            combined_tags = validate_and_combine_tags(volume.tags, base_tags, volume.id)
            
            try:
                # Create snapshot with validated tags
                snapshot = volume.create_snapshot(
                    Description=f"COA automation snapshot for instance {ec2_instance.id}",
                    TagSpecifications=[{
                        'ResourceType': 'snapshot',
                        'Tags': combined_tags
                    }]
                )
                
                snapshot_ids.append(snapshot.id)
                logger.info(f"Created snapshot {snapshot.id} for volume {volume.id} with {len(combined_tags)} tags")
                
            except ClientError as e:
                logger.error(f"Error creating snapshot for volume {volume.id}: {str(e)}")
                raise
                
    except Exception as e:
        logger.error(f"Error in create_snapshots: {str(e)}")
        raise
        
    return snapshot_ids

def lambda_handler(event, context):
    """
    Main Lambda handler for creating snapshots and updating instance
    """
    try:
        # Extract parameters
        account_id = event['account']
        region = event['region']
        resource_id = event['resource_id']
        new_resource_type = event['new_resource_type']
        current_resource_type = event['current_resource_type']
        role_name = os.environ.get('ASSUME_ROLE_NAME', 'coa-update-resource')
        ebs_snapshot_required = os.environ.get('EBSSnapshot', 'no').lower()
        
        # Initialize response
        response = {
            "update_successfully": False,
            "resource_id": resource_id,
            "resource_arn": event['InstanceArn'],
            "account": account_id,
            "region": region,
            "message": "Failed to update the instance"
        }

        # Get EC2 clients
        ec2_resource, ec2_client = get_ec2_clients(account_id, region, role_name)
        if not ec2_resource:
            response["message"] = f"Failed to create EC2 client for account {account_id}"
            return response
        
        # Get instance
        ec2_instance = ec2_resource.Instance(resource_id)
        
        # Create snapshots if required
        snapshot_ids = []
        if ebs_snapshot_required == 'yes':
            try:
                snapshot_ids = create_snapshots(ec2_instance)
                logger.info(f"Created snapshots: {snapshot_ids}")
                response["snapshot_ids"] = snapshot_ids
            except Exception as e:
                response["message"] = f"Failed to create snapshots: {str(e)}"
                return response

        # Get instance state and proceed with modification
        instance_state = ec2_instance.state['Name']
        logger.info(f"Updating the instance: {resource_id}")
        logger.info(f"Current instance state: {instance_state}")

        try:
            if instance_state == 'running':
                logger.info(f"Stopping instance {resource_id}")
                ec2_instance.stop()
                waiter = ec2_client.get_waiter('instance_stopped')
                waiter.wait(InstanceIds=[resource_id])
                
                logger.info(f"Modifying instance type to {new_resource_type}")
                ec2_instance.modify_attribute(InstanceType={'Value': new_resource_type})
                
                logger.info(f"Starting instance {resource_id}")
                ec2_instance.start()
                waiter = ec2_client.get_waiter('instance_running')
                waiter.wait(InstanceIds=[resource_id])
                
            elif instance_state == 'stopped':
                logger.info(f"Modifying stopped instance type to {new_resource_type}")
                ec2_instance.modify_attribute(InstanceType={'Value': new_resource_type})
                
            else:
                raise ValueError(f"Instance is in unsupported state: {instance_state}")

            response.update({
                "update_successfully": True,
                "message": f"Successfully updated instance {resource_id} to {new_resource_type}",
                "snapshot_ids": snapshot_ids
            })
            return response

        except Exception as e:
            error_message = str(e)
            logger.error(f"Error during update: {error_message}")
            
            # Attempt rollback
            try:
                logger.info("Attempting rollback to previous configuration")
                if instance_state == 'running':
                    if ec2_instance.state['Name'] != 'stopped':
                        ec2_instance.stop()
                        waiter = ec2_client.get_waiter('instance_stopped')
                        waiter.wait(InstanceIds=[resource_id])
                    
                ec2_instance.modify_attribute(InstanceType={'Value': current_resource_type})
                
                if instance_state == 'running':
                    ec2_instance.start()
                    waiter = ec2_client.get_waiter('instance_running')
                    waiter.wait(InstanceIds=[resource_id])
                
                response["message"] = f"Update failed and rolled back: {error_message}"
            except Exception as rollback_error:
                response["message"] = f"Update and rollback failed: {error_message}. Rollback error: {str(rollback_error)}"
            
            return response
            
    except Exception as e:
        error_message = f"Unexpected error: {str(e)}"
        logger.error(error_message, exc_info=True)
        return {
            "update_successfully": False,
            "resource_id": event.get('resource_id', 'unknown'),
            "resource_arn": event.get('InstanceArn', 'unknown'),
            "account": event.get('account', 'unknown'),
            "region": event.get('region', 'unknown'),
            "message": error_message,
            "snapshot_ids": snapshot_ids if 'snapshot_ids' in locals() else []
        }

import boto3
import logging
from botocore.exceptions import ClientError
import time
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
            RoleSessionName='ComputeOptimizerSnapshot'
        )
        logger.info(f"Successfully assumed role in account {account_id}")
        return response['Credentials']
    except ClientError as e:
        logger.error(f"Error assuming role in account {account_id}: {e}")
        return None

def get_ec2_client(account_id, region):
    """
    Get an EC2 client for the specified account and region
    """
    role_name = os.environ.get('ASSUME_ROLE_NAME', 'coa-update-resource')
    credentials = assume_role(account_id, role_name)
    if not credentials:
        return None
        
    logger.info(f"Creating EC2 client for account {account_id} in region {region}")
    return boto3.client('ec2',
                    region_name=region,
                    aws_access_key_id=credentials['AccessKeyId'],
                    aws_secret_access_key=credentials['SecretAccessKey'],
                    aws_session_token=credentials['SessionToken'])
    
def create_snapshot(ec2_client, resource_id, tags):
    """
    Create a snapshot of the volume with tags in a single API call
    """
    try:
        # Create snapshot with tags
        response = ec2_client.create_snapshot(
            VolumeId=resource_id,
            Description=f'Automated snapshot created by COA for volume {resource_id}',
            TagSpecifications=[
                {
                    'ResourceType': 'snapshot',
                    'Tags': tags
                },
            ]
        )
        snapshot_id = response['SnapshotId']
        logger.info(f"Created snapshot {snapshot_id} for volume {resource_id} with {len(tags)} tags")
        
        return snapshot_id, None
    except ClientError as e:
        error_message = f"Error creating snapshot for volume {resource_id}: {e}"
        logger.error(error_message)
        return None, error_message

def delete_volume(ec2_client, resource_id):
    """
    Delete the specified volume
    """
    try:
        ec2_client.delete_volume(VolumeId=resource_id)
        logger.info(f"Successfully deleted volume {resource_id}")
        return True, None
    except ClientError as e:
        error_message = f"Error deleting volume {resource_id}: {e}"
        logger.error(error_message)
        return False, error_message

def validate_and_combine_tags(existing_tags, resource_id):
    """
    Validate and combine tags while respecting AWS limits
    """
    try:
        # Convert list of tag dictionaries to dictionary if not already
        if isinstance(existing_tags, list):
            tags_dict = {tag['Key']: tag['Value'] for tag in existing_tags}
        else:
            tags_dict = existing_tags or {}
            
        logger.info(f"Volume {resource_id} has {len(tags_dict)} original tags")

        # Define required tags
        required_tags = {
            'Created-By': 'AWS-COA',
            'Original-Volume-ID': resource_id,
            'Creation-Date': time.strftime('%Y-%m-%d')
        }

        # Add tags if there's space (AWS limit is 50)
        available_slots = 50 - len(tags_dict)
        
        if available_slots > 0:
            logger.info(f"Have {available_slots} slots available for new tags")
            # Add required tags if space permits
            for key, value in required_tags.items():
                if available_slots <= 0:
                    logger.warning(f"Tag limit reached for volume {resource_id}, skipping remaining required tags")
                    break
                if key not in tags_dict:
                    tags_dict[key] = value
                    available_slots -= 1
                    logger.info(f"Added required tag: {key}={value}")
                else:
                    logger.info(f"Tag already exists: {key}={tags_dict[key]}")

        # Convert back to list of dictionaries
        final_tags = [{'Key': k, 'Value': v} for k, v in tags_dict.items()]
        
        # Log which required tags couldn't be added
        if available_slots <= 0:
            missing_tags = [key for key in required_tags if key not in tags_dict]
            if missing_tags:
                logger.warning(f"Could not add these required tags due to limit: {missing_tags}")

        logger.info(f"Final tag count: {len(final_tags)}")
        logger.info(f"Final tags to be applied: {final_tags}")
        
        return final_tags
        
    except Exception as e:
        logger.error(f"Error processing tags for volume {resource_id}: {str(e)}")
        raise

def lambda_handler(event, context):
    """
    Main Lambda handler for creating snapshot and deleting volume
    """
    try:
        logger.info(f"Processing event: {event}")
        
        # Extract required parameters
        account_id = event.get('account')
        region = event.get('region')
        resource_id = event.get('resource_id')
        
        # Define error response structure
        error_response = {
            'statusCode': 500,
            'account': account_id,
            'region': region,
            'resource_id': resource_id,
            'error': 'Unknown error occurred'
        }
        
        if not all([account_id, region, resource_id]):
            error_response['error'] = "Missing required parameters: account, region, or resource_id"
            return error_response

        # Process and validate tags
        try:
            tags = validate_and_combine_tags(event.get('tags', []), resource_id)
        except Exception as e:
            error_response['error'] = f"Error processing tags: {str(e)}"
            return error_response
        
        # Get EC2 client
        ec2_client = get_ec2_client(account_id, region)
        if not ec2_client:
            error_response['error'] = f"Failed to create EC2 client for account {account_id}"
            return error_response
        
        # Create snapshot
        snapshot_id, snapshot_error = create_snapshot(ec2_client, resource_id, tags)
        if snapshot_error:
            error_response['error'] = snapshot_error
            return error_response
        
        # Delete volume
        delete_success, delete_error = delete_volume(ec2_client, resource_id)
        if not delete_success:
            return {
                'account': account_id,
                'region': region,
                'resource_id': resource_id,
                'snapshot_id': snapshot_id,
                'tags': tags,
                'error': f"Snapshot creation started but volume deletion failed: {delete_error}"
            }
        
        # Success response
        result = {
            'account': account_id,
            'region': region,
            'resource_id': resource_id,
            'snapshot_id': snapshot_id,
            'tags': tags,
            'message': f'Successfully created snapshot {snapshot_id} and deleted volume {resource_id}'
        }
        
        logger.info(f"Operation completed successfully: {result}")
        return result
        
    except Exception as e:
        error_message = f"Unexpected error: {str(e)}"
        logger.error(error_message)
        return {
            'account': event.get('account'),
            'region': event.get('region'),
            'resource_id': event.get('resource_id'),
            'error': error_message
        }

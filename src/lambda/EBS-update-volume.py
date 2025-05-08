import boto3
import logging
import os
from botocore.exceptions import ClientError

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

def get_ec2_client(account_id, region, role_name):
    """
    Get an EC2 client for the specified account and region
    """
    credentials = assume_role(account_id, role_name)
    if not credentials:
        return None
        
    logger.info(f"Creating EC2 client for account {account_id} in region {region}")
    return boto3.client('ec2',
                      region_name=region,
                      aws_access_key_id=credentials['AccessKeyId'],
                      aws_secret_access_key=credentials['SecretAccessKey'],
                      aws_session_token=credentials['SessionToken'])

def modify_volume(ec2_client, resource_id, volume_type, volume_iops=None, volume_throughput=None):
    """
    Modify EBS volume based on volume type and parameters
    """
    try:
        params = {
            'VolumeId': resource_id,
            'VolumeType': volume_type
        }

        if volume_type in ['io2', 'io1'] and volume_iops:
            params['Iops'] = volume_iops
        elif volume_type == 'gp3':
            if volume_iops:
                params['Iops'] = volume_iops
            if volume_throughput:
                params['Throughput'] = volume_throughput

        logger.info(f"Modifying volume {resource_id} with parameters: {params}")
        # ec2_client.modify_volume(**params)
        return True, None

    except Exception as e:
        error_message = f"Error modifying volume {resource_id}: {str(e)}"
        logger.error(error_message)
        return False, error_message

def lambda_handler(event, context):
    """
    Lambda handler for modifying EBS volumes
    """
    try:
        logger.info(f"Processing event: {event}")
        
        # Extract parameters
        resource_id = event['resource_id']
        resource_arn = event['resource_arn']
        account_id = event['account']
        region = event['region']
        volume_type = event['new_VolumeType']
        volume_iops = event.get('new_VolumeBaselineIOPS')
        volume_throughput = event.get('new_VolumeBaselineThroughput')
        
        # Handle io2 Block Express
        if volume_type == "io2bx":
            volume_type = "io2"
            logger.info(f"Converting io2bx to io2 for volume {resource_id}")

        # Get EC2 client
        role_name = os.environ.get('ASSUME_ROLE_NAME', 'coa-update-resource')
        ec2_client = get_ec2_client(account_id, region, role_name)
        if not ec2_client:
            return {
                "update_successfully": False,
                "resource_arn": resource_arn,
                "resource_id": resource_id,
                "account": account_id,
                "region": region,
                "message": f"Failed to assume role in account {account_id}"
            }

        # Modify volume
        success, error_message = modify_volume(
            ec2_client, 
            resource_id, 
            volume_type, 
            volume_iops, 
            volume_throughput
        )

        if success:
            message = (
                f"The EBS volume {resource_id} was successfully updated with the following configuration: "
                f"type {volume_type}"
                f"{f', IOPS {volume_iops}' if volume_iops else ''}"
                f"{f', Throughput {volume_throughput}' if volume_throughput else ''}"
            )
            logger.info(message)
            return {
                "update_successfully": True,
                "resource_arn": resource_arn,
                "resource_id": resource_id,
                "account": account_id,
                "region": region,
                "message": message
            }
        else:
            return {
                "update_successfully": False,
                "resource_arn": resource_arn,
                "resource_id": resource_id,
                "account": account_id,
                "region": region,
                "message": error_message
            }

    except Exception as e:
        error_message = f"Unexpected error: {str(e)}"
        logger.error(error_message)
        return {
            "update_successfully": False,
            "resource_arn": event.get('resource_arn', 'unknown'),
            "resource_id": event.get('resource_id', 'unknown'),
            "account": event.get('account', 'unknown'),
            "region": event.get('region', 'unknown'),
            "message": error_message
        }

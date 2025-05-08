import boto3
import json
import logging
import os
from botocore.exceptions import ClientError
import concurrent.futures

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logging.getLogger("boto3").setLevel(logging.WARNING)
logging.getLogger("botocore").setLevel(logging.WARNING)

def assume_role_in_master(master_account_id, role_name):
    """
    Assume a role in the master account
    """
    sts_client = boto3.client('sts')
    role_arn = f'arn:aws:iam::{master_account_id}:role/{role_name}'
    try:
        response = sts_client.assume_role(
            RoleArn=role_arn,
            RoleSessionName='OrganizationAccess'
        )
        logger.info(f"Successfully assumed role in master account {master_account_id}")
        return response['Credentials']
    except Exception as e:
        logger.error(f"Error assuming role in master account {master_account_id}: {str(e)}")
        return None

def get_organization_active_accounts(master_credentials=None):
    """
    Get all active accounts in the organization
    """
    accounts = []
    
    # Create organizations client with master account credentials if provided
    if master_credentials:
        org_client = boto3.client('organizations',
                                aws_access_key_id=master_credentials['AccessKeyId'],
                                aws_secret_access_key=master_credentials['SecretAccessKey'],
                                aws_session_token=master_credentials['SessionToken'])
    else:
        org_client = boto3.client('organizations')
    
    try:
        paginator = org_client.get_paginator('list_accounts')
        for page in paginator.paginate():
            active_accounts = [
                account['Id']
                for account in page['Accounts']
                if account['Status'] == 'ACTIVE'
            ]
            accounts.extend(active_accounts)
            
        logger.info(f"Found {len(accounts)} active accounts")
        return accounts
    except Exception as e:
        logger.error(f"Error getting accounts: {str(e)}")
        raise

def get_master_account_id():
    """
    Get the master (management) account ID of the organization
    """
    try:
        org_client = boto3.client('organizations')
        response = org_client.describe_organization()
        master_account_id = response['Organization']['MasterAccountId']
        logger.info(f"Found master account ID: {master_account_id}")
        return master_account_id
    except Exception as e:
        logger.error(f"Error getting master account ID: {str(e)}")
        return None

def assume_role(account_id, role_name):
    """
    Assume a role in the specified account
    """
    sts_client = boto3.client('sts')
    role_arn = f'arn:aws:iam::{account_id}:role/{role_name}'
    try:
        response = sts_client.assume_role(
            RoleArn=role_arn,
            RoleSessionName='ComputeOptimizerCheck'
        )
        logger.info(f"Successfully assumed role in account {account_id}")
        return response['Credentials']
    except Exception as e:
        logger.error(f"Error assuming role in account {account_id}: {str(e)}")
        return None

def check_compute_optimizer(account_id, credentials):
    """
    Check Compute Optimizer status in all regions for an account
    """
    ec2_client = boto3.client('ec2', 
                              aws_access_key_id=credentials['AccessKeyId'],
                              aws_secret_access_key=credentials['SecretAccessKey'],
                              aws_session_token=credentials['SessionToken'])
    
    regions = [region['RegionName'] for region in ec2_client.describe_regions()['Regions']]
    active_regions = []

    for region in regions:
        try:
            co_client = boto3.client('compute-optimizer', 
                                    region_name=region,
                                    aws_access_key_id=credentials['AccessKeyId'],
                                    aws_secret_access_key=credentials['SecretAccessKey'],
                                    aws_session_token=credentials['SessionToken'])
            status = co_client.get_enrollment_status()
            if status['status'].lower() == 'active':
                active_regions.append(region)
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code != 'OptInRequired':
                logger.warning(f"Account {account_id}, Region {region}: Error - {str(e)}")
        except Exception as e:
            logger.error(f"Account {account_id}, Region {region}: Unexpected error - {str(e)}")
    
    return [(account_id, region) for region in active_regions]

def process_account(account_id, role_name):
    """
    Process a single account
    """
    credentials = assume_role(account_id, role_name)
    if credentials:
        return check_compute_optimizer(account_id, credentials)
    return []

def get_ssm_accounts_regions():
    """
    Get account-region pairs from SSM Parameter Store if configured
    """
    ssm_parameter_name = os.environ.get('SSM_ACCOUNT_REGIONS', '/coa/coa-accounts-regions')
    if not ssm_parameter_name:
        logger.info("SSM parameter name not configured, will try organization discovery")
        return None

    try:
        ssm_client = boto3.client('ssm')
        response = ssm_client.get_parameter(
            Name=ssm_parameter_name,
            WithDecryption=True
        )
        accounts_regions = json.loads(response['Parameter']['Value'])
        logger.info(f"Successfully retrieved {len(accounts_regions)} account-region pairs from SSM")
        return accounts_regions
            
    except ssm_client.exceptions.ParameterNotFound:
        logger.info(f"SSM parameter {ssm_parameter_name} not found, will use organization discovery")
        return None
    except Exception as e:
        logger.error(f"Error retrieving data from SSM: {str(e)}")
        return None

def lambda_handler(event, context):
    role_name = os.environ.get('ASSUME_ROLE_NAME', 'coa-validate-enrollment-status')
    master_role_name = os.environ.get('MASTER_ROLE_NAME', 'coa-organization-role')
    
    try:
        logger.info("Starting to process accounts")
        
        # First try to get account-regions from SSM if configured
        account_regions = get_ssm_accounts_regions()
        
        if account_regions is not None:
            logger.info("Using account-region pairs from SSM")
            return account_regions
        
        # Get master account ID
        master_account_id = get_master_account_id()
        if not master_account_id:
            logger.error("Failed to get master account ID")
            raise
        
        # First, assume role in master account
        master_credentials = assume_role_in_master(master_account_id, master_role_name)
        if not master_credentials:
            logger.error("Failed to assume role in master account")
            raise 
        
        # Get accounts using master account credentials
        accounts = get_organization_active_accounts(master_credentials)
        
        active_pairs = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_account = {executor.submit(process_account, account, role_name): account for account in accounts}
            for future in concurrent.futures.as_completed(future_to_account):
                active_pairs.extend(future.result())
        
        result = [{"account": account, "region": region} for account, region in active_pairs]
        
        logger.info(f"Found {len(result)} active account-region pairs")
        
        return result
        
    except Exception as e:
        logger.error(f"Error in lambda_handler: {str(e)}", exc_info=True)
        raise

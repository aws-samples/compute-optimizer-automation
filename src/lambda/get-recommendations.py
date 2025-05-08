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
            RoleSessionName='ComputeOptimizerCheck'
        )
        logger.info(f"Successfully assumed role in account {account_id}")
        return response['Credentials']
    except Exception as e:
        logger.error(f"Error assuming role in account {account_id}: {str(e)}")
        return None

def get_idle_recommendations(client, account_id, region):
    """
    Get idle recommendations from Compute Optimizer
    """
    data = []
    filters = [{'name': 'Finding', 'values': ['Unattached']}]

    try:
        logger.info(f"Getting idle recommendations for account {account_id} in region {region}")
        response = client.get_idle_recommendations(filters=filters)
        data.extend(response.get("idleRecommendations", []))

        while 'nextToken' in response:
            logger.debug("Getting next page of idle recommendations")
            response = client.get_idle_recommendations(
                nextToken=response["nextToken"],
                filters=filters
            )
            data.extend(response.get("idleRecommendations", []))
        
        filtered_data = []    
        for finding in data:
            savings = finding.get('savingsOpportunityAfterDiscounts', {})
            filtered_data.append({
                'account': account_id,
                'region': region,
                'resourceId': finding.get('resourceId', ''),
                'resourceArn': finding.get('resourceArn', ''),
                'finding': finding.get('finding', ''),
                'savings_opportunity': savings.get('estimatedMonthlySavings', {}).get('value', 0),
                'savings_opportunity_percentage': savings.get('savingsOpportunityPercentage', 0)
            })
        
        logger.info(f"Found {len(filtered_data)} idle recommendations")
        return filtered_data
    except Exception as e:
        logger.error(f"Error getting idle recommendations: {str(e)}")
        return []

def get_ec2_recommendations(client, account_id, region):
    """
    Get EC2 recommendations from Compute Optimizer
    """
    data = []
    filters = [{'name': 'Finding', 'values': ['OVER_PROVISIONED']}]
    recommendationPreferences = {'cpuVendorArchitectures': ['CURRENT']}

    try:
        logger.info(f"Getting EC2 recommendations for account {account_id} in region {region}")
        response = client.get_ec2_instance_recommendations(
            filters=filters,
            recommendationPreferences=recommendationPreferences
        )
        data.extend(response.get("instanceRecommendations", []))

        while 'nextToken' in response:
            logger.debug("Getting next page of EC2 recommendations")
            response = client.get_ec2_instance_recommendations(
                nextToken=response["nextToken"],
                filters=filters,
                recommendationPreferences=recommendationPreferences
            )
            data.extend(response.get("instanceRecommendations", []))

        filtered_data = []    
        for finding in data:
            instance_name = finding.get('instanceName', 'NA')
                
            recommendationOptions = []
            for option in finding.get('recommendationOptions', []):
                savings = option.get('savingsOpportunityAfterDiscounts', {})
                recommendationOptions.append({
                    'instanceType': option.get('instanceType', ''),
                    'performanceRisk': option.get('performanceRisk', ''),
                    'migrationEffort': option.get('migrationEffort', ''),
                    'platformDifferences': option.get('platformDifferences', []),
                    'savings_opportunity': savings.get('estimatedMonthlySavings', {}).get('value', 0),
                    'savings_opportunity_percentage': savings.get('savingsOpportunityPercentage', 0)
                })
                
            instance_arn = finding.get('instanceArn', '')
            filtered_data.append({
                'account': account_id,
                'region': region,
                'resourceId': instance_arn.split('/')[-1] if instance_arn else '',
                'resourceArn': instance_arn,
                'finding': finding.get('finding', ''),
                'resourceName': instance_name,
                'currentInstanceType': finding.get('currentInstanceType', ''),
                'recommendationOptions': recommendationOptions
            })
        
        logger.info(f"Found {len(filtered_data)} EC2 recommendations")
        return filtered_data
    except Exception as e:
        logger.error(f"Error getting EC2 recommendations: {str(e)}")
        return []

def get_ebs_recommendations(client, account_id, region):
    """
    Get EBS recommendations from Compute Optimizer
    """
    data = []
    filters = [{'name': 'Finding', 'values': ['NotOptimized']}]

    try:
        logger.info(f"Getting EBS recommendations for account {account_id} in region {region}")
        response = client.get_ebs_volume_recommendations(filters=filters)
        data.extend(response.get("volumeRecommendations", []))

        while 'nextToken' in response:
            logger.debug("Getting next page of EBS recommendations")
            response = client.get_ebs_volume_recommendations(
                nextToken=response["nextToken"],
                filters=filters
            )
            data.extend(response.get("volumeRecommendations", []))
        
        filtered_data = []    
        for finding in data:
            recommendationOptions = []
            for option in finding.get('volumeRecommendationOptions', []):
                config = option.get('configuration', {})
                savings = option.get('savingsOpportunityAfterDiscounts', {})
                recommendationOptions.append({
                    'performanceRisk': option.get('performanceRisk', ''),
                    'new_VolumeType': config.get('volumeType', ''),
                    'new_VolumeBaselineIOPS': config.get('volumeBaselineIOPS', 0),
                    'new_VolumeBaselineThroughput': config.get('volumeBaselineThroughput', 0),
                    'savings_opportunity': savings.get('estimatedMonthlySavings', {}).get('value', 0),
                    'savings_opportunity_percentage': savings.get('savingsOpportunityPercentage', 0)
                })
            
            current_config = finding.get('currentConfiguration', {})
            volume_arn = finding.get('volumeArn', '')
            filtered_data.append({
                'account': account_id,
                'region': region,
                'resourceId': volume_arn.split('/')[-1] if volume_arn else '',
                'resourceArn': volume_arn,
                'finding': finding.get('finding', ''),
                'current_VolumeType': current_config.get('volumeType', ''),
                'current_VolumeBaselineIOPS': current_config.get('volumeBaselineIOPS', 0),
                'current_VolumeBaselineThroughput': current_config.get('volumeBaselineThroughput', 0),
                'recommendationOptions': recommendationOptions
            })
            
        logger.info(f"Found {len(filtered_data)} EBS recommendations")
        return filtered_data
    except Exception as e:
        logger.error(f"Error getting EBS recommendations: {str(e)}")
        return []

def lambda_handler(event, context):
    """
    Main Lambda handler for getting Compute Optimizer recommendations
    """
    empty_result = {
        'account': event['AccountDetials']['account'],
        'region': event['AccountDetials']['region'],
        'idle_recommendations': [],
        'ec2_recommendations': [],
        'ebs_recommendations': []
    }

    try:
        logger.info(f"Processing event: {event}")
        account_id = event['AccountDetials']['account']
        region = event['AccountDetials']['region']
        role_name = os.environ.get('ASSUME_ROLE_NAME', 'coa-get-recommendations')
        
        credentials = assume_role(account_id, role_name)
        if not credentials:
            logger.error(f"Failed to assume role in account {account_id}")
            return empty_result
        
        co_client = boto3.client('compute-optimizer',
                              region_name=region,
                              aws_access_key_id=credentials['AccessKeyId'],
                              aws_secret_access_key=credentials['SecretAccessKey'],
                              aws_session_token=credentials['SessionToken'])
        
        result = {
            'account': event['AccountDetials']['account'],
            'region': event['AccountDetials']['region'],
            'idle_recommendations': get_idle_recommendations(co_client, account_id, region) if event.get('IdleRecommendations', '').lower() == 'yes' else [],
            'ec2_recommendations': get_ec2_recommendations(co_client, account_id, region) if event.get('EC2Recommendations', '').lower() == 'yes' else [],
            'ebs_recommendations': get_ebs_recommendations(co_client, account_id, region) if event.get('EBSRecommendations', '').lower() == 'yes' else []
        }
        
        logger.info(f"Summary for account {account_id} in region {region}:")
        logger.info(f"Idle recommendations: {len(result['idle_recommendations'])}")
        logger.info(f"EC2 recommendations: {len(result['ec2_recommendations'])}")
        logger.info(f"EBS recommendations: {len(result['ebs_recommendations'])}")
        
        return result
        
    except Exception as e:
        logger.error(f"Error in lambda_handler: {str(e)}")
        return empty_result

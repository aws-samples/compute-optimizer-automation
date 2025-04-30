import boto3

def lambda_handler(event, context):
    match event["AutomationFlow"]:
        case "Idle":
            return get_idle_recommendations()
        case "EC2":
            return get_ec2_recommendations()
        case "EBS":
            return get_ebs_recommendations()
        case _:
            return []

def get_idle_recommendations():
    client = boto3.client('compute-optimizer')
    data = []
    filters = [{'name': 'Finding', 'values': ['Unattached']}]

    response = client.get_idle_recommendations(
        filters=filters
    )
    data.extend(response["idleRecommendations"])

    # Handle pagination
    while 'nextToken' in response:
        response = client.get_idle_recommendations(
            nextToken = response["nextToken"],
            filters=filters
        )
        data.extend(response["idleRecommendations"])
    
    # Process and filter the data
    filtered_data = []    
    for finding in data:
        filtered_data.append({
            'resourceId': finding['resourceId'],
            'resourceArn': finding['resourceArn'],
            'finding': finding['finding'],
            'resourceType': finding['resourceType'],
            'savings_opportunity': finding['savingsOpportunityAfterDiscounts']['estimatedMonthlySavings']['value'],
            'savings_opportunity_percentage': finding['savingsOpportunityAfterDiscounts']['savingsOpportunityPercentage']
        })
        
    return filtered_data
    
def get_ec2_recommendations():
    client = boto3.client('compute-optimizer')
    data = []
    filters = [{'name': 'Finding', 'values': ['OVER_PROVISIONED']}]
    recommendationPreferences = {'cpuVendorArchitectures': ['CURRENT']}

    response = client.get_ec2_instance_recommendations(
        filters = filters,
        recommendationPreferences = recommendationPreferences
    )
    data.extend(response["instanceRecommendations"])

    # Handle pagination
    while 'nextToken' in response:
        response = client.get_ec2_instance_recommendations(
            nextToken = response["nextToken"],
            filters = filters,
            recommendationPreferences = recommendationPreferences
        )
        data.extend(response["instanceRecommendations"])

    # Process and filter the data
    filtered_data = []    
    for finding in data:
        instance_name = 'NA'
        if 'instanceName' in finding:
            instance_name = finding['instanceName']
            
        recommendationOptions = []
        for recommendationOption in finding['recommendationOptions']:
            recommendationOptions.append({
                'instanceType':recommendationOption['instanceType'],
                'performanceRisk': recommendationOption['performanceRisk'],
                'migrationEffort': recommendationOption['migrationEffort'],
                'platformDifferences': recommendationOption['platformDifferences'],
                'savings_opportunity': recommendationOption['savingsOpportunityAfterDiscounts']['estimatedMonthlySavings']['value'],
                'savings_opportunity_percentage': recommendationOption['savingsOpportunityAfterDiscounts']['savingsOpportunityPercentage']
            })
            
        filtered_data.append({
            'resourceId': finding['instanceArn'].split('/')[1],
            'resourceArn': finding['instanceArn'],
            'finding': finding['finding'],
            'resourceName': instance_name,
            'region': finding['instanceArn'].split(':')[3],
            'currentInstanceType': finding['currentInstanceType'],
            'recommendationOptions': recommendationOptions
        })
    
    return filtered_data

def get_ebs_recommendations():
    client = boto3.client('compute-optimizer')
    data = []
    filters = [{'name': 'Finding', 'values': ['NotOptimized']}]

    response = client.get_ebs_volume_recommendations(
        filters = filters
    )
    data.extend(response["volumeRecommendations"])

    # Handle pagination
    while 'nextToken' in response:
        response = client.get_ebs_volume_recommendations(
            nextToken = response["nextToken"],
            filters=filters
        )
        data.extend(response["volumeRecommendations"])
    
    # Process and filter the data
    filtered_data = []    
    for finding in data:
        recommendationOptions = []
        for recommendationOption in finding['volumeRecommendationOptions']:
            recommendationOptions.append({
                'performanceRisk': recommendationOption['performanceRisk'],
                'new_VolumeType': recommendationOption['configuration']['volumeType'],
                'new_VolumeBaselineIOPS': recommendationOption['configuration']['volumeBaselineIOPS'],
                'new_VolumeBaselineThroughput': recommendationOption['configuration']['volumeBaselineThroughput'],
                'savings_opportunity': recommendationOption['savingsOpportunityAfterDiscounts']['estimatedMonthlySavings']['value'],
                'savings_opportunity_percentage': recommendationOption['savingsOpportunityAfterDiscounts']['savingsOpportunityPercentage']
            })
        
        filtered_data.append({
            'resourceId': finding['volumeArn'].split('/')[1],
            'resourceArn': finding['volumeArn'],
            'finding': finding['finding'],
            'current_VolumeType': finding['currentConfiguration']['volumeType'],
            'current_VolumeBaselineIOPS': finding['currentConfiguration']['volumeBaselineIOPS'],
            'current_VolumeBaselineThroughput': finding['currentConfiguration']['volumeBaselineThroughput'],
            'recommendationOptions': recommendationOptions
        })
        
    return filtered_data
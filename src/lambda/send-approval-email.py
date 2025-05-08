import boto3
import logging
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Attr, And
from datetime import datetime
from decimal import Decimal
import json
import urllib.parse
import os
import time

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logging.getLogger("boto3").setLevel(logging.WARNING)
logging.getLogger("botocore").setLevel(logging.WARNING)

def get_pending_approvals(table):
    """
    Get all items from DynamoDB that need approval (approval_sent = no) and are from today
    """
    try:
        items = []
        last_evaluated_key = None
        
        # Get today's date in the same format as stored in DynamoDB (YYYY-MM-DD)
        today = datetime.utcnow().strftime('%Y-%m-%d')
        logger.info(f"Filtering for items from date: {today}")
        
        while True:
            scan_params = {
                'FilterExpression': And(
                    Attr('approval_sent').eq('no'),
                    Attr('event_date').eq(today)
                )
            }
            if last_evaluated_key:
                scan_params['ExclusiveStartKey'] = last_evaluated_key
            
            response = table.scan(**scan_params)
            items.extend(response.get('Items', []))
            
            last_evaluated_key = response.get('LastEvaluatedKey')
            if not last_evaluated_key:
                break
        
        logger.info(f"Found {len(items)} items pending approval from today")
        return items
    except ClientError as e:
        logger.error(f"Error scanning DynamoDB: {e}")
        return []

def get_verified_email_status(ses_client, email_addresses):
    """
    Check if email addresses are verified in SES
    """
    verified_emails = []
    unverified_emails = []
    
    try:
        for email in email_addresses:
            try:
                response = ses_client.get_identity_verification_attributes(
                    Identities=[email]
                )
                status = response['VerificationAttributes'].get(email, {}).get('VerificationStatus', 'NotVerified')
                
                if status.lower() == 'success':
                    verified_emails.append(email)
                else:
                    unverified_emails.append(email)
                    logger.warning(f"Email address not verified: {email}")
                    
            except Exception as e:
                logger.error(f"Error checking verification status for {email}: {str(e)}")
                unverified_emails.append(email)
                
        return verified_emails, unverified_emails
    except Exception as e:
        logger.error(f"Error getting verification status: {str(e)}")
        return [], email_addresses

def modify_email_content(body_html, body_text, unverified_emails, default_email):
    """
    Modify email content to include unverified email notice
    """
    unverified_notice_html = f"""
    <div style="margin: 20px 0; padding: 10px; background-color: #fff3cd; border: 1px solid #ffeeba; border-radius: 4px;">
        <p><strong>Note:</strong> This email was sent to {default_email} because the following email address is not verified in AWS SES:</p>
        <ul>
            {''.join(f'<li>{email}</li>' for email in unverified_emails)}
        </ul>
        <p>To receive these notifications directly, please contact your AWS administrator to verify these email addresses.</p>
    </div>
    """
    
    unverified_notice_text = f"""
    NOTE: This email was sent to {default_email} because the following email address is not verified in AWS SES:
    {', '.join(unverified_emails)}
    To receive these notifications directly, please contact your AWS administrator to verify these email addresses.

    """
    
    # Insert the notice at the beginning of the email body
    modified_html = body_html.replace('<body>', f'<body>{unverified_notice_html}')
    modified_text = unverified_notice_text + body_text
    
    return modified_html, modified_text

def create_email_content(items):
    """
    Create HTML and text email content from the items
    """
    html_rows = ""
    text_rows = ""
    apiGwEndpoint = os.environ.get('ApiGwEndpoint')
    current_time = str(int(time.time())) 
    
    for item in items:
        taskToken = urllib.parse.quote(item.get('task_token', ''))
        resource_arn = urllib.parse.quote(item.get('resource_arn'))
        event_date = urllib.parse.quote(item.get('event_date'))
        approveEndpoint = f'{apiGwEndpoint}?action=Approved&resourceArn={resource_arn}&eventDate={event_date}&timestamp={current_time}&taskToken={taskToken}'
        rejectEndpoint = f'{apiGwEndpoint}?action=Rejected&resourceArn={resource_arn}&eventDate={event_date}&timestamp={current_time}&taskToken={taskToken}'

        if item.get('finding') == 'Unattached':
            change = 'A snapshot will be created and the volume will be deleted'
        
        if item.get('finding') == 'NotOptimized':
            change = f"""
            The volume will be updated as follows:
            <ul>
                <li>Volume Type: from {item.get('current_VolumeType', '')} to {item.get('new_VolumeType', '')}</li>
                <li>Volume IOPS: from {item.get('current_VolumeBaselineIOPS', '')} to {item.get('new_VolumeBaselineIOPS', '')}</li>
                <li>Volume Throughput: from {item.get('current_VolumeBaselineThroughput', '')} to {item.get('new_VolumeBaselineThroughput', '')}</li>
            </ul>
        """
        
        if item.get('finding') == 'OVER_PROVISIONED':
            change = f"""
            The instance will be updated as follows:
            <ul>
                <li>Instance type: from {item.get('current_resource_type', '')} to {item.get('new_resource_type', '')}</li>
            </ul>
        """
        
        risk_levels_list = ['N/A', 'Very Low', 'Low', 'Medium', 'High', 'Very High']
        performanceRisk = risk_levels_list[int(item.get('performance_risk', 0))]

        # Create HTML row
        html_rows += f"""
            <tr>
                <td style="text-align: left;">{item.get('finding', '')}</td>
                <td>{item.get('account', '')}</td>
                <td>{item.get('region', '')}</td>
                <td>{item.get('resource_id', item.get('resource_arn'))}</td>
                <td>${item.get('savings_opportunity', '')} ({item.get('savings_opportunity_percentage', '')}% of current cost)</td>
                <td>{performanceRisk}</td>
                <td style="text-align: left;">{change}</td>
                <td><a href="{approveEndpoint}">Approve</a></td>
                <td><a href="{rejectEndpoint}">Reject</a></td>
            </tr>
        """
        
        # Create text row
        text_rows += f"""
    {item.get('finding', '')}\t{item.get('account', '')}\t{item.get('region', '')}\t{item.get('resource_id', item.get('resource_arn'))}\t${item.get('savings_opportunity', '')}\t{performanceRisk}\t{change}\t{approveEndpoint}\t{rejectEndpoint}"""
    
    body_html = f"""
    <html>
    <head>
        <style>
            table {{
                border: 1px solid #ddd;
                padding: 0;
                margin: 0;
                font-size: 1em;
            }}

            table.responsive {{
                table-layout: fixed;
            }}

            table th,
            table td {{
                padding: 10px;
                background: #fcfcfc;
                text-align: center;
                vertical-align: middle;
                white-space: nowrap;
                overflow: hidden;
                display: block-block;
                text-overflow: ellipsis;
                word-wrap: break-word;
            }}

            table tr:nth-child(even) th,
            table tr:nth-child(even) td {{
                background: #f2f2f2
            }}

            table td {{
                font-size: .85em;
            }}

            table thead tr th {{
                font-size: 1em;
                font-weight: 700;
            }}

            table thead tr th,
            table thead tr td {{
                background-color: #f79d2e;
                color: #131212;
            }}
        </style>
    </head>
    <body>
        <p>Hi,</p>
        <p>We are reaching out because we need your approval in order to automatically apply the recommendations from AWS Compute Optimizer.</p>
        
        <h3>Resources pending approval:</h3>
        <table>
            <thead>
                <tr>
                    <th>Finding</th>
                    <th>Account</th>
                    <th>Region</th>
                    <th>Resource ID</th>
                    <th>Potential Savings</th>
                    <th>Performance Risk</th>
                    <th>Changes</th>
                    <th>Approve</th>
                    <th>Reject</th>
                </tr>
            </thead>
            <tbody>
                {html_rows}
            </tbody>
        </table>
        
        <p>For more information on AWS Compute Optimizer, please visit the 
        <a href="https://docs.aws.amazon.com/compute-optimizer/">AWS Compute Optimizer documentation</a></p>
        
        <p>Thank you!</p>
    </body>
    </html>
    """
    
    body_text = f"""
    Hi,
    
    We are reaching out because we need your approval in order to automatically apply the recommendations from AWS Compute Optimizer.
    
    Resources pending approval:
    Finding\tAccount\tRegion\tRetResource ID\tPotential Savings\tPerformance Risk\tChanges\tApprove\tReject{text_rows}
    
    For more information on AWS Compute Optimizer, please visit the AWS Compute Optimizer documentation:
    https://docs.aws.amazon.com/compute-optimizer/
    
    Thank you!
    """
    
    return body_html, body_text

def update_approval_status(table, items):
    """
    Update approval_sent status to 'yes' for processed items
    """
    try:
        for item in items:
            table.update_item(
                Key={
                    'resource_arn': item['resource_arn'],
                    'event_date': item['event_date']
                },
                UpdateExpression='SET approval_sent = :val',
                ExpressionAttributeValues={
                    ':val': 'yes'
                }
            )
        logger.info(f"Successfully updated {len(items)} items")
        return True
    except ClientError as e:
        logger.error(f"Error updating items: {e}")
        return False

def parse_tags(tags_data):
    """
    Parse tags from either string or list format
    """
    if isinstance(tags_data, str):
        try:
            # Replace single quotes with double quotes for valid JSON
            cleaned_tags = tags_data.replace("'", '"')
            return json.loads(cleaned_tags)
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing tags string: {e}")
            return []
    return tags_data if isinstance(tags_data, list) else []

def group_items_by_approver(items):
    """
    Group items by approver email from tags or default
    """
    default_email = os.environ.get('DEFAULT_EMAIL')
    approval_tag = os.environ.get('APPROVAL_TAG', 'COA-approver-email')
    grouped_items = {}
    
    for item in items:
        # Parse tags
        tags = parse_tags(item.get('tags', []))
        
        # Find approver email in tags
        approver_email = None
        for tag in tags:
            if tag.get('Key') == approval_tag:
                approver_email = tag.get('Value')
                break
        
        # Use default email if no approver tag found
        if not approver_email:
            approver_email = default_email
            logger.info(f"No approver email tag found for resource {item.get('resource_id')}, using default")
        
        # Group items by approver email
        if approver_email not in grouped_items:
            grouped_items[approver_email] = []
        grouped_items[approver_email].append(item)
        
        logger.info(f"Resource {item.get('resource_id')} assigned to approver {approver_email}")
    
    return grouped_items

def send_approval_emails(ses_client, grouped_items):
    """
    Send approval emails to each approver
    """
    default_email = os.environ.get('DEFAULT_EMAIL')
    success = True
    
    for approver_email, items in grouped_items.items():
        try:
            # Check if approver email is verified
            verified_emails, unverified_emails = get_verified_email_status(ses_client, [approver_email])
            
            # Determine final recipient and modify content if needed
            if not verified_emails:
                logger.warning(f"Approver email {approver_email} is not verified, using default email")
                final_recipient = default_email
                body_html, body_text = create_email_content(items)
                modified_html, modified_text = modify_email_content(
                    body_html,
                    body_text,
                    [approver_email],
                    default_email
                )
            else:
                final_recipient = approver_email
                modified_html, modified_text = create_email_content(items)
            
            # Send email
            response = ses_client.send_email(
                Source=default_email,
                Destination={
                    'ToAddresses': [final_recipient],
                },
                Message={
                    'Subject': {
                        'Charset': 'UTF-8',
                        'Data': '[Action Required] AWS COA - Approval for AWS Compute Optimizer Recommendations',
                    },
                    'Body': {
                        'Html': {
                            'Charset': 'UTF-8',
                            'Data': modified_html,
                        },
                        'Text': {
                            'Charset': 'UTF-8',
                            'Data': modified_text,
                        },
                    },
                },
            )
            
            logger.info(f"Email sent successfully to {final_recipient} for {len(items)} resources. MessageId: {response['MessageId']}")
            
        except Exception as e:
            logger.error(f"Error sending email to {approver_email}: {str(e)}")
            success = False
    
    return success

def lambda_handler(event, context):
    """
    Main Lambda handler for processing pending approvals
    """
    try:
        # Initialize AWS clients
        dynamodb = boto3.resource('dynamodb')
        ses = boto3.client('ses')
        table_name = os.environ.get('DDB_TABLE_NAME')
        table = dynamodb.Table(table_name) 
        
        # Get items pending approval
        items = get_pending_approvals(table)
        if not items:
            logger.info("No items pending approval")
            return {
                'statusCode': 200,
                'body': 'No items pending approval'
            }
        
        # Group items by approver email
        grouped_items = group_items_by_approver(items)
        logger.info(f"Grouped items for {len(grouped_items)} different approvers")
        # print(grouped_items)
        
        # Send emails to each approver
        if send_approval_emails(ses, grouped_items):
            # Update approval status
            if update_approval_status(table, items):
                return {
                    'statusCode': 200,
                    'body': f'Successfully processed {len(items)} items for {len(grouped_items)} approvers'
                }
        
        return {
            'statusCode': 500,
            'body': 'Error processing items'
        }
        
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return {
            'statusCode': 500,
            'body': f'Unexpected error: {str(e)}'
        }

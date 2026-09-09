import json
import os
import time
import base64
import urllib.request
import boto3

def lambda_handler(event, context):
    print("Event received: ", json.dumps(event))
    
    # Safely extract and check the body to prevent NoneType errors
    body_str = event.get("body")
    if not body_str:
        # Fallback for direct invocations or empty payloads that aren't Slack webhooks
        return handle_ecs_failure(event, context)
    
    # 1. Check if this is an incoming event from Slack via API Gateway
    if "requestContext" in event:
        try:
            # Handle base64 encoded bodies if API Gateway encodes them
            if event.get("isBase64Encoded", False):
                body_str = base64.b64decode(body_str).decode('utf-8')
                
            body = json.loads(body_str)
            
            # Handle Slack's initial URL verification challenge
            if "challenge" in body:
                return {
                    "statusCode": 200,
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps({"challenge": body["challenge"]})
                }
            
            # Handle actual Slack user mentions/messages
            slack_event = body.get("event", {})
            if slack_event.get("type") == "app_mention" or slack_event.get("type") == "message":
                # Prevent infinite loops from the bot talking to itself
                if slack_event.get("bot_id") or slack_event.get("subtype") == "bot_message":
                    return {'statusCode': 200, 'body': 'Ignored bot message'}
                
                return handle_interactive_chat(slack_event)
                
        except Exception as e:
            print(f"Error parsing API Gateway / Slack event: {str(e)}")
            return {'statusCode': 400, 'body': json.dumps(f"Parsing error: {str(e)}")}

    # 2. Otherwise, fallback to handling the default ECS Fargate task failure alert flow
    return handle_ecs_failure(event, context)


def handle_ecs_failure(event, context):
    """Automated crash reporting pipeline with active log streaming and Nova Lite analysis."""
    logs_client = boto3.client('logs')
    log_group_name = "/ecs/fargate-test-app"
    
    log_snippet = "No log streams found."
    stream_name = None
    
    # Poll for the active log stream
    for attempt in range(3):
        try:
            streams_response = logs_client.describe_log_streams(
                logGroupName=log_group_name,
                orderBy='LastEventTime',
                descending=True,
                limit=1
            )
            streams = streams_response.get('logStreams', [])
            if streams:
                stream_name = streams[0]['logStreamName']
                break
        except Exception as e:
            print(f"Polling attempt failed: {str(e)}")
        time.sleep(2)

    if stream_name:
        try:
            log_events = logs_client.get_log_events(
                logGroupName=log_group_name,
                logStreamName=stream_name,
                limit=15,
                startFromHead=False
            )
            events = log_events.get('events', [])
            log_snippet = "\n".join([e['message'] for e in events]) if events else "Stream empty."
        except Exception as e:
            log_snippet = f"Could not fetch logs: {str(e)}"

    bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')
    prompt = f"""
    You are an expert Autonomous SRE Agent. 
    An ECS task encountered a failure. Recent container logs:
    {log_snippet}
    
    Analyze the failure. Is this a Memory (OOM), CPU bottleneck, or code exception? 
    Provide a concise summary and recommended next steps.
    """
    
    body = {
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "inferenceConfig": {"maxTokens": 300, "temperature": 0.0}
    }
    
    ai_analysis = "Analysis unavailable."
    try:
        bedrock_response = bedrock.invoke_model(modelId="amazon.nova-lite-v1:0", body=json.dumps(body))
        result = json.loads(bedrock_response['body'].read())
        ai_analysis = result['output']['message']['content'][0]['text']
    except Exception as ex:
        ai_analysis = f"Bedrock error: {str(ex)}"

    # Publish notification payload via SNS using the compliant Chatbot custom notification schema
    sns_topic_arn = os.environ.get("SNS_TOPIC_ARN")
    if sns_topic_arn:
        try:
            sns_client = boto3.client('sns')
            custom_notification = {
                "version": "1.0",
                "source": "custom",
                "content": {
                    "textType": "client-markdown",
                    "description": f"🚨 *AutoSRE Agent: Fargate Task Failure*\n\n{ai_analysis}\n\n_Tip: Tag me in this channel to ask follow-up questions!_"
                }
            }
            sns_client.publish(TopicArn=sns_topic_arn, Message=json.dumps(custom_notification))
        except Exception as sns_ex:
            print(f"SNS publish failed: {str(sns_ex)}")

    return {'statusCode': 200, 'body': json.dumps('ECS failure processed.')}


def handle_interactive_chat(slack_event):
    """Fetches fresh logs on-demand, queries Bedrock, and replies directly to Slack."""
    channel_id = slack_event.get("channel")
    user_query = slack_event.get("text", "")
    
    print(f"Interactive query from Slack: {user_query}")
    
    # Fetch recent logs from CloudWatch on-demand for live context
    logs_client = boto3.client('logs')
    log_group_name = "/ecs/fargate-test-app"
    log_snippet = "No recent logs found."
    try:
        streams_response = logs_client.describe_log_streams(
            logGroupName=log_group_name, orderBy='LastEventTime', descending=True, limit=1
        )
        streams = streams_response.get('logStreams', [])
        if streams:
            stream_name = streams[0]['logStreamName']
            log_events = logs_client.get_log_events(
                logGroupName=log_group_name, logStreamName=stream_name, limit=15, startFromHead=False
            )
            events = log_events.get('events', [])
            log_snippet = "\n".join([e['message'] for e in events])
    except Exception as e:
        print(f"Could not fetch logs for chat context: {str(e)}")

    # Ask Bedrock (Nova Lite) using the user's specific prompt + live logs
    bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')
    prompt = f"""
    You are an interactive SRE Chatbot assistant for an AWS lab.
    Recent container logs from /ecs/fargate-test-app:
    {log_snippet}
    
    The engineer asks: "{user_query}"
    
    Analyze the logs and the user's question. Provide a helpful, technical, and clear troubleshooting response with actionable next steps.
    """
    
    body = {
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "inferenceConfig": {"maxTokens": 400, "temperature": 0.2}
    }
    
    reply_text = "I'm having trouble analyzing the logs right now."
    try:
        bedrock_response = bedrock.invoke_model(modelId="amazon.nova-lite-v1:0", body=json.dumps(body))
        result = json.loads(bedrock_response['body'].read())
        reply_text = result['output']['message']['content'][0]['text']
    except Exception as ex:
        reply_text = f"Error generating AI response: {str(ex)}"

    # Post reply back to Slack using Slack's chat.postMessage API
    slack_token = os.environ.get("SLACK_BOT_TOKEN")
    if slack_token:
        slack_url = "https://slack.com/api/chat.postMessage"
        payload = {
            "channel": channel_id,
            "text": reply_text
        }
        req = urllib.request.Request(
            slack_url,
            data=json.dumps(payload).encode('utf-8'),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {slack_token}"
            }
        )
        try:
            urllib.request.urlopen(req)
        except Exception as api_ex:
            print(f"Failed to post message back to Slack API: {str(api_ex)}")

    return {'statusCode': 200, 'body': json.dumps('Chat message processed successfully.')}
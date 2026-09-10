import json
import os
import time
import base64
import ast
import urllib.request
import boto3
from boto3.dynamodb.conditions import Key

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')
table_name = os.environ.get('DYNAMODB_TABLE_NAME', 'sreagent')
table = dynamodb.Table(table_name)

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID", "C0C1B73JTA4")  # Fallback target channel ID
LOG_GROUP_NAME = "/ecs/fargate-test-app"


def parse_slack_body(body_str):
    """Safely parses incoming JSON and strictly guarantees a dictionary is returned."""
    if not body_str:
        return {}
    if isinstance(body_str, dict):
        return body_str
        
    # 1. Try standard JSON loading
    try:
        parsed = json.loads(body_str)
        if isinstance(parsed, str):
            parsed = json.loads(parsed) # Handle double-encoding
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
        
    # 2. Try replacing single quotes with double quotes
    try:
        fixed_str = body_str.replace("'", '"')
        parsed = json.loads(fixed_str)
        if isinstance(parsed, str):
            parsed = json.loads(parsed)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
        
    # 3. Fallback to ast.literal_eval
    try:
        res = ast.literal_eval(body_str)
        if isinstance(res, dict):
            return res
    except Exception:
        pass
        
    raise ValueError(f"Body could not be parsed into a dictionary: {body_str}")


def get_conversation_history(thread_ts):
    """Fetches past messages for this specific Slack thread from DynamoDB."""
    try:
        response = table.query(
            KeyConditionExpression=Key('thread_ts').eq(thread_ts),
            ScanIndexForward=True, # Oldest to newest
            Limit=10 # Keep last 10 messages for context window
        )
        return response.get('Items', [])
    except Exception as e:
        print(f"Error fetching history from DynamoDB: {e}")
        return []


def save_message_to_history(thread_ts, role, content):
    """Saves a message turn to DynamoDB with a 24-hour TTL expiration."""
    try:
        ttl = int(time.time()) + 86400 # 24 hours from now
        table.put_item(
            Item={
                'thread_ts': thread_ts,
                'timestamp': int(time.time() * 1000), # Unique millisecond sort key
                'role': role, # 'user' or 'assistant'
                'content': content,
                'expires_at': ttl
            }
        )
    except Exception as e:
        print(f"Error saving history to DynamoDB: {e}")


def lambda_handler(event, context):
    print("Event received: ", json.dumps(event))
    
    # Check for Slack retry headers and drop them to prevent duplicate spamming
    headers = event.get("headers") or {}
    retry_header_keys = [k for k in headers.keys() if k.lower() == "x-slack-retry-num"]
    if retry_header_keys:
        print(f"Ignored Slack retry event (Header found: {retry_header_keys[0]})")
        return {'statusCode': 200, 'body': json.dumps('Ignored retry')}

    body_str = event.get("body")
    if not body_str:
        # Triggers when event comes from EventBridge / ECS state change directly
        return handle_ecs_failure(event, context)
    
    if "requestContext" in event:
        try:
            if event.get("isBase64Encoded", False):
                body_str = base64.b64decode(body_str).decode('utf-8')
                
            body = parse_slack_body(body_str)
            
            if "challenge" in body:
                return {
                    "statusCode": 200,
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps({"challenge": body["challenge"]})
                }
            
            slack_event = body.get("event", {})
            if slack_event.get("type") == "app_mention" or slack_event.get("type") == "message":
                if slack_event.get("bot_id") or slack_event.get("subtype") == "bot_message":
                    return {'statusCode': 200, 'body': 'Ignored bot message'}
                
                return handle_interactive_chat(slack_event)
                
        except Exception as e:
            print(f"Error parsing API Gateway / Slack event: {str(e)}")
            return {'statusCode': 400, 'body': json.dumps(f"Parsing error: {str(e)}")}

    return handle_ecs_failure(event, context)


def handle_ecs_failure(event, context):
    """Automated crash reporting pipeline with active log streaming, Nova Lite analysis, and direct Slack notification."""
    print("Handling automated ECS failure event...")
    logs_client = boto3.client('logs')
    
    log_snippet = "No log streams found."
    stream_name = None
    
    for attempt in range(3):
        try:
            streams_response = logs_client.describe_log_streams(
                logGroupName=LOG_GROUP_NAME,
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
                logGroupName=LOG_GROUP_NAME,
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
    You are a senior SRE teammate. An ECS task failed. Recent container logs:
    {log_snippet}
    
    Give a short, human-like breakdown of what went wrong and how to prevent it from happening again.
    """
    
    body = {
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "inferenceConfig": {"maxTokens": 200, "temperature": 0.2}
    }
    
    ai_analysis = "Analysis unavailable."
    try:
        bedrock_response = bedrock.invoke_model(modelId="amazon.nova-lite-v1:0", body=json.dumps(body))
        result = json.loads(bedrock_response['body'].read())
        ai_analysis = result['output']['message']['content'][0]['text']
    except Exception as ex:
        ai_analysis = f"Bedrock error: {str(ex)}"

    # Post failure analysis directly to Slack channel
    if SLACK_BOT_TOKEN:
        slack_url = "https://slack.com/api/chat.postMessage"
        payload = {
            "channel": SLACK_CHANNEL_ID,
            "text": f"🚨 *AutoSRE Agent: Fargate Task Failure Detected*\n\n{ai_analysis}"
        }
        req = urllib.request.Request(
            slack_url,
            data=json.dumps(payload).encode('utf-8'),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {SLACK_BOT_TOKEN}"
            }
        )
        try:
            urllib.request.urlopen(req)
            print("Successfully posted failure alert directly to Slack.")
        except Exception as api_ex:
            print(f"Failed to post crash alert to Slack API: {str(api_ex)}")
    else:
        print("WARNING: SLACK_BOT_TOKEN environment variable is not set.")

    return {'statusCode': 200, 'body': json.dumps('ECS failure processed.')}


def handle_interactive_chat(slack_event):
    """Fetches fresh logs on-demand, leverages thread memory, queries Bedrock, and replies to Slack."""
    channel_id = slack_event.get("channel")
    user_query = slack_event.get("text", "").strip()
    thread_ts = slack_event.get("thread_ts") or slack_event.get("ts")
    
    print(f"Interactive query from Slack (Thread: {thread_ts}): {user_query}")
    
    # 1. Fetch short-term conversation history for this specific thread
    history = get_conversation_history(thread_ts)
    history_formatted = ""
    if history:
        history_formatted = "Conversation History in this thread:\n"
        for h in history:
            role_label = "User" if h['role'] == 'user' else "Assistant"
            history_formatted += f"- {role_label}: {h['content']}\n"
        history_formatted += "\n"

    # 2. Fetch live container logs
    logs_client = boto3.client('logs')
    log_snippet = "No recent logs found."
    try:
        streams_response = logs_client.describe_log_streams(
            logGroupName=LOG_GROUP_NAME, orderBy='LastEventTime', descending=True, limit=1
        )
        streams = streams_response.get('logStreams', [])
        if streams:
            stream_name = streams[0]['logStreamName']
            log_events = logs_client.get_log_events(
                logGroupName=LOG_GROUP_NAME, logStreamName=stream_name, limit=15, startFromHead=False
            )
            events = log_events.get('events', [])
            log_snippet = "\n".join([e['message'] for e in events])
    except Exception as e:
        print(f"Could not fetch logs for chat context: {str(e)}")

    # 3. Construct clean, non-contradictory prompt for chat
    bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')
    prompt = f"""
    You are a helpful, senior SRE engineer talking directly to a teammate in Slack. 
    
    {history_formatted}Recent container logs from the app:
    {log_snippet}
    
    The engineer asks: "{user_query}"
    
    Follow these response rules strictly based on the user's intent:
    1. **Small Talk (e.g., "hi", "hello", "thanks"):** Respond conversationally and briefly as a teammate. Do NOT analyze logs or mention crashes.
    2. **Technical Questions / Errors:** Explain what you see in the logs, identify the root cause, and provide clear, concise preventative steps. Filter out background noise like favicon 404s unless relevant.
    3. **Out-of-Scope Questions:** If the user asks about anything outside the monitored ECS app (e.g., weather, general coding, sports), you must reply *only* with this exact phrase and nothing else: "Sorry I am not trained to answer this question. Ask me anything about the ECS app."
    4. **Conversation Summary:** If requested, summarize the thread history concisely.
    
    Keep your response short, natural, and friendly. Avoid robotic walls of text.
    """
    
    body = {
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "inferenceConfig": {"maxTokens": 250, "temperature": 0.3}
    }
    
    reply_text = "Hey, I'm having trouble pulling the logs right now. Give me just a second to check again."
    try:
        bedrock_response = bedrock.invoke_model(modelId="amazon.nova-lite-v1:0", body=json.dumps(body))
        result = json.loads(bedrock_response['body'].read())
        reply_text = result['output']['message']['content'][0]['text']
    except Exception as ex:
        reply_text = f"Ah, ran into a snag getting the AI analysis: {str(ex)}"

    # 4. Save the user query and assistant reply to DynamoDB thread history
    save_message_to_history(thread_ts, 'user', user_query)
    save_message_to_history(thread_ts, 'assistant', reply_text)

    # 5. Post response back to Slack within the thread
    if SLACK_BOT_TOKEN:
        slack_url = "https://slack.com/api/chat.postMessage"
        payload = {
            "channel": channel_id,
            "text": reply_text,
            "thread_ts": thread_ts  # Anchors response inside the Slack thread
        }
        req = urllib.request.Request(
            slack_url,
            data=json.dumps(payload).encode('utf-8'),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {SLACK_BOT_TOKEN}"
            }
        )
        try:
            urllib.request.urlopen(req)
        except Exception as api_ex:
            print(f"Failed to post message back to Slack API: {str(api_ex)}")

    return {'statusCode': 200, 'body': json.dumps('Chat message processed successfully.')}
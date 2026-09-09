import json
import os
import time
import boto3

def lambda_handler(event, context):
    print("AutoSRE Agent triggered with event: ", json.dumps(event))
    
    logs_client = boto3.client('logs')
    log_group_name = "/ecs/fargate-test-app"
    
    log_snippet = "No log streams found."
    
    # 1. Active Log Stream Polling Mechanism
    stream_name = None
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
                print(f"Found active log stream: {stream_name}")
                break
        except Exception as e:
            print(f"Attempt {attempt + 1}: Waiting for log stream to initialize... ({str(e)})")
        
        time.sleep(2)

    # 2. Fetch Log Events
    if stream_name:
        try:
            log_events = logs_client.get_log_events(
                logGroupName=log_group_name,
                logStreamName=stream_name,
                limit=15,
                startFromHead=False
            )
            events = log_events.get('events', [])
            log_snippet = "\n".join([e['message'] for e in events]) if events else "Log stream was empty."
        except Exception as e:
            log_snippet = f"Could not fetch log events: {str(e)}"

    print(f"Extracted Log Snippet for AI: {log_snippet}")

    # 3. Amazon Nova Lite Model Invocation
    bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')
    
    prompt = f"""
    You are an expert Autonomous SRE Agent. 
    An ECS task encountered a failure. Recent container logs:
    {log_snippet}
    
    Analyze the failure. Is this a Memory (OOM) or CPU bottleneck, or a code exception? 
    Provide a brief JSON analysis with keys: 'root_cause', 'recommended_cpu', and 'recommended_memory'.
    """
    
    body = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "text": prompt
                    }
                ]
            }
        ],
        "inferenceConfig": {
            "maxTokens": 300,
            "temperature": 0.0
        }
    }
    
    ai_analysis = "Analysis unavailable."
    try:
        bedrock_response = bedrock.invoke_model(
            modelId="amazon.nova-lite-v1:0",
            body=json.dumps(body)
        )
        result = json.loads(bedrock_response['body'].read())
        ai_analysis = result['output']['message']['content'][0]['text']
        print(f"Nova Lite Diagnosis: {ai_analysis}")
        
    except Exception as ex:
        ai_analysis = f"Bedrock invocation failed: {str(ex)}"

    # 4. Amazon Q Developer / AWS Chatbot Compliant Custom Notification Schema
    sns_topic_arn = os.environ.get("SNS_TOPIC_ARN")
    if sns_topic_arn:
        try:
            sns_client = boto3.client('sns')
            
            # Compliant schema format: source must be 'custom' and message goes into 'description'
            custom_notification = {
                "version": "1.0",
                "source": "custom",
                "content": {
                    "textType": "client-markdown",
                    "description": f"🚨 *AutoSRE Agent: Fargate Task Failure*\n\n{ai_analysis}\n\n_Tip: Type `@aws` or `@Amazon Q` in this channel to ask follow-up questions about this crash!_"
                }
            }
            
            sns_client.publish(
                TopicArn=sns_topic_arn,
                Message=json.dumps(custom_notification),
                Subject="AutoSRE Diagnostic Report"
            )
            print("Successfully published valid custom notification to SNS topic.")
        except Exception as sns_ex:
            print(f"Failed to publish to SNS: {str(sns_ex)}")
    else:
        print("SNS_TOPIC_ARN environment variable not set, skipping notification.")

    return {
        'statusCode': 200,
        'body': json.dumps('Auto-remediation analysis complete with compliant Chatbot notification.')
    }
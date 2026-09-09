import json
import os
import boto3

def lambda_handler(event, context):
    print("AutoSRE Agent triggered with event: ", json.dumps(event))
    
    # 1. Query CloudWatch Logs using FilterLogEvents (handles missing streams gracefully)
    logs_client = boto3.client('logs')
    log_group_name = "/aws/ecs/fargate-test-app"
    
    log_snippet = "No logs available yet."
    try:
        response = logs_client.filter_log_events(
            logGroupName=log_group_name,
            limit=10,
            interleaved=True
        )
        events = response.get('events', [])
        log_snippet = "\n".join([e['message'] for e in events]) if events else "Log group is empty."
    except Exception as e:
        log_snippet = f"Could not fetch logs (group may not exist yet): {str(e)}"

    print(f"Extracted Log Snippet for AI: {log_snippet}")

    # 2. Invoke Amazon Nova Lite for root-cause and sizing recommendation
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
    
    try:
        bedrock_response = bedrock.invoke_model(
            modelId="amazon.nova-lite-v1:0",
            body=json.dumps(body)
        )
        result = json.loads(bedrock_response['body'].read())
        ai_analysis = result['output']['message']['content'][0]['text']
        print(f"Nova Lite Diagnosis: {ai_analysis}")
        
    except Exception as ex:
        print(f"Bedrock invocation failed: {str(ex)}")

    return {
        'statusCode': 200,
        'body': json.dumps('Auto-remediation analysis complete with Nova Lite.')
    }
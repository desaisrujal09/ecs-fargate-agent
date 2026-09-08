import json
import os
import boto3

def lambda_handler(event, context):
    print("AutoSRE Agent triggered with event: ", json.dumps(event))
    
    # Query CloudWatch Logs for container OOM or critical exits
    logs_client = boto3.client('logs')
    log_group_name = "/aws/ecs/fargate-test-app"
    
    log_snippet = "No errors parsed yet."
    try:
        response = logs_client.filter_log_events(
            logGroupName=log_group_name,
            filterPattern="CRITICAL",
            limit=5
        )
        events = response.get('events', [])
        log_snippet = "\n".join([e['message'] for e in events]) if events else "No explicit critical logs found."
    except Exception as e:
        log_snippet = f"Could not fetch logs: {str(e)}"

    # Invoke Amazon Bedrock (Claude 3 Haiku) for root-cause and sizing recommendation
    bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')
    prompt = f"""
    You are an expert Autonomous SRE Agent. 
    An ECS task encountered a failure. Recent container logs:
    {log_snippet}
    
    Analyze the failure. Is this a Memory (OOM) or CPU bottleneck? 
    Provide a brief JSON analysis with keys: 'root_cause', 'recommended_cpu', and 'recommended_memory'.
    """
    
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 300,
        "messages": [{"role": "user", "content": prompt}]
    }
    
    try:
        bedrock_response = bedrock.invoke_model(
            modelId="anthropic.claude-3-haiku-20240307-v1:0",
            body=json.dumps(body)
        )
        result = json.loads(bedrock_response['body'].read())
        ai_analysis = result['content'][0]['text']
        print(f"Bedrock Diagnosis: {ai_analysis}")
    except Exception as ex:
        print(f"Bedrock invocation skipped or failed: {str(ex)}")

    return {
        'statusCode': 200,
        'body': json.dumps('Auto-remediation analysis complete.')
    }
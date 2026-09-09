# AutoSRE — Autonomous SRE ChatOps Agent for AWS ECS (Fargate)

AutoSRE is an event-driven ChatOps agent that detects Amazon ECS / Fargate task failures, extracts recent container logs, and provides concise, actionable root-cause analysis using Amazon Bedrock (Nova Lite). It can also respond interactively to Slack mentions for on-demand troubleshooting.

## Key features
- Automated detection and processing of ECS task STOPPED events (e.g., EssentialContainerExited, OutOfMemory).
- Lambda-based pipeline that fetches recent CloudWatch logs and invokes Bedrock to generate human-friendly analysis.
- Interactive Slack ChatOps: reply to `@app_mention` messages with concise SRE guidance.
- Terraform-driven infrastructure: ECS cluster & service, ECR repo, Lambda, EventBridge rule, API Gateway, CloudWatch log group, SNS notifications.
- Small demo Flask app with endpoints to test crash/OOM scenarios.

## Architecture (high level)
```mermaid
flowchart TD
  Slack[Slack Workspace] -->|@AutoSRE Mention| API[API Gateway]
  API -->|Invoke| L[(AWS Lambda)]
  ECS[Fargate Task] -->|Container Logs| CW[CloudWatch Logs]
  L <-->|Fetch Logs| CW
  L <-->|Invoke| B[Amazon Bedrock (Nova Lite)]
  L -->|Publish| SNS[Amazon SNS]
  L -->|Post| Slack
```

## Stack
- Languages: Python (Lambda + demo app), HCL (Terraform)
- Runtime: Python 3.11 for Lambda and demo app
- Notable libraries/tools: boto3 (AWS SDK), Flask (demo app), Terraform, Docker

## Repository layout
```
Dockerfile                # Demo app container image
app.py                    # Simple Flask app used for Fargate testing (/, /crash, /oom)
Terraform/
  main.tf                 # Terraform infra (ECR, ECS, Lambda, EventBridge, API Gateway, etc.)
  lambda_function.py      # Lambda handler packaged by Terraform
README.md                  # (this file)
.github/                   # GitHub workflow config (if any)
```

How it fits together:
- Terraform provisions AWS resources. The Lambda (Terraform/lambda_function.py) handles both EventBridge-triggered ECS-failure processing and API Gateway Slack events.
- On ECS task STOPPED events, EventBridge triggers the Lambda which fetches logs, asks Bedrock for analysis, and optionally publishes to an SNS topic.
- Slack mentions reach the API Gateway endpoint, which proxies the request to the same Lambda; the Lambda fetches logs and replies back via Slack Web API.

## Quickstart — prerequisites
- AWS account with permissions to create ECR, ECS, Lambda, IAM roles/policies, CloudWatch, EventBridge, API Gateway, SNS.
- Terraform v1.x
- AWS CLI configured (aws configure)
- Docker
- Slack workspace and a Slack App with:
  - Bot token (xoxb...) for `SLACK_BOT_TOKEN`
  - Event subscription for `app_mention` (disable socket mode if using API Gateway)
  - Reinstall to workspace after changing permissions/subscriptions

## Local development / run demo app
Run locally (quick):
```bash
# Option A: run with Python (for quick tests)
python3 -m venv venv && source venv/bin/activate
pip install flask
python app.py
# app listens on :8080
curl http://localhost:8080/
curl http://localhost:8080/crash   # triggers immediate process exit (for testing)
curl http://localhost:8080/oom     # attempts to exhaust memory (for testing)
```

Or build and run with Docker:
```bash
docker build -t fargate-demo:latest .
docker run -p 8080:8080 fargate-demo:latest
```

## Deploy to AWS (recommended flow)
1. Clone repository and set your AWS CLI credentials.
2. Initialize and apply Terraform to create infra (it creates ECR, ECS, Lambda, API Gateway, etc.)
```bash
cd Terraform
terraform init
terraform apply
# Note the terraform output "slack_webhook_url" after apply
```

3. Build and push the container to the ECR repository created by Terraform:
```bash
# Get repo URI from Terraform output or AWS console
REPO_URI=$(terraform output -raw ecr_repository_url 2>/dev/null || echo "<your_ecr_repo_uri_here>")

# Build
docker build -t fargate-app:latest ..

# Tag and push to ECR (example flow; you must authenticate first)
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin ${REPO_URI%/*}
docker tag fargate-app:latest ${REPO_URI}:latest
docker push ${REPO_URI}:latest
```

4. Force ECS to pull the new image (if needed):
```bash
# Replace cluster and service names as created by Terraform
aws ecs update-service --cluster fargate-agent-lab --service fargate-test-service --force-new-deployment --region us-east-1
```

5. Configure Slack:
- Copy the `slack_webhook_url` Terraform output and paste into your Slack App Event Subscriptions → Request URL.
- Set `SLACK_BOT_TOKEN` as the Terraform variable or environment variable used by Lambda (Terraform main.tf references var.slack_bot_token).
- Reinstall the Slack App to your workspace after changing permission/scopes.

## Required environment variables / Terraform variables
- `var.slack_bot_token` — Slack bot token used by Lambda to call chat.postMessage
- `SNS_TOPIC_ARN` — (Terraform sets SNS topic in example; Lambda reads from env)
- AWS credentials must be available to Terraform / CLI for provisioning and ECR push.

## Security & permissions notes
- Terraform creates IAM roles and attaches a custom policy allowing:
  - bedrock:InvokeModel
  - logs:FilterLogEvents, DescribeLogGroups/Streams, GetLogEvents
  - sns:Publish to the configured topic
- Review the custom policy in Terraform before running in production — scope down resource ARNs where possible.

## Troubleshooting & common gotchas
- Slack verification: During setup Slack sends a URL verification `challenge` payload — the Lambda handles this if API Gateway is passing body through correctly.
- Duplicate messages: Slack retries can trigger duplicates; the Lambda checks `X-Slack-Retry-Num` header and returns early to avoid duplicate replies.
- Socket Mode vs HTTP: If using API Gateway ensure `Socket Mode` is disabled in Slack app settings; using both can prevent events from arriving.
- If tasks repeatedly stop after deploying, check:
  - Container logs in CloudWatch: `/ecs/fargate-test-app`
  - ECS task definition image tag and that the container image exists in ECR
  - IAM permissions for ECS task to pull images and send logs
- If Bedrock invocations fail, confirm the Lambda role has the bedrock:InvokeModel permission and Bedrock usage quota / region support.

## Development notes
- Lambda source: Terraform/lambda_function.py
  - Core flows:
    - parse_slack_body(body_str): robust parsing for double-encoded JSON
    - lambda_handler: routes between Slack interactive events and automated ECS failure pipeline
    - handle_ecs_failure: describe log streams, get log events, call Bedrock, publish to SNS
    - handle_interactive_chat: fetch recent logs, prompt Bedrock, reply to Slack via chat.postMessage
- Demo Flask app: app.py — endpoints:
  - `/` — health
  - `/crash` — immediate process exit (stderr message)
  - `/oom` — attempt to exhaust memory for testing OOM behavior

## Cost & region
- Terraform example uses us-east-1 and Bedrock invocation (amazon.nova-lite-v1:0). Bedrock and other services may incur costs. Review AWS pricing before deploying to production.

## Contributing
- Open an issue or PR. If adding features that alter infrastructure, update Terraform and the README deployment steps.

## License
Choose a license and add it to this repo (e.g., MIT). Replace this section with your project license.

## Contact
Maintainer: desaisrujal09 (https://github.com/desaisrujal09)

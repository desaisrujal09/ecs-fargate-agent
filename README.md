# ECS Fargate Agent

![AWS](https://img.shields.io/badge/AWS-ECS%20Fargate-FF9900?logo=amazonaws&logoColor=white)
![Terraform](https://img.shields.io/badge/IaC-Terraform-623CE4?logo=terraform&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/CI%2FCD-GitHub%20Actions-2088FF?logo=githubactions&logoColor=white)
![Docker](https://img.shields.io/badge/Containers-Docker-2496ED?logo=docker&logoColor=white)
![Slack](https://img.shields.io/badge/ChatOps-Slack-4A154B?logo=slack&logoColor=white)
![Python](https://img.shields.io/badge/App-Python%203.11-3776AB?logo=python&logoColor=white)

A portfolio project that demonstrates how to deploy a containerized Python application on **Amazon ECS Fargate** with Terraform-managed infrastructure, GitHub Actions-based CI/CD, remote Terraform state in S3, and a Slack-integrated operational chatbot for failure analysis and response.

## What this project does

This project provisions AWS infrastructure and deploys a lightweight Flask application to ECS on Fargate. It also includes a Lambda-based automation layer that can process Slack events, inspect ECS-related logs, and generate operational responses for chatbot-style incident workflows.

From a portfolio perspective, this repo showcases practical cloud engineering skills across infrastructure as code, container delivery, AWS-native operations, CI/CD automation, and ChatOps-style integrations.

## Highlights

- Deploys a containerized Flask app to **Amazon ECS on Fargate**.
- Uses **Terraform** to provision and manage infrastructure.
- Uses **GitHub Actions** to deploy both infrastructure and application changes.
- Stores Terraform remote state in an **S3 backend**.
- Pushes application images to **Amazon ECR**.
- Integrates **Slack** as the chatbot interface.
- Uses **AWS Lambda** to handle Slack interactions and ECS failure-processing logic.
- Pulls recent **CloudWatch Logs** data for troubleshooting context.
- Uses **Amazon Bedrock Nova Lite** for concise AI-assisted incident analysis.
- Publishes notifications through **Amazon SNS**.

## Architecture

```text
Developer Push / Manual Trigger
            |
            v
     GitHub Actions
      /          \
     v            v
Terraform Apply   Docker Build + Push to ECR
     |                         |
     v                         v
AWS Infrastructure      ECS Service Update
     |                         |
     +-------------> Amazon ECS Fargate
                              |
                              v
                     Flask Test Application
                       |      |       |
                       |      |       +--> /oom   (simulate memory pressure)
                       |      +----------> /crash (simulate container crash)
                       +-----------------> /      (basic app response)

Slack User ---> Slack Events ---> API/Lambda ---> Log fetch / analysis ---> Slack or SNS response
                                     |
                                     +--> CloudWatch Logs
                                     +--> Amazon Bedrock
```

## Tech stack

| Area | Services / Tools |
|------|------------------|
| Cloud platform | AWS |
| Compute | Amazon ECS, AWS Fargate, AWS Lambda |
| Containers | Docker, Amazon ECR |
| Infrastructure as Code | Terraform |
| CI/CD | GitHub Actions |
| State management | Amazon S3 backend for Terraform state |
| Observability | Amazon CloudWatch Logs |
| Notifications | Amazon SNS |
| ChatOps | Slack |
| App runtime | Python 3.11, Flask |
| AI integration | Amazon Bedrock Nova Lite |

## Repository structure

```text
.
├── .github/workflows/
│   ├── app.yaml            # App deployment workflow
│   ├── infra.yaml          # Terraform deployment workflow
│   └── destroy.yaml        # Manual infrastructure teardown workflow
├── Terraform/
│   ├── main.tf             # AWS infrastructure definitions
│   ├── variables.tf        # Terraform variables
│   └── lambda_function.py  # Slack + incident automation logic
├── Dockerfile              # Container image build instructions
├── app.py                  # Flask application
└── README.md
```

## Application endpoints

The Flask service is intentionally small so the focus stays on cloud deployment and operational behavior.

- `/` — returns a simple success response.
- `/crash` — intentionally terminates the app process to simulate a task crash.
- `/oom` — allocates memory continuously to simulate an out-of-memory condition.

These endpoints are useful for validating restart behavior, observing logs, and testing incident-analysis workflows.

## CI/CD workflows

### Infrastructure workflow

The `infra.yaml` workflow deploys Terraform-managed infrastructure when files in the `Terraform/` directory change or when the workflow is triggered manually.

Key actions:
- Checks out the repository.
- Configures AWS credentials.
- Installs Terraform.
- Runs `terraform init`, `terraform plan`, and `terraform apply`.
- Passes the Slack bot token as a Terraform variable from GitHub Secrets.

### Application workflow

The `app.yaml` workflow deploys application changes when `app.py` or `Dockerfile` changes or when manually triggered.

Key actions:
- Authenticates to AWS.
- Logs in to Amazon ECR.
- Builds the Docker image.
- Pushes the image to ECR.
- Forces a new ECS service deployment.

### Destroy workflow

The `destroy.yaml` workflow provides a manual teardown path for the environment. It requires an explicit confirmation value before running `terraform destroy`.

## Terraform remote state

This project uses an **S3 backend** for Terraform state management, which is a strong production-aligned practice compared with keeping state only on a local machine.

Benefits include:
- Centralized state storage.
- Safer collaboration and repeatability.
- Better alignment with automated CI/CD workflows.

A useful next step would be adding **DynamoDB state locking** for stronger concurrency protection.

## Slack and AutoSRE flow

The Lambda function acts as the operational control point for the project.

It supports two main scenarios:

1. **Slack chatbot interaction** — accepts Slack events, filters retries or bot-originated messages, and returns short operational responses.
2. **ECS failure analysis** — fetches recent CloudWatch log events, sends log context to Amazon Bedrock, and publishes a concise incident-style summary through SNS.

This makes the project more than a basic ECS deployment; it demonstrates a lightweight **ChatOps + AutoSRE** pattern using AWS-native services.

## Local development

### Run with Python

```bash
pip install flask
python app.py
```

Open `http://localhost:8080` after starting the app.

### Run with Docker

```bash
docker build -t ecs-fargate-agent .
docker run -p 8080:8080 ecs-fargate-agent
```

## Required secrets

The GitHub Actions workflows expect repository secrets such as:

- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `SLACK_BOT_TOKEN`

Depending on your Terraform implementation, you may also choose to add environment-specific variables for SNS topics, Slack signing configuration, or Bedrock-related settings.

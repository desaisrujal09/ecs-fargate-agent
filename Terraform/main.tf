terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"    }
  }

  # Remote S3 Backend Configuration for Persistent State
  backend "s3" {
    bucket = "sre-agent-terraform"
    key    = "fargate-lab/terraform.tfstate"
    region = "us-east-1"
  }
}

provider "aws" {
  region = "us-east-1"
}

# --- Data Blocks to Lookup Existing Network ---

data "aws_vpc" "myvpc" {
  filter {
    name   = "tag:Name"
    values = ["my-vpc"] 
  }
}


data "aws_subnet" "public_subnet" {
  vpc_id = data.aws_vpc.myvpc.id
  filter {
    name   = "tag:Name"
    values = ["my-vpc-public-1"] 
  }
}

data "aws_security_group" "mysg" {
  vpc_id = data.aws_vpc.myvpc.id
  filter {
    name   = "tag:Name"
    values = ["mysg"] 
  }
}

resource "aws_ecr_repository" "app_repo" {
  name                 = "fargate-app"
  image_tag_mutability = "MUTABLE"
  force_delete         = true
}

resource "aws_ecs_cluster" "cluster" {
  name = "fargate-agent-lab"
}

resource "aws_iam_role" "ecs_execution_role" {
  name = "fargate_ecs_execution_role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })
}


resource "aws_iam_role_policy_attachment" "ecs_execution" {
  role       = aws_iam_role.ecs_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_cloudwatch_log_group" "app_log_group" {
  name              = "/ecs/fargate-test-app"
  retention_in_days = 7
}

resource "aws_ecs_task_definition" "task" {
  family                   = "fargate-test-task"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = tostring(var.container_cpu)
  memory                   = tostring(var.container_memory)
  execution_role_arn       = aws_iam_role.ecs_execution_role.arn

  container_definitions = jsonencode([
    {
      name      = "app"
      image     = "${aws_ecr_repository.app_repo.repository_url}:latest"
      essential = true
      portMappings = [{
        containerPort = 8080
        hostPort      = 8080
      }]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.app_log_group.name
          "awslogs-region"        = "us-east-1"
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])
}


resource "aws_ecs_service" "service" {
  name            = "fargate-test-service"
  cluster         = aws_ecs_cluster.cluster.id
  task_definition = aws_ecs_task_definition.task.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = [data.aws_subnet.public_subnet.id]
    security_groups  = [data.aws_security_group.mysg.id]
    assign_public_ip = true
  }

  lifecycle {
    ignore_changes = [task_definition]
  }
}

resource "aws_iam_role" "lambda_sre_role" {
  name = "autosre_lambda_execution_role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_sre_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_policy" "autosre_custom_policy" {
  name = "autosre_custom_policy"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel"
        ]
        Resource = "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-lite-v1:0"
      },
      {
        Effect = "Allow"
        Action = [
          "logs:FilterLogEvents",
          "logs:DescribeLogGroups",
          "logs:DescribeLogStreams",
          "logs:GetLogEvents"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "sns:Publish"
        ]
        Resource = "arn:aws:sns:us-east-1:162898224956:autosre-alert-bot"
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_autosre_attach" {
  role       = aws_iam_role.lambda_sre_role.name
  policy_arn = aws_iam_policy.autosre_custom_policy.arn
}

data "archive_file" "lambda_zip" {
  type        = "zip"
  source_file = "${path.module}/lambda_function.py"
  output_path = "${path.module}/lambda_function.zip"
}

resource "aws_lambda_function" "autosre_agent" {
  filename         = data.archive_file.lambda_zip.output_path
  function_name    = "auto-sre-remediation-agent"
  role             = aws_iam_role.lambda_sre_role.arn
  handler          = "lambda_function.lambda_handler"
  runtime          = "python3.11"
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  timeout          = 30

  environment {
    variables = {
      ENVIRONMENT = "production"
      SNS_TOPIC_ARN = "arn:aws:sns:us-east-1:162898224956:autosre-alert-bot"
    }
  }
}

resource "aws_cloudwatch_event_rule" "ecs_task_failure_rule" {
  name        = "ecs-task-failure-sre-trigger"
  description = "Triggers AutoSRE Lambda agent when ECS tasks fail or crash"

  event_pattern = jsonencode({
    source      = ["aws.ecs"]
    detail-type = ["ECS Task State Change"]
    detail = {
      lastStatus = ["STOPPED"]
      stopCode   = ["EssentialContainerExited", "OutMemory"]
    }
  })
}

resource "aws_cloudwatch_event_target" "invoke_sre_lambda" {
  rule      = aws_cloudwatch_event_rule.ecs_task_failure_rule.name
  target_id = "AutoSRELambdaTarget"
  arn       = aws_lambda_function.autosre_agent.arn
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.autosre_agent.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.ecs_task_failure_rule.arn
}

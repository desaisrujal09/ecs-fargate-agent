terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
    }
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
  cpu                      = "512"
  memory                   = "1024"
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
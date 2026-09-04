data "archive_file" "fanout" {
  type        = "zip"
  source_dir  = var.lambda_source_dir
  output_path = "${path.module}/fanout.zip"
}

# Lambda execution role
resource "aws_iam_role" "lambda" {
  name = "${var.app_name}-fanout-lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "lambda_ecs" {
  name = "ecs-run-task"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecs:RunTask"]
        Resource = ["arn:aws:ecs:*:*:task-definition/${var.task_family}:*"]
      },
      {
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = [var.execution_role_arn, var.task_role_arn]
      }
    ]
  })
}

# CloudWatch log group for Lambda — created explicitly so retention is set from day one.
# Lambda would auto-create this group on first invocation, but with no retention policy.
resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.app_name}-fanout"
  retention_in_days = 14
}

# Fan-out Lambda — receives EventBridge event, spawns one ECS task per event config
resource "aws_lambda_function" "fanout" {
  function_name    = "${var.app_name}-fanout"
  filename         = data.archive_file.fanout.output_path
  source_code_hash = data.archive_file.fanout.output_base64sha256
  role             = aws_iam_role.lambda.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  timeout          = 300

  depends_on = [aws_cloudwatch_log_group.lambda]

  environment {
    variables = {
      ECS_CLUSTER_ARN         = var.ecs_cluster_arn
      TASK_DEFINITION_FAMILY  = var.task_family
      SUBNET_IDS              = join(",", var.public_subnet_ids)
      SECURITY_GROUP_ID       = var.ecs_task_sg_id
      FACEBOOK_EVENT_CONFIGS  = jsonencode(var.facebook_event_configs)
      SEATGEEK_EVENT_CONFIGS  = jsonencode(var.seatgeek_event_configs)
    }
  }
}

# EventBridge Scheduler role
resource "aws_iam_role" "scheduler" {
  name = "${var.app_name}-eventbridge-scheduler"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "scheduler_invoke" {
  name = "invoke-lambda"
  role = aws_iam_role.scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["lambda:InvokeFunction"]
      Resource = [aws_lambda_function.fanout.arn]
    }]
  })
}

# Facebook — every 12 hours, first run at 04:00 UTC (04:00, 16:00)
# Disabled by default — enable manually in the AWS console when ready.
resource "aws_scheduler_schedule" "facebook_periodic" {
  name       = "${var.app_name}-facebook-periodic"
  group_name = "default"
  state      = "DISABLED"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression          = "cron(0 4/12 * * ? *)"
  schedule_expression_timezone = "UTC"

  target {
    arn      = aws_lambda_function.fanout.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ mode = "periodic", command = "from-apify", stage = "all" })
  }
}

# SeatGeek — every 8 hours, first run at 02:00 UTC (02:00, 10:00, 18:00)
# Disabled by default — enable manually in the AWS console when ready.
resource "aws_scheduler_schedule" "seatgeek_periodic" {
  name       = "${var.app_name}-seatgeek-periodic"
  group_name = "default"
  state      = "DISABLED"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression          = "cron(0 2/8 * * ? *)"
  schedule_expression_timezone = "UTC"

  target {
    arn      = aws_lambda_function.fanout.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ mode = "periodic", command = "from-seatgeek" })
  }
}

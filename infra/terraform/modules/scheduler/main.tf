data "archive_file" "fanout" {
  type        = "zip"
  source_dir  = var.lambda_source_dir
  output_path = "${path.module}/fanout.zip"
}

# ── DynamoDB: per-event-per-source run state ───────────────────────────────────
# pk = "{config_name}#{source}"
resource "aws_dynamodb_table" "pipeline_state" {
  name         = "${var.app_name}-pipeline-state"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"

  attribute {
    name = "pk"
    type = "S"
  }

  tags = { App = var.app_name }
}

# ── Lambda: task_producer + record_result ─────────────────────────────────────
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

resource "aws_iam_role_policy" "lambda_policy" {
  name = "dispatcher-policy"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:BatchGetItem", "dynamodb:UpdateItem", "dynamodb:PutItem"]
        Resource = [aws_dynamodb_table.pipeline_state.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["cloudwatch:PutMetricData"]
        Resource = ["*"]
      }
    ]
  })
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.app_name}-fanout"
  retention_in_days = 14
}

resource "aws_lambda_function" "fanout" {
  function_name    = "${var.app_name}-fanout"
  filename         = data.archive_file.fanout.output_path
  source_code_hash = data.archive_file.fanout.output_base64sha256
  role             = aws_iam_role.lambda.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  timeout          = 60

  depends_on = [aws_cloudwatch_log_group.lambda]

  environment {
    variables = {
      STATE_TABLE_NAME = aws_dynamodb_table.pipeline_state.name
      EVENT_CONFIGS    = jsonencode(var.event_configs)
    }
  }
}

# ── Step Functions ─────────────────────────────────────────────────────────────
resource "aws_cloudwatch_log_group" "sfn" {
  name              = "/aws/states/${var.app_name}-dispatcher"
  retention_in_days = 30
}

resource "aws_iam_role" "sfn" {
  name = "${var.app_name}-sfn-dispatcher"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "states.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "sfn_policy" {
  name = "sfn-dispatcher-policy"
  role = aws_iam_role.sfn.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecs:RunTask", "ecs:StopTask", "ecs:DescribeTasks"]
        Resource = ["arn:aws:ecs:*:*:task-definition/${var.task_family}:*", "arn:aws:ecs:*:*:task/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = [var.execution_role_arn, var.task_role_arn]
      },
      # Required for ECS .waitForTaskToken — SFN manages an internal EventBridge rule
      {
        Effect   = "Allow"
        Action   = ["events:PutTargets", "events:PutRule", "events:DescribeRule"]
        Resource = ["arn:aws:events:*:*:rule/StepFunctionsGetEventsForECSTaskRule"]
      },
      {
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = [aws_lambda_function.fanout.arn]
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogDelivery", "logs:GetLogDelivery", "logs:UpdateLogDelivery",
          "logs:DeleteLogDelivery", "logs:ListLogDeliveries",
          "logs:PutResourcePolicy", "logs:DescribeResourcePolicies", "logs:DescribeLogGroups"
        ]
        Resource = ["*"]
      }
    ]
  })
}

# ── Locals: shared ASL building blocks ────────────────────────────────────────
locals {
  lambda_arn = aws_lambda_function.fanout.arn

  lambda_retry = [{
    ErrorEquals     = ["Lambda.ServiceException", "Lambda.AWSLambdaException", "Lambda.SdkClientException", "Lambda.TooManyRequestsException"]
    IntervalSeconds = 2
    MaxAttempts     = 3
    BackoffRate     = 2
  }]

  # Shared Map iterator — identical for all 3 source branches.
  #
  # Input to each iteration: {"task": {"command": [...], "state_key": "...", "mode": "..."}}
  #
  # Flow:
  #   LaunchTask (waitForTaskToken) — injects TASK_TOKEN into ECS container env var.
  #     The ECS task calls send_task_success({stats}) or send_task_failure(error, cause).
  #     ResultPath=$.result merges the callback payload into the current state.
  #
  #   RecordSuccess / RecordFailure — one Lambda (record_result action) updates DynamoDB.
  #
  #   Done — terminal Pass state so the Map item always ends cleanly.
  task_iterator = {
    StartAt = "LaunchTask"
    States = {
      LaunchTask = {
        Type             = "Task"
        Resource         = "arn:aws:states:::ecs:runTask.waitForTaskToken"
        HeartbeatSeconds = 3600   # if ECS task crashes without calling back, fail after 1h
        Parameters = {
          LaunchType     = "FARGATE"
          Cluster        = var.ecs_cluster_arn
          TaskDefinition = var.task_family
          NetworkConfiguration = {
            AwsvpcConfiguration = {
              Subnets        = var.public_subnet_ids
              SecurityGroups = [var.ecs_task_sg_id]
              AssignPublicIp = "ENABLED"
            }
          }
          Overrides = {
            ContainerOverrides = [{
              Name        = "pipeline"
              "Command.$" = "$.task.command"
              Environment = [{
                Name      = "TASK_TOKEN"
                "Value.$" = "$$.Task.Token"
              }]
            }]
          }
        }
        ResultPath = "$.result"   # callback payload lands here; $.task stays intact
        Next       = "RecordSuccess"
        Retry = [{
          ErrorEquals     = ["ECS.EcsException"]
          IntervalSeconds = 15
          MaxAttempts     = 2
          BackoffRate     = 2
        }]
        Catch = [{
          ErrorEquals = ["States.ALL"]
          ResultPath  = "$.error"
          Next        = "RecordFailure"
        }]
      }

      RecordSuccess = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = local.lambda_arn
          Payload = {
            action        = "record_result"
            outcome       = "success"
            "state_key.$" = "$.task.state_key"
            "mode.$"      = "$.task.mode"
            "stats.$"     = "$.result"
          }
        }
        ResultPath = null
        Retry      = local.lambda_retry
        Catch      = [{ ErrorEquals = ["States.ALL"], ResultPath = null, Next = "Done" }]
        Next       = "Done"
      }

      RecordFailure = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = local.lambda_arn
          Payload = {
            action        = "record_result"
            outcome       = "failure"
            "state_key.$" = "$.task.state_key"
            "error.$"     = "$.error"
          }
        }
        ResultPath = null
        Retry      = local.lambda_retry
        Catch      = [{ ErrorEquals = ["States.ALL"], ResultPath = null, Next = "Done" }]
        Next       = "Done"
      }

      # Always reached — ensures the Map item never "fails" from SFN's perspective.
      Done = { Type = "Pass", End = true }
    }
  }
}

# ── State machine ──────────────────────────────────────────────────────────────
#
# Flow:
#   TaskProducer (Lambda)
#     reads current time → morning | evening
#     reads event configs → applies frequency rules per source
#     batch-reads DynamoDB → gets mode per event×source
#     returns {run, tasks: {facebook_legacy:[...], facebook_new:[...], stubhub:[...]}}
#
#   RunSources (Parallel — all 3 branches run simultaneously)
#     Branch 1: RunFBLegacy  — Map (MaxConcurrency=1, sequential)
#     Branch 2: RunFBNew     — Map (MaxConcurrency=1, sequential)
#     Branch 3: RunStubHub   — Map (MaxConcurrency=1, sequential)
#
#   Each Map item:
#     LaunchTask (ECS waitForTaskToken) → RecordSuccess | RecordFailure → Done
#
resource "aws_sfn_state_machine" "dispatcher" {
  name     = "${var.app_name}-dispatcher"
  role_arn = aws_iam_role.sfn.arn

  logging_configuration {
    level                  = "ERROR"
    include_execution_data = true
    log_destination        = "${aws_cloudwatch_log_group.sfn.arn}:*"
  }

  definition = jsonencode({
    Comment = "Ticket tracker pipeline dispatcher"
    StartAt = "TaskProducer"

    States = {
      TaskProducer = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = local.lambda_arn
          "Payload.$"  = "$"   # forward full input so manual run= override works
        }
        ResultSelector = {
          "run.$"   = "$.Payload.run"
          "tasks.$" = "$.Payload.tasks"
        }
        Retry = local.lambda_retry
        Next  = "RunSources"
      }

      RunSources = {
        Type = "Parallel"
        End  = true

        Branches = [
          # ── Branch 1: Facebook Legacy ────────────────────────────────────────
          {
            StartAt = "RunFBLegacy"
            States = {
              RunFBLegacy = {
                Type           = "Map"
                ItemsPath      = "$.tasks.facebook_legacy"
                MaxConcurrency = 1   # sequential — one event at a time per source
                Parameters     = { "task.$" = "$$.Map.Item.Value" }
                Iterator       = local.task_iterator
                End            = true
              }
            }
          },

          # ── Branch 2: Facebook New ───────────────────────────────────────────
          {
            StartAt = "RunFBNew"
            States = {
              RunFBNew = {
                Type           = "Map"
                ItemsPath      = "$.tasks.facebook_new"
                MaxConcurrency = 1
                Parameters     = { "task.$" = "$$.Map.Item.Value" }
                Iterator       = local.task_iterator
                End            = true
              }
            }
          },

          # ── Branch 3: StubHub ────────────────────────────────────────────────
          {
            StartAt = "RunStubHub"
            States = {
              RunStubHub = {
                Type           = "Map"
                ItemsPath      = "$.tasks.stubhub"
                MaxConcurrency = 1
                Parameters     = { "task.$" = "$$.Map.Item.Value" }
                Iterator       = local.task_iterator
                End            = true
              }
            }
          }
        ]
      }
    }
  })

  depends_on = [aws_cloudwatch_log_group.sfn]
}

# ── EventBridge Scheduler ──────────────────────────────────────────────────────
# Fires at 00:00 UTC (8pm ET) and 12:00 UTC (8am ET).
# TaskProducer Lambda reads the clock to decide morning vs evening.
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
  name = "start-step-functions"
  role = aws_iam_role.scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["states:StartExecution"]
      Resource = [aws_sfn_state_machine.dispatcher.arn]
    }]
  })
}

resource "aws_scheduler_schedule" "dispatcher" {
  name       = "${var.app_name}-dispatcher"
  group_name = "default"

  flexible_time_window { mode = "OFF" }

  schedule_expression          = "cron(0 */12 * * ? *)"
  schedule_expression_timezone = "UTC"

  target {
    arn      = aws_sfn_state_machine.dispatcher.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = "{}"
  }
}

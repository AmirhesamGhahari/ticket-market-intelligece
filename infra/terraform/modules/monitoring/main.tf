resource "aws_sns_topic" "alerts" {
  name = "${var.app_name}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_sns_topic_policy" "allow_eventbridge" {
  arn = aws_sns_topic.alerts.arn

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "events.amazonaws.com" }
      Action    = "SNS:Publish"
      Resource  = aws_sns_topic.alerts.arn
    }]
  })
}

# ── Alarm 1: Lambda plan-builder errors ────────────────────────────────────────
# If the plan-builder Lambda throws, Step Functions gets no task list and runs nothing.
resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "${var.app_name}-plan-builder-errors"
  alarm_description   = "Dispatcher Lambda threw an unhandled error — Step Functions received no run plan"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    FunctionName = var.lambda_function_name
  }
}

# ── Alarm 2: Step Functions execution failures ─────────────────────────────────
# Fires when the overall dispatcher execution fails (not individual ECS task failures —
# those are handled per-task and recorded in DynamoDB).
resource "aws_cloudwatch_metric_alarm" "sfn_execution_failures" {
  alarm_name          = "${var.app_name}-sfn-execution-failed"
  alarm_description   = "Step Functions dispatcher execution failed — the entire run plan did not complete"
  namespace           = "AWS/States"
  metric_name         = "ExecutionsFailed"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    StateMachineArn = var.sfn_state_machine_arn
  }
}

# ── Alarm 3: Step Functions execution timeout ──────────────────────────────────
# A dispatcher run taking >90 min suggests an ECS task is hung or Fargate is stuck.
resource "aws_cloudwatch_metric_alarm" "sfn_execution_timeout" {
  alarm_name          = "${var.app_name}-sfn-execution-timeout"
  alarm_description   = "Step Functions dispatcher execution took >90 min — possible hung ECS task"
  namespace           = "AWS/States"
  metric_name         = "ExecutionTime"
  extended_statistic  = "p95"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 5400000   # 90 minutes in milliseconds
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    StateMachineArn = var.sfn_state_machine_arn
  }
}

# ── Alarm 4: Consecutive pipeline source failures ──────────────────────────────
# The dispatcher Lambda emits this metric to TicketTracker/Pipeline when
# consecutive_failures ≥ 3 for any event×source. This catches scraper rot
# (e.g. Scrapfly blocks, Apify actor broken, StubHub URL changed).
resource "aws_cloudwatch_metric_alarm" "consecutive_source_failures" {
  alarm_name          = "${var.app_name}-consecutive-source-failures"
  alarm_description   = "A scraper source has failed 3+ times consecutively — check Step Functions execution history and DynamoDB pipeline-state table"
  namespace           = "TicketTracker/Pipeline"
  metric_name         = "ConsecutiveFailures"
  statistic           = "Maximum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

# ── Alarm 5: ECS tasks that failed to start (infra-level failure) ─────────────
resource "aws_cloudwatch_event_rule" "ecs_task_failed_to_start" {
  name        = "${var.app_name}-ecs-task-failed-to-start"
  description = "ECS task failed to start (image pull error, resource unavailable)"

  event_pattern = jsonencode({
    source        = ["aws.ecs"]
    "detail-type" = ["ECS Task State Change"]
    detail = {
      clusterArn = [{ prefix = var.ecs_cluster_arn }]
      lastStatus = ["STOPPED"]
      stopCode   = ["TaskFailedToStart"]
    }
  })
}

resource "aws_cloudwatch_event_target" "ecs_task_failed_to_sns" {
  rule      = aws_cloudwatch_event_rule.ecs_task_failed_to_start.name
  target_id = "sns"
  arn       = aws_sns_topic.alerts.arn

  input_transformer {
    input_paths = {
      task       = "$.detail.taskArn"
      stopReason = "$.detail.stoppedReason"
    }
    input_template = "\"ECS task failed to start. Task: <task>  Reason: <stopReason>\""
  }
}

# ── Alarm 6: Application-level pipeline failures (ECS log metric filter) ───────
# Catches status=failed JSON log lines emitted by the pipeline CLIs.
resource "aws_cloudwatch_log_metric_filter" "pipeline_failures" {
  name           = "${var.app_name}-pipeline-failures"
  pattern        = "{ $.status = \"failed\" }"
  log_group_name = var.log_group_name

  metric_transformation {
    name          = "PipelineFailures"
    namespace     = "TicketTracker/Pipeline"
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_metric_alarm" "pipeline_failures" {
  alarm_name          = "${var.app_name}-pipeline-stage-failed"
  alarm_description   = "A pipeline stage logged a failure (stage1 extract or stage2 transform)"
  namespace           = "TicketTracker/Pipeline"
  metric_name         = "PipelineFailures"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

# ── Alarm 7: Aurora CPU high ───────────────────────────────────────────────────
resource "aws_cloudwatch_metric_alarm" "aurora_cpu" {
  alarm_name          = "${var.app_name}-aurora-cpu-high"
  alarm_description   = "Aurora CPU above 80% — consider increasing max_capacity"
  namespace           = "AWS/RDS"
  metric_name         = "CPUUtilization"
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 2
  threshold           = 80
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    DBClusterIdentifier = "${var.app_name}-aurora"
  }
}

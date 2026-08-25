resource "aws_sns_topic" "alerts" {
  name = "${var.app_name}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# Allow EventBridge to publish to SNS
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

# Alarm 1: Lambda fan-out errors
resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "${var.app_name}-fanout-errors"
  alarm_description   = "Fan-out Lambda threw an unhandled error — no ECS tasks were launched"
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

# Alarm 2: ECS tasks that failed to start (infra-level failure, not app failure)
resource "aws_cloudwatch_event_rule" "ecs_task_failed_to_start" {
  name        = "${var.app_name}-ecs-task-failed-to-start"
  description = "ECS task failed to start (e.g. image pull error, resource unavailable)"

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

# Alarm 3: Application-level pipeline failures logged to CloudWatch
resource "aws_cloudwatch_log_metric_filter" "pipeline_failures" {
  name           = "${var.app_name}-pipeline-failures"
  pattern        = "{ $.status = \"failed\" }"
  log_group_name = var.log_group_name

  metric_transformation {
    name          = "PipelineFailures"
    namespace     = "TicketTracker"
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_metric_alarm" "pipeline_failures" {
  alarm_name          = "${var.app_name}-pipeline-failures"
  alarm_description   = "Pipeline stage logged a failure (stage1 extract or stage2 transform)"
  namespace           = "TicketTracker"
  metric_name         = "PipelineFailures"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

# Alarm 4: Aurora CPU high (early warning if scraping volume grows)
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

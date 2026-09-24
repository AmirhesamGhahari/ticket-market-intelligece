variable "app_name" {
  type = string
}

variable "alert_email" {
  type = string
}

variable "ecs_cluster_arn" {
  type = string
}

variable "lambda_function_name" {
  description = "Plan-builder Lambda function name (alarms on Lambda errors prevent Step Functions from receiving a run plan)"
  type        = string
}

variable "sfn_state_machine_arn" {
  description = "Step Functions dispatcher state machine ARN — used for execution failure and timeout alarms"
  type        = string
}

variable "log_group_name" {
  description = "ECS task CloudWatch log group name — used for log metric filters"
  type        = string
}

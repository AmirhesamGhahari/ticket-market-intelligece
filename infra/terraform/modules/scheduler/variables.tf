variable "app_name" {
  type = string
}

variable "ecs_cluster_arn" {
  type = string
}

variable "execution_role_arn" {
  type = string
}

variable "task_role_arn" {
  type = string
}

variable "public_subnet_ids" {
  type = list(string)
}

variable "ecs_task_sg_id" {
  type = string
}

variable "event_configs" {
  type = list(string)
}

variable "lambda_source_dir" {
  type = string
}

variable "task_family" {
  description = "ECS task definition family name (used without revision to always run latest)"
  type        = string
}

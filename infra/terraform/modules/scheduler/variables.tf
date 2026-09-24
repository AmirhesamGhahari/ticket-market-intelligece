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
  description = "Event config objects. Each entry has 'name' (YAML filename without .yaml) and 'event_dates' (list of YYYY-MM-DD). Single-date events have a one-item list. The Lambda uses event_dates for frequency checks and StubHub task generation; ECS CLIs read the full YAML from disk."
  type = list(object({
    name        = string
    event_dates = list(string)
  }))
}

variable "lambda_source_dir" {
  type = string
}

variable "task_family" {
  description = "ECS task definition family name (used without revision to always run latest)"
  type        = string
}

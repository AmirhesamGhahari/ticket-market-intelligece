variable "app_name" {
  type = string
}

variable "region" {
  type = string
}

variable "github_owner" {
  description = "GitHub username or organization"
  type        = string
}

variable "github_repo" {
  description = "GitHub repository name (without owner prefix)"
  type        = string
}

variable "github_branch" {
  description = "Branch that triggers the pipeline"
  type        = string
  default     = "main"
}

variable "ecr_repository_url" {
  type = string
}

variable "ecr_repository_arn" {
  type = string
}

variable "execution_role_arn" {
  type = string
}

variable "task_role_arn" {
  type = string
}

variable "task_family" {
  description = "ECS task definition family name"
  type        = string
}

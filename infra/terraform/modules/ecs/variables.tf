variable "app_name" {
  type = string
}

variable "region" {
  type = string
}

variable "ecr_repository_url" {
  type = string
}

variable "db_url_secret_arn" {
  type = string
}

variable "apify_token_secret_arn" {
  type = string
}

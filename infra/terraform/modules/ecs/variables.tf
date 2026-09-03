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

variable "gemini_api_key_secret_arn" {
  type = string
}

variable "seatgeek_client_id_secret_arn" {
  type = string
}

variable "seatgeek_client_secret_secret_arn" {
  type = string
}

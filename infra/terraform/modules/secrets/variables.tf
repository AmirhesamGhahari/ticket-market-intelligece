variable "app_name" {
  type = string
}

variable "apify_api_token" {
  type      = string
  sensitive = true
}

variable "gemini_api_key" {
  type      = string
  sensitive = true
}

variable "seatgeek_client_id" {
  type      = string
  sensitive = true
}

variable "seatgeek_client_secret" {
  type      = string
  sensitive = true
}

variable "db_master_username" {
  type = string
}

variable "db_master_password" {
  type      = string
  sensitive = true
}

variable "aurora_endpoint" {
  type = string
}

variable "aurora_port" {
  type = number
}

variable "db_name" {
  type = string
}

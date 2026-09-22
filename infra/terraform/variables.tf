variable "region" {
  description = "AWS region"
  type        = string
  default     = "ca-central-1"
}

variable "app_name" {
  description = "Application name used for resource naming"
  type        = string
  default     = "ticket-price-tracker"
}

variable "apify_api_token" {
  description = "Apify API token for the scraper"
  type        = string
  sensitive   = true
}

variable "scrapfly_api_key" {
  description = "Scrapfly API key for the StubHub scraper"
  type        = string
  sensitive   = true
}

variable "gemini_api_key" {
  description = "Google Gemini API key for LLM classification"
  type        = string
  sensitive   = true
}

variable "seatgeek_client_id" {
  description = "SeatGeek API client ID"
  type        = string
  sensitive   = true
}

variable "seatgeek_client_secret" {
  description = "SeatGeek API client secret"
  type        = string
  sensitive   = true
}

variable "db_master_username" {
  description = "Aurora master username"
  type        = string
  default     = "amir_ghahari"
}

variable "db_master_password" {
  description = "Aurora master password (min 8 chars)"
  type        = string
  sensitive   = true
}

variable "db_name" {
  description = "Aurora database name"
  type        = string
  default     = "ticket_price_tracker"
}

variable "alert_email" {
  description = "Email address to receive CloudWatch alarm notifications"
  type        = string
}

variable "github_owner" {
  description = "GitHub username or organization (e.g. amirhesam)"
  type        = string
}

variable "github_repo" {
  description = "GitHub repository name, without the owner prefix (e.g. ticket-tracker)"
  type        = string
}

variable "github_branch" {
  description = "Branch that triggers the CI/CD pipeline"
  type        = string
  default     = "main"
}

variable "event_configs" {
  description = "Config names (YAML in configs/) for all pipelines — each CLI skips if its source is disabled in the config"
  type        = list(string)
  default     = []
}

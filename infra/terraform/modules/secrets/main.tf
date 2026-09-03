resource "aws_secretsmanager_secret" "db_url" {
  name                    = "${var.app_name}/database-url"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "db_url" {
  secret_id = aws_secretsmanager_secret.db_url.id
  secret_string = join("", [
    "postgresql://",
    var.db_master_username, ":", var.db_master_password,
    "@", var.aurora_endpoint, ":", tostring(var.aurora_port),
    "/", var.db_name
  ])
}

resource "aws_secretsmanager_secret" "apify_token" {
  name                    = "${var.app_name}/apify-api-token"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "apify_token" {
  secret_id     = aws_secretsmanager_secret.apify_token.id
  secret_string = var.apify_api_token
}

resource "aws_secretsmanager_secret" "gemini_api_key" {
  name                    = "${var.app_name}/gemini-api-key"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "gemini_api_key" {
  secret_id     = aws_secretsmanager_secret.gemini_api_key.id
  secret_string = var.gemini_api_key
}

resource "aws_secretsmanager_secret" "seatgeek_client_id" {
  name                    = "${var.app_name}/seatgeek-client-id"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "seatgeek_client_id" {
  secret_id     = aws_secretsmanager_secret.seatgeek_client_id.id
  secret_string = var.seatgeek_client_id
}

resource "aws_secretsmanager_secret" "seatgeek_client_secret" {
  name                    = "${var.app_name}/seatgeek-client-secret"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "seatgeek_client_secret" {
  secret_id     = aws_secretsmanager_secret.seatgeek_client_secret.id
  secret_string = var.seatgeek_client_secret
}

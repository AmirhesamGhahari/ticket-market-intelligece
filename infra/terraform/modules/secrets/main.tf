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

output "db_url_secret_arn" {
  value = aws_secretsmanager_secret.db_url.arn
}

output "apify_token_secret_arn" {
  value = aws_secretsmanager_secret.apify_token.arn
}

output "gemini_api_key_secret_arn" {
  value = aws_secretsmanager_secret.gemini_api_key.arn
}

output "seatgeek_client_id_secret_arn" {
  value = aws_secretsmanager_secret.seatgeek_client_id.arn
}

output "seatgeek_client_secret_secret_arn" {
  value = aws_secretsmanager_secret.seatgeek_client_secret.arn
}

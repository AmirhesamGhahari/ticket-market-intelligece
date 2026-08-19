output "db_url_secret_arn" {
  value = aws_secretsmanager_secret.db_url.arn
}

output "apify_token_secret_arn" {
  value = aws_secretsmanager_secret.apify_token.arn
}

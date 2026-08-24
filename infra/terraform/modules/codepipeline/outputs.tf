output "pipeline_name" {
  value = aws_codepipeline.main.name
}

output "connection_arn" {
  description = "Authorize this connection in AWS console → Developer Tools → Connections after first apply"
  value       = aws_codestarconnections_connection.github.arn
}

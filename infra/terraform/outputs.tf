output "ecr_repository_url" {
  description = "ECR repository URL (also available in CodeBuild as ECR_REPO_URL env var)"
  value       = module.ecr.repository_url
}

output "codepipeline_name" {
  value = module.codepipeline.pipeline_name
}

output "codestar_connection_arn" {
  description = "After first apply: open AWS console → Developer Tools → Connections → authorize this connection"
  value       = module.codepipeline.connection_arn
}

output "aurora_endpoint" {
  description = "Aurora cluster writer endpoint"
  value       = module.aurora.cluster_endpoint
}

output "aurora_port" {
  value = module.aurora.cluster_port
}

output "ecs_cluster_name" {
  value = module.ecs.cluster_name
}

output "task_definition_arn" {
  value = module.ecs.task_definition_arn
}

output "fanout_lambda_arn" {
  value = module.scheduler.lambda_arn
}

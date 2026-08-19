output "cluster_endpoint" {
  value = aws_rds_cluster.main.endpoint
}

output "cluster_port" {
  value = aws_rds_cluster.main.port
}

output "cluster_arn" {
  value = aws_rds_cluster.main.arn
}

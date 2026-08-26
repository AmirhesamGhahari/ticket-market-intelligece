resource "aws_db_subnet_group" "main" {
  name       = "${var.app_name}-aurora"
  subnet_ids = var.public_subnet_ids
}

resource "aws_rds_cluster" "main" {
  cluster_identifier     = "${var.app_name}-aurora"
  engine                 = "aurora-postgresql"
  engine_version         = "16.14"
  database_name          = var.db_name
  master_username        = var.db_master_username
  master_password        = var.db_master_password
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [var.aurora_sg_id]
  skip_final_snapshot    = true
  deletion_protection    = false
  storage_encrypted      = true

  serverlessv2_scaling_configuration {
    min_capacity = 0
    max_capacity = 2
  }
}

resource "aws_rds_cluster_instance" "main" {
  identifier          = "${var.app_name}-aurora-1"
  cluster_identifier  = aws_rds_cluster.main.id
  instance_class      = "db.serverless"
  engine              = aws_rds_cluster.main.engine
  engine_version      = aws_rds_cluster.main.engine_version
  publicly_accessible = true
}

data "aws_caller_identity" "current" {}

# S3 bucket for CodePipeline artifacts
resource "aws_s3_bucket" "artifacts" {
  bucket        = "${var.app_name}-pipeline-${data.aws_caller_identity.current.account_id}"
  force_destroy = true
}

resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket                  = aws_s3_bucket.artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# GitHub connection via CodeStar Connections.
# IMPORTANT: After `terraform apply`, go to AWS console →
# Developer Tools → Connections → click the connection → "Update pending connection"
# to authorize GitHub access. The pipeline will not run until this is done.
resource "aws_codestarconnections_connection" "github" {
  name          = "${var.app_name}-github"
  provider_type = "GitHub"
}

# ── IAM: CodePipeline ────────────────────────────────────────────────────────

resource "aws_iam_role" "codepipeline" {
  name = "${var.app_name}-codepipeline"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "codepipeline.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "codepipeline" {
  name = "pipeline-permissions"
  role = aws_iam_role.codepipeline.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject", "s3:GetObjectVersion", "s3:GetBucketVersioning",
          "s3:PutObjectAcl", "s3:PutObject"
        ]
        Resource = [aws_s3_bucket.artifacts.arn, "${aws_s3_bucket.artifacts.arn}/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["codestar-connections:UseConnection"]
        Resource = aws_codestarconnections_connection.github.arn
      },
      {
        Effect   = "Allow"
        Action   = ["codebuild:BatchGetBuilds", "codebuild:StartBuild"]
        Resource = aws_codebuild_project.build.arn
      }
    ]
  })
}

# ── IAM: CodeBuild ───────────────────────────────────────────────────────────

resource "aws_iam_role" "codebuild" {
  name = "${var.app_name}-codebuild"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "codebuild.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "codebuild" {
  name = "build-permissions"
  role = aws_iam_role.codebuild.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:${var.region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/codebuild/${var.app_name}-build:*"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject", "s3:GetObjectVersion",
          "s3:PutObject", "s3:GetBucketAcl", "s3:GetBucketLocation"
        ]
        Resource = [aws_s3_bucket.artifacts.arn, "${aws_s3_bucket.artifacts.arn}/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage", "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:PutImage"
        ]
        Resource = var.ecr_repository_arn
      },
      {
        Effect   = "Allow"
        Action   = ["ecs:RegisterTaskDefinition", "ecs:DescribeTaskDefinition"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = [var.execution_role_arn, var.task_role_arn]
      }
    ]
  })
}

# ── CodeBuild project ────────────────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "codebuild" {
  name              = "/aws/codebuild/${var.app_name}-build"
  retention_in_days = 14
}

resource "aws_codebuild_project" "build" {
  name         = "${var.app_name}-build"
  service_role = aws_iam_role.codebuild.arn

  artifacts {
    type = "CODEPIPELINE"
  }

  # ARM64 native build — no cross-compilation, matches ECS Fargate Graviton runtime
  environment {
    compute_type    = "BUILD_GENERAL1_SMALL"
    image           = "aws/codebuild/amazonlinux2-aarch64-standard:3.0"
    type            = "ARM_CONTAINER"
    privileged_mode = true

    environment_variable {
      name  = "ECR_REPO_URL"
      value = var.ecr_repository_url
    }
    environment_variable {
      name  = "AWS_REGION"
      value = var.region
    }
    environment_variable {
      name  = "TASK_FAMILY"
      value = var.task_family
    }
  }

  source {
    type      = "CODEPIPELINE"
    buildspec = file("${path.module}/buildspec.yml")
  }

  logs_config {
    cloudwatch_logs {
      group_name = aws_cloudwatch_log_group.codebuild.name
    }
  }
}

# ── CodePipeline ─────────────────────────────────────────────────────────────

resource "aws_codepipeline" "main" {
  name     = "${var.app_name}-pipeline"
  role_arn = aws_iam_role.codepipeline.arn

  artifact_store {
    location = aws_s3_bucket.artifacts.bucket
    type     = "S3"
  }

  stage {
    name = "Source"
    action {
      name             = "GitHub"
      category         = "Source"
      owner            = "AWS"
      provider         = "CodeStarSourceConnection"
      version          = "1"
      output_artifacts = ["source"]

      configuration = {
        ConnectionArn    = aws_codestarconnections_connection.github.arn
        FullRepositoryId = "${var.github_owner}/${var.github_repo}"
        BranchName       = var.github_branch
      }
    }
  }

  stage {
    name = "Build"
    action {
      name            = "BuildAndDeploy"
      category        = "Build"
      owner           = "AWS"
      provider        = "CodeBuild"
      version         = "1"
      input_artifacts = ["source"]

      configuration = {
        ProjectName = aws_codebuild_project.build.name
      }
    }
  }
}

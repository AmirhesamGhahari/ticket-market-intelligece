# Terraform Infrastructure — Ticket Price Tracker

This document is a complete reference for the AWS infrastructure defined in this Terraform codebase.
It covers what every file and resource does, how the modules connect to each other, and the exact
steps to deploy, update, and tear down the infrastructure.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [File Structure](#file-structure)
3. [Core Terraform Concepts](#core-terraform-concepts)
4. [Root-Level Files](#root-level-files)
5. [Module: networking](#module-networking)
6. [Module: ecr](#module-ecr)
7. [Module: aurora](#module-aurora)
8. [Module: secrets](#module-secrets)
9. [Module: ecs](#module-ecs)
10. [Module: scheduler](#module-scheduler)
11. [Module: codepipeline](#module-codepipeline)
12. [Module: monitoring](#module-monitoring)
13. [Module Dependency Chain](#module-dependency-chain)
14. [Deployment Guide](#deployment-guide)
15. [Post-Deploy Manual Steps](#post-deploy-manual-steps)
16. [Day-2 Operations](#day-2-operations)
17. [Tearing Down](#tearing-down)

---

## Architecture Overview

This is a fully serverless, event-driven scraping pipeline on AWS. There is no always-on server.
Resources only run when a scrape job is triggered.

```
EventBridge (cron, every 6h)
       |
       v
  Lambda (fan-out)  ──────────────────────────────────────────────────────────>  CloudWatch Alarms
       |                                                                               |
       v                                                                               v
  ECS Fargate Task                                                              SNS Topic
  (Python scraper)                                                                     |
       |                                                                               v
       |──── reads secrets from ──>  Secrets Manager                           Email Alert
       |
       v
  Aurora Serverless PostgreSQL
  (private subnet, not internet-accessible)

GitHub push
       |
       v
  CodePipeline  -->  CodeBuild  -->  Docker image  -->  ECR  -->  new ECS task definition revision
```

**Key design decisions encoded in this infrastructure:**

- ECS tasks live in **public subnets** with no NAT Gateway (saves ~$30/month) — they have public IPs but the security group allows no inbound connections.
- Aurora lives in **private subnets** only — the internet cannot reach it directly. Only ECS tasks can connect, enforced at the security group level.
- Docker images are tagged with both a **short commit SHA** (traceable, immutable) and `latest` (always points to newest).
- Everything is ARM64 (Graviton) — both the CodeBuild environment and ECS runtime — so images built locally match what runs in production.

---

## File Structure

```
infra/terraform/
├── providers.tf              # Terraform version + AWS provider config
├── variables.tf              # All input variable declarations
├── terraform.tfvars.example  # Template — copy to terraform.tfvars and fill in secrets
├── main.tf                   # Root: wires all modules together
├── outputs.tf                # Values printed after terraform apply
└── modules/
    ├── networking/           # VPC, subnets, security groups
    │   ├── main.tf
    │   ├── variables.tf
    │   └── outputs.tf
    ├── ecr/                  # Docker image registry
    │   ├── main.tf
    │   ├── variables.tf
    │   └── outputs.tf
    ├── aurora/               # Aurora Serverless PostgreSQL
    │   ├── main.tf
    │   ├── variables.tf
    │   └── outputs.tf
    ├── secrets/              # AWS Secrets Manager (DB URL + Apify token)
    │   ├── main.tf
    │   ├── variables.tf
    │   └── outputs.tf
    ├── ecs/                  # ECS Cluster + Fargate task definition + IAM roles
    │   ├── main.tf
    │   ├── variables.tf
    │   └── outputs.tf
    ├── scheduler/            # EventBridge + Lambda fan-out
    │   ├── main.tf
    │   ├── variables.tf
    │   └── outputs.tf
    ├── codepipeline/         # CI/CD pipeline (GitHub → ECR → ECS)
    │   ├── main.tf
    │   ├── variables.tf
    │   ├── outputs.tf
    │   └── buildspec.yml     # The actual shell script CodeBuild runs
    └── monitoring/           # CloudWatch alarms + SNS email alerts
        ├── main.tf
        └── variables.tf
```

---

## Core Terraform Concepts

Before diving into modules, these concepts apply everywhere.

### variables.tf vs terraform.tfvars

`variables.tf` is the **contract** — it declares what inputs exist, their type, and an optional default:

```hcl
variable "db_master_password" {
  type      = string
  sensitive = true          # never printed to terminal or stored in state in plaintext
}

variable "region" {
  type    = string
  default = "ca-central-1" # used if not overridden
}
```

`terraform.tfvars` is where you **supply the actual values**. Terraform reads this file automatically:

```hcl
db_master_password = "my-actual-password"
region             = "ca-central-1"
```

Variables with no `default` in `variables.tf` are required — Terraform errors if they are missing from `terraform.tfvars`.

`terraform.tfvars.example` is just a human-readable template committed to git. The real `terraform.tfvars` should never be committed (it contains secrets). It is already in `.gitignore`.

### Modules

A module is a folder with its own `variables.tf`, `main.tf`, and `outputs.tf`. It is a self-contained unit of infrastructure. The root `main.tf` calls each module and wires outputs from one as inputs to another:

```hcl
module "secrets" {
  source          = "./modules/secrets"
  aurora_endpoint = module.aurora.cluster_endpoint  # output of aurora → input of secrets
}
```

### outputs.tf

Root `outputs.tf` selectively re-exports module outputs — only the values a human or external system needs after deployment (endpoints to connect to, ARNs to paste somewhere, connections to authorize). Internal wiring between modules does not need to be in root outputs.

### data sources

A `data` block reads existing AWS state rather than creating something:

```hcl
data "aws_caller_identity" "current" {}
# data.aws_caller_identity.current.account_id → your 12-digit AWS account ID
```

---

## Root-Level Files

### providers.tf

```hcl
terraform {
  required_version = ">= 1.6"
  required_providers {
    aws     = { source = "hashicorp/aws", version = "~> 5.0" }
    archive = { source = "hashicorp/archive", version = "~> 2.0" }
  }
}

provider "aws" {
  region = var.region
}
```

- Pins the minimum Terraform CLI version to 1.6.
- Pins the AWS provider to the 5.x family (`~> 5.0` means >= 5.0 and < 6.0). Pinning prevents a future provider release from silently breaking your code.
- The `archive` provider is needed by the scheduler module to zip the Lambda source code.
- The S3 backend block is commented out — uncomment it when you want Terraform state stored remotely in S3 instead of locally. Required for team collaboration.

### variables.tf

Declares every input for the entire infrastructure. Most have defaults; the ones that do not (secrets, email, GitHub config) are required in `terraform.tfvars`.

### main.tf

The orchestrator. Calls every module in order, passing outputs from upstream modules as inputs to downstream ones. This file is where the dependency chain is explicitly wired. See the [Module Dependency Chain](#module-dependency-chain) section for the full graph.

### outputs.tf

Prints these values to the terminal after `terraform apply`:

| Output | Why you need it |
|---|---|
| `ecr_repository_url` | To push Docker images manually or verify CodeBuild is targeting the right repo |
| `codepipeline_name` | Reference for the AWS console |
| `codestar_connection_arn` | You must authorize this in the AWS console before the pipeline works |
| `aurora_endpoint` | Connect a DB client (e.g. psql, DataGrip) for debugging |
| `aurora_port` | Always 5432 for PostgreSQL |
| `ecs_cluster_name` | Reference for manual ECS operations |
| `task_definition_arn` | Reference for the initial task definition revision |
| `fanout_lambda_arn` | Reference for manual Lambda invocations |

---

## Module: networking

**What it creates:** The network envelope that everything else lives inside.

### VPC

```hcl
resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true
}
```

A Virtual Private Cloud — your isolated slice of AWS networking. `10.0.0.0/16` gives you 65,536 private IP addresses to assign to resources. DNS hostnames and DNS support are enabled so resources can refer to each other by hostname rather than raw IP.

### Subnets

Two **public subnets** (one per availability zone, `ca-central-1a` and `ca-central-1b`):
- CIDR blocks: `10.0.1.0/24` and `10.0.2.0/24`
- ECS Fargate tasks run here. They get a public IP so they can reach the Apify API without a NAT Gateway.
- The security group permits no inbound traffic, so "public" only means outbound internet access, not that they're reachable.

Two **private subnets** (one per AZ):
- CIDR blocks: `10.0.10.0/24` and `10.0.11.0/24`
- Aurora lives here. No route to the internet gateway — cannot be reached from outside the VPC.
- Two subnets are required by Aurora even if you only have one instance (AWS enforces multi-AZ subnet groups for RDS).

### Internet Gateway + Route Table

The Internet Gateway connects the VPC to the internet. The public route table has a single rule: send all traffic (`0.0.0.0/0`) to the gateway. This rule is associated with both public subnets. Private subnets have no route table association, so they have no internet access.

### Security Groups

**ECS tasks security group:**
- No inbound rules (no one can connect into a running task)
- All outbound traffic allowed (tasks need to reach Apify API, ECR, Secrets Manager, Aurora)

**Aurora security group:**
- Inbound: port 5432 (PostgreSQL) from the ECS tasks security group only
- Outbound: all traffic allowed
- This is the firewall rule that enforces "only the scraper can talk to the database."

---

## Module: ecr

**What it creates:** A private Docker image registry for your scraper container.

```hcl
resource "aws_ecr_repository" "main" {
  name                 = var.app_name
  image_tag_mutability = "MUTABLE"
  force_delete         = false

  image_scanning_configuration {
    scan_on_push = true
  }
}
```

- `image_tag_mutability = "MUTABLE"` — the `latest` tag can be overwritten on each push. If you wanted `latest` to be pinned forever you'd use `IMMUTABLE`, but then you'd need to always use commit-SHA tags.
- `scan_on_push = true` — AWS automatically scans every pushed image for known CVEs using ECR's built-in vulnerability scanner.
- `force_delete = false` — `terraform destroy` will refuse to delete this repo if it still contains images. This is a safety net; set to `true` only if you're certain you want images destroyed.

### Lifecycle Policy

```hcl
resource "aws_ecr_lifecycle_policy" "main" { ... }
```

Automatically cleans up old images to keep storage costs low:
- Keep the last 10 tagged images with tags starting with `sha-` or `v` (your commit-tagged images)
- Delete untagged images (intermediate build layers) after 1 day

Without this, ECR storage grows unbounded with every push.

---

## Module: aurora

**What it creates:** The PostgreSQL database — the central data store for all scraped listings.

### Subnet Group

```hcl
resource "aws_db_subnet_group" "main" {
  name       = "${var.app_name}-aurora"
  subnet_ids = var.private_subnet_ids
}
```

Tells Aurora which subnets it can place instances in. Must span at least two AZs (AWS requirement for RDS), which is why networking creates two private subnets.

### The Cluster

```hcl
resource "aws_rds_cluster" "main" {
  cluster_identifier     = "${var.app_name}-aurora"
  engine                 = "aurora-postgresql"
  engine_version         = "16.4"
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
```

The **cluster** is the logical database — it owns the data, the endpoint, and the configuration. It is not a server itself.

- `skip_final_snapshot = true` — when destroyed, don't take a backup snapshot. Set to `false` in production if you want a safety net before teardown.
- `deletion_protection = false` — allows `terraform destroy` to delete the cluster. Set to `true` in production.
- `storage_encrypted = true` — all data at rest is encrypted.
- `min_capacity = 0` — Aurora Serverless v2 can scale to zero ACUs when idle (no scrape running). Eliminates idle compute cost.
- `max_capacity = 2` — maximum 2 Aurora Capacity Units. Raise this if the monitoring CPU alarm fires repeatedly.

### Cluster vs Instance

**Cluster** = the logical database (endpoint, data, config). Not a server.
**Instance** = the compute node that does the actual SQL work, registered inside a cluster.

```hcl
resource "aws_rds_cluster_instance" "main" {
  identifier         = "${var.app_name}-aurora-1"
  cluster_identifier = aws_rds_cluster.main.id
  instance_class     = "db.serverless"
  engine             = aws_rds_cluster.main.engine
  engine_version     = aws_rds_cluster.main.engine_version
}
```

`db.serverless` is the instance class for Aurora Serverless v2 — it auto-scales between `min_capacity` and `max_capacity`.

To add a read replica, add another `aws_rds_cluster_instance` block pointing at the same `cluster_identifier`. Do NOT add another `aws_rds_cluster` — that creates an entirely separate database.

---

## Module: secrets

**What it creates:** Two encrypted secrets in AWS Secrets Manager — the DB connection string and the Apify API token.

```hcl
resource "aws_secretsmanager_secret" "db_url" {
  name                    = "${var.app_name}/database-url"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "db_url" {
  secret_id     = aws_secretsmanager_secret.db_url.id
  secret_string = "postgresql://${var.db_master_username}:${var.db_master_password}@${var.aurora_endpoint}:${var.aurora_port}/${var.db_name}"
}
```

Each secret is two resources:
- `aws_secretsmanager_secret` — the named container (like a key in a vault)
- `aws_secretsmanager_secret_version` — the actual value stored in that container

`recovery_window_in_days = 0` disables the default 7-day recovery window. Without this, destroying and re-creating the secret (e.g. during a `terraform destroy` + `terraform apply` cycle) would fail because the name is reserved during recovery. Setting it to 0 means immediate deletion.

### Why secrets are created after Aurora

The DB connection string value (`secret_string`) includes the Aurora cluster endpoint — a hostname that only exists after Aurora is provisioned. So Aurora must be created first to produce the endpoint, and only then can secrets store it. Secrets depend on Aurora, not the other way around.

### How secrets reach the container

The ECS task definition (in the ecs module) references both secret ARNs in its `secrets` block. At task launch, the ECS agent fetches the secret values from Secrets Manager and injects them as environment variables (`DATABASE_URL`, `APIFY_API_TOKEN`) inside the container. Your Python code reads them as normal env vars — it never needs the AWS SDK to fetch them.

---

## Module: ecs

**What it creates:** The ECS cluster, the task definition (container blueprint), and two IAM roles.

### CloudWatch Log Group

```hcl
resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/${var.app_name}"
  retention_in_days = 30
}
```

Created explicitly with a 30-day retention policy. If ECS created it automatically on first task run, it would have no retention and logs would accumulate forever at increasing cost.

### ECS Cluster

```hcl
resource "aws_ecs_cluster" "main" {
  name = var.app_name
}
```

The cluster is the logical grouping for your tasks. With Fargate, there are no EC2 instances to manage — AWS provides the underlying compute on demand.

### Two IAM Roles

ECS uses two separate roles for security separation:

**Execution Role** — used by the ECS agent (the AWS infrastructure layer) to:
- Pull your Docker image from ECR
- Fetch secrets from Secrets Manager and inject them into the container as env vars
- Write logs to CloudWatch

The base policy (`AmazonECSTaskExecutionRolePolicy`) covers ECR and CloudWatch. The additional `secrets-read` policy scopes Secrets Manager access to only the two specific secret ARNs this app needs.

**Task Role** — used by your running application code (the Python process inside the container). Currently empty — no permissions granted. Add permissions here if your scraper ever needs to call other AWS services directly (e.g. S3, SQS).

The distinction matters: if your app code is compromised, it cannot use the execution role's broader permissions (like pulling images or reading all secrets).

### Task Definition

```hcl
resource "aws_ecs_task_definition" "pipeline" {
  family                   = "${var.app_name}-pipeline"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256    # 0.25 vCPU
  memory                   = 512    # 512 MB
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"  # Graviton — cheaper than x86, same performance
  }
  ...
}
```

The task definition is the blueprint for your container — like a `docker run` command stored in AWS. Key points:

- `cpu = 256, memory = 512` — the smallest Fargate size. Sufficient for a scraper. Can be increased if tasks are killed with OOM errors.
- `cpu_architecture = "ARM64"` — must match the architecture the Docker image was built for (CodeBuild also builds on ARM64).
- ECS task definitions are **immutable and versioned**. You cannot edit a revision — you register a new one. CodeBuild does this automatically on every push.
- `command = ["--help"]` is the default — the Lambda fan-out always overrides this with the real subcommand when launching a task.

---

## Module: scheduler

**What it creates:** A Lambda function and an EventBridge schedule that triggers scrape runs every 6 hours.

### How Zipping Works

```hcl
data "archive_file" "fanout" {
  type        = "zip"
  source_dir  = var.lambda_source_dir   # infra/lambda/fanout/
  output_path = "${path.module}/fanout.zip"
}
```

This `data` block runs before the Lambda resource is evaluated. It zips the Lambda source directory and places the zip on disk. The Lambda resource then uploads that zip to AWS.

### source_code_hash — Automatic Change Detection

```hcl
resource "aws_lambda_function" "fanout" {
  filename         = data.archive_file.fanout.output_path
  source_code_hash = data.archive_file.fanout.output_base64sha256
  ...
}
```

`source_code_hash` stores a SHA256 fingerprint of the zip contents. On each `terraform apply`, Terraform re-zips and recomputes the hash. If it differs from the hash in state, Terraform knows the Lambda code changed and uploads the new zip. Without this field, Terraform would only check whether the filename changed — always the same string — and never redeploy even if you edited the Python code.

**Practical result:** Edit the Lambda handler, run `terraform apply`, and the new code is live automatically.

### IAM Roles

**Lambda execution role:** Allows the Lambda service to assume it. Gets `AWSLambdaBasicExecutionRole` (CloudWatch log writes) plus a custom policy to call `ecs:RunTask` and `iam:PassRole` (required to hand the ECS execution/task roles to a new task).

### Lambda Environment Variables

The Lambda receives all the ECS context it needs to launch tasks:

```hcl
environment {
  variables = {
    ECS_CLUSTER_ARN        = var.ecs_cluster_arn
    TASK_DEFINITION_FAMILY = var.task_family
    SUBNET_IDS             = join(",", var.public_subnet_ids)
    SECURITY_GROUP_ID      = var.ecs_task_sg_id
    EVENT_CONFIGS          = jsonencode(var.event_configs)
  }
}
```

`EVENT_CONFIGS` is a JSON-encoded list of event config names (e.g. `["veld_2026", "electric_island_sep2026"]`). The Lambda loops over this list and launches one ECS task per config — that is the "fan-out" behaviour.

### EventBridge Schedule

```hcl
resource "aws_scheduler_schedule" "periodic" {
  schedule_expression          = "cron(0 */6 * * ? *)"
  schedule_expression_timezone = "UTC"

  target {
    arn   = aws_lambda_function.fanout.arn
    input = jsonencode({ mode = "periodic" })
  }
}
```

Fires at 00:00, 06:00, 12:00, 18:00 UTC every day. On each fire, it invokes the Lambda with `{ "mode": "periodic" }`. The Lambda then reads `EVENT_CONFIGS` and starts one ECS task per event.

---

## Module: codepipeline

**What it creates:** A CI/CD pipeline that automatically builds and deploys new code when you push to the main branch.

### Full Flow

```
git push origin main
       |
       v
CodePipeline detects push via GitHub connection (CodeStar)
       |
       v
Stage 1 — Source: pulls repo, zips it, puts in S3 artifact bucket
       |
       v
Stage 2 — Build: CodeBuild runs buildspec.yml
       |
       ├── pre_build:  docker login to ECR
       ├── build:      docker build, tag with short commit SHA and "latest"
       └── post_build: docker push to ECR, register new ECS task definition revision
```

### S3 Artifact Bucket

CodePipeline uses S3 as a handoff zone between stages. The bucket name includes your AWS account ID because S3 bucket names must be globally unique across all AWS accounts worldwide.

The bucket has versioning enabled (CodePipeline requirement), AES-256 encryption at rest, and all public access blocked.

### GitHub Connection (CodeStar)

```hcl
resource "aws_codestarconnections_connection" "github" {
  name          = "${var.app_name}-github"
  provider_type = "GitHub"
}
```

Terraform creates the connection resource, but cannot complete the OAuth authorization — that requires a human to click "Authorize" in the AWS console. The pipeline will not run until this is done. See [Post-Deploy Manual Steps](#post-deploy-manual-steps).

### IAM Roles

Two separate roles with least-privilege permissions:

**CodePipeline role** can: read/write the S3 artifact bucket, use the GitHub CodeStar connection, start CodeBuild builds.

**CodeBuild role** can: write to CloudWatch Logs, read source from S3, authenticate to ECR (`ecr:GetAuthorizationToken` must be `Resource: "*"` — it's a global token), push images to the specific ECR repo, register ECS task definitions (`Resource: "*"` required — AWS doesn't support per-resource ARN here), pass the ECS execution/task roles into new task definitions.

### CodeBuild Project

```hcl
environment {
  compute_type    = "BUILD_GENERAL1_SMALL"
  image           = "aws/codebuild/amazonlinux2-aarch64-standard:3.0"
  type            = "ARM_CONTAINER"
  privileged_mode = true
}
```

- ARM64 build environment so images are built natively for Graviton (no cross-compilation).
- `privileged_mode = true` is required to run Docker inside the CodeBuild container.
- Three env vars are injected: `ECR_REPO_URL`, `AWS_REGION`, `TASK_FAMILY` — used by `buildspec.yml`.

### buildspec.yml — The Build Script

```yaml
pre_build:
  - aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $ECR_REPO_URL
  - COMMIT_ID=$(echo $CODEBUILD_RESOLVED_SOURCE_VERSION | cut -c1-8)
```

Gets a temporary ECR auth token and logs in. Trims the full 40-char Git commit SHA to 8 characters for use as a short image tag.

```yaml
build:
  - docker build -t $ECR_REPO_URL:$COMMIT_ID -t $ECR_REPO_URL:latest .
```

Builds the Docker image from the root Dockerfile and applies two tags simultaneously.

```yaml
post_build:
  - docker push $ECR_REPO_URL:$COMMIT_ID
  - docker push $ECR_REPO_URL:latest
  - TASK_DEF=$(aws ecs describe-task-definition --task-definition $TASK_FAMILY ...)
  - NEW_TASK_DEF=$(echo "$TASK_DEF" | jq 'del(...) | .containerDefinitions[0].image = $IMAGE')
  - aws ecs register-task-definition --cli-input-json "$NEW_TASK_DEF"
```

Pushes both image tags to ECR. Then fetches the current ECS task definition, strips AWS-managed read-only fields (they would cause an API error if resubmitted), swaps the image tag to the new commit SHA, and registers it as a new revision. The next ECS task launch will use this new revision automatically.

---

## Module: monitoring

**What it creates:** An SNS notification topic and 4 CloudWatch alarms covering each failure layer of the pipeline.

### Notification Channel: SNS

```hcl
resource "aws_sns_topic" "alerts" {
  name = "${var.app_name}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}
```

SNS is a pub/sub system — a megaphone that delivers to all subscribers. Here, the only subscriber is your email address. All 4 alarms publish to this topic when they fire, so a single email subscription covers everything.

After `terraform apply`, AWS sends a confirmation email to `var.alert_email`. You must click "Confirm subscription" or alerts will not be delivered.

```hcl
resource "aws_sns_topic_policy" "allow_eventbridge" { ... }
```

Grants `events.amazonaws.com` permission to publish into the SNS topic. Required for Alarm 2, where EventBridge is the publisher (not CloudWatch).

### Alarm 1: Lambda Fan-out Errors

```hcl
namespace           = "AWS/Lambda"
metric_name         = "Errors"
statistic           = "Sum"
period              = 300
evaluation_periods  = 1
threshold           = 0
comparison_operator = "GreaterThanThreshold"
treat_missing_data  = "notBreaching"
```

Watches the built-in `Errors` metric AWS publishes for every Lambda. Any invocation that throws an unhandled exception increments this metric.

- Fires when: `Sum of errors in the last 5 minutes > 0`
- What it means: the Lambda crashed before it could launch any ECS tasks — no scrape ran at all
- `treat_missing_data = "notBreaching"`: if Lambda had zero invocations in a period, that is not an error

### Alarm 2: ECS Task Failed to Start

```hcl
resource "aws_cloudwatch_event_rule" "ecs_task_failed_to_start" {
  event_pattern = jsonencode({
    source        = ["aws.ecs"]
    "detail-type" = ["ECS Task State Change"]
    detail = {
      clusterArn = [{ prefix = var.ecs_cluster_arn }]
      lastStatus = ["STOPPED"]
      stopCode   = ["TaskFailedToStart"]
    }
  })
}
```

ECS emits an event to EventBridge every time a task changes state. This rule pattern-matches events where a task in your cluster stopped with `stopCode = "TaskFailedToStart"`. This specific code means the container never got running — image pull error, no Fargate capacity, networking misconfiguration, etc.

The `input_transformer` converts the raw JSON event into a human-readable string before publishing to SNS:
```
"ECS task failed to start. Task: arn:aws:ecs:...  Reason: CannotPullContainerError: ..."
```

This alarm uses EventBridge → SNS directly, not CloudWatch metrics, because ECS task failures are discrete events, not time-series metrics.

### Alarm 3: Application-Level Pipeline Failures

```hcl
resource "aws_cloudwatch_log_metric_filter" "pipeline_failures" {
  pattern        = "\"status\": \"failed\""
  log_group_name = var.log_group_name

  metric_transformation {
    name          = "PipelineFailures"
    namespace     = "TicketTracker"
    value         = "1"
    default_value = "0"
  }
}
```

A log metric filter scans ECS container logs in real-time. Every time a log line matches the pattern `"status": "failed"`, it emits `+1` to a custom CloudWatch metric `TicketTracker/PipelineFailures`.

This is a **contract with your Python code** — your scraper must log JSON containing `"status": "failed"` when a stage fails. The monitoring layer converts that log line into an alert automatically.

`default_value = "0"` ensures the metric always has a value even in periods with no matches, so the alarm below always has data to evaluate.

The corresponding `aws_cloudwatch_metric_alarm` watches this custom metric with the same `Sum > 0 in 5 minutes` logic as Alarm 1.

### Alarm 4: Aurora CPU High

```hcl
namespace           = "AWS/RDS"
metric_name         = "CPUUtilization"
statistic           = "Average"
period              = 300
evaluation_periods  = 2
threshold           = 80
```

- Uses `Average` not `Sum` — CPU is a percentage, averaging makes sense.
- `evaluation_periods = 2` — must be above 80% for two consecutive 5-minute periods (10 minutes total) before alarming. Filters out brief spikes.
- Fires when: average CPU > 80% for 10 consecutive minutes.
- What to do: increase `max_capacity` in the aurora module and re-apply.

### The 4 Alarms Cover All Failure Layers

```
EventBridge triggers Lambda
    |
    ├── Lambda crashes?               → Alarm 1 (Lambda Errors metric)
    |
    └── Lambda OK → ECS task launched
           |
           ├── Task can't start?      → Alarm 2 (EventBridge pattern match)
           |
           └── Task starts → Python runs
                  |
                  ├── Code logs failure? → Alarm 3 (log metric filter)
                  |
                  └── Code writes to Aurora
                         |
                         └── DB overloaded? → Alarm 4 (CPU metric)
```

---

## Module Dependency Chain

Terraform resolves dependencies automatically based on references between resources. This is the full graph:

```
networking
    |
    ├──> aurora     (needs private_subnet_ids, aurora_sg_id)
    |       |
    |       └──> secrets  (needs aurora_endpoint, aurora_port)
    |               |
    |               └──> ecs  (needs db_url_secret_arn, apify_token_secret_arn)
    |
    └──> ecs        (also needs public_subnet_ids, ecs_task_sg_id)

ecr ──────────────> ecs         (needs ecr_repository_url)
                    |
                    ├──> scheduler    (needs cluster_arn, execution_role_arn, task_role_arn)
                    |       |
                    |       └──> monitoring  (needs lambda_function_name)
                    |
                    ├──> codepipeline (needs execution_role_arn, task_role_arn)
                    |
                    └──> monitoring   (needs ecs_cluster_arn, log_group_name)
```

Terraform figures out this order automatically — you do not need to specify it manually. But understanding the chain explains why, for example, you cannot provision `secrets` before `aurora`, or `ecs` before `secrets`.

---

## Deployment Guide

### Prerequisites

Install the following tools before starting:

```bash
# Terraform
brew install terraform

# AWS CLI
brew install awscli

# Verify versions
terraform --version   # must be >= 1.6
aws --version
```

### Step 1: Configure AWS credentials

```bash
aws configure
# Enter your AWS Access Key ID
# Enter your AWS Secret Access Key
# Default region: ca-central-1
# Default output format: json
```

Verify it works:

```bash
aws sts get-caller-identity
# Should return your account ID, user ID, and ARN
```

### Step 2: Create your tfvars file

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars` and fill in all values:

```hcl
region             = "ca-central-1"
app_name           = "ticket-tracker"

apify_api_token    = "apify_api_YOUR_REAL_TOKEN"
db_master_username = "ticket_tracker"
db_master_password = "a-strong-password-at-least-8-chars"
db_name            = "ticket_tracker"

alert_email    = "your-real-email@example.com"
github_owner   = "your-github-username"
github_repo    = "ticket-tracker"
github_branch  = "main"
```

Never commit `terraform.tfvars` — it contains secrets. It is already in `.gitignore`.

### Step 3: Initialize Terraform

```bash
terraform init
```

This downloads the AWS and archive provider plugins and sets up the local state file. Only needs to be run once (and again if you add new providers or modules).

Expected output:
```
Terraform has been successfully initialized!
```

### Step 4: Preview what will be created

```bash
terraform plan
```

This shows every resource Terraform will create, modify, or destroy — without actually doing anything. Review the output carefully.

Look for:
- Total count of resources to add (should be ~40+ on first apply)
- Any unexpected modifications or destructions (should be none on first apply)
- `Plan: X to add, 0 to change, 0 to destroy`

### Step 5: Apply

```bash
terraform apply
```

Terraform shows the plan again and prompts for confirmation:

```
Do you want to perform these actions?
  Terraform will perform the actions described above.
  Only 'yes' will be accepted to approve.

  Enter a value: yes
```

Type `yes` and press Enter. This typically takes 5–10 minutes — Aurora provisioning is the slowest step.

When complete, Terraform prints the root outputs:

```
Outputs:

aurora_endpoint       = "ticket-tracker-aurora.cluster-xxxx.ca-central-1.rds.amazonaws.com"
aurora_port           = 5432
codestar_connection_arn = "arn:aws:codestar-connections:..."
ecr_repository_url    = "123456789012.dkr.ecr.ca-central-1.amazonaws.com/ticket-tracker"
ecs_cluster_name      = "ticket-tracker"
...
```

Save these values — you will need them in the next steps.

### Step 6: Push the initial Docker image

The ECS task definition references `ecr_repository_url:latest`, but ECR is empty until you push an image. Push one now so the first scheduled task launch does not fail with an image-not-found error.

```bash
# Authenticate Docker to ECR
aws ecr get-login-password --region ca-central-1 \
  | docker login --username AWS --password-stdin <ecr_repository_url>

# Build the image from the repo root (where the Dockerfile lives)
cd ../../..   # navigate to repo root
docker build -t <ecr_repository_url>:latest .

# Push
docker push <ecr_repository_url>:latest
```

Replace `<ecr_repository_url>` with the value from the Terraform output.

If you are on an Apple Silicon Mac (ARM64), your local build matches the ARM64 ECS runtime — no extra flags needed. If you are on an Intel Mac or Linux x86 machine, add `--platform linux/arm64` to the build command:

```bash
docker build --platform linux/arm64 -t <ecr_repository_url>:latest .
```

---

## Post-Deploy Manual Steps

These two steps cannot be automated by Terraform and must be done in the AWS console after every fresh deployment.

### 1. Authorize the GitHub connection

The CodePipeline will not trigger until the GitHub connection is authorized.

1. Open the [AWS console](https://console.aws.amazon.com) → region `ca-central-1`
2. Navigate to: **Developer Tools** → **Settings** → **Connections**
3. Find the connection named `ticket-tracker-github` — it will show status `Pending`
4. Click the connection name → click **"Update pending connection"**
5. A GitHub OAuth window appears — authorize AWS to access your GitHub account
6. Status changes to `Available`

The pipeline will now automatically trigger on the next push to `main`.

### 2. Confirm the SNS email subscription

CloudWatch alarms will not deliver email notifications until the subscription is confirmed.

1. Check the inbox of the email address you set as `alert_email` in `terraform.tfvars`
2. Find the email from `AWS Notifications` with subject `AWS Notification - Subscription Confirmation`
3. Click the `Confirm subscription` link inside it

If you do not receive the email within a few minutes, check your spam folder. You can also force-resend from the AWS console: **Simple Notification Service** → **Subscriptions** → find the pending subscription → **Request confirmation**.

---

## Day-2 Operations

### View current Terraform state

```bash
# List all resources Terraform is tracking
terraform state list

# Show details of one specific resource
terraform state show module.aurora.aws_rds_cluster.main
```

### Re-read outputs after apply

```bash
terraform output
```

### Apply changes incrementally

After editing any `.tf` file, the workflow is always:

```bash
terraform plan    # review what will change
terraform apply   # apply after confirming the plan looks correct
```

### Target a single module

To apply changes only to one module without touching others:

```bash
terraform plan   -target=module.monitoring
terraform apply  -target=module.monitoring
```

Use sparingly — targeting can leave state inconsistent if the module depends on others.

### Redeploy Lambda code only

If you edited the Lambda fan-out handler and want to redeploy without touching the rest of the infrastructure:

```bash
terraform apply -target=module.scheduler
```

Terraform will detect the `source_code_hash` change and upload the new zip automatically.

### Manually trigger a scrape run

Invoke the fan-out Lambda directly via the AWS CLI:

```bash
aws lambda invoke \
  --function-name ticket-tracker-fanout \
  --payload '{"mode": "manual"}' \
  --cli-binary-format raw-in-base64-out \
  /tmp/lambda-response.json

cat /tmp/lambda-response.json
```

### Check ECS task logs

```bash
# List recent log streams
aws logs describe-log-streams \
  --log-group-name /ecs/ticket-tracker \
  --order-by LastEventTime \
  --descending \
  --max-items 5

# Tail logs from a specific stream
aws logs get-log-events \
  --log-group-name /ecs/ticket-tracker \
  --log-stream-name pipeline/pipeline/<task-id>
```

Or use the AWS console: **CloudWatch** → **Log groups** → `/ecs/ticket-tracker`.

### Connect to Aurora for debugging

Aurora is in a private subnet and not reachable from the internet directly. To connect from your laptop, use an ECS task as a bastion, or temporarily use the AWS console's Query Editor:

1. **AWS console** → **RDS** → **Query Editor**
2. Select your cluster (`ticket-tracker-aurora`)
3. Enter your DB credentials from `terraform.tfvars`
4. Run SQL directly

Alternatively, use an SSM Session Manager tunnel (more complex but scriptable — worth setting up for regular use).

### Rotate secrets

If you need to change the DB password or Apify token:

1. Update the value in `terraform.tfvars`
2. Run `terraform apply`
3. Terraform updates the Secrets Manager secret version
4. The next ECS task launch will automatically pick up the new secret (no restart needed)

### Scale Aurora up

If the CPU alarm fires repeatedly, increase `max_capacity` in `modules/aurora/main.tf`:

```hcl
serverlessv2_scaling_configuration {
  min_capacity = 0
  max_capacity = 4   # was 2
}
```

Then run `terraform apply`. Aurora scales to the new maximum without downtime.

---

## Tearing Down

To destroy all infrastructure:

```bash
terraform destroy
```

Terraform shows a destruction plan and prompts for `yes`.

**Be aware:**
- Aurora data is deleted permanently (`skip_final_snapshot = true`). If you want a backup, set `skip_final_snapshot = false` and `deletion_protection = false` before destroying, then run `terraform apply` first, then `terraform destroy`.
- ECR images are NOT deleted (`force_delete = false` on the ECR repo). You must manually delete images in the AWS console or via CLI before `terraform destroy` can remove the repo. Or set `force_delete = true` in `modules/ecr/main.tf` and `terraform apply` first.
- Secrets Manager secrets have `recovery_window_in_days = 0` so they are deleted immediately (no 7-day hold).
- The S3 artifact bucket has `force_destroy = true` so it is deleted even if it contains build artifacts.

To destroy only one module (e.g. for troubleshooting):

```bash
terraform destroy -target=module.monitoring
```

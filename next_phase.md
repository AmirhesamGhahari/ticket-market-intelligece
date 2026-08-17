# Next Phase — Cloud Deployment Plan

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                          AWS VPC                            │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │                   Public Subnet                      │  │
│  │                                                      │  │
│  │  ┌──────────────────┐    ┌──────────────────────┐   │  │
│  │  │  ECS Fargate     │    │  EC2 t4g.nano        │   │  │
│  │  │  Task (per event)│    │  PostgreSQL 16        │   │  │
│  │  │                  │───▶│  /data on EBS 20GB   │   │  │
│  │  │  run-pipeline    │    │                      │   │  │
│  │  │  from-apify      │    │  Port 5432 open only │   │  │
│  │  │  --config X      │    │  to ECS SG           │   │  │
│  │  └──────────────────┘    └──────────────────────┘   │  │
│  │          ▲                                           │  │
│  │          │ triggers (1 task per event, parallel)     │  │
│  │  ┌───────────────┐                                   │  │
│  │  │ Lambda fan-out│                                   │  │
│  │  └───────────────┘                                   │  │
│  │          ▲                                           │  │
│  └──────────│────────────────────────────────────────── ┘  │
│             │                                               │
│  ┌──────────────────────────┐                              │
│  │  EventBridge Scheduler   │                              │
│  │  cron: 0 6,14,22 * * *   │                              │
│  └──────────────────────────┘                              │
└─────────────────────────────────────────────────────────────┘
          │
          ▼ (outbound, per ECS task)
    Apify API
    (Facebook Marketplace scraper)
```

---

## Component Decisions

| Component | Choice | Why |
|-----------|--------|-----|
| Scheduler | EventBridge Scheduler | Native AWS cron, ~$0/month |
| Fan-out | Lambda (Python) | Triggers 10 ECS tasks in parallel, runs for ~2s |
| Compute | ECS Fargate | No servers, pay only when running, no 15-min timeout |
| Database | EC2 t4g.nano + PostgreSQL 16 | ~$5/month, you control everything |
| Container registry | ECR | Native ECS integration |
| Secrets | AWS Secrets Manager | Injects DATABASE_URL + APIFY_API_TOKEN into tasks |
| Monitoring | CloudWatch Logs + Alarm → SNS | ECS streams logs automatically |
| IaC | Terraform | Industry standard, large ecosystem, readable state |

---

## Networking Design

One public subnet, no NAT Gateway (saves ~$32/month).

- **ECS Fargate tasks**: public subnet, assigned public IPs for outbound Apify calls
- **EC2 PostgreSQL**: same public subnet, but security group restricts port 5432 to only the ECS task SG — not reachable from the internet
- **Port 22 on EC2**: open only to your home/office IP for management via SSH

Traffic between ECS tasks and EC2 travels over private IPs within the VPC — it never touches the internet regardless of public IP assignments.

---

## Cost Estimate

| Item | Monthly Cost |
|------|-------------|
| EC2 t4g.nano (on-demand) | ~$3.50 |
| EBS gp3 20GB (PostgreSQL data) | ~$1.60 |
| ECS Fargate (10 events × 3 runs × 30 days, ~10 min, 0.25 vCPU / 0.5 GB) | ~$3 |
| Lambda fan-out (~900 invocations/month) | ~$0 |
| ECR storage | ~$0.50 |
| EventBridge Scheduler | ~$0 |
| Secrets Manager (2 secrets) | ~$0.80 |
| CloudWatch Logs + Alarm | ~$1 |
| **Total** | **~$10–11/month** |

---

## Part 1 — EC2 PostgreSQL Setup

### 1.1 What Terraform provisions

- EC2 `t4g.nano` (ARM, Ubuntu 22.04 LTS)
- EBS gp3 volume (20 GB) mounted at `/data` — PostgreSQL data lives here, not on the root volume so you can snapshot or resize independently
- Elastic IP — fixed IP so your connection string never changes on restart
- Security group: port 5432 from ECS SG only, port 22 from your IP only
- IAM instance profile with permission to read its own secret from Secrets Manager
- Userdata script that bootstraps PostgreSQL on first boot

### 1.2 Userdata bootstrap script (`infra/modules/database/userdata.sh`)

```bash
#!/bin/bash
set -e

# Install PostgreSQL 16
apt-get update -y
apt-get install -y postgresql-16 awscli

# Format and mount the EBS data volume
mkfs.ext4 /dev/nvme1n1
mkdir -p /data
mount /dev/nvme1n1 /data
echo "/dev/nvme1n1 /data ext4 defaults,nofail 0 2" >> /etc/fstab

# Move PostgreSQL data directory to the EBS volume
systemctl stop postgresql
rsync -av /var/lib/postgresql/ /data/postgresql/
sed -i "s|/var/lib/postgresql|/data/postgresql|g" \
  /etc/postgresql/16/main/postgresql.conf

# Allow connections from the VPC CIDR
echo "host all all 10.0.0.0/16 scram-sha-256" \
  >> /etc/postgresql/16/main/pg_hba.conf
sed -i "s/#listen_addresses = 'localhost'/listen_addresses = '*'/" \
  /etc/postgresql/16/main/postgresql.conf

systemctl start postgresql
systemctl enable postgresql

# Fetch DB password from Secrets Manager and create DB + user
DB_PASSWORD=$(aws secretsmanager get-secret-value \
  --secret-id ticket-tracker/db-password \
  --query SecretString --output text \
  --region ${aws_region})

sudo -u postgres psql <<SQL
  CREATE USER ticket_tracker WITH PASSWORD '$DB_PASSWORD';
  CREATE DATABASE ticket_tracker OWNER ticket_tracker;
SQL

# Daily pg_dump backup to S3
cat > /etc/cron.daily/pg-backup <<'EOF'
#!/bin/bash
DATE=$(date +%Y-%m-%d)
sudo -u postgres pg_dump ticket_tracker | gzip \
  | aws s3 cp - s3://${backup_bucket}/postgres/$DATE.sql.gz
EOF
chmod +x /etc/cron.daily/pg-backup
```

### 1.3 Connection string

After provisioning, your `DATABASE_URL` stored in Secrets Manager will be:

```
postgresql://ticket_tracker:<password>@<ec2-elastic-ip>:5432/ticket_tracker
```

### 1.4 Ongoing management

Connect via SSH:
```bash
ssh -i ~/.ssh/your-key.pem ubuntu@<elastic-ip>
sudo -u postgres psql ticket_tracker
```

Run Alembic migrations from your laptop (or a one-off ECS task):
```bash
DATABASE_URL=postgresql://... alembic upgrade head
```

---

## Part 2 — Application Container

### 2.1 Dockerfile

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (layer cache)
COPY pyproject.toml .
RUN pip install --no-cache-dir -e . 2>/dev/null || true

# Copy source and configs
COPY src/ src/
COPY configs/ configs/
RUN pip install --no-cache-dir -e .

ENTRYPOINT ["run-pipeline"]
```

### 2.2 Build and push to ECR

```bash
# Authenticate
aws ecr get-login-password --region ca-central-1 \
  | docker login --username AWS --password-stdin \
    <account-id>.dkr.ecr.ca-central-1.amazonaws.com

# Build for ARM64 (matches Fargate Graviton — cheaper and faster)
docker buildx build --platform linux/arm64 \
  -t ticket-tracker:latest \
  -t <account-id>.dkr.ecr.ca-central-1.amazonaws.com/ticket-tracker:latest \
  --push .
```

---

## Part 3 — Fan-out Lambda

This is a small Python Lambda that reads your event config list and triggers one ECS task per event in parallel.

### `infra/lambda/fanout/handler.py`

```python
import boto3
import json
import os

ecs = boto3.client("ecs")

CLUSTER = os.environ["ECS_CLUSTER_ARN"]
TASK_DEF = os.environ["TASK_DEFINITION_ARN"]
SUBNET_ID = os.environ["SUBNET_ID"]
SECURITY_GROUP_ID = os.environ["SECURITY_GROUP_ID"]
EVENTS = json.loads(os.environ["EVENT_CONFIGS"])  # ["veld_2026", "electric_island_2026", ...]

def handler(event, context):
    mode = event.get("mode", "periodic")

    for config_name in EVENTS:
        ecs.run_task(
            cluster=CLUSTER,
            taskDefinition=TASK_DEF,
            launchType="FARGATE",
            networkConfiguration={
                "awsvpcConfiguration": {
                    "subnets": [SUBNET_ID],
                    "securityGroups": [SECURITY_GROUP_ID],
                    "assignPublicIp": "ENABLED",
                }
            },
            overrides={
                "containerOverrides": [{
                    "name": "ticket-tracker",
                    "command": [
                        "from-apify",
                        "--config", config_name,
                        "--mode", mode,
                    ],
                }]
            },
        )
        print(f"Triggered task for {config_name} ({mode})")
```

---

## Part 4 — Terraform Structure

### Directory layout

```
infra/
├── main.tf               # Root: wires all modules together
├── variables.tf          # Input variables
├── outputs.tf            # Outputs (IPs, ARNs, etc.)
├── terraform.tfvars      # Your values — GITIGNORED
├── modules/
│   ├── vpc/
│   │   ├── main.tf       # VPC, subnet, IGW, route table
│   │   └── outputs.tf
│   ├── database/
│   │   ├── main.tf       # EC2, EBS, Elastic IP, SG, IAM
│   │   ├── userdata.sh   # Bootstrap script (above)
│   │   └── outputs.tf
│   ├── ecr/
│   │   └── main.tf       # ECR repository
│   ├── ecs/
│   │   ├── main.tf       # Cluster, task definition, IAM roles, SG
│   │   └── outputs.tf
│   ├── secrets/
│   │   └── main.tf       # Secrets Manager entries
│   └── scheduler/
│       └── main.tf       # EventBridge rule, fan-out Lambda, IAM
```

### Key Terraform resources

**`infra/variables.tf`**
```hcl
variable "region"          { default = "ca-central-1" }
variable "your_ip"         { description = "Your IP for SSH access (x.x.x.x/32)" }
variable "db_password"     { sensitive = true }
variable "apify_api_token" { sensitive = true }
variable "event_configs"   {
  default = ["veld_2026"]
  description = "List of config names to run — must match filenames in configs/"
}
variable "ecr_image_uri"   { description = "Full ECR image URI after first push" }
```

**`infra/modules/vpc/main.tf`** (key resources)
```hcl
resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  tags = { Name = "ticket-tracker" }
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.0.1.0/24"
  availability_zone       = "${var.region}a"
  map_public_ip_on_launch = false  # we assign IPs explicitly per resource
  tags = { Name = "ticket-tracker-public" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}
```

**`infra/modules/database/main.tf`** (key resources)
```hcl
resource "aws_security_group" "postgres" {
  name   = "ticket-tracker-postgres"
  vpc_id = var.vpc_id

  # PostgreSQL from ECS tasks only
  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [var.ecs_task_sg_id]
  }

  # SSH from your IP only
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.your_ip]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "postgres" {
  ami                    = "ami-0c9bfc21ac5bf10eb"  # Ubuntu 22.04 ARM64, ca-central-1
  instance_type          = "t4g.nano"
  subnet_id              = var.subnet_id
  vpc_security_group_ids = [aws_security_group.postgres.id]
  key_name               = var.key_pair_name
  iam_instance_profile   = aws_iam_instance_profile.postgres.name
  associate_public_ip_address = true

  user_data = templatefile("${path.module}/userdata.sh", {
    aws_region    = var.region
    backup_bucket = var.backup_bucket
  })

  root_block_device {
    volume_size = 8
    volume_type = "gp3"
  }

  tags = { Name = "ticket-tracker-postgres" }
}

resource "aws_ebs_volume" "data" {
  availability_zone = "${var.region}a"
  size              = 20
  type              = "gp3"
  tags = { Name = "ticket-tracker-postgres-data" }
}

resource "aws_volume_attachment" "data" {
  device_name = "/dev/sdf"
  volume_id   = aws_ebs_volume.data.id
  instance_id = aws_instance.postgres.id
}

resource "aws_eip" "postgres" {
  instance = aws_instance.postgres.id
  domain   = "vpc"
}
```

**`infra/modules/ecs/main.tf`** (key resources)
```hcl
resource "aws_ecs_cluster" "main" {
  name = "ticket-tracker"
  setting {
    name  = "containerInsights"
    value = "disabled"  # saves money; enable if you need metrics
  }
}

resource "aws_security_group" "ecs_tasks" {
  name   = "ticket-tracker-ecs-tasks"
  vpc_id = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]  # outbound to Apify
  }
}

resource "aws_ecs_task_definition" "pipeline" {
  family                   = "ticket-tracker-pipeline"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256   # 0.25 vCPU
  memory                   = 512   # 0.5 GB
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"  # Graviton — cheaper than x86
  }

  container_definitions = jsonencode([{
    name  = "ticket-tracker"
    image = var.ecr_image_uri
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = "/ecs/ticket-tracker"
        awslogs-region        = var.region
        awslogs-stream-prefix = "pipeline"
      }
    }
    secrets = [
      { name = "DATABASE_URL",    valueFrom = var.db_url_secret_arn },
      { name = "APIFY_API_TOKEN", valueFrom = var.apify_token_secret_arn },
    ]
  }])
}
```

**`infra/modules/scheduler/main.tf`** (key resources)
```hcl
resource "aws_lambda_function" "fanout" {
  function_name = "ticket-tracker-fanout"
  filename      = data.archive_file.fanout.output_path
  handler       = "handler.handler"
  runtime       = "python3.12"
  role          = aws_iam_role.fanout_lambda.arn
  timeout       = 30

  environment {
    variables = {
      ECS_CLUSTER_ARN      = var.ecs_cluster_arn
      TASK_DEFINITION_ARN  = var.task_definition_arn
      SUBNET_ID            = var.subnet_id
      SECURITY_GROUP_ID    = var.ecs_task_sg_id
      EVENT_CONFIGS        = jsonencode(var.event_configs)
    }
  }
}

resource "aws_scheduler_schedule" "periodic" {
  name = "ticket-tracker-periodic"

  flexible_time_window { mode = "OFF" }

  # 06:00, 14:00, 22:00 UTC daily
  schedule_expression          = "cron(0 6,14,22 * * ? *)"
  schedule_expression_timezone = "UTC"

  target {
    arn      = aws_lambda_function.fanout.arn
    role_arn = aws_iam_role.eventbridge_invoke.arn
    input    = jsonencode({ mode = "periodic" })
  }
}
```

---

## Part 5 — Secrets Manager Setup

Two secrets, created once manually (or via Terraform):

```hcl
# infra/modules/secrets/main.tf
resource "aws_secretsmanager_secret" "db_url" {
  name = "ticket-tracker/database-url"
}
resource "aws_secretsmanager_secret_version" "db_url" {
  secret_id     = aws_secretsmanager_secret.db_url.id
  secret_string = var.database_url  # set after EC2 provisions
}

resource "aws_secretsmanager_secret" "apify_token" {
  name = "ticket-tracker/apify-api-token"
}
resource "aws_secretsmanager_secret_version" "apify_token" {
  secret_id     = aws_secretsmanager_secret.apify_token.id
  secret_string = var.apify_api_token
}
```

ECS task execution role needs `secretsmanager:GetSecretValue` on both ARNs. The task pulls them at start and injects as environment variables — your pydantic-settings config reads them automatically.

---

## Part 6 — Monitoring

```hcl
# CloudWatch log group (ECS streams here automatically)
resource "aws_cloudwatch_log_group" "pipeline" {
  name              = "/ecs/ticket-tracker"
  retention_in_days = 14
}

# Alarm: any ECS task failure
resource "aws_cloudwatch_metric_alarm" "task_failures" {
  alarm_name          = "ticket-tracker-task-failures"
  namespace           = "ECS/ContainerInsights"
  metric_name         = "TaskCount"
  dimensions          = { ClusterName = "ticket-tracker", TaskDefinitionFamily = "ticket-tracker-pipeline" }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "LessThanOrEqualToThreshold"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_sns_topic" "alerts" { name = "ticket-tracker-alerts" }
resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}
```

---

## Part 7 — Implementation Order

Do these steps in order. Each step is independently testable before moving to the next.

### Step 1 — Prerequisites
```bash
# Install tools
brew install terraform awscli

# Configure AWS credentials
aws configure
# Set region to ca-central-1 (or your preferred region)

# Create an EC2 key pair for SSH to PostgreSQL instance
aws ec2 create-key-pair --key-name ticket-tracker \
  --query 'KeyMaterial' --output text > ~/.ssh/ticket-tracker.pem
chmod 400 ~/.ssh/ticket-tracker.pem
```

### Step 2 — Provision VPC + PostgreSQL EC2
```bash
cd infra
terraform init

# Apply only VPC and database first
terraform apply -target=module.vpc -target=module.database
```

Wait for EC2 userdata to finish (~3 min). Verify:
```bash
ssh -i ~/.ssh/ticket-tracker.pem ubuntu@<elastic-ip>
sudo -u postgres psql ticket_tracker -c "\dt"  # should show empty schema
```

### Step 3 — Run Alembic migrations (from your laptop)
```bash
DATABASE_URL=postgresql://ticket_tracker:<pw>@<elastic-ip>:5432/ticket_tracker \
  alembic upgrade head
```

### Step 4 — Build and push Docker image
```bash
# Provision ECR first
terraform apply -target=module.ecr

# Build ARM64 image and push
docker buildx build --platform linux/arm64 \
  -t <account-id>.dkr.ecr.ca-central-1.amazonaws.com/ticket-tracker:latest \
  --push .
```

### Step 5 — Provision ECS + Secrets
```bash
# Add secrets to terraform.tfvars
terraform apply -target=module.secrets -target=module.ecs
```

**Test a single pipeline run manually:**
```bash
aws ecs run-task \
  --cluster ticket-tracker \
  --task-definition ticket-tracker-pipeline \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[<subnet-id>],securityGroups=[<sg-id>],assignPublicIp=ENABLED}" \
  --overrides '{"containerOverrides":[{"name":"ticket-tracker","command":["from-file","--config","veld_2026","--file","sample_data/actual_data_raider_craper.json"]}]}'
```

Watch logs:
```bash
aws logs tail /ecs/ticket-tracker --follow
```

### Step 6 — Run initial scrape (full history)
```bash
aws ecs run-task \
  --cluster ticket-tracker \
  --task-definition ticket-tracker-pipeline \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[<subnet-id>],securityGroups=[<sg-id>],assignPublicIp=ENABLED}" \
  --overrides '{"containerOverrides":[{"name":"ticket-tracker","command":["from-apify","--config","veld_2026","--mode","initial"]}]}'
```

### Step 7 — Deploy fan-out Lambda + EventBridge Scheduler
```bash
# Zip and deploy the Lambda
cd infra/lambda/fanout && zip -r ../fanout.zip handler.py
cd ../..

terraform apply -target=module.scheduler
```

Verify by manually invoking:
```bash
aws lambda invoke \
  --function-name ticket-tracker-fanout \
  --payload '{"mode":"periodic"}' \
  response.json
```

### Step 8 — Ongoing deployment workflow

When you update code:
```bash
# Rebuild and push
docker buildx build --platform linux/arm64 \
  -t <account-id>.dkr.ecr.ca-central-1.amazonaws.com/ticket-tracker:latest \
  --push .

# Force ECS to use the new image on next task start
# (Fargate always pulls :latest on each task run — no extra step needed)
```

When you add a new event:
```bash
# 1. Add the config file
cp configs/veld_2026.yaml configs/new_event.yaml
# Edit it with the new event details

# 2. Add to your terraform.tfvars
event_configs = ["veld_2026", "new_event"]

# 3. Rebuild image (configs are baked in) and push
docker buildx build ...

# 4. Update Terraform (just updates the Lambda env var)
terraform apply -target=module.scheduler
```

---

## Part 8 — S3 Backup Bucket (for pg_dump)

```hcl
resource "aws_s3_bucket" "backups" {
  bucket = "ticket-tracker-backups-${var.account_id}"
}

resource "aws_s3_bucket_lifecycle_configuration" "backups" {
  bucket = aws_s3_bucket.backups.id
  rule {
    id     = "expire-old-backups"
    status = "Enabled"
    expiration { days = 30 }
  }
}
```

Daily pg_dump runs via cron on the EC2 instance (wired in the userdata script above). Backups automatically expire after 30 days to keep storage costs near $0.

---

## Summary

| Phase | Command |
|-------|---------|
| Provision infra | `terraform apply` |
| First-time DB schema | `alembic upgrade head` (from laptop) |
| Deploy app | `docker buildx build ... --push` |
| Initial scrape (one-time) | `aws ecs run-task ... --mode initial` |
| Ongoing (automated) | EventBridge fires fan-out Lambda 3× daily |
| Add new event | Add config file + update `event_configs` + redeploy |
| SSH to DB | `ssh -i ~/.ssh/ticket-tracker.pem ubuntu@<elastic-ip>` |
| View pipeline logs | `aws logs tail /ecs/ticket-tracker --follow` |

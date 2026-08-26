variable "app_name" {
  type = string
}

variable "public_subnet_ids" {
  type = list(string)
}

variable "aurora_sg_id" {
  type = string
}

variable "db_master_username" {
  type = string
}

variable "db_master_password" {
  type      = string
  sensitive = true
}

variable "db_name" {
  type = string
}

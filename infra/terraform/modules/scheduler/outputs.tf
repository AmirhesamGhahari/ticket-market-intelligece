output "lambda_arn" {
  value = aws_lambda_function.fanout.arn
}

output "lambda_function_name" {
  value = aws_lambda_function.fanout.function_name
}

output "schedule_arn" {
  value = aws_scheduler_schedule.periodic.arn
}

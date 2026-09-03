output "lambda_arn" {
  value = aws_lambda_function.fanout.arn
}

output "lambda_function_name" {
  value = aws_lambda_function.fanout.function_name
}

output "facebook_schedule_arn" {
  value = aws_scheduler_schedule.facebook_periodic.arn
}

output "seatgeek_schedule_arn" {
  value = aws_scheduler_schedule.seatgeek_periodic.arn
}

output "lambda_arn" {
  value = aws_lambda_function.fanout.arn
}

output "lambda_function_name" {
  value = aws_lambda_function.fanout.function_name
}

output "sfn_state_machine_arn" {
  value = aws_sfn_state_machine.dispatcher.arn
}

output "sfn_state_machine_name" {
  value = aws_sfn_state_machine.dispatcher.name
}

output "pipeline_state_table_name" {
  value = aws_dynamodb_table.pipeline_state.name
}

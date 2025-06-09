# Outputs
output "api_gateway_url" {
  value = "https://${aws_api_gateway_rest_api.receipt_api.id}.execute-api.${var.aws_region}.amazonaws.com/prod"
}

output "frontend_url" {
  value = "http://${aws_s3_bucket.frontend_hosting.id}.s3-website.${var.aws_region}.amazonaws.com"
}

output "receipt_upload_bucket" {
  value = aws_s3_bucket.receipt_uploads.id
}
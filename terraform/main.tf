# S3 Bucket for receipt uploads
resource "aws_s3_bucket" "receipt_uploads" {
  bucket = "${var.project_name}-receipts-${random_string.suffix.result}"
}

resource "random_string" "suffix" {
  length  = 8
  special = false
  upper   = false
}

# DynamoDB table
resource "aws_dynamodb_table" "receipt_data" {
  name           = "${var.project_name}-receipts"
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "receiptId"

  attribute {
    name = "receiptId"
    type = "S"
  }

  tags = {
    Name = "Receipt Parser Data"
  }
}

# IAM role for Lambda
resource "aws_iam_role" "lambda_role" {
  name = "${var.project_name}-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}
# IAM policy for Lambda execution
resource "aws_iam_role_policy" "lambda_policy" {
  name = "${var.project_name}-lambda-policy"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream", 
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject"
        ]
        Resource = "${aws_s3_bucket.receipt_uploads.arn}/*"
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:GetItem",
          "dynamodb:Query",
          "dynamodb:Scan"
        ]
        Resource = aws_dynamodb_table.receipt_data.arn
      },
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel"
        ]
        Resource = "arn:aws:bedrock:${var.aws_region}::foundation-model/anthropic.claude-3-5-sonnet-20241022-v2:0"
      }
    ]
  })
}

# Lambda function for OCR processing
resource "aws_lambda_function" "ocr_processor" {
  filename         = "../src/ocr-processor/ocr-processor.zip"
  function_name    = "${var.project_name}-ocr-processor"
  role            = aws_iam_role.lambda_role.arn
  handler         = "lambda_function.lambda_handler"
  runtime         = "python3.11"
  timeout         = 60
  memory_size     = 512

  depends_on = [aws_iam_role_policy.lambda_policy]
}

# S3 bucket notification
# resource "aws_s3_bucket_notification" "receipt_upload_notification" {
#   bucket = aws_s3_bucket.receipt_uploads.id

#   lambda_function {
#     lambda_function_arn = aws_lambda_function.ocr_processor.arn
#     events             = ["s3:ObjectCreated:*"]
#     filter_prefix      = "receipts/"
#     filter_suffix      = ""
#   }

#   depends_on = [aws_lambda_permission.allow_s3_invoke]
# }

# Permission for S3 to invoke Lambda
resource "aws_lambda_permission" "allow_s3_invoke" {
  statement_id  = "AllowExecutionFromS3Bucket"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ocr_processor.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.receipt_uploads.arn
}


# API Gateway
resource "aws_api_gateway_rest_api" "receipt_api" {
  name        = "${var.project_name}-api"
  description = "Receipt Parser API"
}

# CORS configuration
resource "aws_api_gateway_gateway_response" "cors" {
  rest_api_id   = aws_api_gateway_rest_api.receipt_api.id
  response_type = "DEFAULT_4XX"

  response_templates = {
    "application/json" = jsonencode({
      message = "$context.error.messageString"
    })
  }

  response_parameters = {
    "gatewayresponse.header.Access-Control-Allow-Origin"  = "'*'"
    "gatewayresponse.header.Access-Control-Allow-Headers" = "'*'"
    "gatewayresponse.header.Access-Control-Allow-Methods" = "'*'"
  }
}

# API Lambda function
resource "aws_lambda_function" "api_handler" {
  filename         = "../src/api-handler/api-handler.zip"
  function_name    = "${var.project_name}-api-handler"
  role            = aws_iam_role.lambda_role.arn
  handler         = "lambda_function.lambda_handler"
  runtime         = "python3.11"
  timeout         = 30

  environment {
    variables = {
      TABLE_NAME = aws_dynamodb_table.receipt_data.name
    }
  }

  depends_on = [aws_iam_role_policy.lambda_policy]
}

# Lambda permission for API Gateway
resource "aws_lambda_permission" "api_gateway_invoke" {
  statement_id  = "AllowExecutionFromAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api_handler.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.receipt_api.execution_arn}/*/*"
}

# API Resources
resource "aws_api_gateway_resource" "receipts" {
  rest_api_id = aws_api_gateway_rest_api.receipt_api.id
  parent_id   = aws_api_gateway_rest_api.receipt_api.root_resource_id
  path_part   = "receipts"
}

resource "aws_api_gateway_resource" "receipt_by_id" {
  rest_api_id = aws_api_gateway_rest_api.receipt_api.id
  parent_id   = aws_api_gateway_resource.receipts.id
  path_part   = "{id}"
}

resource "aws_api_gateway_resource" "receipts_by_category" {
  rest_api_id = aws_api_gateway_rest_api.receipt_api.id
  parent_id   = aws_api_gateway_resource.receipts.id
  path_part   = "category"
}

resource "aws_api_gateway_resource" "category_name" {
  rest_api_id = aws_api_gateway_rest_api.receipt_api.id
  parent_id   = aws_api_gateway_resource.receipts_by_category.id
  path_part   = "{category}"
}

# API Methods
resource "aws_api_gateway_method" "get_receipts" {
  rest_api_id   = aws_api_gateway_rest_api.receipt_api.id
  resource_id   = aws_api_gateway_resource.receipts.id
  http_method   = "GET"
  authorization = "NONE"
}

resource "aws_api_gateway_method" "get_receipt_by_id" {
  rest_api_id   = aws_api_gateway_rest_api.receipt_api.id
  resource_id   = aws_api_gateway_resource.receipt_by_id.id
  http_method   = "GET"
  authorization = "NONE"
}

resource "aws_api_gateway_method" "get_receipts_by_category" {
  rest_api_id   = aws_api_gateway_rest_api.receipt_api.id
  resource_id   = aws_api_gateway_resource.category_name.id
  http_method   = "GET"
  authorization = "NONE"
}

# CORS OPTIONS methods
resource "aws_api_gateway_method" "options_receipts" {
  rest_api_id   = aws_api_gateway_rest_api.receipt_api.id
  resource_id   = aws_api_gateway_resource.receipts.id
  http_method   = "OPTIONS"
  authorization = "NONE"
}

# Integrations
resource "aws_api_gateway_integration" "get_receipts_integration" {
  rest_api_id = aws_api_gateway_rest_api.receipt_api.id
  resource_id = aws_api_gateway_resource.receipts.id
  http_method = aws_api_gateway_method.get_receipts.http_method

  integration_http_method = "POST"
  type                   = "AWS_PROXY"
  uri                    = aws_lambda_function.api_handler.invoke_arn
}

resource "aws_api_gateway_integration" "get_receipt_by_id_integration" {
  rest_api_id = aws_api_gateway_rest_api.receipt_api.id
  resource_id = aws_api_gateway_resource.receipt_by_id.id
  http_method = aws_api_gateway_method.get_receipt_by_id.http_method

  integration_http_method = "POST"
  type                   = "AWS_PROXY"
  uri                    = aws_lambda_function.api_handler.invoke_arn
}

resource "aws_api_gateway_integration" "get_receipts_by_category_integration" {
  rest_api_id = aws_api_gateway_rest_api.receipt_api.id
  resource_id = aws_api_gateway_resource.category_name.id
  http_method = aws_api_gateway_method.get_receipts_by_category.http_method

  integration_http_method = "POST"
  type                   = "AWS_PROXY"
  uri                    = aws_lambda_function.api_handler.invoke_arn
}

# CORS OPTIONS integration
resource "aws_api_gateway_integration" "options_receipts_integration" {
  rest_api_id = aws_api_gateway_rest_api.receipt_api.id
  resource_id = aws_api_gateway_resource.receipts.id
  http_method = aws_api_gateway_method.options_receipts.http_method

  type = "MOCK"
  request_templates = {
    "application/json" = jsonencode({
      statusCode = 200
    })
  }
}

resource "aws_api_gateway_method_response" "options_receipts_response" {
  rest_api_id = aws_api_gateway_rest_api.receipt_api.id
  resource_id = aws_api_gateway_resource.receipts.id
  http_method = aws_api_gateway_method.options_receipts.http_method
  status_code = "200"

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = true
    "method.response.header.Access-Control-Allow-Methods" = true
    "method.response.header.Access-Control-Allow-Origin"  = true
  }
}

resource "aws_api_gateway_integration_response" "options_receipts_integration_response" {
  rest_api_id = aws_api_gateway_rest_api.receipt_api.id
  resource_id = aws_api_gateway_resource.receipts.id
  http_method = aws_api_gateway_method.options_receipts.http_method
  status_code = aws_api_gateway_method_response.options_receipts_response.status_code

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = "'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token'"
    "method.response.header.Access-Control-Allow-Methods" = "'GET,OPTIONS,POST,PUT'"
    "method.response.header.Access-Control-Allow-Origin"  = "'*'"
  }
}

# API Deployment
resource "aws_api_gateway_deployment" "api_deployment" {
  depends_on = [
    aws_api_gateway_integration.get_receipts_integration,
    aws_api_gateway_integration.get_receipt_by_id_integration,
    aws_api_gateway_integration.get_receipts_by_category_integration,
    aws_api_gateway_integration.options_receipts_integration,
    aws_api_gateway_integration.post_upload_integration,
    aws_api_gateway_integration.options_upload_integration
  ]

  rest_api_id = aws_api_gateway_rest_api.receipt_api.id
  stage_name  = "prod"

  triggers = {
    redeployment = sha1(jsonencode([
      aws_api_gateway_resource.receipts.id,
      aws_api_gateway_resource.upload.id,
      aws_api_gateway_method.get_receipts.id,
      aws_api_gateway_method.post_upload.id,
      aws_api_gateway_method.options_upload.id,
      aws_api_gateway_integration.post_upload_integration.id,
      aws_api_gateway_integration.options_upload_integration.id,
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }
}

# S3 bucket for frontend hosting
resource "aws_s3_bucket" "frontend_hosting" {
  bucket = "${var.project_name}-frontend-${random_string.suffix.result}"
}

resource "aws_s3_bucket_website_configuration" "frontend_website" {
  bucket = aws_s3_bucket.frontend_hosting.id

  index_document {
    suffix = "index.html"
  }
}

resource "aws_s3_bucket_policy" "frontend_bucket_policy" {
  bucket = aws_s3_bucket.frontend_hosting.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "PublicReadGetObject"
        Effect    = "Allow"
        Principal = "*"
        Action    = "s3:GetObject"
        Resource  = "${aws_s3_bucket.frontend_hosting.arn}/*"
      }
    ]
  })
}
resource "aws_s3_bucket_public_access_block" "frontend_pab" {
  bucket = aws_s3_bucket.frontend_hosting.id

  block_public_acls       = false
  block_public_policy     = false
  ignore_public_acls      = false
  restrict_public_buckets = false
}

# Upload endpoint resource
resource "aws_api_gateway_resource" "upload" {
  rest_api_id = aws_api_gateway_rest_api.receipt_api.id
  parent_id   = aws_api_gateway_rest_api.receipt_api.root_resource_id
  path_part   = "upload"
}

# Upload POST method
resource "aws_api_gateway_method" "post_upload" {
  rest_api_id   = aws_api_gateway_rest_api.receipt_api.id
  resource_id   = aws_api_gateway_resource.upload.id
  http_method   = "POST"
  authorization = "NONE"
}

# Upload integration
resource "aws_api_gateway_integration" "post_upload_integration" {
  rest_api_id = aws_api_gateway_rest_api.receipt_api.id
  resource_id = aws_api_gateway_resource.upload.id
  http_method = aws_api_gateway_method.post_upload.http_method

  integration_http_method = "POST"
  type                   = "AWS_PROXY"
  uri                    = aws_lambda_function.api_handler.invoke_arn
}

# Upload OPTIONS for CORS
resource "aws_api_gateway_method" "options_upload" {
  rest_api_id   = aws_api_gateway_rest_api.receipt_api.id
  resource_id   = aws_api_gateway_resource.upload.id
  http_method   = "OPTIONS"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "options_upload_integration" {
  rest_api_id = aws_api_gateway_rest_api.receipt_api.id
  resource_id = aws_api_gateway_resource.upload.id
  http_method = aws_api_gateway_method.options_upload.http_method

  type = "MOCK"
  request_templates = {
    "application/json" = jsonencode({
      statusCode = 200
    })
  }
}

resource "aws_api_gateway_method_response" "options_upload_response" {
  rest_api_id = aws_api_gateway_rest_api.receipt_api.id
  resource_id = aws_api_gateway_resource.upload.id
  http_method = aws_api_gateway_method.options_upload.http_method
  status_code = "200"

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = true
    "method.response.header.Access-Control-Allow-Methods" = true
    "method.response.header.Access-Control-Allow-Origin"  = true
  }
}

resource "aws_api_gateway_integration_response" "options_upload_integration_response" {
  rest_api_id = aws_api_gateway_rest_api.receipt_api.id
  resource_id = aws_api_gateway_resource.upload.id
  http_method = aws_api_gateway_method.options_upload.http_method
  status_code = aws_api_gateway_method_response.options_upload_response.status_code

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = "'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token'"
    "method.response.header.Access-Control-Allow-Methods" = "'GET,OPTIONS,POST,PUT'"
    "method.response.header.Access-Control-Allow-Origin"  = "'*'"
  }
}

resource "aws_s3_bucket_cors_configuration" "receipt_uploads_cors" {
  bucket = aws_s3_bucket.receipt_uploads.id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["GET", "PUT", "POST"]
    allowed_origins = ["*"]  # Allow all for testing
    expose_headers  = ["ETag"]
    max_age_seconds = 3000
  }
}
# Step function for processing receipts

# Step Functions IAM Role

resource "aws_iam_role" "step_functions_role" {
  name = "${var.project_name}-step-functions-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "states.amazonaws.com"
        }
      }
    ]
  })
}

# Step Functions IAM Policy
# Step Functions IAM Policy 
resource "aws_iam_role_policy" "step_functions_policy" {
  name = "${var.project_name}-step-functions-policy"
  role = aws_iam_role.step_functions_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "lambda:InvokeFunction"
        ]
        Resource = [
          aws_lambda_function.ocr_processor.arn,
          "${aws_lambda_function.ocr_processor.arn}:*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogDelivery",
          "logs:GetLogDelivery", 
          "logs:UpdateLogDelivery",
          "logs:DeleteLogDelivery",
          "logs:ListLogDeliveries",
          "logs:PutResourcePolicy",
          "logs:DescribeResourcePolicies",
          "logs:DescribeLogGroups"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "logs:DescribeLogStreams"
        ]
        Resource = [
          aws_cloudwatch_log_group.step_functions_logs.arn,
          "${aws_cloudwatch_log_group.step_functions_logs.arn}:*"
        ]
      }
    ]
  })
}

# Step Functions State Machine
resource "aws_sfn_state_machine" "receipt_processor" {
  name     = "${var.project_name}-receipt-processor"
  role_arn = aws_iam_role.step_functions_role.arn

  definition = jsonencode({
    Comment = "Receipt Processing Workflow"
    StartAt = "ProcessReceipt"
    States = {
      ProcessReceipt = {
        Type = "Task"
        Resource = aws_lambda_function.ocr_processor.arn
        TimeoutSeconds = 300
        Retry = [
          {
            ErrorEquals = ["Lambda.ServiceException", "Lambda.AWSLambdaException", "Lambda.SdkClientException"]
            IntervalSeconds = 2
            MaxAttempts = 3
            BackoffRate = 2.0
          }
        ]
        Catch = [
          {
            ErrorEquals = ["States.TaskFailed"]
            Next = "ProcessingFailed"
            ResultPath = "$.error"
          }
        ]
        Next = "ProcessingSucceeded"
      }
      ProcessingSucceeded = {
        Type = "Succeed"
        Comment = "Receipt processed successfully"
      }
      ProcessingFailed = {
        Type = "Fail"
        Comment = "Receipt processing failed"
        Cause = "Lambda function failed to process receipt"
      }
    }
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.step_functions_logs.arn}:*"
    include_execution_data = true
    level                  = "ALL"
  }

  tags = {
    Name = "Receipt Processor State Machine"
  }
}

# CloudWatch Log Group for Step Functions
resource "aws_cloudwatch_log_group" "step_functions_logs" {
  name              = "/aws/stepfunctions/${var.project_name}-receipt-processor"
  retention_in_days = 14
}

# Lambda function to trigger Step Functions from S3
resource "aws_lambda_function" "step_functions_trigger" {
  filename         = "../src/step-functions-trigger/step-functions-trigger.zip"
  function_name    = "${var.project_name}-step-functions-trigger"
  role            = aws_iam_role.step_functions_trigger_role.arn
  handler         = "lambda_function.lambda_handler"
  runtime         = "python3.11"
  timeout         = 30

  environment {
    variables = {
      STATE_MACHINE_ARN = aws_sfn_state_machine.receipt_processor.arn
    }
  }

  depends_on = [aws_iam_role_policy.step_functions_trigger_policy]
}

# IAM role for Step Functions trigger Lambda
resource "aws_iam_role" "step_functions_trigger_role" {
  name = "${var.project_name}-step-functions-trigger-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

# IAM policy for Step Functions trigger Lambda
resource "aws_iam_role_policy" "step_functions_trigger_policy" {
  name = "${var.project_name}-step-functions-trigger-policy"
  role = aws_iam_role.step_functions_trigger_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream", 
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect = "Allow"
        Action = [
          "states:StartExecution"
        ]
        Resource = aws_sfn_state_machine.receipt_processor.arn
      }
    ]
  })
}

# Permission for S3 to invoke Step Functions trigger Lambda
resource "aws_lambda_permission" "allow_s3_invoke_step_functions_trigger" {
  statement_id  = "AllowExecutionFromS3Bucket"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.step_functions_trigger.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.receipt_uploads.arn
}

# Update S3 bucket notification to trigger Step Functions instead
resource "aws_s3_bucket_notification" "receipt_upload_notification_step_functions" {
  bucket = aws_s3_bucket.receipt_uploads.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.step_functions_trigger.arn
    events             = ["s3:ObjectCreated:*"]
    filter_prefix      = "receipts/"
    filter_suffix      = ""
  }

  depends_on = [aws_lambda_permission.allow_s3_invoke_step_functions_trigger]
}

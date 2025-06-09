# 🚀 Smart Receipt Parser - Deployment Guide

## Prerequisites

Before deploying this application, ensure you have:

### **1. AWS Account Setup**
- AWS account with administrative privileges
- AWS CLI installed and configured
- Access to Amazon Bedrock (Claude model) - **Important!**
- Sufficient service limits for the deployment region

### **2. Required Tools**
```bash
# Install AWS CLI
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install

# Install Terraform
wget https://releases.hashicorp.com/terraform/1.6.0/terraform_1.6.0_linux_amd64.zip
unzip terraform_1.6.0_linux_amd64.zip
sudo mv terraform /usr/local/bin/

# Verify installations
aws --version
terraform --version
```

### **3. AWS Configuration**
```bash
# Configure AWS credentials
aws configure
# Enter your Access Key ID, Secret Access Key, Region (eu-west-2), and output format (json)

# Verify access
aws sts get-caller-identity
```

## 🎯 Quick Deployment (Recommended)

### **Step 1: Clone Repository**
```bash
git clone https://github.com/yourusername/smart-receipt-parser
cd smart-receipt-parser
```

### **Step 2: Enable Amazon Bedrock Access**
**⚠️ CRITICAL: This step is required before deployment**

1. Open AWS Console → Amazon Bedrock
2. Go to "Model access" in the left sidebar
3. Click "Request model access"
4. Enable access for **Anthropic Claude **
5. Wait for approval (usually instant)

### **Step 3: Prepare Lambda Functions**
```bash
# Make deployment script executable
chmod +x scripts/create-lambda-zips.sh
chmod +x scripts/deploy.sh

# Package all Lambda functions
./scripts/create-lambda-zips.sh
```

### **Step 4: Deploy Infrastructure**
```bash
# Quick deployment
./scripts/deploy.sh

# Or manual deployment
cd terraform
terraform init
terraform plan
terraform apply
```

### **Step 5: Deploy Frontend**
```bash
# Get frontend bucket name from Terraform output
FRONTEND_BUCKET=$(terraform output -raw frontend_bucket_name)

# Upload frontend files
aws s3 sync src/frontend/ s3://$FRONTEND_BUCKET/ --delete

echo "Frontend deployed to: $(terraform output -raw frontend_url)"
```

## 🔧 Manual Deployment (Detailed)

### **Step 1: Prepare Environment**
```bash
# Create project directory
mkdir smart-receipt-parser
cd smart-receipt-parser

# Copy all source files from repository
```

### **Step 2: Create Lambda Deployment Packages**
```bash
# API Handler Lambda
cd src/api-handler
zip -r api-handler.zip lambda_function.py
cd ../..

# OCR Processor Lambda  
cd src/ocr-processor
zip -r ocr-processor.zip lambda_function.py
cd ../..

# Step Functions Trigger Lambda
cd src/step-functions-trigger
zip -r step-functions-trigger.zip lambda_function.py
cd ../..
```

### **Step 3: Configure Terraform Variables**
```bash
cd terraform

# Create terraform.tfvars file
cat > terraform.tfvars << EOF
project_name = "receipt-parser"
aws_region   = "eu-west-2"  # Change to your preferred region
EOF
```

### **Step 4: Deploy Infrastructure**
```bash
# Initialize Terraform
terraform init

# Review deployment plan
terraform plan

# Deploy (type 'yes' when prompted)
terraform apply

# Note the outputs - you'll need these URLs
terraform output
```

### **Step 5: Verify Deployment**
```bash
# Check Lambda functions
aws lambda list-functions --query 'Functions[?contains(FunctionName, `receipt-parser`)].FunctionName'

# Check Step Functions
aws stepfunctions list-state-machines --query 'stateMachines[?contains(name, `receipt-parser`)].name'

# Check S3 buckets
aws s3 ls | grep receipt-parser
```

## 🧪 Testing Your Deployment

### **1. Frontend Access Test**
```bash
# Get frontend URL
terraform output frontend_url

# Open in browser - you should see the receipt parser interface
```

### **2. API Endpoint Test**
```bash
# Get API URL
API_URL=$(terraform output -raw api_url)

# Test API health
curl $API_URL/receipts

# Should return empty array: {"receipts": [], "count": 0, ...}
```

### **3. Upload Test**
```bash
# Test upload URL generation
curl -X POST $API_URL/upload \
  -H "Content-Type: application/json" \
  -d '{"filename": "test.jpg", "contentType": "image/jpeg"}'

# Should return presigned URL
```

### **4. Complete Integration Test**
1. Open frontend in browser
2. Upload a sample receipt image
3. Watch processing status
4. Verify results appear
5. Check AWS consoles:
   - Step Functions: View execution
   - CloudWatch: Check logs
   - DynamoDB: Verify data storage

## 🔍 Troubleshooting

### **Common Issues & Solutions**

#### **1. Bedrock Access Denied**
```
Error: AccessDeniedException when calling Bedrock
```
**Solution:** Enable model access in Bedrock console (see Step 2 above)

#### **2. Lambda Timeout Errors**
```
Task timed out after X seconds
```
**Solution:** Check OCR Processor Lambda timeout setting (should be 300 seconds)

#### **3. CORS Errors in Browser**
```
Access to fetch blocked by CORS policy
```
**Solution:** Verify API Gateway CORS configuration and redeploy

#### **4. Step Functions Execution Failures**
```
States.TaskFailed in Step Functions
```
**Solution:** Check CloudWatch logs for the OCR Processor Lambda

#### **5. S3 Upload Failures**
```
Upload failed: 403 Forbidden
```
**Solution:** Verify S3 bucket CORS configuration in Terraform

### **Debug Commands**
```bash
# Check Lambda function logs
aws logs describe-log-groups --log-group-name-prefix "/aws/lambda/receipt-parser"

# View recent Step Functions executions
aws stepfunctions list-executions --state-machine-arn $(terraform output -raw step_functions_arn)

# Check DynamoDB table
aws dynamodb scan --table-name $(terraform output -raw dynamodb_table_name) --limit 5
```

## 📊 Monitoring Your Deployment

### **1. CloudWatch Dashboards**
- Navigate to CloudWatch → Dashboards
- View Lambda function metrics
- Monitor API Gateway request rates
- Track Step Functions execution success rates

### **2. Step Functions Console**
- AWS Console → Step Functions → State machines
- Click on "receipt-parser-receipt-processor"
- View execution history and details

### **3. Cost Monitoring**
```bash
# Check current month costs
aws ce get-cost-and-usage \
  --time-period Start=2025-06-01,End=2025-06-30 \
  --granularity MONTHLY \
  --metrics BlendedCost \
  --group-by Type=DIMENSION,Key=SERVICE
```

## 🧹 Cleanup Resources

### **Complete Cleanup**
```bash
# Run cleanup script
./scripts/cleanup.sh

# Or manual cleanup
cd terraform
terraform destroy
```

### **Partial Cleanup (Keep Data)**
```bash
# Remove compute resources but keep data
terraform destroy -target=aws_lambda_function.api_handler
terraform destroy -target=aws_lambda_function.ocr_processor
terraform destroy -target=aws_sfn_state_machine.receipt_processor
```

## 🚀 Production Considerations

### **Security Enhancements**
- Replace wildcard CORS with specific domains
- Implement API authentication (API Keys or Cognito)
- Enable VPC for Lambda functions
- Use AWS Secrets Manager for sensitive configuration

### **Performance Optimization**
- Enable Lambda provisioned concurrency for consistent performance
- Implement CloudFront for frontend distribution
- Configure DynamoDB auto-scaling for high traffic
- Add API Gateway caching

### **Monitoring & Alerting**
- Set up CloudWatch alarms for error rates
- Configure SNS notifications for failures
- Implement X-Ray tracing for distributed monitoring
- Set up cost alerts for budget management

## 📞 Support

If you encounter issues during deployment:

1. **Check Prerequisites:** Ensure all tools are installed and configured
2. **Verify Permissions:** Confirm AWS account has necessary permissions
3. **Review Logs:** Check CloudWatch logs for detailed error messages
4. **Test Components:** Use the testing commands above to isolate issues
5. **Clean Deploy:** If issues persist, run cleanup and redeploy

## 🎯 Success Criteria

Your deployment is successful when:

- ✅ Frontend loads without errors
- ✅ File upload generates presigned URLs
- ✅ Receipt processing completes within 30 seconds
- ✅ Step Functions executions show as "Succeeded"
- ✅ Processed data appears in frontend
- ✅ All AWS services are functioning correctly

**Deployment typically takes 5-10 minutes end-to-end.**
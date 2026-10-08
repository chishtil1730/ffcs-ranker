# TaskFlow AWS Deployment --- Commands Used

## Connection

``` powershell
ssh -i "E:\taskflow-key.pem" ec2-user@13.206.237.254
```

## Upload application files

``` powershell
scp -i "E:\taskflow-key.pem" app.py index.html requirements.txt deploy.sh ec2-user@13.206.237.254:/opt/taskflow/
```

For later UI/backend updates:

``` powershell
scp -i "E:\taskflow-key.pem" app.py index.html ec2-user@13.206.237.254:/opt/taskflow/
```

## Initial deployment

``` bash
cd /opt/taskflow
nano deploy.sh
chmod +x deploy.sh
sudo bash deploy.sh
```

Deployment configuration:

``` bash
export AWS_REGION="ap-south-1"
export DYNAMODB_TABLE="taskflow-tasks"
export S3_BUCKET="taskflow-demo-taskbucket-ds7cweifashm"
```

## Health checks

Direct Gunicorn:

``` bash
curl http://127.0.0.1:5000/api/health
```

Through Nginx:

``` bash
curl http://localhost/api/health
```

Public endpoint:

``` bash
curl http://13.206.237.254/api/health
```

Expected:

``` json
{"aws_region":"ap-south-1","ok":true,"service":"task-planner"}
```

## Nginx troubleshooting

List configuration files:

``` bash
sudo ls -la /etc/nginx/conf.d/
```

Find listeners/server names:

``` bash
sudo grep -R "listen 80\|server_name" /etc/nginx/
```

Inspect main configuration:

``` bash
sudo sed -n '1,160p' /etc/nginx/nginx.conf
```

Edit Nginx:

``` bash
sudo nano /etc/nginx/nginx.conf
sudo nano /etc/nginx/conf.d/taskflow.conf
```

Test configuration:

``` bash
sudo nginx -t
```

Restart Nginx:

``` bash
sudo systemctl restart nginx
```

TaskFlow reverse proxy:

``` nginx
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## Gunicorn

Check running Gunicorn processes:

``` bash
ps aux | grep gunicorn
```

Stop the existing Gunicorn processes:

``` bash
sudo pkill -f '/opt/taskflow/venv/bin/gunicorn'
```

Start Gunicorn:

``` bash
cd /opt/taskflow
sudo /opt/taskflow/venv/bin/gunicorn --bind 127.0.0.1:5000 --workers 2 --timeout 120 app:app &
```

> `taskflow.service` was not created by the deployment, so
> `sudo systemctl restart taskflow` is not the correct restart command
> for this deployment.

## AWS configuration inspection

``` bash
grep -nE "AWS_REGION|DYNAMODB_TABLE|S3_BUCKET|boto3.resource|boto3.client|TaskPlannerTasks|us-east-1" app.py
```

``` bash
grep -nE "REGION|TABLE_NAME|BUCKET_NAME" app.py
```

Correct defaults:

``` python
REGION = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "ap-south-1"))
TABLE_NAME = os.getenv("DYNAMODB_TABLE", "taskflow-tasks")
BUCKET_NAME = os.getenv("S3_BUCKET", "taskflow-demo-taskbucket-ds7cweifashm")
```

Fix region if necessary:

``` bash
sudo sed -i 's/"us-east-1"/"ap-south-1"/' app.py
```

Fix DynamoDB table if necessary:

``` bash
sudo sed -i 's/"TaskPlannerTasks"/"taskflow-tasks"/' app.py
```

Fix S3 fallback if necessary:

``` bash
sudo sed -i 's/os.getenv("S3_BUCKET", "")/os.getenv("S3_BUCKET", "taskflow-demo-taskbucket-ds7cweifashm")/' app.py
```

## Normal UI update workflow

1.  Replace `app.py` and/or `index.html` locally.
2.  Upload them:

``` powershell
scp -i "E:\taskflow-key.pem" app.py index.html ec2-user@13.206.237.254:/opt/taskflow/
```

3.  SSH:

``` powershell
ssh -i "E:\taskflow-key.pem" ec2-user@13.206.237.254
```

4.  Restart Gunicorn:

``` bash
sudo pkill -f '/opt/taskflow/venv/bin/gunicorn'
cd /opt/taskflow
sudo /opt/taskflow/venv/bin/gunicorn --bind 127.0.0.1:5000 --workers 2 --timeout 120 app:app &
```

5.  Verify:

``` bash
curl http://localhost/api/health
```

6.  Open:

``` text
http://13.206.237.254
```

Hard refresh after frontend changes:

``` text
Ctrl + Shift + R
```

## Useful file commands

``` bash
cd /opt/taskflow
ls
ls -la
nano app.py
nano index.html
```

## AWS resources used

``` text
Region: ap-south-1
CloudFormation Stack: taskflow-demo
EC2 Instance: i-0d071076f9de0100d
Public IP: 13.206.237.254
DynamoDB Table: taskflow-tasks
S3 Bucket: taskflow-demo-taskbucket-ds7cweifashm
VPC: vpc-040c8a8f321c36df
```

## Architecture

``` text
Internet
   |
   v
EC2 Public IP
   |
   v
Nginx :80
   |
   v
Gunicorn :5000
   |
   v
Flask TaskFlow
   |
   +----------+----------+
   |                     |
   v                     v
DynamoDB                 S3
taskflow-tasks           taskflow-demo-taskbucket-ds7cweifashm
   |
   +-- Task metadata
   +-- Status
   +-- Priority
   +-- Due date
   +-- Task type

EC2
 |
 +-- IAM Role
 |
 +-- VPC
     +-- Public Subnet
     +-- Internet Gateway
     +-- Route Table
     +-- Security Group
     +-- S3 Gateway Endpoint
     +-- DynamoDB Gateway Endpoint
```

## Cleanup after the demo

The infrastructure was created using the CloudFormation stack:

``` text
taskflow-demo
```

After the final demonstration, delete the CloudFormation stack to clean
up the AWS resources. If CloudFormation refuses to delete the S3 bucket
because it contains objects, empty the bucket first.

Do not delete the stack while the live demo is still needed.

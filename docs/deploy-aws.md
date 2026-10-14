# Deploying Vigía on AWS

Two paths, from simplest to most production-like. Both fit inside the credits AWS gives new
accounts (up to USD 200 for 6 months at the time of writing), but **always set a budget alarm and
delete what you create** when the demo is over.

> AWS App Runner is closed to new customers. AWS recommends **Amazon ECS Express Mode** instead,
> which is what option B uses.

## Before you start

1. Create the account, enable MFA on the root user and create an IAM user or SSO identity for daily work.
2. Billing console -> Budgets -> create a monthly cost budget (for example USD 10) with an email alert.
3. Install and configure the AWS CLI v2: `aws configure` (region, for example `us-east-1`).

## Option A: one EC2 instance with Docker Compose (fastest)

The whole stack on one virtual machine: good for a live demo, cheap, and it exercises the basics
(IaaS, SSH, security groups, Linux administration).

1. **Launch the instance** (EC2 console -> Launch instance):
   * AMI: Ubuntu Server 24.04 LTS; type: `t3.medium` (2 vCPU, 4 GB) since four containers plus two
     databases need the memory.
   * Key pair: create one and keep the `.pem` file (`chmod 400 vigia.pem`).
   * Security group: allow **SSH (22) from My IP only**. Do not open the application ports to the
     internet; use an SSH tunnel instead (step 4).
   * Storage: 20 GB gp3.
2. **Connect and install Docker:**
   ```bash
   ssh -i vigia.pem ubuntu@<public-ip>
   sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 git make python3-venv
   sudo usermod -aG docker ubuntu && exit     # log in again so the group applies
   ```
3. **Deploy:**
   ```bash
   ssh -i vigia.pem ubuntu@<public-ip>
   git clone https://github.com/lobby9000/vigia.git && cd vigia
   ./scripts/bootstrap.sh
   python3 -m venv .venv && . .venv/bin/activate && pip install -r scripts/requirements.txt
   make seed && make simulate && make scan
   ```
4. **Open it from your laptop through a tunnel** (traffic is encrypted by SSH, ports stay closed):
   ```bash
   ssh -i vigia.pem -L 8001:localhost:8001 -L 8000:localhost:8000 -L 8080:localhost:8080 ubuntu@<public-ip>
   ```
   Then browse http://localhost:8001 as usual.
5. **Schedule the maintenance jobs** with `crontab -e`:
   ```
   */15 * * * * /home/ubuntu/vigia/scripts/refresh_views.sh >> /home/ubuntu/vigia/refresh.log 2>&1
   15 3 * * *   /home/ubuntu/vigia/scripts/db_backup.sh    >> /home/ubuntu/vigia/backup.log 2>&1
   ```
6. **Stop the instance** when you are not using it (you only pay for the disk while stopped) and
   **terminate** it when you are done.

## Option B: managed services (production-like)

```
Internet -> ECS Express Mode (HTTPS, load balancer, autoscaling) -> containers from ECR
                                    |                      |
                         Amazon RDS for PostgreSQL     MongoDB Atlas (or Amazon DocumentDB)
                         secrets in AWS Secrets Manager, logs in CloudWatch
```

### 1. Container images in Amazon ECR

```bash
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGION=us-east-1
REGISTRY=$ACCOUNT.dkr.ecr.$REGION.amazonaws.com
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $REGISTRY

for service in ingest-service analytics-api dashboard; do
  aws ecr create-repository --repository-name vigia/$service --image-scanning-configuration scanOnPush=true
  docker build -t $REGISTRY/vigia/$service:1.0.0 ./$service
  docker push $REGISTRY/vigia/$service:1.0.0
done
```

### 2. Databases

* **PostgreSQL:** RDS console -> Create database -> PostgreSQL 17, template *Free tier* or
  *Dev/Test*, `db.t4g.micro`, **public access: No**. Note the endpoint. Load the schema from a
  machine inside the VPC (for example the EC2 instance of option A):
  ```bash
  for f in database/01_schema.sql database/02_views.sql database/03_seed_reference.sql; do
    psql "host=<rds-endpoint> user=vigia dbname=vigia sslmode=require" -v ON_ERROR_STOP=1 -f "$f"
  done
  ```
* **MongoDB:** the simplest option is a free MongoDB Atlas cluster created in the same AWS region.
  Amazon DocumentDB is the AWS-native alternative (MongoDB-compatible, not free).

### 3. Secrets

```bash
aws secretsmanager create-secret --name vigia/jwt-secret --secret-string "$(openssl rand -hex 32)"
aws secretsmanager create-secret --name vigia/db-password --secret-string '<the RDS password>'
```

### 4. ECS Express Mode

Create the two IAM roles once (task execution role with `AmazonECSTaskExecutionRolePolicy`, and the
infrastructure role with `AmazonECSInfrastructureRoleforExpressGatewayServices`), as described in
the [Express Mode getting started guide](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/express-service-getting-started.html).
The execution role also needs `secretsmanager:GetSecretValue` on the `vigia/*` secrets.

Then one service per container. The analytics API, for example:

```bash
aws ecs create-express-gateway-service \
  --service-name vigia-analytics \
  --execution-role-arn arn:aws:iam::$ACCOUNT:role/ecsTaskExecutionRole \
  --infrastructure-role-arn arn:aws:iam::$ACCOUNT:role/ecsInfrastructureRoleForExpressServices \
  --health-check-path /health \
  --cpu 512 --memory 1024 \
  --primary-container '{
    "image": "'$REGISTRY'/vigia/analytics-api:1.0.0",
    "containerPort": 8000,
    "environment": [
      {"name": "MONGO_URL", "value": "<atlas connection string>"},
      {"name": "MONGO_DB",  "value": "vigia"}
    ],
    "secrets": [
      {"name": "JWT_SECRET_KEY", "valueFrom": "arn:aws:secretsmanager:'$REGION':'$ACCOUNT':secret:vigia/jwt-secret"}
    ]
  }' \
  --monitor-resources DEPLOYMENT
```

`DATABASE_URL` contains the password, so build it inside the container from separate variables or
store the whole URL as a secret. Repeat for `ingest-service` (port 8080, health check
`/actuator/health`, variables `SPRING_DATASOURCE_*`, `SPRING_MONGODB_URI`, `JWT_SECRET`) and
`dashboard` (port 8001, health check `/login/`). Each service receives an HTTPS URL of the form
`https://<service>.ecs.<region>.on.aws/`.

Networking: put the RDS instance in the same VPC and allow inbound 5432 **only from the security
group of the ECS services**.

### 5. Clean up

```bash
aws ecs delete-express-gateway-service --service-arn <arn>   # one per service
aws rds delete-db-instance --db-instance-identifier vigia --skip-final-snapshot
aws ecr delete-repository --repository-name vigia/analytics-api --force   # and the other two
aws secretsmanager delete-secret --secret-id vigia/jwt-secret --force-delete-without-recovery
```

## The same architecture on Azure and Google Cloud

| Need | AWS | Azure | Google Cloud |
|---|---|---|---|
| Virtual machine | EC2 | Virtual Machines | Compute Engine |
| Serverless containers | ECS Express Mode / Fargate | Container Apps | Cloud Run |
| Container registry | ECR | Container Registry | Artifact Registry |
| Managed PostgreSQL | RDS / Aurora | Database for PostgreSQL (Flexible Server) | Cloud SQL / AlloyDB |
| MongoDB compatible | DocumentDB | Cosmos DB for MongoDB | MongoDB Atlas (marketplace) |
| Wide column (Cassandra) | Keyspaces | Cosmos DB for Apache Cassandra | Bigtable (similar model) |
| Secrets | Secrets Manager | Key Vault | Secret Manager |
| Logs and metrics | CloudWatch | Azure Monitor | Cloud Logging / Monitoring |
| Identity and permissions | IAM | Entra ID + RBAC | Cloud IAM |
| Object storage | S3 | Blob Storage | Cloud Storage |

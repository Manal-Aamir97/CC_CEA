#!/bin/bash
# /opt/expense/deploy.sh <image-tag>
# Runs ON the EC2 instance. Called by user-data at first boot and by the
# CI/CD pipeline (via AWS Systems Manager Run Command) on every release.
#   1. reads secrets from SSM Parameter Store using the instance role
#   2. writes them to a root-only .env file
#   3. pulls the requested image tag from GHCR and restarts the containers
set -euo pipefail

TAG="${1:-latest}"
GHCR_OWNER="__GHCR_OWNER__"          # replaced by user-data.sh
PARAM_PREFIX="/expense-tracker"
cd /opt/expense

# Instance metadata (IMDSv2)
TOKEN=$(curl -fsS -X PUT http://169.254.169.254/latest/api/token -H "X-aws-ec2-metadata-token-ttl-seconds: 300")
md() { curl -fsS -H "X-aws-ec2-metadata-token: $TOKEN" "http://169.254.169.254/latest/meta-data/$1"; }
REGION=$(md placement/region)
INSTANCE_ID=$(md instance-id)

param() {
  aws ssm get-parameter --region "$REGION" --name "$PARAM_PREFIX/$1" \
    --with-decryption --query Parameter.Value --output text
}

umask 077
cat > .env.new <<ENV
GHCR_OWNER=${GHCR_OWNER}
IMAGE_TAG=${TAG}
APP_VERSION=${TAG}
AWS_REGION=${REGION}
INSTANCE_ID=${INSTANCE_ID}
DB_HOST=$(param db_host)
DB_NAME=$(param db_name)
DB_USER=$(param db_user)
DB_PASSWORD=$(param db_password)
SECRET_KEY=$(param secret_key)
S3_BUCKET=$(param s3_bucket)
DB_SSL_CA=/app/certs/rds-global-bundle.pem
CURRENCY=Rs
ENV
mv .env.new .env

echo "Deploying ${GHCR_OWNER} images with tag ${TAG} on ${INSTANCE_ID}"
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d --remove-orphans
docker image prune -f >/dev/null

# Wait until the app answers through Nginx, so a broken release fails the pipeline
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1/health >/dev/null; then
    echo "Healthy: $(curl -fsS http://127.0.0.1/health)"
    exit 0
  fi
  sleep 3
done
echo "Application did not become healthy" >&2
docker compose -f docker-compose.prod.yml logs --tail 50 >&2
exit 1

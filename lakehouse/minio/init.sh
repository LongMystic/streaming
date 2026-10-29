#!/bin/sh
# One-shot MinIO bootstrap (minio-init service): warehouse bucket + a non-root access key
# that may only touch that bucket. Idempotent, safe to re-run on every `docker compose up`.
set -eu

mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null

mc mb --ignore-existing "local/$LAKEHOUSE_BUCKET"

cat > /tmp/lakehouse-rw.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:GetBucketLocation", "s3:ListBucket", "s3:ListBucketMultipartUploads"],
      "Resource": ["arn:aws:s3:::$LAKEHOUSE_BUCKET"]
    },
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject",
                 "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"],
      "Resource": ["arn:aws:s3:::$LAKEHOUSE_BUCKET/*"]
    }
  ]
}
EOF
mc admin policy create local lakehouse-rw /tmp/lakehouse-rw.json >/dev/null

# `user add` on an existing user just resets its secret, so a changed .env value takes effect.
mc admin user add local "$LAKEHOUSE_S3_ACCESS_KEY" "$LAKEHOUSE_S3_SECRET_KEY" >/dev/null
# `policy attach` fails when the policy is already attached; only that case is acceptable.
mc admin policy attach local lakehouse-rw --user "$LAKEHOUSE_S3_ACCESS_KEY" >/dev/null 2>&1 \
  || mc admin user info local "$LAKEHOUSE_S3_ACCESS_KEY" | grep -q lakehouse-rw

echo "MinIO ready: bucket '$LAKEHOUSE_BUCKET', user '$LAKEHOUSE_S3_ACCESS_KEY' (policy lakehouse-rw)"

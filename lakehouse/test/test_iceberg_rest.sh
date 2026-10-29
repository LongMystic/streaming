#!/usr/bin/env bash
# End-to-end lakehouse check. Run from the streaming/ folder: bash lakehouse/test/test_iceberg_rest.sh
# Creates a throwaway namespace + table through the REST catalog, then checks that the metadata file
# landed in MinIO and the catalog pointer landed in Aiven MySQL. Cleans up after itself.
set -Eeuo pipefail
export MSYS_NO_PATHCONV=1

set -a
. ./.env
set +a

REST=http://127.0.0.1:8181/v1
NS="smoke_$(date +%s)_$RANDOM"
TABLE=events

pass() { echo "PASS  $1"; }
fail() { echo "FAIL  $1"; exit 1; }

# http_delete <url>  -> prints the HTTP status code (000 when the request never got an answer)
http_delete() {
  curl -s -o /dev/null -w '%{http_code}' --max-time 30 -X DELETE "$1" || true
}

# Only runs if the script stops before its own drop steps succeed.
CLEANED=0
cleanup() {
  [ "$CLEANED" = 1 ] && return
  http_delete "$REST/namespaces/$NS/tables/$TABLE?purgeRequested=true" >/dev/null
  http_delete "$REST/namespaces/$NS" >/dev/null
}
trap cleanup EXIT

# mc_lakehouse <mc args...>  (as the bucket-scoped key, i.e. the same identity iceberg-rest uses)
mc_lakehouse() {
  docker exec -e MC_HOST_lh="http://$LAKEHOUSE_S3_ACCESS_KEY:$LAKEHOUSE_S3_SECRET_KEY@minio:9000" minio mc "$@"
}

# catalog_sql <sql>  (borrows the mysql client in mysql-primary; Aiven requires TLS)
catalog_sql() {
  docker exec -e MYSQL_PWD="$ICEBERG_DB_PASSWORD" mysql-primary \
    mysql -h "$ICEBERG_DB_HOST" -P "$ICEBERG_DB_PORT" -u "$ICEBERG_DB_USER" --ssl-mode=REQUIRED \
    -D "$ICEBERG_DB_NAME" -N -e "$1"
}

curl -fs "$REST/config" >/dev/null \
  && pass "REST catalog answers /v1/config" \
  || fail "REST catalog is not reachable on 8181"

curl -fs -X POST "$REST/namespaces" -H 'Content-Type: application/json' \
  -d "{\"namespace\": [\"$NS\"]}" >/dev/null \
  && pass "created namespace $NS" \
  || fail "could not create namespace $NS"

response=$(curl -fs -X POST "$REST/namespaces/$NS/tables" -H 'Content-Type: application/json' -d "{
  \"name\": \"$TABLE\",
  \"schema\": {\"type\": \"struct\", \"schema-id\": 0, \"fields\": [
    {\"id\": 1, \"name\": \"id\", \"type\": \"long\", \"required\": true},
    {\"id\": 2, \"name\": \"message\", \"type\": \"string\", \"required\": false}
  ]}
}") || fail "could not create table $NS.$TABLE"
metadata=$(printf '%s' "$response" | grep -o '"metadata-location":"[^"]*"' | cut -d'"' -f4)
[[ "$metadata" == "s3://$LAKEHOUSE_BUCKET/"* ]] \
  && pass "created table $NS.$TABLE, metadata at $metadata" \
  || fail "unexpected metadata location: '$metadata'"

mc_lakehouse stat "lh/${metadata#s3://}" >/dev/null \
  && pass "metadata file exists in MinIO" \
  || fail "metadata file is missing from MinIO"

[ "$(catalog_sql "SELECT metadata_location FROM iceberg_tables
                  WHERE table_namespace = '$NS' AND table_name = '$TABLE'")" = "$metadata" ] \
  && pass "Aiven MySQL iceberg_tables points at the same metadata file" \
  || fail "catalog row in Aiven MySQL is missing or stale"

code=$(http_delete "$REST/namespaces/$NS/tables/$TABLE?purgeRequested=true")
[[ "$code" == 20? ]] \
  && pass "dropped table $NS.$TABLE (purge)" \
  || fail "drop table returned HTTP $code"

code=$(http_delete "$REST/namespaces/$NS")
[[ "$code" == 20? ]] \
  && pass "dropped namespace $NS" \
  || fail "drop namespace returned HTTP $code"
CLEANED=1

echo "All lakehouse checks passed."

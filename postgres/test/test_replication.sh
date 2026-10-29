#!/usr/bin/env bash
# End-to-end replication check. Run from the streaming/ folder: bash postgres/test/test_replication.sh
set -Eeuo pipefail
export MSYS_NO_PATHCONV=1

set -a
. ./.env
set +a

PRIMARY=postgres-primary
REPLICA=postgres-replica
MARKER="replication-test-$(date +%s)-$RANDOM"

# psql <container> <user> <password> <database> <sql>
run_psql() {
  docker exec -e PGPASSWORD="$3" "$1" \
    psql -h 127.0.0.1 -U "$2" -d "$4" -v ON_ERROR_STOP=1 -qAt -c "$5"
}

pass() { echo "PASS  $1"; }
fail() { echo "FAIL  $1"; exit 1; }

[ "$(run_psql "$REPLICA" "$POSTGRES_USER" "$POSTGRES_PASSWORD" postgres 'SELECT pg_is_in_recovery()')" = t ] \
  && pass "replica is in recovery (standby) mode" \
  || fail "replica is not a standby"

[ "$(run_psql "$PRIMARY" "$POSTGRES_USER" "$POSTGRES_PASSWORD" postgres \
  "SELECT count(*) FROM pg_stat_replication WHERE state = 'streaming'")" -ge 1 ] \
  && pass "primary has a streaming replica" \
  || fail "primary has no streaming replica"

run_psql "$PRIMARY" "$POSTGRES_APP_USER" "$POSTGRES_APP_PASSWORD" appdb "
  SET client_min_messages TO warning;
  CREATE TABLE IF NOT EXISTS replication_test (
    id SERIAL PRIMARY KEY,
    message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  );
  INSERT INTO replication_test (message) VALUES ('$MARKER');"
pass "app wrote '$MARKER' on primary"

for _ in $(seq 1 10); do
  count=$(run_psql "$REPLICA" "$POSTGRES_READER_USER" "$POSTGRES_READER_PASSWORD" appdb \
    "SELECT count(*) FROM replication_test WHERE message = '$MARKER'" 2>/dev/null || echo 0)
  [ "$count" = 1 ] && break
  sleep 1
done
[ "$count" = 1 ] \
  && pass "reader sees the row on replica" \
  || fail "row did not reach the replica within 10s"

if run_psql "$REPLICA" "$POSTGRES_APP_USER" "$POSTGRES_APP_PASSWORD" appdb \
  "INSERT INTO replication_test (message) VALUES ('must-fail')" 2>/dev/null; then
  fail "replica accepted a write"
else
  pass "replica rejects writes"
fi

echo "All PostgreSQL replication checks passed."

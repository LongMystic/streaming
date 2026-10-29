#!/usr/bin/env bash
# End-to-end replication check. Run from the streaming/ folder: bash mysql/test/test_replication.sh
set -Eeuo pipefail
export MSYS_NO_PATHCONV=1

set -a
. ./.env
set +a

PRIMARY=mysql-primary
REPLICA=mysql-replica
MARKER="replication-test-$(date +%s)-$RANDOM"

# mysql_tcp <container> <user> <password> <sql>
mysql_tcp() {
  docker exec -e MYSQL_PWD="$3" "$1" \
    mysql --protocol=TCP -h 127.0.0.1 -u"$2" -N -e "$4"
}

# mysql_root <container> <mysql args...>  (root only exists as root@localhost, i.e. over the socket)
mysql_root() {
  local container=$1
  shift
  docker exec -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" "$container" mysql -uroot "$@"
}

pass() { echo "PASS  $1"; }
fail() { echo "FAIL  $1"; exit 1; }

[ "$(mysql_root "$REPLICA" -e 'SHOW REPLICA STATUS\G' | grep -cE 'Replica_(IO|SQL)_Running: Yes')" = 2 ] \
  && pass "replica IO and SQL threads are running" \
  || fail "replica threads are not running"

[ "$(mysql_root "$REPLICA" -N -e 'SELECT @@read_only, @@super_read_only')" = "$(printf '1\t1')" ] \
  && pass "replica has read_only and super_read_only enabled" \
  || fail "replica is not read-only"

mysql_tcp "$PRIMARY" "$MYSQL_APP_USER" "$MYSQL_APP_PASSWORD" "
  CREATE TABLE IF NOT EXISTS appdb.replication_test (
    id INT AUTO_INCREMENT PRIMARY KEY,
    message VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  );
  INSERT INTO appdb.replication_test (message) VALUES ('$MARKER');"
pass "app wrote '$MARKER' on primary"

for _ in $(seq 1 10); do
  count=$(mysql_tcp "$REPLICA" "$MYSQL_READER_USER" "$MYSQL_READER_PASSWORD" \
    "SELECT count(*) FROM appdb.replication_test WHERE message = '$MARKER'" 2>/dev/null || echo 0)
  [ "$count" = 1 ] && break
  sleep 1
done
[ "$count" = 1 ] \
  && pass "reader sees the row on replica" \
  || fail "row did not reach the replica within 10s"

if mysql_root "$REPLICA" -e "INSERT INTO appdb.replication_test (message) VALUES ('must-fail')" 2>/dev/null; then
  fail "replica accepted a write from root"
else
  pass "replica rejects writes, even from root (super_read_only)"
fi

echo "All MySQL replication checks passed."

#!/usr/bin/env bash
# No "set -u": the entrypoint sources this file instead of executing it when it is not executable.
set -Eeo pipefail

# Quote a value as a SQL string literal so passwords containing ' or \ cannot break the statement.
sql_quote() {
  local s=${1//'\'/'\\'}
  s=${s//\'/\'\'}
  printf "'%s'" "$s"
}

echo "Waiting for the replication account on ${MYSQL_SOURCE_HOST}..."

# Succeeds only once the primary is up and primary-init.sh has created the account.
until MYSQL_PWD="${MYSQL_REPLICATION_PASSWORD}" mysql \
  --protocol=TCP \
  -h "${MYSQL_SOURCE_HOST}" \
  -u"${MYSQL_REPLICATION_USER}" \
  -e "SELECT 1" >/dev/null 2>&1; do
  sleep 2
done

echo "Configuring replication..."

MYSQL_PWD="${MYSQL_ROOT_PASSWORD}" mysql -uroot <<SQL
CHANGE REPLICATION SOURCE TO
  SOURCE_HOST=$(sql_quote "$MYSQL_SOURCE_HOST"),
  SOURCE_PORT=3306,
  SOURCE_USER=$(sql_quote "$MYSQL_REPLICATION_USER"),
  SOURCE_PASSWORD=$(sql_quote "$MYSQL_REPLICATION_PASSWORD"),
  SOURCE_AUTO_POSITION=1,
  GET_SOURCE_PUBLIC_KEY=1;

START REPLICA;

-- Enabled last so the entrypoint could still create its users; persisted across restarts.
SET PERSIST read_only = ON;
SET PERSIST super_read_only = ON;
SQL

echo "Replica initialization completed."

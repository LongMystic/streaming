#!/usr/bin/env bash
# No "set -u": the entrypoint sources this file instead of executing it when it is not executable.
set -Eeo pipefail

# Quote a value as a SQL string literal so passwords containing ' or \ cannot break the statement.
sql_quote() {
  local s=${1//'\'/'\\'}
  s=${s//\'/\'\'}
  printf "'%s'" "$s"
}

export MYSQL_PWD="${MYSQL_ROOT_PASSWORD}"

mysql -uroot <<SQL
CREATE USER $(sql_quote "$MYSQL_REPLICATION_USER")@'%'
  IDENTIFIED BY $(sql_quote "$MYSQL_REPLICATION_PASSWORD");

GRANT REPLICATION SLAVE ON *.*
  TO $(sql_quote "$MYSQL_REPLICATION_USER")@'%';

CREATE DATABASE appdb;

CREATE USER $(sql_quote "$MYSQL_APP_USER")@'%'
  IDENTIFIED BY $(sql_quote "$MYSQL_APP_PASSWORD");

CREATE USER $(sql_quote "$MYSQL_READER_USER")@'%'
  IDENTIFIED BY $(sql_quote "$MYSQL_READER_PASSWORD");

GRANT ALL PRIVILEGES ON appdb.* TO $(sql_quote "$MYSQL_APP_USER")@'%';
GRANT SELECT ON appdb.* TO $(sql_quote "$MYSQL_READER_USER")@'%';
SQL

unset MYSQL_PWD

echo "Primary initialization completed."

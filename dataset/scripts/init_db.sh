#!/usr/bin/env bash
# Creates the dataset schemas in the running stack and grants access. Safe to re-run.
# Run from the streaming/ folder: bash dataset/scripts/init_db.sh
set -Eeuo pipefail
export MSYS_NO_PATHCONV=1
cd "$(dirname "$0")/../.."

set -a
. ./.env
set +a

CDC_USER="${CDC_USER:-cdc}"
PG_SCHEMAS="ref, product, customer, account, ledger, custody, margin, corp_action, crm, compliance, content"

pg() {
  docker exec -i -e PGPASSWORD="$POSTGRES_PASSWORD" postgres-primary \
    psql -h 127.0.0.1 -U "$POSTGRES_USER" -d appdb -v ON_ERROR_STOP=1 -q "$@"
}
my() {
  docker exec -i -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql-primary mysql -uroot "$@"
}

# --- PostgreSQL: objects are owned by the app user so the generator can write and truncate them.
if [ "$(pg -tAc "SELECT to_regnamespace('ref') IS NOT NULL")" = t ]; then
  echo "PostgreSQL: schemas already exist, skipping DDL"
else
  echo "PostgreSQL: creating schemas in appdb (owner: $POSTGRES_APP_USER)"
  { echo "SET ROLE \"$POSTGRES_APP_USER\";"; cat dataset/ddl/postgres_core.sql; } | pg
fi

pg -v app="$POSTGRES_APP_USER" -v reader="$POSTGRES_READER_USER" -v cdc="$CDC_USER" <<SQL
GRANT USAGE ON SCHEMA $PG_SCHEMAS TO :"reader";
GRANT SELECT ON ALL TABLES IN SCHEMA $PG_SCHEMAS TO :"reader";
ALTER DEFAULT PRIVILEGES FOR ROLE :"app" IN SCHEMA $PG_SCHEMAS GRANT SELECT ON TABLES TO :"reader";

SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'cdc') AS has_cdc \gset
\if :has_cdc
GRANT USAGE ON SCHEMA $PG_SCHEMAS TO :"cdc";
GRANT SELECT ON ALL TABLES IN SCHEMA $PG_SCHEMAS TO :"cdc";
ALTER DEFAULT PRIVILEGES FOR ROLE :"app" IN SCHEMA $PG_SCHEMAS GRANT SELECT ON TABLES TO :"cdc";
\endif

-- Full before-images in Debezium update events for the high-churn snapshot tables.
ALTER TABLE ledger.cash_balances REPLICA IDENTITY FULL;
ALTER TABLE custody.positions REPLICA IDENTITY FULL;
ALTER TABLE margin.loans REPLICA IDENTITY FULL;
SQL
echo "PostgreSQL: grants applied (reader, ${CDC_USER} if it exists)"

# --- MySQL
if [ "$(my -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'oms'")" != 0 ]; then
  echo "MySQL: database oms already exists, skipping DDL"
else
  echo "MySQL: creating database oms"
  my < dataset/ddl/mysql_oms.sql
fi
my <<SQL
GRANT ALL PRIVILEGES ON oms.* TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT ON oms.* TO '${MYSQL_READER_USER}'@'%';
SQL
echo "MySQL: grants applied"

echo "Done. Next: cd dataset/generator && python -m fingen backfill --preset S"

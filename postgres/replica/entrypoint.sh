#!/usr/bin/env bash
set -Eeuo pipefail

export PGDATA="${PGDATA:-/var/lib/postgresql/data/pgdata}"
PRIMARY_PORT="${PRIMARY_PORT:-5432}"
STAGING_DIR="${PGDATA}.tmp"

# Wait until the primary accepts connections
until pg_isready -h "$PRIMARY_HOST" -p "$PRIMARY_PORT"; do
  echo "Waiting for PostgreSQL primary..."
  sleep 2
done

# Bootstrap only when the replica data directory is empty.
if [ ! -s "$PGDATA/PG_VERSION" ]; then
  echo "Initializing replica from primary..."

  export PGPASSWORD="$REPLICATION_PASSWORD"

  # A previous replica (e.g. after "down -v" on the replica only) may have left the slot behind.
  psql -h "$PRIMARY_HOST" -p "$PRIMARY_PORT" -U "$REPLICATION_USER" -d postgres \
    -v ON_ERROR_STOP=1 -v slot="$REPLICATION_SLOT" -qAt >/dev/null <<'SQL'
SELECT pg_drop_replication_slot(slot_name)
FROM pg_replication_slots
WHERE slot_name = :'slot' AND NOT active;
SQL

  # Back up into a staging directory so a failed run never leaves a half-written PGDATA.
  rm -rf "$STAGING_DIR"

  pg_basebackup \
    -h "$PRIMARY_HOST" \
    -p "$PRIMARY_PORT" \
    -U "$REPLICATION_USER" \
    -D "$STAGING_DIR" \
    -C -S "$REPLICATION_SLOT" \
    -R \
    -X stream \
    -P

  unset PGPASSWORD

  rm -rf "$PGDATA"
  mv "$STAGING_DIR" "$PGDATA"

  echo "Replica bootstrap completed."
fi

exec /usr/local/bin/docker-entrypoint.sh postgres -c hba_file=/etc/postgresql/pg_hba.conf

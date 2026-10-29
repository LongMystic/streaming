#!/usr/bin/env bash
# No "set -u": the entrypoint sources this file instead of executing it when it is not executable.
set -Eeo pipefail

psql \
    -v ON_ERROR_STOP=1 \
    --username "$POSTGRES_USER" \
    --dbname postgres \
    -v replication_user="$REPLICATION_USER" \
    -v replication_password="$REPLICATION_PASSWORD" \
    -v app_user="$APP_USER" \
    -v app_password="$APP_PASSWORD" \
    -v reader_user="$READER_USER" \
    -v reader_password="$READER_PASSWORD" << 'SQL'

CREATE ROLE :"replication_user"
    WITH LOGIN REPLICATION
    PASSWORD :'replication_password';

CREATE ROLE :"app_user"
    WITH LOGIN
    PASSWORD :'app_password';

CREATE ROLE :"reader_user"
    WITH LOGIN
    PASSWORD :'reader_password';

CREATE DATABASE appdb OWNER :"app_user";

GRANT CONNECT ON DATABASE appdb TO :"reader_user";

\connect appdb

GRANT USAGE ON SCHEMA public TO :"reader_user";

-- quyền này cho phép reader đọc được các bảng mới do user app tạo thêm, default là không
ALTER DEFAULT PRIVILEGES FOR ROLE :"app_user" IN SCHEMA public
    GRANT SELECT ON TABLES TO :"reader_user";

SQL

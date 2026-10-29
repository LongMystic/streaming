# Streaming lab: PostgreSQL & MySQL primary/replica

Môi trường lab chạy bằng Docker Compose, gồm 2 cặp primary → replica làm nguồn dữ liệu cho phần CDC/Kafka về sau.

| Service | Image | Cổng trên host | Vai trò |
|---|---|---|---|
| `postgres-primary` | `postgres:17.11` | `127.0.0.1:5432` | Primary, nhận ghi |
| `postgres-replica` | `postgres:17.11` | `127.0.0.1:5433` | Streaming replica (physical), chỉ đọc |
| `mysql-primary` | `mysql:8.4.13` | `127.0.0.1:3307` | Source, binlog ROW + GTID |
| `mysql-replica` | `mysql:8.4.13` | `127.0.0.1:3308` | Replica GTID auto-position, `super_read_only` |
| `minio` | `minio/minio` (RELEASE.2025-09-07) | `127.0.0.1:9000` (S3), `127.0.0.1:9001` (console) | Object storage của lakehouse |
| `minio-init` | `minio/minio` | — | Chạy một lần: tạo bucket + access key riêng cho lakehouse |
| `iceberg-rest` | `streaming/iceberg-rest:1.10.1-mysql` (build local) | `127.0.0.1:8181` | Iceberg REST catalog, metastore trên Aiven MySQL |

Mọi service nằm trong network `streaming` với subnet cố định `172.28.0.0/24`. `pg_hba.conf` chỉ cho phép subnet này, nên khi đổi subnet phải sửa cả hai nơi.

## Cấu trúc

```
streaming/
├── docker-compose.yml
├── .env.example                  # mẫu biến môi trường (copy thành .env)
├── postgres/
│   ├── pg_hba.conf               # dùng chung cho primary và replica
│   ├── primary/postgresql.conf
│   ├── init/01-create-users.sh   # tạo replicator, app, reader, appdb (chỉ chạy lần init đầu)
│   ├── replica/entrypoint.sh     # pg_basebackup + replication slot rồi chạy postgres
│   └── test/test_replication.sh
└── mysql/
    ├── init/primary-init.sh      # tạo replicator, app, reader, appdb
    ├── init/replica-init.sh      # CHANGE REPLICATION SOURCE + bật super_read_only
    └── test/test_replication.sh
└── lakehouse/
    ├── minio/init.sh             # bucket warehouse + user lakehouse (policy chỉ trên bucket này)
    ├── iceberg-rest/Dockerfile   # apache/iceberg-rest-fixture + MySQL Connector/J
    └── test/test_iceberg_rest.sh
```

Config của MySQL được truyền qua `command:` thay vì mount `my.cnf`. Trên Docker Desktop for Windows, file bind-mount luôn có quyền `0777`, và MySQL bỏ qua file config world-writable.

## Chạy

```bash
cp .env.example .env      # rồi đổi mật khẩu
docker compose up -d --wait
docker compose ps         # mọi service healthy, riêng minio-init là Exited (0)
```

Healthcheck của replica kiểm tra cả trạng thái replication, không chỉ kiểm tra server còn sống:
- Postgres replica: `pg_stat_wal_receiver.status = 'streaming'`.
- MySQL replica: cả hai thread IO và SQL đều đang chạy.

Vì vậy `healthy` ở replica có nghĩa là replication đang hoạt động.

## Kiểm tra replication

Chạy từ thư mục `streaming/` (Git Bash hoặc WSL):

```bash
bash postgres/test/test_replication.sh
bash mysql/test/test_replication.sh
```

Mỗi script làm 3 việc:
1. Ghi một dòng có marker ngẫu nhiên bằng user `app` trên primary.
2. Đọc lại dòng đó bằng user `reader` trên replica.
3. Xác nhận replica từ chối lệnh ghi (với MySQL, kể cả `root`).

Nếu có bước nào lỗi, script in `FAIL` và trả exit code khác 0.

## Kết nối

| Mục đích | Lệnh |
|---|---|
| psql vào primary | `docker exec -it -e PGPASSWORD=<pw> postgres-primary psql -h 127.0.0.1 -U postgres` |
| mysql root (chỉ có `root@localhost`) | `docker exec -it mysql-primary mysql -uroot -p` |
| Từ máy host (DBeaver, …) | dùng user `app` / `reader` qua `127.0.0.1:<cổng>` |

## Reset (quan trọng)

Script init chỉ chạy khi volume còn trống. Ngoài ra replica phụ thuộc vào trạng thái của primary: Postgres cần replication slot, MySQL cần GTID. Vì vậy luôn reset cả primary lẫn replica cùng lúc:

```bash
docker compose down -v
docker compose up -d --wait
```

Không nên chỉ xoá volume của primary. Replica sẽ trỏ vào một primary đã khác hẳn và replication sẽ hỏng.

Nếu chỉ cần dựng lại replica:
- **Postgres:** xoá volume `postgres-replica-data`. Entrypoint sẽ tự xoá slot cũ (nếu slot không còn active) rồi chạy `pg_basebackup` lại.
- **MySQL:** xoá volume `mysql-replica-data`. Replica dùng GTID auto-position nên sẽ tự kéo lại dữ liệu từ binlog, miễn là binlog trên primary chưa bị xoá (hiện giữ 7 ngày).

## Ghi chú thiết kế

- **Replication slot (Postgres):** replica dùng slot `postgres_replica`, nên primary không xoá WAL khi replica đang offline. `max_slot_wal_keep_size = 1GB` giới hạn lượng WAL được giữ lại. Nếu replica offline lâu hơn mức này, slot bị vô hiệu và replica phải bootstrap lại.
- **Bootstrap an toàn (Postgres):** `pg_basebackup` ghi vào `pgdata.tmp` trước, chỉ đổi tên thành `pgdata` khi thành công. Nhờ vậy một lần chạy lỗi không để lại PGDATA dở dang.
- **`super_read_only` (MySQL):** được bật bằng `SET PERSIST` ở cuối `replica-init.sh`, không đặt trong `command:`. Nếu đặt trong `command:`, entrypoint không tạo được user trong lần init đầu tiên.
- **Mật khẩu trong SQL:** script MySQL escape giá trị bằng `sql_quote`. Script Postgres dùng biến psql (`:'var'`, `:"var"`). Nhờ vậy mật khẩu chứa `'` hoặc `\` không làm hỏng câu lệnh.
- **Script init để trong `docker-entrypoint-initdb.d`:** nếu file không có quyền thực thi, entrypoint sẽ `source` thay vì chạy nó. Vì vậy các script này không dùng `set -u`. `.gitattributes` ép `*.sh` dùng LF.

## Lakehouse: MinIO + Iceberg REST catalog

Chia vai trò:
- **MinIO** giữ toàn bộ file của bảng Iceberg (data Parquet, manifest, `metadata.json`) trong bucket `warehouse`.
- **Iceberg REST catalog** (`iceberg-rest`) là điểm vào duy nhất cho các engine (Spark, Trino, Flink, PyIceberg). Bên trong nó dùng `JdbcCatalog`, chỉ lưu con trỏ "bảng X → file `metadata.json` hiện tại" vào **MySQL trên Aiven** (bảng `iceberg_tables`, `iceberg_namespace_properties` trong DB `ICEBERG_DB_NAME`). Commit của Iceberg là một lệnh UPDATE có điều kiện trên con trỏ này.

Cấu hình qua `.env` (xem `.env.example`):
- `MINIO_ROOT_*`: tài khoản root, chỉ dùng cho console và `minio-init`.
- `LAKEHOUSE_S3_ACCESS_KEY` / `LAKEHOUSE_S3_SECRET_KEY`: key mà `iceberg-rest` và các engine dùng. Policy `lakehouse-rw` chỉ cho đọc/ghi/xoá trong bucket `LAKEHOUSE_BUCKET`.
- `ICEBERG_DB_*`: lấy từ trang Overview của service MySQL trên Aiven. DB `ICEBERG_DB_NAME` được tạo tự động nếu chưa có (`createDatabaseIfNotExist=true`), các bảng catalog được tạo ở lần khởi động đầu.

```bash
docker compose up -d --wait minio minio-init iceberg-rest
bash lakehouse/test/test_iceberg_rest.sh
```

Script test tạo một namespace + bảng tạm qua REST API, kiểm tra file `metadata.json` có trên MinIO và dòng tương ứng trong `iceberg_tables` trên Aiven trỏ đúng file đó, rồi xoá đi.

Kết nối từ engine (trong network `streaming`):

| Thuộc tính | Giá trị |
|---|---|
| Catalog type / URI | `rest`, `http://iceberg-rest:8181` (từ host: `http://127.0.0.1:8181`) |
| Warehouse | `s3://warehouse/` |
| S3 endpoint | `http://minio:9000` (từ host: `http://127.0.0.1:9000`), path-style access, region `us-east-1` |
| S3 credentials | `LAKEHOUSE_S3_ACCESS_KEY` / `LAKEHOUSE_S3_SECRET_KEY` |

REST catalog này không cấp credential cho client (không có credential vending), nên mỗi engine phải tự cấu hình S3 endpoint và key như trên.

Ghi chú:
- **Image MinIO:** MinIO đã ngừng phát hành image chính thức, `minio/minio` không còn pull được. Compose dùng bản `latest` (RELEASE.2025-09-07) còn trong cache Docker của máy này. Máy khác sẽ không pull được, cần đổi sang một bản fork (vd. `pgsty/minio`).
- **Image catalog:** `apache/iceberg-rest-fixture` chỉ đóng gói driver SQLite. `lakehouse/iceberg-rest/Dockerfile` thêm MySQL Connector/J 9.7.0 (có kiểm tra checksum) và chạy server bằng `-cp` thay cho `-jar`, vì `java -jar` bỏ qua classpath bên ngoài.
- **Schema V1:** `CATALOG_JDBC_SCHEMA__VERSION=V1` bật cột `iceberg_type` để lưu được view. Nên giữ nguyên từ đầu, vì bảng catalog chỉ được tạo một lần.
- **Reset:** `docker compose down -v` xoá dữ liệu MinIO nhưng **không** đụng tới Aiven. Khi đó các dòng trong `iceberg_tables` sẽ trỏ tới file không còn tồn tại. Reset sạch thì xoá luôn DB catalog trên Aiven: `DROP DATABASE iceberg_catalog;`.
- **Aiven free tier** tự tắt service nếu lâu không dùng. Nếu `iceberg-rest` lỗi `Communications link failure` lúc khởi động, kiểm tra service trên Aiven console trước.

## Kế hoạch tiếp theo: CDC với Kafka Connect

Mục tiêu: stream thay đổi (insert/update/delete) của `appdb` trên cả hai DB vào Kafka bằng Debezium.

1. **Chuẩn bị nguồn**
   - Postgres: đổi `wal_level = logical`, tạo user `cdc` (`REPLICATION` + `SELECT` trên các bảng cần stream) và một `PUBLICATION`.
   - MySQL: tạo user `cdc` với quyền `SELECT, RELOAD, SHOW DATABASES, REPLICATION SLAVE, REPLICATION CLIENT`. Binlog ROW + GTID đã có sẵn.
2. **Hạ tầng:** thêm `kafka` (KRaft, 1 broker), `kafka-connect` (image Debezium) và `kafka-ui` vào compose, chung network `streaming`.
3. **Connector:** đăng ký 2 connector (Postgres, MySQL) qua REST API của Kafka Connect. File JSON cấu hình đặt trong `connect/`.
4. **Kiểm chứng:** viết script test tương tự hiện tại. Script ghi trên primary, sau đó đọc topic bằng `kafka-console-consumer` hoặc kafka-ui và kiểm tra có đủ event `c`/`u`/`d`.
5. **Vận hành:** theo dõi slot và độ trễ (`pg_replication_slots`, connector status). Thử các tình huống như restart connector, đổi schema bảng, hoặc replica/primary bị tắt.

CDC đọc từ primary. Dùng replica làm nguồn cũng được (Postgres 16+ hỗ trợ logical decoding trên standby, MySQL replica đã bật `log_replica_updates` mặc định), nhưng phức tạp hơn nên để sau.

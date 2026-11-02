# Kế hoạch: cụm observability trên máy Dell

Mục tiêu: một cụm observability (metrics + logs + alert) chạy riêng trên máy Dell, quan sát platform hiện tại (Docker Compose: Postgres/MySQL primary-replica, Kafka, Kafka Connect/Debezium, MinIO, Iceberg REST, Aiven MySQL), và giữ nguyên được khi platform chuyển sang Kubernetes.

## 1. Bối cảnh và giả định

| Máy | Thông số | Vai trò |
|---|---|---|
| Dell | i5-7300U 2C/4T, 16 GB RAM, SSD 256 GB (giả định trống 30 GB), Windows 10 Pro | **Backend observability** |
| Lenovo | trống 150 GB (CPU/RAM chưa rõ) | Platform (Docker, sau là k8s) |

Giả định: platform chạy trên một máy khác Dell (Lenovo hoặc máy hiện tại). Thiết kế bên dưới không phụ thuộc platform nằm ở máy nào, chỉ cần máy đó gọi tới được Dell qua mạng.

## 2. Quyết định kiến trúc

### 2.1 Push từ platform về Dell, không để Dell kéo (pull)

```
┌──────────── Máy platform ────────────┐            ┌──────────── Dell ────────────┐
│ postgres  mysql  kafka  connect      │            │                              │
│ minio  iceberg-rest  (sau: k8s pods) │            │  Prometheus  ◄── remote_write│
│        ▲ scrape / đọc log docker     │   LAN /    │  Loki        ◄── push logs   │
│  ┌─────┴──────┐                      │  Tailscale │  Alertmanager ─► Telegram    │
│  │ Grafana    │──── metrics, logs ───┼───────────►│  Grafana (UI, :3000)         │
│  │ Alloy      │                      │            │                              │
│  └────────────┘                      │            │                              │
└──────────────────────────────────────┘            └──────────────────────────────┘
```

- Agent (**Grafana Alloy**) chạy cạnh platform: scrape exporter trong network nội bộ, đọc log container, rồi **đẩy** về Dell.
- Chỉ Dell cần mở cổng inbound (Prometheus remote-write, Loki push). Máy platform không phải publish cổng exporter ra LAN.
- **Đây là điểm giúp migrate k8s dễ:** khi lên k8s, backend trên Dell giữ nguyên. Chỉ thay agent Docker bằng Alloy chạy trong cluster (Helm chart `k8s-monitoring`), đẩy về đúng các endpoint cũ.
- Backend nằm ngoài hệ thống bị quan sát: platform sập hoặc hết RAM thì vẫn xem được metric và log của lúc sập.

### 2.2 Chọn thành phần

| Vai trò | Chọn | Lý do / phương án bỏ |
|---|---|---|
| Metrics store | **Prometheus** (bật `--web.enable-remote-write-receiver`) | Chuẩn chung với k8s (PrometheusRule, dashboard cộng đồng). Lượng series của lab nhỏ, 15 ngày chỉ vài GB. Nếu disk căng thì VictoriaMetrics single-node là phương án thay thế (nhận remote_write, API tương thích, tốn ít disk hơn). |
| Logs | **Loki** single binary, lưu filesystem | Rẻ RAM, query bằng label giống Prometheus. Không dùng ELK: Elasticsearch cần ≥ 4 GB heap, không hợp máy 2 core. |
| Agent | **Grafana Alloy** | Một agent làm cả metrics và logs, có sẵn exporter Postgres/MySQL/Kafka/blackbox/cAdvisor, và đọc được ServiceMonitor khi lên k8s. Promtail đã hết hỗ trợ (EOL 3/2026) nên không dùng. |
| Alert | **Prometheus rules + Alertmanager** → Telegram | Rule viết dạng file, lên k8s chuyển thẳng thành `PrometheusRule`. Grafana-managed alert tiện hơn nhưng khó quản lý bằng code. |
| UI | **Grafana** | Datasource và dashboard provisioning bằng file trong repo. |
| Traces | **Tempo**, *để sau* (Phase 6) | Hiện chưa có service tự viết nào phát trace. Bật khi có app (Spark job, LLM agent…) instrument OpenTelemetry. |

### 2.3 Quy ước label (quyết định ngay từ đầu)

Đặt label sao cho cùng một dashboard và alert chạy được cho cả Docker lẫn k8s:

| Label | Docker | k8s |
|---|---|---|
| `cluster` | `docker-lab` | `k8s-lab` |
| `namespace` | tên compose project (`streaming`) | namespace |
| `service` | `com.docker.compose.service` (`kafka`, `mysql-primary`…) | label `app.kubernetes.io/name` |
| `component` | đặt tay: `kafka`, `postgres`, `mysql`, `minio`, `iceberg-catalog`, `cdc` | giống Docker |
| `env` | `lab` | `lab` |

Alloy gắn `cluster` / `env` qua `external_labels` và relabel `namespace` / `service` từ docker labels. Dashboard luôn có biến `cluster`, nên trong lúc migrate có thể so Docker với k8s cạnh nhau.

## 3. Chuẩn bị máy Dell (Phase 0)

### 3.1 Hệ điều hành: khuyến nghị cài Ubuntu Server 24.04 LTS

Windows 10 đã hết hỗ trợ (14/10/2025). Máy Dell chỉ có 2 core, nên Windows + WSL2 + Docker Desktop tốn khoảng 2–3 GB RAM và một phần CPU chỉ để chạy lớp ảo hoá.

| Phương án | Ưu | Nhược |
|---|---|---|
| **A. Cài Ubuntu Server (xoá Windows)** — khuyến nghị | Dùng trọn 256 GB disk và 16 GB RAM. Docker Engine chạy native, cổng mở thẳng ra LAN. systemd tự khởi động lại sau khi mất điện. | Mất Windows trên máy này. |
| B. Giữ Windows 10, dùng Docker Desktop (WSL2) | Không phải cài lại máy. | Chỉ còn 30 GB disk. File VHDX của WSL không tự co lại. Mỗi container phải đi qua NAT của WSL. Phải đăng nhập Windows thì Docker mới chạy. Docker Desktop có thể ngừng hỗ trợ Win10. |

Nếu chọn B:
- Tạo `%UserProfile%\.wslconfig` với `memory=10GB`, `processors=4`, `swap=4GB`.
- Bật "Start Docker Desktop when you sign in" và cho Windows tự đăng nhập.
- Tắt sleep/hibernate khi cắm sạc.

### 3.2 Mạng giữa hai máy

- **Cùng LAN:** đặt IP tĩnh (hoặc DHCP reservation trên router) cho Dell, ví dụ `192.168.1.50`.
- **Khác mạng** (máy platform mang lên công ty): dùng Tailscale. Dell có tên cố định dạng `dell-obs.<tailnet>.ts.net`, không cần mở port trên router. Kiểm tra chính sách công ty trước khi cài Tailscale lên máy làm việc.
- Cổng Dell mở cho máy platform:
  - `9090`: Prometheus remote_write + query
  - `3100`: Loki push
  - `3000`: Grafana
  - `9093`: Alertmanager, chỉ mở khi cần xem UI
  - Chặn mọi nguồn khác bằng `ufw` (phương án A) hoặc Windows Firewall (phương án B), chỉ cho phép IP máy platform / dải Tailscale.

### 3.3 Ngân sách tài nguyên trên Dell

| Thành phần | RAM | Disk (giới hạn cứng) |
|---|---|---|
| Prometheus (retention 15 ngày) | 1–1.5 GB | `--storage.tsdb.retention.size=8GB` |
| Loki (retention 7 ngày) | 0.5–1 GB | khoảng 6 GB, compactor xoá log quá hạn |
| Grafana | 0.2 GB | < 0.5 GB |
| Alertmanager + node_exporter + Alloy (tự giám sát Dell) | 0.3 GB | — |
| Docker images | — | khoảng 2 GB |
| *Tempo (Phase 6)* | *0.5 GB* | *3 GB* |
| **Tổng** | **khoảng 3–4 GB** | **khoảng 17–20 GB** |

Với giả định 30 GB trống thì vừa đủ, còn khoảng 10 GB dự phòng. Retention phải luôn có **giới hạn theo dung lượng**, không chỉ theo thời gian. Phải có alert khi disk Dell vượt 80%.

**Xong khi:** từ máy platform gọi `curl http://<dell>:9090/-/ready` và `curl http://<dell>:3100/ready` đều trả về OK.

## 4. Các phase triển khai

Ước lượng theo buổi (khoảng 2–3 giờ một buổi).

### Phase 1 — Backend trên Dell (1–2 buổi)

1. Viết `observability/backend/docker-compose.yml` gồm Prometheus, Loki, Alertmanager, Grafana, node_exporter (hoặc Alloy) để Dell tự giám sát chính nó. Pin version image cụ thể, mỗi service có volume riêng và có healthcheck.
2. Viết config Prometheus:
   - Bật remote-write receiver.
   - Retention 15 ngày / 8 GB.
   - Scrape chính Prometheus, Loki, Alertmanager, Grafana và node_exporter của Dell.
3. Viết config Loki:
   - Schema `v13` + `tsdb`, lưu filesystem.
   - `retention_period: 168h`, bật `compactor.retention_enabled`.
   - `ingestion_rate_mb` vừa phải để log bùng không làm đầy disk.
4. Provisioning Grafana bằng file:
   - Datasource Prometheus, Loki, Alertmanager.
   - Thư mục dashboard nạp từ `grafana/dashboards/*.json`.
   - Mật khẩu admin lấy từ `.env`.
5. Đặt `restart: unless-stopped` cho mọi service.

**Xong khi:** Grafana hiện dashboard *Node Exporter Full* (ID 1860) của Dell. Tab Explore → Loki đọc được log của chính các container obs. Restart máy Dell xong mọi thứ tự lên lại.

### Phase 2 — Agent trên máy platform: host, container, log (1 buổi)

1. Thêm service `alloy` vào `streaming/docker-compose.yml` (chung network `streaming`), mount:
   - `/var/run/docker.sock`
   - `/sys`, `/proc` của VM Docker (cho cAdvisor / unix exporter)
   - `observability/agent-docker/config.alloy`
2. Viết `config.alloy`:
   - `prometheus.exporter.unix` + `prometheus.exporter.cadvisor` → `prometheus.remote_write` tới `http://<dell>:9090/api/v1/write`
   - `discovery.docker` + `loki.source.docker` → `loki.write` tới `http://<dell>:3100/loki/api/v1/push`
   - Relabel theo quy ước ở mục 2.3, `external_labels { cluster="docker-lab", env="lab" }`
   - Tách level (`ERROR` / `WARN`) từ log thành label có số giá trị thấp. Không đưa id request, user… vào label.
3. Trên Docker Desktop (Windows), cAdvisor đôi khi không đọc được đủ cgroup. Nếu thiếu metric thì xác nhận lại và ghi chú vào README.

**Xong khi:** dashboard container (CPU, RAM, restart) hiện đủ các container của `streaming`. Lọc log trong Loki được theo `{service="kafka-connect"}`. Tắt mạng tới Dell 5 phút rồi bật lại, metric được đẩy bù (WAL của Alloy) và log không mất.

### Phase 3 — Exporter cho từng thành phần + dashboard (2–3 buổi)

| Thành phần | Cách lấy metric | Metric quan trọng nhất cho lab CDC |
|---|---|---|
| Postgres primary/replica | `prometheus.exporter.postgres` trong Alloy, user riêng có `pg_monitor` | `pg_up`, độ trễ replica, **WAL bị giữ lại bởi replication slot** (slot của Debezium bị inactive sẽ làm đầy disk) |
| MySQL primary/replica | `prometheus.exporter.mysql`, user riêng có `PROCESS, REPLICATION CLIENT, SELECT` | `mysql_up`, thread IO/SQL của replica, seconds behind source, dung lượng binlog |
| Kafka broker | JMX exporter javaagent (mount jar, `KAFKA_OPTS=-javaagent:...`) | broker up, offline partitions, request rate, disk log size |
| Consumer lag | `prometheus.exporter.kafka` trong Alloy | lag theo consumer group (sink connector, Flink/Spark về sau) |
| Kafka Connect / Debezium | JMX exporter javaagent trên `kafka-connect` (`KAFKA_OPTS`) | `connector-failed-task-count`, trạng thái connector, Debezium `MilliSecondsBehindSource`, `Connected` |
| MinIO | endpoint có sẵn `/minio/v2/metrics/cluster` (`MINIO_PROMETHEUS_AUTH_TYPE=public` trong lab) | up, dung lượng bucket, lỗi S3 |
| Iceberg REST | không có metric, dùng `prometheus.exporter.blackbox` gọi HTTP `/v1/config` | probe success, latency |
| Aiven MySQL (metastore) | blackbox TCP probe tới host:port | reachable (Aiven free tự tắt service khi không dùng) |

Dashboard (import rồi lưu JSON vào repo để provisioning):
- Node Exporter Full (1860)
- PostgreSQL (9628)
- MySQL Overview (7362)
- Kafka Exporter Overview (7589)
- MinIO (13502)
- Thêm một dashboard tự viết **"CDC pipeline"**: trên một màn hình hiện slot lag Postgres, binlog/replica MySQL, trạng thái connector, `MilliSecondsBehindSource`, lag topic.

Kiểm tra lại ID dashboard trên grafana.com trước khi import, vì một số dashboard đổi metric theo version exporter.

**Xong khi:** mọi panel có số liệu. Dừng `kafka-connect` 2 phút thì thấy `MilliSecondsBehindSource` và WAL slot tăng lên rồi hạ xuống sau khi bật lại.

### Phase 4 — Alerting (1 buổi)

1. Tạo bot Telegram và cấu hình receiver trong Alertmanager. Đặt `group_by: [alertname, cluster, service]` và `repeat_interval: 4h`.
2. Rule file `observability/backend/prometheus/rules/*.yml`, mỗi nhóm một file:
   - **Platform:** target down > 2 phút, container restart lặp lại, RAM container > 90% limit.
   - **Replication/CDC:** replica Postgres/MySQL không streaming, slot giữ WAL > 1 GB, connector có task failed, `MilliSecondsBehindSource` > 5 phút.
   - **Storage/catalog:** probe Iceberg REST hoặc Aiven fail > 5 phút.
   - **Obs tự giám sát:** disk Dell > 80%, Prometheus remote-write lỗi, Loki ingest bị giới hạn, Alloy ngừng đẩy (`absent()` trên metric của agent). Alert này cực kỳ quan trọng: agent chết thì mọi alert khác im lặng.
3. Thêm `promtool check rules` vào một script test, tương tự `test_replication.sh`.

**Xong khi:** từng tình huống sau đều sinh đúng một tin Telegram, rồi gửi tiếp tin resolved:
- dừng `mysql-replica`
- pause connector Debezium
- tắt Alloy

### Phase 5 — Vận hành và độ bền (0.5 buổi)

- Backup: thư mục provisioning đã nằm trong git. Volume Grafana chỉ chứa thứ tạo bằng tay, nên khuyến khích export ra JSON và commit lại.
- Viết runbook ngắn trong README: cách thêm target, cách xoá dữ liệu khi disk đầy, cách đổi IP Dell.
- Thử mất điện Dell: bật lại thì stack tự lên, Alloy đẩy bù phần dữ liệu còn trong WAL.

### Phase 6 (tuỳ chọn) — Traces và độ tươi dữ liệu

- Thêm Tempo vào backend, Alloy nhận OTLP (4317/4318) rồi forward về Dell. Instrument job Spark/Flink hoặc app Python bằng OpenTelemetry.
- Metric **độ tươi dữ liệu**: script/job định kỳ đọc snapshot mới nhất của từng bảng Iceberg qua REST catalog, đẩy `iceberg_table_last_commit_timestamp`. Alert khi bảng CDC không có commit mới quá N phút. Alert này đo được cả pipeline từ đầu đến cuối, điều mà các metric hạ tầng không làm được.

### Phase 7 — Khi platform chuyển sang Kubernetes (2–3 buổi)

1. **Giữ nguyên backend trên Dell.** Không đưa obs vào cùng cluster.
2. Cài Helm chart `grafana/k8s-monitoring` vào cluster:
   - Destination là Prometheus và Loki trên Dell.
   - `cluster.name=k8s-lab`.
   - Bật kube-state-metrics, node-exporter, kubelet/cAdvisor, thu log pod, thu event k8s.
3. Thành phần stateful dùng operator. Mỗi operator có metric sẵn, Alloy đọc qua `ServiceMonitor` / `PodMonitor`, không cần cài Prometheus Operator trong cluster:

   | Thành phần | Operator |
   |---|---|
   | Kafka + Connect | Strimzi (JMX exporter + kafka-exporter khai báo trong CR) |
   | Postgres | CloudNativePG (PodMonitor có sẵn) |
   | MySQL | Percona Operator hoặc MySQL Operator |
   | MinIO | chart/operator có ServiceMonitor |

4. Chuyển rule sang chạy cho cả hai cluster. Expression đã dùng label chung nên phần lớn giữ nguyên. Bổ sung rule riêng cho k8s: pod CrashLoopBackOff, PVC sắp đầy, node NotReady.
5. **Chạy song song:** Docker (`cluster=docker-lab`) và k8s (`cluster=k8s-lab`) cùng đẩy về Dell. So dashboard cạnh nhau, rồi tắt agent Docker khi đã cutover.
6. (Chỉ để học) Nếu muốn tập triển khai LGTM bằng Helm thì dựng k3s single-node *trên Lenovo* hoặc trong cluster lab, không dựng trên Dell: 2 core không đủ cho control plane cộng với obs.

## 5. Cấu trúc thư mục dự kiến

```
streaming/observability/
├── PLAN.md                      # file này
├── backend/                     # chạy trên Dell
│   ├── docker-compose.yml
│   ├── .env.example             # mật khẩu Grafana, token Telegram
│   ├── prometheus/prometheus.yml
│   ├── prometheus/rules/{platform,cdc,storage,meta}.yml
│   ├── alertmanager/alertmanager.yml
│   ├── loki/loki.yml
│   └── grafana/provisioning/{datasources,dashboards}/ + dashboards/*.json
├── agent-docker/
│   ├── config.alloy             # service `alloy` trong streaming/docker-compose.yml
│   └── jmx/kafka.yml, connect.yml   # rule cho JMX exporter
├── agent-k8s/values.yaml        # Phase 7
└── test/                        # kiểm tra rule + kịch bản kích hoạt alert
```

## 6. Thứ tự ưu tiên nếu ít thời gian

Phase 0 → 1 → 2 → (Postgres slot + Debezium trong Phase 3) → 4. Đây là phần nhỏ nhất vẫn bắt được sự cố đặc trưng của CDC: slot giữ WAL làm đầy disk, connector chết âm thầm, replica ngừng chạy. Các phần còn lại làm dần.

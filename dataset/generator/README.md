# fingen: nguồn sự kiện cho các luồng streaming

`fingen` mô phỏng hoạt động của một công ty chứng khoán (thiết kế ở [../README.md](../README.md)). Nó có 3 đầu ra:

1. Ghi vào **Postgres `appdb`** (core / back-office) và **MySQL `oms`** (giao dịch). Debezium biến các thay đổi này thành topic Kafka.
2. Bắn thẳng vào **Kafka** các luồng không đi qua DB: `marketdata.ticks` và `app.clickstream`. Chỉ có ở chế độ `live`.
3. Ghi **ground truth** ra file. Đây là những gì chỉ simulator biết, dùng để đối soát output của pipeline.

README này viết cho người xây pipeline phía sau ([consumers/PLAN.md](../../consumers/PLAN.md)): topic nào có gì, thời gian hiểu thế nào, kịch bản nào để test, và cách reset.

## 1. Chuẩn bị (một lần, đúng thứ tự)

Chạy từ thư mục `streaming/`:

```bash
bash dataset/scripts/init_db.sh                    # tạo schema, cấp quyền app/reader/cdc, REPLICA IDENTITY FULL; chạy lại được
cd dataset/generator
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt        # Linux/WSL: .venv/bin/python
```

**Cập nhật connector trước khi backfill.** Nội dung cụ thể ở [PLAN mục 1.1](../../consumers/PLAN.md#11-nạp-dataset-đúng-thứ-tự): thêm `oms` vào MySQL, `decimal.handling.mode=string`, JSON không kèm schema, 3 partition. Backfill đẩy khoảng 3 triệu thay đổi qua CDC. Nếu connector chưa đúng cấu hình lúc đó, sẽ phải reset toàn bộ (mục 8).

Kết nối lấy từ `streaming/.env` (user `app`). Có thể ghi đè bằng `GEN_PG_HOST/PORT/DB/USER/PASSWORD`, `GEN_MYSQL_*`, `GEN_KAFKA_BOOTSTRAP` (mặc định `localhost:9094`).

## 2. Hai chế độ chạy

```bash
.venv/Scripts/python -m fingen backfill --preset S             # lịch sử 04-06/2025, khoảng 5 phút
.venv/Scripts/python -m fingen live --speed 60                 # chạy tiếp từ 01/07/2025; Ctrl+C để dừng
.venv/Scripts/python -m fingen live --speed 600 --duration 120 # chạy thử 2 phút rồi tự dừng
.venv/Scripts/python -m fingen reset                           # TRUNCATE các bảng dataset (xem mục 8 trước khi dùng)
```

| | `backfill` | `live` |
|---|---|---|
| Cách ghi | Theo lô: mỗi ngày mô phỏng ghi một lần lúc 23:59:59 | Từng thay đổi, đúng thứ tự, commit khoảng 0,2 giây một lần |
| CDC thấy gì | **Trạng thái cuối ngày** của mỗi dòng. Ví dụ một lệnh chỉ xuất hiện một lần với trạng thái cuối, không có NEW → PARTIALLY_FILLED | **Mọi trạng thái trung gian**: lệnh trung bình khoảng 3 phiên bản; tiền đi từ phong toả sang chờ thanh toán T+2 rồi đã thanh toán |
| Nhịp đến Kafka | Cả ngày dữ liệu đến cùng lúc (theo thời gian thật) | Đều theo đồng hồ mô phỏng |
| `marketdata.ticks`, `app.clickstream` | Không có | Có |
| Dùng cho | Nạp lịch sử, bronze, huấn luyện ML | Phát triển và demo pipeline real-time, đo độ trễ |

**Đồng hồ trong `live`:**
- Simulator chạy tiếp ngày giao dịch sau ngày cuối của backfill. Timestamp vẫn là năm 2025, không phải giờ hiện tại.
- Các khoảng không có sự kiện dài hơn 10 phút mô phỏng (đêm, nghỉ trưa) được tự động bỏ qua.
- Thời gian thật để chạy hết phiên khớp lệnh (09:00–14:45):

| `--speed` | Thời gian thật cho phiên khớp lệnh |
|---|---|
| 1 | 5 giờ 45 phút |
| 10 | khoảng 35 phút |
| 60 | khoảng 6 phút |
| 600 | khoảng 35 giây |

**State:** `backfill` lưu state vào `output/state.pkl`, và `live` nạp state đó để chạy tiếp. Mỗi lần dừng, `live` lưu lại state. `live` chỉ chạy khi DB khớp **chính xác** với state; nếu không khớp thì phải reset rồi backfill lại.

## 3. Bản đồ sự kiện

Lưu lượng ghi trong bảng là trung bình mỗi ngày giao dịch của preset `S`, đo từ một lần backfill.

**Kiểu ghi:**
- **insert**: chỉ thêm dòng mới.
- **vòng đời**: một dòng được update qua nhiều trạng thái.
- **snapshot**: trạng thái hiện tại, bị update liên tục.

### MySQL `oms` (topic `mysql.oms.<bảng>`)

| Topic | Key | Kiểu ghi | Event time | Lưu lượng/ngày | Dùng ở |
|---|---|---|---|---|---|
| `orders` | `order_id` | vòng đời: `PENDING_NEW → NEW → PARTIALLY_FILLED → FILLED / CANCELLED / EXPIRED / REJECTED` | `created_at`, `updated_at` | ~4.000 lệnh | P2 silver, P3 feature |
| `order_events` | `order_event_id` | insert | `event_time` | ~13.600 | P2 CEP spoofing, P3 |
| `executions` | `execution_id` | insert | `matched_at` | ~4.400 | Cả 3 (đối chứng), P2 làm giàu |
| `client_sessions` | `session_id` | insert (`logout_at` tính sẵn) | `login_at` | vài nghìn | P3 feature thiết bị |
| `watchlists`, `watchlist_items` | id / (`watchlist_id`, `instrument_id`, `added_at`) | insert | `created_at`, `added_at` | ít | Gợi ý sản phẩm (sau này) |

### Postgres `appdb` (topic `pg.<schema>.<bảng>`)

| Topic | Key | Kiểu ghi | Event time | Lưu lượng/ngày | Dùng ở |
|---|---|---|---|---|---|
| `ledger.cash_balances` | `account_id` | **snapshot**, update mỗi khi đặt lệnh, khớp, thanh toán, nạp/rút | `updated_at` | rất nhiều update | P1, P2 |
| `ledger.cash_transactions` | `cash_txn_id` | insert, `balance_after` luỹ kế | `created_at` (ngày nghiệp vụ: `value_date`) | ~12.600 | P3 |
| `custody.positions` | (`account_id`, `instrument_id`) | **snapshot** | `updated_at` | rất nhiều update | P1, P2 |
| `custody.position_movements` | `movement_id` | insert | `created_at` | ~4.400 | P3 |
| `custody.settlement_instructions` | `settlement_id` | vòng đời: `PENDING` (lúc khớp) → `SETTLED` (T+2, 08:30) | `created_at`, `settled_at` | ~4.400 tạo + ~4.400 cập nhật | P3 |
| `margin.loans` | `loan_id` | vòng đời: `ACTIVE → REPAID / OVERDUE` | `disbursed_at`, `updated_at` | ~660 khoản mới | P1, P2 |
| `margin.margin_calls` | `margin_call_id` | vòng đời: `OPEN → MET_* / FORCE_SOLD` | `call_date` (15:00) | gần 0, tập trung trong đợt điều chỉnh | Kiểm chứng P1 |
| `margin.interest_accruals` | (`loan_id`, `accrual_date`) | insert | `accrual_date` | 1 dòng / khoản vay đang mở | |
| `product.eod_prices` | (`instrument_id`, `trade_date`) | insert lúc 15:00 | `trade_date` | ~150 | Giá dự phòng cho P1 |
| `product.instruments`, `account.accounts`, `customer.customers`, `margin.loan_products` | id | gần như tĩnh | — | ít | Bảng chiều |
| `compliance.aml_alerts` | `alert_id` | vòng đời: `OPEN → CLOSED` + `disposition` | `alert_date` (rule chạy 23:00) | ~6 | So sánh với P2/P3 |
| `corp_action.events`, `corp_action.entitlements` | id | vòng đời | các ngày GDKHQ, chốt quyền, thanh toán | theo sự kiện | Giải thích giá giảm ở ngày GDKHQ |
| `crm.*`, `content.*` | id | insert / vòng đời | `opened_at`, `published_at` | vài chục | Bài toán LLM, không phải trọng tâm streaming |

### Kafka trực tiếp (chỉ khi chạy `live`)

| Topic | Key | Nội dung | Lưu lượng |
|---|---|---|---|
| `marketdata.ticks` | `symbol` | Một tick cho mỗi mã đang giao dịch, mỗi phút khớp liên tục (giây 59,9) | khoảng 140 mã × 225 phút ≈ 31.000/ngày |
| `app.clickstream` | `customer_id` | `VIEW_SYMBOL` các mã trong watchlist khi khách đăng nhập | theo số lần đăng nhập |

```json
{"symbol": "ZTC", "instrument_id": 1, "exchange": "HOSE", "price": 25350, "reference_price": 25100,
 "ceiling_price": 26850, "floor_price": 23350, "volume": 41200, "event_time": "2025-07-01T03:12:59.900000+00:00"}
{"event_type": "VIEW_SYMBOL", "customer_id": 1234, "session_id": 99881, "symbol": "ZAB",
 "event_time": "2025-07-01T02:05:11.300000+00:00"}
```

Giá trong tick lấy từ cùng đường giá mà simulator dùng để khớp lệnh. Vì vậy tick và `executions` nhất quán với nhau. `volume` là khối lượng toàn thị trường được mô phỏng, không phải tổng các lệnh của khách công ty.

## 4. Thời gian và thứ tự

- **Event time là cột nghiệp vụ** trong bảng ở mục 3. **Đừng dùng `source.ts_ms` của Debezium**, vì nó là thời điểm commit thật. Khi backfill, một ngày mô phỏng được commit trong vài giây.
- **Mọi timestamp đều là UTC.** Ngày nghiệp vụ (`trade_date`, `value_date`) theo giờ Việt Nam (UTC+7). Phiên 09:00–14:45 giờ Việt Nam tương ứng 02:00–07:45 UTC.
- **Lịch trong ngày (giờ Việt Nam):**
  - 07:00–08:50: tin tức.
  - 08:00: xử lý quyền cổ đông.
  - 08:15: thu lãi margin, vào ngày đầu tháng.
  - 08:30: thanh toán T+2.
  - 09:00–14:45: lệnh và khớp lệnh.
  - 15:00: chốt phiên, gồm lệnh hết hạn, `eod_prices`, lãi vay, margin call.
  - 16:00–18:59: báo cáo phân tích, BCTC.
  - Đến 21:59: CSKH, đăng nhập.
  - 23:00: rule AML.
- **Thứ tự:**
  - Trong một khoá, các thay đổi đến theo đúng thứ tự xảy ra (cùng partition).
  - Giữa các bảng khác nhau thì không có đảm bảo. Ví dụ `executions` có thể đến trước bản cập nhật `orders` tương ứng.
  - Khi cần loại bản cũ, so cột `version` (có ở `orders`, `cash_balances`, `positions`, `loans`).
- **Generator không tự tạo dữ liệu trễ hay sai thứ tự.** Muốn test watermark và late data thì cần một injector riêng (PLAN mục 5).
- **Thiếu tick khi backfill:** backfill không có tick. Pipeline cần giá trong backfill thì dùng `eod_prices`, hoặc giá của chính các lần khớp lệnh.

## 5. Envelope Debezium và kiểu dữ liệu

Bảng chuyển kiểu (decimal thành chuỗi, `DATETIME(6)` thành epoch micro giây, `date` thành số ngày…) nằm ở [PLAN mục 1.2](../../consumers/PLAN.md#12-hợp-đồng-dữ-liệu). Một số đặc điểm riêng của dataset:

- **Không có delete nghiệp vụ.** Mọi "xoá" đều là đổi trạng thái (`CANCELLED`, `REPAID`, `CLOSED`, `removed_at`). Event `op=d` chỉ xuất hiện khi reset.
- **`TRUNCATE` (lệnh `reset`) không đi qua CDC như một delete.** Debezium Postgres mặc định bỏ qua truncate; với MySQL, `TRUNCATE` là DDL. Hệ quả ở mục 8.
- **Cột JSON:** `compliance.aml_alerts.details` là `jsonb`. Trong message, nó là một chuỗi JSON lồng bên trong.

## 6. Kịch bản có sẵn để test pipeline

Ngày cụ thể của từng kịch bản nằm trong `output/ground_truth/injected_patterns.parquet`. Bộ ngày cố định nếu giữ `--seed 42`.

| Kịch bản | Dấu hiệu trong dữ liệu | Test cho |
|---|---|---|
| `MARKET_CORRECTION` | 3–5 phiên liên tiếp thị trường giảm 2,5–5,5% mỗi phiên | P1: tài khoản margin rơi xuống dưới ngưỡng duy trì, sinh `margin_calls`, có cả `FORCE_SOLD` (lệnh bán có `order_events.source = 'SYSTEM'`) |
| `SPOOFING` | 25–40 lệnh mua lớn đặt xa giá, huỷ sau 1–4,5 giây, trong 3 ngày | P2: CEP; so với rule `SPOOFING` cuối ngày |
| `WASH_TRADE_RING` | 4–6 khách dùng chung một thiết bị/IP, mua bán đối ứng cùng mã trong vài phút | P2/P3: join `client_sessions` × `executions` |
| `STRUCTURING` | 3–5 lần nạp tiền 250–300 triệu trong một ngày; một ngày cố ý chỉ 2 lần để lọt rule | P3: feature nạp tiền; đo số ca rule bỏ sót |
| `RAPID_IN_OUT` | Nạp 0,5–3 tỷ, hôm sau rút 95–100%, không giao dịch | P3 |
| Churn (`customer_hidden_profile.churn_date`) | Hoạt động giảm còn khoảng 2%, rút gần hết tiền, có thể có ticket khiếu nại trước đó | P3 + ML |
| Quyền cổ đông (`corp_action.events`) | Giá tham chiếu bị điều chỉnh vào ngày GDKHQ; cổ tức tiền/cổ phiếu vào tài khoản ngày thanh toán | P1: giá trị danh mục giảm nhưng không phải lỗ thật |
| T+2 | `receivable_amount` → `available_amount` lúc 08:30 ngày T+2 | P1/P2: số dư thay đổi không do lệnh trong ngày |

## 7. Ground truth và đối soát

Các file trong `output/ground_truth/`:

| File | Nội dung |
|---|---|
| `customer_hidden_profile.parquet` | Phân khúc thật, tần suất đặt lệnh, ngày churn, loại gian lận, nhóm gian lận |
| `injected_patterns.parquet` | Các kịch bản ở mục 6 và đợt điều chỉnh thị trường |
| `news_sentiment_truth.parquet` | Sentiment thật và cú sốc giá thật của từng tin tức |
| `disclosure_extraction_truth.parquet` | Giá trị đúng của từng văn bản công bố thông tin |
| `margin_call_context.parquet` | Bối cảnh của từng margin call |
| `rag_qa.jsonl` | Câu hỏi và đáp án cho knowledge base |

"Sự thật" để đối soát bài `trade_stats_1m` (PLAN mục 1.5), chạy trên MySQL:

```sql
SELECT symbol,
       DATE_FORMAT(matched_at, '%Y-%m-%d %H:%i:00') AS window_start_utc,
       COUNT(*)              AS trade_count,
       SUM(matched_quantity) AS volume,
       SUM(matched_value)    AS value,
       ROUND(SUM(matched_value) / SUM(matched_quantity), 4) AS vwap,
       MAX(matched_price)    AS high,
       MIN(matched_price)    AS low
FROM oms.executions
WHERE trade_date = '2025-06-16'
GROUP BY symbol, window_start_utc;
```

Các bất biến mà dữ liệu nguồn luôn thoả. Có thể dùng làm phép kiểm tra cho bảng silver:
- **Sổ cái tiền:** `cash_transactions.balance_after` bằng tổng luỹ kế `amount` theo tài khoản. Dòng cuối bằng `available + blocked + payable` của `cash_balances`.
- **Vị thế:** `total = available + receiving + blocked + pledged`. `total` bằng tổng `position_movements` cộng các lệnh đang chờ thanh toán (`PENDING`).
- **Lệnh:** `orders.filled_quantity` bằng tổng `executions.matched_quantity` của lệnh đó.

## 8. Reset và phát lại toàn bộ

`fingen reset` chỉ xoá **DB**. Kafka, Iceberg và state của các engine vẫn giữ dữ liệu cũ, còn connector thì không phát event xoá. Làm đủ các bước sau:

1. **Dừng pipeline:** `docker compose --profile kstreams --profile flink --profile spark stop`.
2. **Dừng generator** nếu đang chạy `live`, rồi chạy `python -m fingen reset`.
3. **Xoá connector và offset của nó.** Nếu chỉ xoá connector, offset vẫn nằm trong `connect_offsets`, và đăng ký lại cùng tên sẽ đọc tiếp từ vị trí cũ:

   ```bash
   for c in postgres-appdb mysql-appdb; do
     curl -s -X PUT    localhost:8083/connectors/$c/stop
     curl -s -X DELETE localhost:8083/connectors/$c/offsets
     curl -s -X DELETE localhost:8083/connectors/$c
   done
   ```

   Sau đó xoá replication slot trên Postgres: `SELECT pg_drop_replication_slot('debezium_appdb');`.
4. **Xoá topic:**

   ```bash
   docker exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --delete \
     --topic 'pg\..*|mysql\..*|schema-history\..*|marketdata\..*|app\..*|risk\..*|surveillance\..*|.*trade_stats_1m'
   ```

5. **Xoá state của các engine:**
   - Kafka Streams: `kafka-streams-application-reset --application-id risk-service`, rồi xoá `state.dir`.
   - Flink: cancel job, xoá checkpoint và savepoint.
   - Spark: xoá thư mục checkpoint `s3://warehouse/_checkpoints/...`.
6. **Xoá dữ liệu Iceberg:** drop các bảng trong `bronze`, `silver`, `gold`.
7. **Dựng lại:** đăng ký lại connector, rồi chạy backfill.

Nếu chỉ cần thêm dữ liệu, cứ chạy tiếp `live`. Không cần reset gì.

## 9. Giới hạn cần biết khi xây pipeline

- **Khớp lệnh:** không có sổ lệnh. Lệnh được khớp dựa trên đường giá do simulator sinh ra; giá khớp và khối lượng thị trường cũng là mô phỏng.
- **Khoản vay margin:** mỗi lần giải ngân là một dòng `margin.loans` riêng, nên dư nợ phải cộng theo tài khoản.
- **Margin call:** chỉ được kiểm tra lúc 15:00, theo giá đóng cửa. Đây là cố ý, để P1 có cái để vượt.
- **Lưu lượng thấp so với thực tế:** preset `S` khoảng 4.000 lệnh/ngày. Muốn thử tải, dùng `--speed` cao hoặc preset `M`. `M` chưa đo thời gian backfill, dự kiến hàng giờ.
- **Kafka thật:** đường gửi `marketdata.ticks` và `app.clickstream` mới được chạy thử với broker không tồn tại, chưa kiểm chứng với Kafka thật. Hãy kiểm tra topic ngay lần chạy `live` đầu tiên.
- **Lịch nghỉ:** lịch nghỉ lễ năm 2026 là ước tính.
